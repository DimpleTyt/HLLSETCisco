# ================= DATA: identification (green) and access (orange) =================
# Issues access tokens. In ewm-state-machine there is ONE universe with fixed channel
# seeds [0, 1, 2] (+3 for slide4): a user's world is the interpretation of the shared
# lattice through the user's own token LUTs, not a private hash seed.
PORT = 5001
TOKEN_TTL = 3600          # ticks (30 min)
MAX_FAILS = 5             # wrong passwords in a row -> lock
LOCK_TICKS = 120          # 60 s

USERS = {
    "user1": {"pass": "pass1"},
    "user2": {"pass": "pass2"},
    "user3": {"pass": "pass3"},
}
TOKENS = {}   # token -> [user, issued tick]
FAILS = {}    # user -> [count, locked until tick]


def new_token():
    digits = "0123456789abcdef"
    s = ""
    for i in range(32):
        s = s + digits[random.randint(0, 15)]
    return s


def handle(conn, rid, cmd, a):
    if cmd == "AUTH":
        user, pw = a[0], a[1]
        f = FAILS.get(user, [0, 0])
        if f[1] > TICK[0]:
            log("GREEN", "AUTH " + user + " -> LOCKED")
            conn.send([rid, "DENY", "locked, try later"])
            return
        u = USERS.get(user)
        if u is None or u["pass"] != pw:
            f[0] = f[0] + 1
            if f[0] >= MAX_FAILS:
                f = [0, TICK[0] + LOCK_TICKS]
            FAILS[user] = f
            log("GREEN", "AUTH " + user + " -> DENY")
            conn.send([rid, "DENY", "bad login"])
            return
        FAILS[user] = [0, 0]
        tok = new_token()
        TOKENS[tok] = [user, TICK[0]]
        log("ORANGE", "AUTH " + user + " -> token " + tok[:6] + "...")
        conn.send([rid, "OK", tok, user])
    elif cmd == "CHECK":
        tok = a[0]
        t = TOKENS.get(tok)
        if t is not None and TICK[0] - t[1] > TOKEN_TTL:
            del TOKENS[tok]
            t = None
        if t is None:
            log("GREEN", "CHECK " + tok[:6] + "... -> DENY")
            conn.send([rid, "DENY", "invalid token"])
            return
        conn.send([rid, "OK", t[0]])
    elif cmd == "LOGOUT":
        tok = a[0]
        if tok in TOKENS:
            log("GREEN", "LOGOUT " + TOKENS[tok][0])
            del TOKENS[tok]
        conn.send([rid, "OK"])
    else:
        conn.send([rid, "ERR", "unknown " + cmd])


SERVER = Server("DATA", PORT, handle)


def tick():
    pass


def main():
    log("DATA", "identification server starting, users: " + " ".join(sorted(USERS.keys())))
    SERVER.start()
    run(tick)
