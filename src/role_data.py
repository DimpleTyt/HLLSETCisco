# ================= DATA: identification (green) and access (orange) =================
# Issues access tokens and keeps each user's world: hash configuration (murmur3, seed).
PORT = 5001

USERS = {
    "user1": {"pass": "pass1", "seed": 101},
    "user2": {"pass": "pass2", "seed": 102},
    "user3": {"pass": "pass3", "seed": 103},
}
TOKENS = {}   # token -> user


def new_token():
    digits = "0123456789abcdef"
    s = ""
    for i in range(16):
        s = s + digits[random.randint(0, 15)]
    return s


def handle(conn, rid, cmd, a):
    if cmd == "AUTH":
        user, pw = a[0], a[1]
        u = USERS.get(user)
        if u is None or u["pass"] != pw:
            log("GREEN", "AUTH " + user + " -> DENY")
            conn.send([rid, "DENY", "bad login"])
            return
        tok = new_token()
        TOKENS[tok] = user
        log("ORANGE", "AUTH " + user + " -> token " + tok[:6] + "... world seed=" + str(u["seed"]))
        conn.send([rid, "OK", tok, user])
    elif cmd == "CHECK":
        tok = a[0]
        user = TOKENS.get(tok)
        if user is None:
            log("GREEN", "CHECK " + tok[:6] + "... -> DENY")
            conn.send([rid, "DENY", "invalid token"])
            return
        conn.send([rid, "OK", user, USERS[user]["seed"]])
    elif cmd == "LOGOUT":
        tok = a[0]
        if tok in TOKENS:
            log("GREEN", "LOGOUT " + TOKENS[tok])
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
