# ================= FPGA board (swarm member): soldered HLLSet core =================
# Integer-only work: n-gram windows -> murmur3 -> (reg, tz) -> bit, LUT fibers, TF counts,
# lattice algebra OR/AND/AND-NOT/XOR, popcount, D/R/N, c_s histogram and the ordered
# materialize walk. Planes live in GRID (MERGE / SEAL / GET / PUT through the network).
BOARD = "FPGA?"            # <-- set per board: FPGA1 .. FPGA5
PORT = 5100
GRID_IP = "192.168.40.10"
GRID_PORT = 5200

GRID = Peer("GRID", GRID_IP, GRID_PORT)
STATS = {"windows": 0, "ops": 0}


def part(conn, rid, a):
    # PART|user|job|part|a|b|n|tok tok ...   window starts [a, b) of [PAD]+text+[PAD,PAD]
    user, job, pi, lo, hi, n = a[0], a[1], a[2], int(a[3]), int(a[4]), int(a[5])
    toks = a[6].split(" ")
    if lo < 0 or hi > n + 3 or lo >= hi or len(toks) != min(hi + 3, n + 3) - lo:
        conn.send([rid, "ERR", BOARD + ": bad part range"])
        return
    p = ingest_part(toks, lo, hi, n)
    STATS["windows"] = STATS["windows"] + (hi - lo)
    bits = len(p["g"][0]) + len(p["g"][1]) + len(p["g"][2])
    log("RED", BOARD + " PART " + user + " job " + job + "#" + pi + " windows " + str(lo) + ".." + str(hi - 1) + " -> " + str(bits) + " atoms")

    def done(r):
        if r[0] == "OK":
            conn.send([rid, "OK", BOARD, pi, hi - lo, bits])
        else:
            conn.send([rid, "ERR", BOARD + ": " + r[-1]])

    GRID.call(["MERGE", user, job, pi] + rec_fields(p), done)


def seal_req(conn, rid, a):
    # SEAL|user|job|name|n|parts
    def done(r):
        if r[0] == "OK":
            conn.send([rid, "OK", BOARD] + r[1:])
        else:
            conn.send([rid, "ERR", BOARD + ": " + r[-1]])
    GRID.call(["SEAL"] + a[:5], done)


def load2(user, ra, rb, cb):
    # fetch one or two planes from GRID, then cb(pa, pb) or cb(None, err)
    def got_a(r):
        if r[0] != "OK":
            cb(None, r[-1])
            return
        pa = plane_from(r[2])
        if rb is None:
            cb(pa, None)
            return

        def got_b(r2):
            if r2[0] != "OK":
                cb(None, r2[-1])
                return
            cb(pa, plane_from(r2[2]))

        GRID.call(["GET", user, rb], got_b)

    GRID.call(["GET", user, ra], got_a)


def query(conn, rid, a):
    # QUERY|user|OP|A|B
    user, op = a[0], a[1]
    ra = a[2] if len(a) > 2 else ""
    rb = a[3] if len(a) > 3 and a[3] != "" else None
    STATS["ops"] = STATS["ops"] + 1
    log("RED", BOARD + " " + op + " " + user + " " + ra + ("" if rb is None else " " + rb))

    def fail(msg):
        conn.send([rid, "ERR", BOARD + ": " + msg])

    def put_and_reply(name, p, extra):
        def ok(r):
            if r[0] == "OK":
                conn.send([rid, "OK", BOARD, name, r[1], r[2]] + extra)
            else:
                fail(r[-1])
        GRID.call(["PUT", user, name, plane_str(p)], ok)

    def compute(pa, pb):
        if pa is None:
            fail(pb)
            return
        if op == "INFO" or op == "POPCOUNT":
            conn.send([rid, "OK", BOARD, ra, cid_of(pa), len(pa)])
        elif op == "HIST":
            conn.send([rid, "OK", BOARD, ra, ",".join([str(c) for c in p_hist(pa)])])
        elif op == "UNION":
            put_and_reply(ra + "+" + rb, p_union(pa, pb), [])
        elif op == "INTERSECT":       # R-link: an HLLSet with its own CID
            put_and_reply(ra + "*" + rb, p_inter(pa, pb), [])
        elif op == "DIFF":
            put_and_reply(ra + "-" + rb, p_diff(pa, pb), [])
        elif op == "XOR":
            put_and_reply(ra + "^" + rb, p_xor(pa, pb), [])
        elif op == "SUBSET":
            conn.send([rid, "OK", BOARD, ra + "<=" + rb, "yes" if len(p_diff(pa, pb)) == 0 else "no"])
        elif op == "DRN":
            # A = H(t-1) previous state, B = S(t) current state (ewm-git view.rs)
            d = p_diff(pa, pb)
            r = p_inter(pa, pb)
            n = p_diff(pb, pa)
            res = []

            def step(i):
                parts = [["D." + ra + "." + rb, d], ["R." + ra + "." + rb, r], ["N." + ra + "." + rb, n]]
                if i == 3:
                    conn.send([rid, "OK", BOARD, "DRN"] + res)
                    return
                nm = parts[i][0]

                def ok(x):
                    if x[0] != "OK":
                        fail(x[-1])
                        return
                    res.append(nm[0] + "=" + str(x[2]) + "@" + x[1][:14])
                    step(i + 1)
                GRID.call(["PUT", user, nm, plane_str(parts[i][1])], ok)
            step(0)
        elif op == "LOOKUP":
            def got(r):
                if r[0] == "OK":
                    conn.send([rid, "OK", BOARD, ra, r[1], r[2], "set"])
                else:
                    fail(r[-1])
            GRID.call(["LOOKUP", user, plane_str(pa)], got)
        else:
            fail("unknown op " + op)

    if op == "LIST" or op == "STAT" or op == "HLUT":
        def got_list(r):
            conn.send([rid] + r[:1] + [BOARD] + r[1:])
        GRID.call([op, user], got_list)
        return
    if op == "LOOKUP" or op == "TOKENS":
        # an ingest record is restored by hllset-morphisms::materialize (ordered) or
        # materialize_no_order; a computed node falls back to the LUT-first set
        def got_rec(r):
            if r[0] == "NOREC":
                load2(user, ra, None, compute)
                return
            if r[0] != "OK":
                fail(r[-1])
                return
            rec = rec_from(r[3:11], int(r[2]))
            if op == "TOKENS":
                toks = unordered_tokens(rec)
                mode = "no_order"
            else:
                res = materialize_ordered(rec)
                toks = res[0]
                mode = res[1]
            conn.send([rid, "OK", BOARD, ra, len(toks), " ".join(toks) if len(toks) > 0 else "-", mode])
        GRID.call(["REC", user, ra], got_rec)
        return
    two = op in ["UNION", "INTERSECT", "DIFF", "XOR", "SUBSET", "DRN"]
    if two and rb is None:
        fail(op + " needs two sets")
        return
    load2(user, ra, rb if two else None, compute)


def handle(conn, rid, cmd, a):
    if cmd == "PART":
        part(conn, rid, a)
    elif cmd == "SEAL":
        seal_req(conn, rid, a)
    elif cmd == "QUERY":
        query(conn, rid, a)
    elif cmd == "PING":
        conn.send([rid, "OK", BOARD, "grid=" + ("up" if GRID.ready else "down")])
    else:
        conn.send([rid, "ERR", "unknown " + cmd])


SERVER = Server(BOARD, PORT, handle)


def tick():
    GRID.tick()
    if TICK[0] % 120 == 0:
        log(BOARD, "windows=" + str(STATS["windows"]) + " ops=" + str(STATS["ops"]) + " grid=" + ("up" if GRID.ready else "down"))


def main():
    log(BOARD, "board starting")
    SERVER.start()
    run(tick)
