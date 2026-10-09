# ================= USER client (host side): tokenizes, sends work, computes floats =================
USER = "user1"            # <-- user1 / user2 / user3
PASSWORD = "pass1"        # <-- pass1 / pass2 / pass3
DISP = Peer("DISPATCHER", "192.168.20.20", 5000)

TEXT_A = "the quick brown fox jumps over the lazy dog"
TEXT_B = "the quick red fox runs past the sleepy cat"

SCENARIOS = {
    # full walk through the model
    "user1": [
        ["STATUS"],
        ["LOGIN"],
        ["INGEST", "doc1", TEXT_A],
        ["INGEST", "doc2", TEXT_B],
        ["QUERY", "INFO", "doc1"],
        ["QUERY", "UNION", "doc1", "doc2"],
        ["QUERY", "INTERSECT", "doc1", "doc2"],
        ["QUERY", "DRN", "doc1", "doc2"],
        ["QUERY", "HIST", "doc1"],
        ["QUERY", "LOOKUP", "doc1*doc2"],
        ["QUERY", "LIST"],
        ["QUERY", "STAT"],
    ],
    # same text as user1/doc1, other world (seed): other bits, other CID
    "user2": [
        ["LOGIN"],
        ["INGEST", "doc1", TEXT_A],
        ["QUERY", "INFO", "doc1"],
        ["QUERY", "LOOKUP", "doc1"],
        ["QUERY", "STAT"],
    ],
    # security checks: bad password, fake token, direct access to a board (ACL)
    "user3": [
        ["LOGIN_BAD"],
        ["FAKE_TOKEN"],
        ["DIRECT", "192.168.30.11", "5100"],
        ["LOGIN"],
        ["INGEST", "notes", "hllset worlds share one lattice"],
        ["QUERY", "HIST", "notes"],
    ],
}

STATE = {"step": 0, "wait": False, "token": "", "direct": None, "direct_ticks": 0}


def cardinality(counts):
    # Horvitz-Thompson estimate from the 32 integer counts c_s (float math stays on the host)
    n = 1024.0
    total = 0.0
    for c in counts:
        if c <= 0:
            continue
        if c >= 1024:
            total = total + n * math.log(n)
        else:
            total = total + (-n * math.log(1.0 - c / n))
    return int(total + 0.5)


def show(step, r):
    title = " ".join(step[:4]) if step[0] != "INGEST" else "INGEST " + step[1]
    if len(step) > 1 and step[0] == "QUERY" and step[1] == "HIST" and r[0] == "OK":
        counts = [int(x) for x in r[3].split(",")]
        log("USER", title + " -> c_s=" + r[3] + "  card~" + str(cardinality(counts)))
        return
    log("USER", title + " -> " + " | ".join(r))


def finish(step, r):
    show(step, r)
    STATE["wait"] = False
    STATE["step"] = STATE["step"] + 1


def run_step(step):
    cmd = step[0]
    STATE["wait"] = True
    if cmd == "STATUS":
        DISP.call(["STATUS"], lambda r: finish(step, r))
    elif cmd == "LOGIN" or cmd == "LOGIN_BAD":
        pw = PASSWORD if cmd == "LOGIN" else "wrong"

        def got(r):
            if r[0] == "OK":
                STATE["token"] = r[1]
                r = ["OK", "token " + r[1][:6] + "..."]
            finish(step, r)
        DISP.call(["LOGIN", USER, pw], got)
    elif cmd == "FAKE_TOKEN":
        DISP.call(["QUERY", "0000000000000000", "LIST"], lambda r: finish(step, r))
    elif cmd == "INGEST":
        DISP.call(["INGEST", STATE["token"], step[1], clean(step[2])], lambda r: finish(step, r))
    elif cmd == "QUERY":
        DISP.call(["QUERY", STATE["token"]] + step[1:], lambda r: finish(step, r))
    elif cmd == "DIRECT":
        STATE["direct"] = Peer("FPGA-direct", step[1], int(step[2]))
        STATE["direct_ticks"] = 0


def tick():
    DISP.tick()
    d = STATE["direct"]
    if d is not None:
        d.tick()
        STATE["direct_ticks"] = STATE["direct_ticks"] + 1
        if d.ready:
            STATE["direct"] = None
            finish(SCENARIOS[USER][STATE["step"]], ["OPEN", "board reachable directly - check ACL!"])
        elif STATE["direct_ticks"] > 12:
            STATE["direct"] = None
            finish(SCENARIOS[USER][STATE["step"]], ["BLOCKED", "no answer from board (ACL works)"])
        return
    steps = SCENARIOS[USER]
    if STATE["step"] >= len(steps):
        if STATE["step"] == len(steps):
            log("USER", "scenario finished")
            STATE["step"] = STATE["step"] + 1
        return
    if not STATE["wait"] and DISP.ready:
        run_step(steps[STATE["step"]])


def main():
    log("USER", USER + " client starting")
    run(tick)
