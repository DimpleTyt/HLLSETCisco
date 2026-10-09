# ---------------- HLLSet plane as a set of bit positions ----------------
# position = reg * 32 + tz  (0 .. 32767); plane = dict {position: 1}

def plane_from(s):
    p = {}
    if s == "" or s == "-":
        return p
    for x in s.split(","):
        p[int(x)] = 1
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
    # c_s = number of registers with bit s set (input for Horvitz-Thompson cardinality on host)
    c = [0] * 32
    for k in p:
        c[k % 32] = c[k % 32] + 1
    return c


def cid_of(p):
    # content key of a node: SHA-1 over the canonical position list
    return "h:" + sha1_hex(plane_str(p))
