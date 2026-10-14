# ================= DISPATCHER: swarm scheduler (the "Router" of the drawing) =================
# Users talk only to this node. It checks tokens with DATA (green/orange), validates the
# request and spreads model work (red) over identical swarm boards. An ingest is split by
# n-gram WINDOW positions across ALL ready boards; every board ORs its part into the same
# GRID job, and SEAL registers the union only when every part arrived.
PORT = 5000
DATA = Peer("DATA", "192.168.20.10", 5001)
BOARDS = [Peer("FPGA" + str(i), "192.168.30." + str(10 + i), 5100) for i in range(1, 6)]
RR = [0]
JOB = [0]
MAX_TOKENS = 400          # per ingest: the boards are slow (64-bit math on 16-bit limbs)
MAX_NAME = 24
OPS = ["INFO", "POPCOUNT", "HIST", "UNION", "INTERSECT", "DIFF", "XOR", "SUBSET", "DRN",
       "LOOKUP", "TOKENS", "LIST", "STAT", "HLUT"]
SALT = str(random.randint(100000, 999999))     # job ids stay unique across dispatcher restarts


def ready_boards():
    return [b for b in BOARDS if b.ready]


def next_board(avoid=None):
    rb = [b for b in ready_boards() if b is not avoid]
    if len(rb) == 0:
        return None
    RR[0] = (RR[0] + 1) % len(rb)
    return rb[RR[0]]


def with_user(conn, rid, token, then):
    def checked(r):
        if r[0] != "OK":
            log("GREEN", "token rejected")
            conn.send([rid, "DENY", r[-1]])
            return
        then(r[1])
    DATA.call(["CHECK", token], checked)


def do_ingest(conn, rid, user, name, text):
    toks = tokenize(text)
    boards = ready_boards()
    if len(toks) == 0 or len(boards) == 0:
        conn.send([rid, "ERR", "no tokens" if len(toks) == 0 else "no boards ready"])
        return
    if len(toks) > MAX_TOKENS:
        conn.send([rid, "ERR", "too many tokens " + str(len(toks)) + " > " + str(MAX_TOKENS)])
        return
    n = len(toks)
    padded = [PAD] + toks + [PAD, PAD]
    L = n + 3
    k = min(len(boards), L)
    JOB[0] = JOB[0] + 1
    job = SALT + "-" + str(JOB[0])
    step = (L + k - 1) // k
    ranges = []
    lo = 0
    while lo < L:
        ranges.append([lo, min(lo + step, L)])
        lo = lo + step
    state = {"left": len(ranges), "used": [], "failed": 0}
    log("RED", "INGEST " + user + "/" + name + " " + str(n) + " tokens, " + str(L) + " windows -> " + str(len(ranges)) + " boards")

    def finish():
        if state["failed"] > 0:
            conn.send([rid, "ERR", "ingest aborted: " + str(state["failed"]) + " part(s) failed", " ".join(state["used"])])
            return
        b = next_board()
        if b is None:
            conn.send([rid, "ERR", "no boards ready"])
            return

        def sealed(x):
            if x[0] == "OK":
                conn.send([rid, "OK", name, "tokens=" + str(n), "cid=" + x[2], "bits=" + str(x[3]),
                           "G1,G2,G3=" + x[4], "prev=" + x[5], "boards=" + " ".join(state["used"])])
            else:
                conn.send([rid, "ERR", x[-1]])
        b.call(["SEAL", user, job, name, n, len(ranges)], sealed)

    def send_part(i, board, retry):
        lo2 = ranges[i][0]
        hi2 = ranges[i][1]
        chunk = padded[lo2:min(hi2 + 3, L)]

        def part_done(r):
            if r[0] == "OK":
                state["used"].append(r[1] + ":" + str(r[3]))
            elif retry:
                other = next_board(board)
                if other is not None:
                    log("RED", "part " + str(i) + " failed on " + board.name + ", retry on " + other.name)
                    send_part(i, other, False)
                    return
                state["failed"] = state["failed"] + 1
            else:
                state["failed"] = state["failed"] + 1
                state["used"].append("ERR(" + r[-1] + ")")
            state["left"] = state["left"] - 1
            if state["left"] == 0:
                finish()
        board.call(["PART", user, job, i, lo2, hi2, n, " ".join(chunk)], part_done)

    for i in range(len(ranges)):
        send_part(i, boards[i % len(boards)], True)


def handle(conn, rid, cmd, a):
    if cmd == "LOGIN":
        user, pw = clean(a[0]), clean(a[1])
        log("GREEN", "LOGIN " + user)

        def authed(r):
            if r[0] == "OK":
                log("ORANGE", "access granted to " + user)
                conn.send([rid, "OK", r[1]])
            else:
                conn.send([rid, "DENY", r[-1]])
        DATA.call(["AUTH", user, pw], authed)
    elif cmd == "LOGOUT":
        DATA.call(["LOGOUT", clean(a[0])], lambda r: conn.send([rid] + r))
    elif cmd == "INGEST":
        token, name = clean(a[0]), a[1]
        text = " ".join(a[2:])                # a "|" inside the text must not cut it
        if not valid(name, NAME_CHARS, MAX_NAME):
            conn.send([rid, "ERR", "bad name (a-z 0-9 _ , 1-" + str(MAX_NAME) + " chars)"])
            return
        with_user(conn, rid, token, lambda user: do_ingest(conn, rid, user, name, text))
    elif cmd == "QUERY":
        token = clean(a[0])
        args = a[1:4]
        if len(args) == 0 or args[0] not in OPS:
            conn.send([rid, "ERR", "unknown op"])
            return
        for x in args[1:]:
            if x != "" and not valid(x, REF_CHARS, 200):
                conn.send([rid, "ERR", "bad set name " + clean(x)])
                return

        def go(user):
            b = next_board()
            if b is None:
                conn.send([rid, "ERR", "no boards ready"])
                return
            b.call(["QUERY", user] + args, lambda r: conn.send([rid] + r))
        with_user(conn, rid, token, go)
    elif cmd == "STATUS":
        conn.send([rid, "OK", "data=" + ("up" if DATA.ready else "down"),
                   "boards=" + ",".join([b.name for b in ready_boards()])])
    else:
        conn.send([rid, "ERR", "unknown " + clean(cmd)])


SERVER = Server("DISPATCHER", PORT, handle)


def tick():
    DATA.tick()
    for b in BOARDS:
        b.tick()
    if TICK[0] % 120 == 0:
        log("DISP", "data=" + ("up" if DATA.ready else "down") + " boards=" + ",".join([b.name for b in ready_boards()]))


def main():
    log("DISP", "dispatcher starting")
    SERVER.start()
    run(tick)
