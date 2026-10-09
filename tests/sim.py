import sys, types, random, io, contextlib
import inspect
def plain(cb):
    return None if inspect.ismethod(cb) else cb   # emulate PT: bound methods never fire
BUILD = sys.argv[1]
rnd = random.Random(42)
CUR = ['']
EVENTS = []
SERVERS = {}
LOGS = {}

def allowed(src, dst, port):
    vl = lambda ip: ip.split('.')[2]
    if vl(src) == vl(dst): return True
    if vl(src) == '10': return dst == '192.168.20.20' and port == 5000
    if src == '192.168.20.20': return vl(dst) == '30' and port == 5100
    if vl(src) == '30': return dst == '192.168.40.10' and port == 5200
    return False

class TCPClient:
    def __init__(self):
        self.owner = CUR[0]; self.peer = None; self.rx = None; self.cc = None; self.rip = ''
    def onReceive(self, cb): self.rx = plain(cb)
    def onConnectionChange(self, cb): self.cc = plain(cb)
    def remoteIP(self): return self.rip
    def connect(self, ip, port):
        self.rip = ip
        srv = SERVERS.get((ip, port))
        if srv is None or not allowed(self.owner, ip, port): return True
        p = TCPClient.__new__(TCPClient); p.owner = ip; p.rx = None; p.cc = None; p.rip = self.owner
        p.peer = self; self.peer = p
        EVENTS.append((ip, lambda: srv.cb and srv.cb(p)))
        return True
    def send(self, data):
        if self.peer is None: return
        peer = self.peer
        # random chunking to test line buffering
        chunks = []
        while data:
            n = rnd.randint(1, max(1, len(data)))
            chunks.append(data[:n]); data = data[n:]
        for c in chunks:
            EVENTS.append((peer.owner, (lambda c=c: peer.rx and peer.rx(c))))
    def close(self):
        if self.peer: self.peer.peer = None
        self.peer = None

class TCPServer:
    def __init__(self): self.owner = CUR[0]; self.cb = None
    def onNewClient(self, cb): self.cb = plain(cb)
    def listen(self, port): SERVERS[(self.owner, port)] = self
    def stop(self): pass

tcp = types.ModuleType('tcp'); tcp.TCPClient = TCPClient; tcp.TCPServer = TCPServer; tcp.__all__ = ['TCPClient', 'TCPServer']
tm = types.ModuleType('time'); tm.sleep = lambda s: None; tm.__all__ = ['sleep']
sys.modules['tcp'] = tcp; sys.modules['time'] = tm

DEVICES = [('GRID','192.168.40.10','GRID.py')] + [('FPGA%d'%i,'192.168.30.%d'%(10+i),'FPGA%d.py'%i) for i in range(1,6)] + \
          [('DATA','192.168.20.10','DATA.py'),('DISPATCHER','192.168.20.20','DISPATCHER.py')] + \
          [('user%d'%i,'192.168.10.%d'%(99+i),'USER'+str(i)+'.py') for i in (1,2,3)]
NS = {}
def call(ip, fn):
    CUR[0] = ip
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): fn()
    for line in buf.getvalue().splitlines(): LOGS.setdefault(ip, []).append(line)

for name, ip, f in DEVICES:
    src = open(BUILD + '/' + f).read()
    if name.startswith('user'):
        n = name[-1]
        src = src.replace('USER = "user1"', 'USER = "user%s"' % n).replace('PASSWORD = "pass1"', 'PASSWORD = "pass%s"' % n)
    ns = {'__name__': 'pt_' + name}
    call(ip, lambda: exec(compile(src, f, 'exec'), ns))
    NS[name] = (ip, ns)
    if 'SERVER' in ns: call(ip, ns['SERVER'].start)

for t in range(400):
    for name, (ip, ns) in NS.items():
        def tk(ns=ns):
            ns['TICK'][0] += 1; ns['tick']()
        call(ip, tk)
    guard = 0
    while EVENTS and guard < 100000:
        ip, ev = EVENTS.pop(0); call(ip, ev); guard += 1

for name, (ip, ns) in NS.items():
    print('=====', name, ip)
    for l in LOGS.get(ip, []): print('  ', l)
