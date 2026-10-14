import sys, types, hashlib, random, string
sys.modules['tcp']=types.ModuleType('tcp'); m=sys.modules['tcp']; m.TCPServer=type('S',(),{'onNewClient':lambda s,c:None}); m.TCPClient=object; m.__all__=['TCPServer','TCPClient']
t=types.ModuleType('time'); t.sleep=lambda s:None; t.__all__=['sleep']; sys.modules['time']=t
ns={'__name__':'x'}; exec(open(sys.argv[1]+'/GRID.py').read(), ns)
# 1) sha1 vs hashlib
random.seed(3); bad=0
for n in list(range(0,130))+[1000]:
    s=''.join(random.choice(string.ascii_letters+',0123456789я') for _ in range(n))
    if ns['sha1_hex'](s)!=hashlib.sha1(s.encode()).hexdigest(): bad+=1
print('sha1 mismatches', bad)
# 2) swarm ingest (any split of window positions) gives the same CID as one Rust ingest()
toks=ns['tokenize']("the quick brown fox jumps over the lazy dog")
rec=ns['seal'](ns['ingest_all'](toks))
print('single-board cid', rec['key'], 'expected h:7d9a5e9f037701086178d45f191e35fae6d0c062')
