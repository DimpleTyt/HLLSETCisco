# ---------------- HLLSet plane (hllset-core::HLLSet) as a set of bit positions ----------------
# bit = reg * 32 + tz  (0 .. 32767); plane = dict {bit: 1}
# Content key = "h:" + sha1(Roaring serialization), exactly like HLLSet::content_key()
# (roaring-rs 0.10, portable format without run containers).

ARRAY_LIMIT = 4096


def plane_from(s):
    p = {}
    if s == "" or s == "-":
        return p
    for x in s.split(","):
        b = int(x)
        if b < 0 or b >= 32768:
            raise Exception("bit out of range " + x)
        p[b] = 1
    return p


def plane_str(p):
    keys = sorted(p.keys())
    if len(keys) == 0:
        return "-"
    return ",".join([str(k) for k in keys])


def p_union(a, b):
    r = {}
    for k in a:
        r[k] = 1
    for k in b:
        r[k] = 1
    return r


def p_inter(a, b):
    r = {}
    for k in a:
        if k in b:
            r[k] = 1
    return r


def p_diff(a, b):
    r = {}
    for k in a:
        if k not in b:
            r[k] = 1
    return r


def p_xor(a, b):
    return p_union(p_diff(a, b), p_diff(b, a))


def p_hist(p):
    # HLLSet::bit_counts(): c_s = number of registers with bit s set (HT input, host side)
    c = [0] * 32
    for k in p:
        c[k % 32] = c[k % 32] + 1
    return c


def roaring_bytes(p):
    # RoaringBitmap::serialize_into: cookie 12346, container count, (key, card-1),
    # offsets, then the container. All bits < 32768 -> at most one container (key 0).
    keys = sorted(p.keys())
    n = len(keys)
    out = [0x3A, 0x30, 0, 0]
    if n == 0:
        return out + [0, 0, 0, 0]
    out = out + [1, 0, 0, 0, 0, 0, (n - 1) % 256, (n - 1) // 256, 16, 0, 0, 0]
    if n <= ARRAY_LIMIT:
        for k in keys:
            out.append(k % 256)
            out.append(k // 256)
        return out
    bm = [0] * 8192
    for k in keys:
        bm[k // 8] = bm[k // 8] | (1 << (k % 8))
    return out + bm


def cid_of(p):
    # HLLSet::content_key(): "h:" + sha1(roaring bytes)
    return "h:" + sha1_bytes(roaring_bytes(p))


def hexkey(t):
    # bytewise (UTF-8) sort key: Rust orders tokens as Vec<u8>; JS compares UTF-16 units
    digits = "0123456789abcdef"
    s = ""
    for b in utf8(t):
        s = s + digits[b >> 4] + digits[b & 15]
    return s


def sort_bytes(tokens):
    m = {}
    for t in tokens:
        m[hexkey(t)] = t
    return [m[k] for k in sorted(m.keys())]


# ---- wire encodings for LUT fibers and TF ----
def lut_str(lut):
    # lut = {bit: {token: 1}} -> "bit:tok;bit:tok"
    out = []
    for b in sorted(lut.keys()):
        for t in sort_bytes(lut[b].keys()):
            out.append(str(b) + ":" + t)
    return ";".join(out) if len(out) > 0 else "-"


def lut_from(s, into):
    if s == "" or s == "-":
        return into
    for e in s.split(";"):
        i = e.index(":")
        b = int(e[:i])
        fib = into.get(b)
        if fib is None:
            fib = {}
            into[b] = fib
        fib[e[i + 1:]] = 1
    return into


def tf_str(tf):
    out = []
    for t in sort_bytes(tf.keys()):
        out.append(t + ":" + str(tf[t]))
    return ";".join(out) if len(out) > 0 else "-"


def tf_from(s):
    tf = {}
    if s == "" or s == "-":
        return tf
    for e in s.split(";"):
        i = e.index(":")
        tf[e[:i]] = int(e[i + 1:])
    return tf
