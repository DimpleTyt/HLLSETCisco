# ================= GRID: shared HLLSet lattice + hllsetLUT + per-world token LUTs =================
# One lattice for all users (one universe). Nodes are content-addressed (CID = h:<sha1>).
# A user's world is read only through that user's LUT (virtual isolation by interpretation).
PORT = 5200

NODES = {}      # hllsetLUT: cid -> plane                 (registration = existence)
NAMES = {}      # (user, name) -> cid                     (user's handle on a node)
LUT = {}        # user -> {position: {token: tf}}         (world interpretation, TF counts)
SYSTEM = {}     # H_system = union of everything ever registered (monotone)


def register(p):
    cid = cid_of(p)
    if cid not in NODES:
        NODES[cid] = p
        for k in p:
            SYSTEM[k] = 1
    return cid


def resolve(user, ref):
    if ref.startswith("h:"):
        return NODES.get(ref)
    cid = NAMES.get(user + "/" + ref)
    if cid is None:
        return None
    return NODES[cid]


def handle(conn, rid, cmd, a):
    if cmd == "MERGE":
        # MERGE|user|name|positions|pos:token;pos:token
        user, name, pos, lut = a[0], a[1], a[2], a[3]
        old = resolve(user, name)
        new = plane_from(pos)
        p = p_union(old if old is not None else {}, new)     # monotone join
        cid = register(p)
        NAMES[user + "/" + name] = cid
        w = LUT.get(user)
        if w is None:
            w = {}
            LUT[user] = w
        if lut != "-" and lut != "":
            for e in lut.split(";"):
                kv = e.split(":")
                k = int(kv[0])
                fib = w.get(k)
                if fib is None:
                    fib = {}
                    w[k] = fib
                fib[kv[1]] = fib.get(kv[1], 0) + 1
        log("BLUE", "MERGE " + user + "/" + name + " +" + str(len(new)) + " bits -> " + cid[:14] + " pop=" + str(len(p)))
        conn.send([rid, "OK", cid, len(p)])
    elif cmd == "GET":
        user, ref = a[0], a[1]
        p = resolve(user, ref)
        if p is None:
            conn.send([rid, "ERR", "no such set " + ref])
            return
        conn.send([rid, "OK", cid_of(p), plane_str(p)])
    elif cmd == "PUT":
        # register a computed node under a user's name (existence is registration)
        user, name, pos = a[0], a[1], a[2]
        p = plane_from(pos)
        cid = register(p)
        NAMES[user + "/" + name] = cid
        log("BLUE", "PUT " + user + "/" + name + " -> " + cid[:14] + " pop=" + str(len(p)))
        conn.send([rid, "OK", cid, len(p)])
    elif cmd == "LOOKUP":
        # materialize: read active bits through THIS user's LUT only
        user, pos = a[0], a[1]
        w = LUT.get(user, {})
        out = {}
        for k in plane_from(pos):
            fib = w.get(k)
            if fib is not None:
                for t in fib:
                    out[t] = 1
        toks = sorted(out.keys())
        conn.send([rid, "OK", len(toks), " ".join(toks) if len(toks) > 0 else "-"])
    elif cmd == "LIST":
        user = a[0]
        names = []
        for key in NAMES:
            if key.startswith(user + "/"):
                names.append(key[len(user) + 1:] + "=" + NAMES[key][:14])
        conn.send([rid, "OK", len(names), " ".join(sorted(names)) if len(names) > 0 else "-"])
    elif cmd == "STAT":
        conn.send([rid, "OK", "nodes=" + str(len(NODES)), "system_pop=" + str(len(SYSTEM)), "worlds=" + str(len(LUT))])
    else:
        conn.send([rid, "ERR", "unknown " + cmd])


SERVER = Server("GRID", PORT, handle)


def tick():
    if TICK[0] % 120 == 0:
        log("GRID", "nodes=" + str(len(NODES)) + " system_pop=" + str(len(SYSTEM)) + " worlds=" + str(len(LUT)))


def main():
    log("GRID", "shared lattice starting")
    SERVER.start()
    run(tick)
