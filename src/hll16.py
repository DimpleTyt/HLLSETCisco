# HLLSet core for Packet Tracer SBC Python.
# PT Python runs on a JavaScript engine: integers are doubles (exact only up to 2^53)
# and bitwise ops are 32-bit. So every 64-bit value is 4 limbs of 16 bits,
# little-endian: [bits 0-15, 16-31, 32-47, 48-63]. Bitwise ops only touch values < 2^16,
# products of two limbs stay < 2^32 (exact in a double) and are split with % and //.
# Bit-exact with hllset-contracts (ewm-state-machine):
# h = murmur3_x64_128(bytes, seed as u32).low64, reg = h & 0x3FF, tz = min(ctz(h >> 10), 31),
# bit = reg * 32 + tz.

L16 = 65536
C1 = [0x53d5, 0x1142, 0x7b91, 0x87c3]   # 0x87c37b91114253d5
C2 = [0x937f, 0x2745, 0xad43, 0x4cf5]   # 0x4cf5ad432745937f
F1 = [0x8ccd, 0xed55, 0xafd7, 0xff51]   # 0xff51afd7ed558ccd
F2 = [0xec53, 0x1a85, 0xb9fe, 0xc4ce]   # 0xc4ceb9fe1a85ec53
A1 = [0xe729, 0x52dc, 0, 0]             # 0x52dce729
A2 = [0x5ab5, 0x3849, 0, 0]             # 0x38495ab5
FIVE = [5, 0, 0, 0]


def small(n):
    # non-negative int < 2^48 -> limbs (arithmetic only)
    r = []
    for i in range(4):
        q = n // L16
        r.append(n - q * L16)
        n = q
    return r


def add(a, b):
    r = [0, 0, 0, 0]
    c = 0
    for i in range(4):
        s = a[i] + b[i] + c
        c = s // L16
        r[i] = s - c * L16
    return r


def mul(a, b):
    # (a * b) mod 2^64
    acc = [0, 0, 0, 0]
    for i in range(4):
        for j in range(4 - i):
            acc[i + j] = acc[i + j] + a[i] * b[j]
    r = [0, 0, 0, 0]
    c = 0
    for k in range(4):
        s = acc[k] + c
        c = s // L16
        r[k] = s - c * L16
    return r


def xor(a, b):
    return [a[0] ^ b[0], a[1] ^ b[1], a[2] ^ b[2], a[3] ^ b[3]]


def rotl(x, r):
    q = r // 16
    s = r - q * 16
    y = [x[(i - q + 4) % 4] for i in range(4)]
    if s == 0:
        return y
    return [((y[i] << s) & 0xFFFF) | (y[(i + 3) % 4] >> (16 - s)) for i in range(4)]


def shr(x, r):
    q = r // 16
    s = r - q * 16
    y = [0, 0, 0, 0]
    for i in range(4):
        if i + q < 4:
            y[i] = x[i + q]
    if s == 0:
        return y
    out = []
    for i in range(4):
        hi = y[i + 1] if i < 3 else 0
        out.append((y[i] >> s) | ((hi << (16 - s)) & 0xFFFF))
    return out


def fmix(k):
    k = xor(k, shr(k, 33))
    k = mul(k, F1)
    k = xor(k, shr(k, 33))
    k = mul(k, F2)
    k = xor(k, shr(k, 33))
    return k


def utf8(s):
    out = []
    for ch in s:
        c = ord(ch)
        if c < 0x80:
            out.append(c)
        elif c < 0x800:
            out.append(0xC0 | (c >> 6))
            out.append(0x80 | (c & 0x3F))
        elif c < 0x10000:
            out.append(0xE0 | (c >> 12))
            out.append(0x80 | ((c >> 6) & 0x3F))
            out.append(0x80 | (c & 0x3F))
        else:
            out.append(0xF0 | (c >> 18))
            out.append(0x80 | ((c >> 12) & 0x3F))
            out.append(0x80 | ((c >> 6) & 0x3F))
            out.append(0x80 | (c & 0x3F))
    return out


def word(d, i, n):
    # n (<= 8) little-endian bytes starting at d[i] -> limbs
    r = [0, 0, 0, 0]
    for j in range(n):
        r[j // 2] = r[j // 2] | (d[i + j] << (8 * (j % 2)))
    return r


def murmur64(text, seed):
    return murmur64_bytes(utf8(text), seed)


def murmur64_bytes(d, seed):
    # d = list of byte values 0..255
    n = len(d)
    s32 = seed % 4294967296
    h1 = small(s32)
    h2 = small(s32)
    nb = n // 16
    for b in range(nb):
        k1 = word(d, b * 16, 8)
        k2 = word(d, b * 16 + 8, 8)
        k1 = mul(rotl(mul(k1, C1), 31), C2)
        h1 = xor(h1, k1)
        h1 = add(mul(add(rotl(h1, 27), h2), FIVE), A1)
        k2 = mul(rotl(mul(k2, C2), 33), C1)
        h2 = xor(h2, k2)
        h2 = add(mul(add(rotl(h2, 31), h1), FIVE), A2)
    t = nb * 16
    rest = n - t
    if rest > 8:
        k2 = word(d, t + 8, rest - 8)
        h2 = xor(h2, mul(rotl(mul(k2, C2), 33), C1))
    if rest > 0:
        k1 = word(d, t, min(rest, 8))
        h1 = xor(h1, mul(rotl(mul(k1, C1), 31), C2))
    ln = small(n)
    h1 = xor(h1, ln)
    h2 = xor(h2, ln)
    h1 = add(h1, h2)
    h2 = add(h2, h1)
    h1 = fmix(h1)
    h2 = fmix(h2)
    return add(h1, h2)


def hex64(x):
    digits = "0123456789abcdef"
    s = ""
    for i in range(3, -1, -1):
        v = x[i]
        for k in (12, 8, 4, 0):
            s = s + digits[(v >> k) & 15]
    return "0x" + s


def ctz(x):
    for i in range(4):
        if x[i] != 0:
            v = x[i]
            c = 0
            while (v & 1) == 0:
                v = v >> 1
                c = c + 1
            return i * 16 + c
    return 64


def position_of(h):
    # hllset-contracts::hash_to_position: reg = h & 1023, tz = min(ctz(h >> 10), 31)
    # (h >> 10 == 0 gives ctz = 64 -> 31, the saturated convention of Rust)
    reg = h[0] & 0x3FF
    tz = ctz(shr(h, 10))
    if tz > 31:
        tz = 31
    return reg, tz


def position(text, seed):
    return position_of(murmur64(text, seed))


def bit_of_bytes(d, seed):
    # BitAddress::of_token_seeded(bytes, seed).bit() = reg * 32 + tz
    reg, tz = position_of(murmur64_bytes(d, seed))
    return reg * 32 + tz
