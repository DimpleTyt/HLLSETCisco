import sys, random, string, builtins
sys.path.insert(0, sys.argv[1])
import hll16, mmh3
LIM32 = 2**31; LIM53 = 2**53
viol = []
def chk_bit(v, a, b, op):
    for x in (a, b, v):
        if not (-LIM32 <= x < LIM32): viol.append((op, int(a), int(b), int(v)))
def chk_ar(v, op):
    if abs(v) >= LIM53: viol.append((op, int(v)))
class S(int):
    def _w(self, v): return S(v)
for name, kind in [('__and__','b'),('__or__','b'),('__xor__','b'),('__lshift__','b'),('__rshift__','b'),
                   ('__rand__','b'),('__ror__','b'),('__rxor__','b'),('__rlshift__','b'),('__rrshift__','b'),
                   ('__add__','a'),('__radd__','a'),('__sub__','a'),('__rsub__','a'),('__mul__','a'),('__rmul__','a'),
                   ('__floordiv__','a'),('__rfloordiv__','a'),('__mod__','a'),('__rmod__','a')]:
    def mk(name=name, kind=kind):
        base = getattr(int, name)
        def f(self, o):
            v = base(int(self), int(o))
            if v is NotImplemented: return v
            if kind == 'b': chk_bit(v, int(self), int(o), name)
            else: chk_ar(v, name)
            return S(v)
        return f
    setattr(S, name, mk())
hll16.ord = lambda c: S(builtins.ord(c))
hll16.len = lambda x: S(builtins.len(x))
for k in ['C1','C2','F1','F2','A1','A2','FIVE']:
    setattr(hll16, k, [S(v) for v in getattr(hll16, k)])
random.seed(7); bad = 0; cnt = 0
for n in range(0, 50):
    for seed in [0, 1, 2, 101, 4294967295]:
        s = ''.join(random.choice(string.ascii_letters + 'абвжз€😀') for _ in range(n))
        ref = mmh3.hash128(s.encode(), seed, True, False) & ((1 << 64) - 1)
        h = hll16.murmur64(s, S(seed))
        got = sum(int(h[i]) << (16 * i) for i in range(4))
        cnt += 1
        if got != ref: bad += 1
        r, tz = hll16.position(s, S(seed))
        rr = ref & 0x3FF; t = (ref >> 10); tt = 64 if t == 0 else (t & -t).bit_length() - 1
        if (r, tz) != (rr, min(tt, 31)): bad += 1
print('cases', cnt, 'mismatch', bad, 'range violations', len(viol), viol[:3])
print(hll16.hex64(hll16.murmur64('hello', 0)), hll16.position('hello', 0))
