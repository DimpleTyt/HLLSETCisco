# ---------------- host side: Horvitz-Thompson cardinality (hllset-core::cardinality_ht) ----------------
# Floats live on the host; the boards return only the integer counts c_s.

def cardinality(counts):
    n = 1024.0
    m = 1024
    last_non_sat = -1
    last_f_hat = 0.0
    for s in range(32):
        c = counts[s]
        if c > 0 and c < m:
            # Rust breaks at the FIRST non-saturated position (the name says "last")
            last_non_sat = s
            last_f_hat = -n * math.log(1.0 - c / n)
            break
    total = 0.0
    for s in range(32):
        c = counts[s]
        if c == 0:
            continue
        if c < m:
            total = total + (-n * math.log(1.0 - c / n))
        elif last_non_sat > s:
            total = total + last_f_hat * math.pow(2.0, last_non_sat - s)
        else:
            total = total + n * math.log(n)
    if total <= 0:
        return 0
    return int(math.floor(total + 0.5))      # f64::round (half away from zero), total >= 0
