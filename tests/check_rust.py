"""Checks the PT Python port against golden vectors produced by the Rust crates of
ewm-state-machine (hllset-morphisms::ingest / materialize, HLLSet::content_key,
cardinality_ht). Usage:  python tests/check_rust.py src
"""
import sys, json, math, os, types
SRC = sys.argv[1] if len(sys.argv) > 1 else "src"
tcp = types.ModuleType("tcp"); tcp.TCPServer = object; tcp.TCPClient = object; tcp.__all__ = []
sys.modules["tcp"] = tcp
ns = {"__name__": "lib", "math": math}
for m in ["hll16.py", "net.py", "planes.py", "morph.py", "card.py"]:
    exec(compile(open(os.path.join(SRC, m), encoding="utf-8").read(), m, "exec"), ns)
gold = json.load(open(os.path.join(os.path.dirname(__file__), "rust_golden.json"), encoding="utf-8"))
bad = 0
for c in gold:
    rec = ns["seal"](ns["ingest_all"](c["tokens"]))
    got = [rec["key"], rec["keys"], ns["materialize_ordered"](rec)[0], ns["unordered_tokens"](rec),
           ns["cardinality"](ns["p_hist"](rec["proj"]))]
    exp = [c["key"], c["keys"], c["ordered"], c["no_order"], int(c["card"])]
    if got != exp:
        bad += 1
        print("MISMATCH", " ".join(c["tokens"]))
print("rust golden cases", len(gold), "mismatch", bad)
