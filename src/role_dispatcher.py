# ================= DISPATCHER: swarm scheduler (the "Router" of the drawing) =================
# Users talk only to this node. It checks tokens with DATA (green/orange) and spreads
# model work (red) over identical swarm boards. Ingest is split across ALL ready boards:
# each board ORs its part into the same GRID node; union is order-independent.
PORT = 5000
DATA = Peer("DATA", "192.168.20.10", 5001)
BOARDS = [Peer("FPGA" + str(i), "192.168.30." + str(10 + i), 5100) for i in range(1, 6)]
RR = [0]


def ready_boards():
    return [b for b in BOARDS if b.ready]


def next_board():
    rb = ready_boards()
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
        then(r[1], r[2])
    DATA.call(["CHECK", token], checked)


def do_ingest(conn, rid, user, seed, name, text):
    toks = tokenize(text)
    boards = ready_boards()
    if len(toks) == 0 or len(boards) == 0:
        conn.send([rid, "ERR", "no tokens" if len(toks) == 0 else "no boards ready"])
        return
    k = min(len(boards), len(toks))
    state = {"left": k, "used": []}
    log("RED", "INGEST " + user + "/" + name + " " + str(len(toks)) + " tokens -> " + str(k) + " boards")

    def part_done(r):
        state["left"] = state["left"] - 1
        if r[0] == "OK":
            state["used"].append(r[1] + ":" + r[2])
        else:
            state["used"].append("ERR(" + r[-1] + ")")
        if state["left"] == 0:
            def info(x):
                if x[0] == "OK":
                    conn.send([rid, "OK", name, "tokens=" + str(len(toks)), "cid=" + x[3], "bits=" + str(x[4]), "boards=" + " ".join(state["used"])])
                else:
                    conn.send([rid, "ERR", x[-1]])
            b = next_board()
            b.call(["QUERY", user, seed, "INFO", name], info)

    for i in range(k):
        batch = [toks[j] for j in range(i, len(toks), k)]
        boards[i].call(["INGEST", user, seed, name, " ".join(batch)], part_done)


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
        DATA.call(["LOGOUT", a[0]], lambda r: conn.send([rid] + r))
    elif cmd == "INGEST":
        token, name, text = a[0], clean(a[1]), a[2]
        with_user(conn, rid, token, lambda user, seed: do_ingest(conn, rid, user, seed, name, text))
    elif cmd == "QUERY":
        token = a[0]
        args = [clean(x) for x in a[1:]]

        def go(user, seed):
            b = next_board()
            if b is None:
                conn.send([rid, "ERR", "no boards ready"])
                return
            b.call(["QUERY", user, seed] + args, lambda r: conn.send([rid] + r))
        with_user(conn, rid, token, go)
    elif cmd == "STATUS":
        conn.send([rid, "OK", "data=" + ("up" if DATA.ready else "down"),
                   "boards=" + ",".join([b.name for b in ready_boards()])])
    else:
        conn.send([rid, "ERR", "unknown " + cmd])


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
