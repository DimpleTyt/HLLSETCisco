# ---------------- common: SHA-1, line protocol over PT tcp ----------------
# Wire format: one message per line, fields separated by "|":  <rid>|<CMD>|<arg>|...
# rid = request id; replies reuse the rid of the request.
# Handshake: client sends "0|HELLO|<name>" until it gets "0|WELCOME|<name>".

TICK = [0]          # main-loop tick counter (0.5 s per tick)
TIMEOUT_TICKS = 30  # 15 s


def log(tag, text):
    print("[" + tag + "] " + text)


def clean(s):
    # strip protocol delimiters from user data
    out = ""
    for ch in s:
        if ch in "|;,:~\n\r\t":
            continue
        out = out + ch
    return out


def tokenize(text):
    toks = []
    for raw in text.lower().split(" "):
        t = ""
        for ch in raw:
            if ch in ".!?\"'()[]{}<>|;,:~\n\r\t":
                continue
            t = t + ch
        if t != "":
            toks.append(t)
    return toks


# ---- SHA-1 on 16-bit halves: word = [lo, hi] ----
def _w(v):
    hi = v // 65536
    return [v - hi * 65536, hi]


def _add(a, b):
    lo = a[0] + b[0]
    c = lo // 65536
    hi = a[1] + b[1] + c
    return [lo - c * 65536, hi % 65536]


def _rotl(x, n):
    lo = x[0]
    hi = x[1]
    if n >= 16:
        lo, hi = hi, lo
        n = n - 16
    if n == 0:
        return [lo, hi]
    return [((lo << n) & 0xFFFF) | (hi >> (16 - n)), ((hi << n) & 0xFFFF) | (lo >> (16 - n))]


def sha1_hex(text):
    d = utf8(text)
    n = len(d)
    d.append(0x80)
    while len(d) % 64 != 56:
        d.append(0)
    bits = n * 8
    tail = []
    for i in range(8):
        q = bits // 256
        tail.append(bits - q * 256)
        bits = q
    for i in range(7, -1, -1):
        d.append(tail[i])
    h = [[0x2301, 0x6745], [0xab89, 0xefcd], [0xdcfe, 0x98ba], [0x5476, 0x1032], [0xe1f0, 0xc3d2]]
    K = [[0x7999, 0x5a82], [0xeba1, 0x6ed9], [0xbcdc, 0x8f1b], [0xc1d6, 0xca62]]
    for blk in range(0, len(d), 64):
        w = []
        for i in range(16):
            j = blk + i * 4
            w.append([(d[j + 2] << 8) | d[j + 3], (d[j] << 8) | d[j + 1]])
        for i in range(16, 80):
            x = [w[i - 3][0] ^ w[i - 8][0] ^ w[i - 14][0] ^ w[i - 16][0],
                 w[i - 3][1] ^ w[i - 8][1] ^ w[i - 14][1] ^ w[i - 16][1]]
            w.append(_rotl(x, 1))
        a = h[0]
        b = h[1]
        c = h[2]
        e4 = h[3]
        e = h[4]
        for i in range(80):
            if i < 20:
                f = [(b[0] & c[0]) | ((0xFFFF - b[0]) & e4[0]), (b[1] & c[1]) | ((0xFFFF - b[1]) & e4[1])]
                k = K[0]
            elif i < 40:
                f = [b[0] ^ c[0] ^ e4[0], b[1] ^ c[1] ^ e4[1]]
                k = K[1]
            elif i < 60:
                f = [(b[0] & c[0]) | (b[0] & e4[0]) | (c[0] & e4[0]),
                     (b[1] & c[1]) | (b[1] & e4[1]) | (c[1] & e4[1])]
                k = K[2]
            else:
                f = [b[0] ^ c[0] ^ e4[0], b[1] ^ c[1] ^ e4[1]]
                k = K[3]
            t = _add(_add(_add(_add(_rotl(a, 5), f), e), k), w[i])
            e = e4
            e4 = c
            c = _rotl(b, 30)
            b = a
            a = t
        h = [_add(h[0], a), _add(h[1], b), _add(h[2], c), _add(h[3], e4), _add(h[4], e)]
    digits = "0123456789abcdef"
    s = ""
    for wd in h:
        for v in (wd[1], wd[0]):
            for k in (12, 8, 4, 0):
                s = s + digits[(v >> k) & 15]
    return s


# ---- line-oriented connection helpers ----
class Line:
    """Wraps a PT TCPClient: buffers input, splits lines, dispatches."""

    def __init__(self, sock, on_line):
        self.sock = sock
        self.buf = ""
        self.on_line = on_line
        me = self

        def on_receive(data):          # PT calls plain functions only, not bound methods
            me._recv(data)
        sock.onReceive(on_receive)

    def _recv(self, data):
        self.buf = self.buf + data
        while "\n" in self.buf:
            i = self.buf.index("\n")
            line = self.buf[:i]
            self.buf = self.buf[i + 1:]
            if line != "":
                try:
                    self.on_line(self, line.split("|"))
                except Exception as e:
                    log("ERR", "handler: " + str(e))

    def send(self, fields):
        try:
            self.sock.send("|".join([str(f) for f in fields]) + "\n")
            return True
        except Exception as e:
            log("NET", "send failed: " + str(e))
            return False


class Server:
    """Listens on a port; handler(conn, rid, cmd, args) answers with conn.send([rid, ...])."""

    def __init__(self, name, port, handler):
        self.name = name
        self.port = port
        self.handler = handler
        self.srv = TCPServer()
        me = self

        def on_new_client(sock):       # PT calls plain functions only, not bound methods
            me._new(sock)
        self.srv.onNewClient(on_new_client)

    def start(self):
        self.srv.listen(self.port)
        log("NET", self.name + " listening on " + str(self.port))

    def _new(self, sock):
        Line(sock, self._line)

    def _line(self, conn, f):
        if len(f) < 2:
            return
        if f[1] == "HELLO":
            conn.send(["0", "WELCOME", self.name])
            return
        try:
            self.handler(conn, f[0], f[1], f[2:])
        except Exception as e:
            log("ERR", f[1] + ": " + str(e))
            conn.send([f[0], "ERR", clean(str(e))])


class Peer:
    """Outgoing connection with HELLO handshake, request ids and timeouts."""

    def __init__(self, name, ip, port):
        self.name = name
        self.ip = ip
        self.port = port
        self.ready = False
        self.conn = None
        self.tries = 0
        self.pending = {}
        self.next_id = [1]

    def _connect(self):
        if self.conn is not None:
            try:
                self.conn.sock.close()
            except Exception:
                pass
        sock = TCPClient()
        self.conn = Line(sock, self._line)
        sock.connect(self.ip, self.port)
        self.tries = 0

    def _line(self, conn, f):
        if len(f) >= 2 and f[0] == "0" and f[1] == "WELCOME":
            if not self.ready:
                log("NET", "connected to " + self.name + " " + self.ip + ":" + str(self.port))
            self.ready = True
            return
        rid = f[0]
        if rid in self.pending:
            cb = self.pending[rid][0]
            del self.pending[rid]
            cb(f[1:])

    def tick(self):
        if self.conn is None or (not self.ready and self.tries >= 20):
            self._connect()
        if not self.ready:
            self.tries = self.tries + 1
            self.conn.send(["0", "HELLO", self.name])
        dead = []
        for rid in self.pending:
            if TICK[0] - self.pending[rid][1] > TIMEOUT_TICKS:
                dead.append(rid)
        for rid in dead:
            cb = self.pending[rid][0]
            del self.pending[rid]
            cb(["ERR", "timeout " + self.name])

    def call(self, fields, cb):
        if not self.ready:
            cb(["ERR", self.name + " not connected"])
            return
        rid = "r" + str(self.next_id[0])
        self.next_id[0] = self.next_id[0] + 1
        self.pending[rid] = [cb, TICK[0]]
        self.conn.send([rid] + fields)


def run(tick_fn):
    while True:
        TICK[0] = TICK[0] + 1
        tick_fn()
        sleep(0.5)
