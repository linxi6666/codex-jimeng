import json, sys, time
sys.path.insert(0, r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync")
from api import call
t0=time.time()
try:
    r = call("zzdh_llm_chat", {"messages":[{"role":"user","content":"只回复两个字：可以"}], "parse_mode":"raw", "timeout_seconds":120}, timeout=300)
    print("elapsed %.1fs" % (time.time()-t0))
    s = json.dumps(r, ensure_ascii=False)
    print("keys:", list(r.keys()) if isinstance(r, dict) else type(r))
    print(s[:1500])
except Exception as e:
    print("err", repr(e)[:500])