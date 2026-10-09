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
# 2) single-board ingest gives same CID as 5-board parallel ingest
toks=ns['tokenize']("the quick brown fox jumps over the lazy dog")
p={}
for tk in toks:
    r,tz=ns['position'](tk,101); p[r*32+tz]=1
print('single-board cid', ns['cid_of'](p))
