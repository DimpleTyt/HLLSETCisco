# ---------------- hllset-morphisms::api — default ingest / materialize ----------------
# Port of ewm-state-machine/crates/hllset-morphisms/src/api.rs:
#   padded = [PAD] + tokens + [PAD, PAD]
#   channel 0 (G1): 1-grams, seed 0     channel 1 (G2): 2-grams, seed 1
#   channel 2 (G3): 3-grams, seed 2     slide4 (S4_1d): 4-gram windows, seed 3, NO LUT
#   n-gram bytes = utf8 parts joined with a NUL byte.
#   LUT fiber of a window's bit holds the window's FIRST token, only for real start
#   positions 1..n (pad-leading windows only set the atom).
#   key = h:sha1(roaring(G1 | G2 | G3)); slide4 is not part of the projection.
# The swarm splits the window START positions [0, L) into ranges; every board ingests
# its range, the GRID unions the parts. Union is order-free, so the result is the same
# as one Rust ingest() call over the whole text.

PAD = "<PAD>"
CHANNEL_SEEDS = [0, 1, 2]
SLIDE_SEED = 3
CHANNEL_NAMES = ["G1", "G2", "G3"]
WALK_BUDGET = 20000     # node budget of the ordered walk (same as Rust)
BITCACHE = {}


def window_bit(parts, seed):
    key = str(seed) + " " + " ".join(parts)      # tokens never contain spaces
    b = BITCACHE.get(key)
    if b is not None:
        return b
    d = []
    for i in range(len(parts)):
        if i > 0:
            d.append(0)
        d = d + utf8(parts[i])
    b = bit_of_bytes(d, seed)
    if len(BITCACHE) > 20000:
        for k in list(BITCACHE.keys()):
            del BITCACHE[k]
    BITCACHE[key] = b
    return b


def ingest_part(toks, a, b, nreal):
    # toks = padded[a : min(b + 3, L)], window starts s in [a, b), L = nreal + 3
    L = nreal + 3
    g = [{}, {}, {}]
    s4 = {}
    luts = [{}, {}, {}]
    tf = {}
    for s in range(a, b):
        for n in range(1, 5):
            if s + n > L:
                continue
            w = toks[s - a: s - a + n]
            if n == 4:
                s4[window_bit(w, SLIDE_SEED)] = 1
                continue
            bit = window_bit(w, CHANNEL_SEEDS[n - 1])
            g[n - 1][bit] = 1
            if s >= 1 and s <= nreal:
                fib = luts[n - 1].get(bit)
                if fib is None:
                    fib = {}
                    luts[n - 1][bit] = fib
                fib[w[0]] = 1
        if s >= 1 and s <= nreal:
            t = toks[s - a]
            tf[t] = tf.get(t, 0) + 1
    return {"g": g, "s4": s4, "luts": luts, "tf": tf, "n": nreal}


def ingest_all(tokens):
    # the single-machine reference: one part covering every window
    padded = [PAD] + tokens + [PAD, PAD]
    return ingest_part(padded, 0, len(padded), len(tokens))


def seal(rec):
    # projection, keys and the hllsetLUT entries of a finished ingest
    proj = p_union(p_union(rec["g"][0], rec["g"][1]), rec["g"][2])
    rec["proj"] = proj
    rec["key"] = cid_of(proj)
    rec["keys"] = [cid_of(rec["g"][i]) for i in range(3)]
    return rec


def unordered_tokens(rec):
    # materialize_no_order: LUT-first over the three (sketch, LUT) pairs, keep every candidate
    out = {}
    for ch in range(3):
        for bit in rec["g"][ch]:
            fib = rec["luts"][ch].get(bit)
            if fib is not None:
                for t in fib:
                    out[t] = 1
    return sort_bytes(out.keys())


def _has(rec, ch, parts):
    return window_bit(parts, CHANNEL_SEEDS[ch]) in rec["g"][ch]


def _has4(rec, parts):
    return window_bit(parts, SLIDE_SEED) in rec["s4"]


def _edge_ok(rec, path, prev, cur, c):
    # the joint 2-/3-/4-gram edge check of walk() / beam_search()
    if not (_has(rec, 1, [cur, c]) and _has(rec, 2, [prev, cur, c])):
        return False
    if len(path) < 2:
        return True
    pp = PAD if len(path) == 2 else path[len(path) - 3]
    return _has4(rec, [pp, prev, cur, c])


def _rank(cands, tf):
    # TF descending, then bytewise ascending (Rust: b.tf.cmp(a.tf).then(a.cmp(b)))
    m = {}
    for t in cands:
        k = str(10000000 - tf.get(t, 0)) + "/" + hexkey(t)
        m[k] = t
    return [m[k] for k in sorted(m.keys())]


def materialize_ordered(rec):
    # api::materialize (Order::Ordered, beam 1): count-constrained greedy De Bruijn walk
    # with backtracking, anchored at the start pad. Iterative (no deep recursion on PT).
    tokens = unordered_tokens(rec)
    n = rec["n"]
    tf = rec["tf"]
    if len(tokens) == 0 or n == 0:
        return [], "empty"
    remaining = {}
    for t in tokens:
        if tf.get(t, 0) > 0:
            remaining[t] = tf[t]
    starts = _rank([t for t in tokens if remaining.get(t, 0) > 0 and _has(rec, 1, [PAD, t])], tf)
    budget = [WALK_BUDGET]
    for start in starts:
        if n == 1:
            return [start], "ordered"
        path = [start]
        rem = {}
        for t in remaining:
            rem[t] = remaining[t]
        rem[start] = rem[start] - 1
        if _walk(rec, tokens, path, rem, budget):
            return path, "ordered"
        if budget[0] == 0:
            break
    return tokens, "fallback-set"


def _enter(rec, tokens, path, rem, budget, prev, cur):
    # one call of Rust walk(): True / False, or a list of successors to try
    if budget[0] == 0:
        return False
    budget[0] = budget[0] - 1
    if len(path) == rec["n"]:
        return _edge_ok(rec, path, prev, cur, PAD)
    nexts = [c for c in tokens if rem.get(c, 0) > 0 and _edge_ok(rec, path, prev, cur, c)]
    return _rank(nexts, rec["tf"])


def _walk(rec, tokens, path, rem, budget):
    first = _enter(rec, tokens, path, rem, budget, PAD, path[0])
    if first is True or first is False:
        return first
    stack = [[PAD, path[0], first, 0]]          # frame = [prev, cur, nexts, next index]
    while len(stack) > 0:
        fr = stack[len(stack) - 1]
        if fr[3] >= len(fr[2]):
            stack.pop()                          # frame exhausted -> parent undoes its step
            if len(stack) == 0:
                return False
            last = path.pop()
            rem[last] = rem[last] + 1
            continue
        nx = fr[2][fr[3]]
        fr[3] = fr[3] + 1
        rem[nx] = rem[nx] - 1
        path.append(nx)
        r = _enter(rec, tokens, path, rem, budget, fr[1], nx)
        if r is True:
            return True
        if r is False:
            path.pop()
            rem[nx] = rem[nx] + 1
            continue
        stack.append([fr[1], nx, r, 0])
    return False


# ---- record wire format: g1|g2|g3|s4|lut1|lut2|lut3|tf ----
def rec_fields(rec):
    return [plane_str(rec["g"][0]), plane_str(rec["g"][1]), plane_str(rec["g"][2]), plane_str(rec["s4"]),
            lut_str(rec["luts"][0]), lut_str(rec["luts"][1]), lut_str(rec["luts"][2]), tf_str(rec["tf"])]


def rec_from(f, n):
    return {"g": [plane_from(f[0]), plane_from(f[1]), plane_from(f[2])], "s4": plane_from(f[3]),
            "luts": [lut_from(f[4], {}), lut_from(f[5], {}), lut_from(f[6], {})], "tf": tf_from(f[7]), "n": n}
