# ================= GRID: one lattice for all users + hllsetLUT + token LUTs =================
# One universe (ewm-state-machine): every HLLSet is a node of the same Boolean lattice,
# content-addressed by h:sha1(roaring). Ingest parts from the swarm are unioned per job;
# SEAL registers the result (existence is registration). A user reads nodes only through
# the token LUTs of the user's own ingests (interpretation), never through other users'.
PORT = 5200
JOB_TTL = 240            # ticks (2 min): unfinished swarm jobs are dropped after that

NODES = {}      # content key -> plane                       (registration = existence)
HLUT = {}       # "name\tkey" -> TH   (hllset-morphisms::HllsetLut: (name, key) -> touch count)
NAMES = {}      # "user/name" -> key                          (user's handle on a node)
RECS = {}       # "user/name" -> ingest record (G1-G3, slide4, LUTs, TF, n)
VERS = {}       # "user/name" -> number of versions sealed under this name
ULUT = {}       # user -> [lut G1, lut G2, lut G3]  join of the user's ingest LUTs
JOBS = {}       # "user/job" -> {"parts": {i: fields}, "tick": t}
SYSTEM = {}     # H_system = union of every registered node (monotone)


def register(p):
    cid = cid_of(p)
    if cid not in NODES:
        NODES[cid] = p
        for k in p:
            SYSTEM[k] = 1
    return cid


def hlut_touch(name, key):
    # register_named + touch_named
    k = name + "\t" + key
    HLUT[k] = HLUT.get(k, 0) + 1


def resolve(user, ref):
    if ref.startswith("h:"):
        return NODES.get(ref)
    cid = NAMES.get(user + "/" + ref)
    if cid is None:
        return None
    return NODES[cid]


def merge(conn, rid, a):
    # MERGE|user|job|part|g1|g2|g3|s4|lut1|lut2|lut3|tf   (idempotent per part: a retry overwrites)
    user, job, part = a[0], a[1], int(a[2])
    if len(a) < 11:
        conn.send([rid, "ERR", "MERGE needs 11 fields"])
        return
    rec_from(a[3:11], 0)                 # validate before storing
    jk = user + "/" + job
    j = JOBS.get(jk)
    if j is None:
        j = {"parts": {}, "tick": TICK[0]}
        JOBS[jk] = j
    j["parts"][part] = a[3:11]
    j["tick"] = TICK[0]
    conn.send([rid, "OK", part, len(j["parts"])])


def seal_job(conn, rid, a):
    # SEAL|user|job|name|n|parts -> union of all parts = one Rust ingest() of the text
    user, job, name, n, nparts = a[0], a[1], a[2], int(a[3]), int(a[4])
    jk = user + "/" + job
    j = JOBS.get(jk)
    if j is None:
        conn.send([rid, "ERR", "no such job"])
        return
    for i in range(nparts):
        if i not in j["parts"]:
            conn.send([rid, "ERR", "part " + str(i) + " missing"])
            return
    rec = {"g": [{}, {}, {}], "s4": {}, "luts": [{}, {}, {}], "tf": {}, "n": n}
    for i in range(nparts):
        p = rec_from(j["parts"][i], n)
        for ch in range(3):
            for b in p["g"][ch]:
                rec["g"][ch][b] = 1
            for b in p["luts"][ch]:
                fib = rec["luts"][ch].get(b)
                if fib is None:
                    fib = {}
                    rec["luts"][ch][b] = fib
                for t in p["luts"][ch][b]:
                    fib[t] = 1
        for b in p["s4"]:
            rec["s4"][b] = 1
        for t in p["tf"]:
            rec["tf"][t] = rec["tf"].get(t, 0) + p["tf"][t]
    total = 0
    for t in rec["tf"]:
        total = total + rec["tf"][t]
    if total != n:
        conn.send([rid, "ERR", "token count mismatch " + str(total) + "/" + str(n)])
        return
    del JOBS[jk]
    seal(rec)
    key = register(rec["proj"])
    for ch in range(3):
        register(rec["g"][ch])
        hlut_touch(CHANNEL_NAMES[ch], rec["keys"][ch])
    nk = user + "/" + name
    prev = "-"
    old = RECS.get(nk)
    if old is not None:
        # named HLLSets are immutable: the old version stays registered as name@v,
        # the new one takes the name. H(t) = (S(t), H(t-1), D, R, N)
        v = VERS.get(nk, 1)
        RECS[nk + "@" + str(v)] = old
        NAMES[nk + "@" + str(v)] = old["key"]
        VERS[nk] = v + 1
        h0 = old["proj"]
        s1 = rec["proj"]
        prev = (name + "@" + str(v) + " " + old["key"][:14] + " D=" + str(len(p_diff(h0, s1))) +
                " R=" + str(len(p_inter(h0, s1))) + " N=" + str(len(p_diff(s1, h0))))
    else:
        VERS[nk] = 1
    RECS[nk] = rec
    NAMES[nk] = key
    w = ULUT.get(user)
    if w is None:
        w = [{}, {}, {}]
        ULUT[user] = w
    for ch in range(3):
        lut_from(lut_str(rec["luts"][ch]), w[ch])
    log("BLUE", "SEAL " + nk + " parts=" + str(nparts) + " -> " + key[:14] + " pop=" + str(len(rec["proj"])))
    conn.send([rid, "OK", key, len(rec["proj"]), ",".join([k[:14] for k in rec["keys"]]), prev])


def handle(conn, rid, cmd, a):
    if cmd == "MERGE":
        merge(conn, rid, a)
    elif cmd == "SEAL":
        seal_job(conn, rid, a)
    elif cmd == "GET":
        user, ref = a[0], a[1]
        p = resolve(user, ref)
        if p is None:
            conn.send([rid, "ERR", "no such set " + ref])
            return
        conn.send([rid, "OK", cid_of(p), plane_str(p)])
    elif cmd == "REC":
        # the full ingest record (for the ordered materialize on a board)
        user, ref = a[0], a[1]
        rec = RECS.get(user + "/" + ref)
        if rec is None:
            conn.send([rid, "NOREC", ref])
            return
        conn.send([rid, "OK", rec["key"], rec["n"]] + rec_fields(rec))
    elif cmd == "PUT":
        # register a computed node under a user's name (existence is registration)
        user, name, pos = a[0], a[1], a[2]
        if (user + "/" + name) in RECS:
            conn.send([rid, "ERR", "name belongs to an ingest " + name])
            return
        p = plane_from(pos)
        cid = register(p)
        NAMES[user + "/" + name] = cid
        log("BLUE", "PUT " + user + "/" + name + " -> " + cid[:14] + " pop=" + str(len(p)))
        conn.send([rid, "OK", cid, len(p)])
    elif cmd == "LOOKUP":
        # materialize a computed node: LUT-first over THIS user's LUTs only,
        # every candidate of an active bit is kept (probabilistic restoration)
        user, pos = a[0], a[1]
        w = ULUT.get(user, [{}, {}, {}])
        out = {}
        for k in plane_from(pos):
            for ch in range(3):
                fib = w[ch].get(k)
                if fib is not None:
                    for t in fib:
                        out[t] = 1
        toks = sort_bytes(out.keys())
        conn.send([rid, "OK", len(toks), " ".join(toks) if len(toks) > 0 else "-"])
    elif cmd == "LIST":
        user = a[0]
        names = []
        for key in NAMES:
            if key.startswith(user + "/"):
                mark = "*" if key in RECS else ""
                names.append(key[len(user) + 1:] + mark + "=" + NAMES[key][:14])
        conn.send([rid, "OK", len(names), " ".join(sorted(names)) if len(names) > 0 else "-"])
    elif cmd == "STAT":
        # per-user view only: global counters would leak other users' activity
        user = a[0]
        nn = 0
        nr = 0
        for key in NAMES:
            if key.startswith(user + "/"):
                nn = nn + 1
                if key in RECS:
                    nr = nr + 1
        w = ULUT.get(user, [{}, {}, {}])
        conn.send([rid, "OK", "names=" + str(nn), "ingests=" + str(nr),
                   "lut_bits=" + str(len(w[0]) + len(w[1]) + len(w[2]))])
    elif cmd == "HLUT":
        # hllsetLUT ranked (TH desc, name, key) restricted to the user's own channel keys
        user = a[0]
        mine = {}
        for key in RECS:
            if key.startswith(user + "/"):
                for ch in range(3):
                    mine[CHANNEL_NAMES[ch] + "\t" + RECS[key]["keys"][ch]] = 1
        rows = []
        for k in mine:
            rows.append(str(10000000 - HLUT.get(k, 0)) + "\t" + k)
        out = []
        for r in sorted(rows):
            f = r.split("\t")
            out.append(f[1] + ":" + f[2][:14] + ":" + str(10000000 - int(f[0])))
        conn.send([rid, "OK", len(out), " ".join(out) if len(out) > 0 else "-"])
    else:
        conn.send([rid, "ERR", "unknown " + cmd])


SERVER = Server("GRID", PORT, handle)


def tick():
    old = []
    for jk in JOBS:
        if TICK[0] - JOBS[jk]["tick"] > JOB_TTL:
            old.append(jk)
    for jk in old:
        log("GRID", "drop unfinished job " + jk)
        del JOBS[jk]
    if TICK[0] % 120 == 0:
        log("GRID", "nodes=" + str(len(NODES)) + " system_pop=" + str(len(SYSTEM)) + " worlds=" + str(len(ULUT)) +
            " hllsetLUT=" + str(len(HLUT)) + " jobs=" + str(len(JOBS)))


def main():
    log("GRID", "shared lattice starting")
    SERVER.start()
    run(tick)
