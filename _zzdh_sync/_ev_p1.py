import sys, os, json
sys.path.insert(0, r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync")
from api import call
out = call("zzdh_get_edit_view_data", {"unique_name":"twr4svhxpb"}, timeout=60)
p = r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync\_ev_p1.json"
json.dump(out, open(p,"w",encoding="utf-8"), ensure_ascii=False, indent=1)
d = out.get("data", out)
print("topkeys:", list(out.keys())[:10])
if isinstance(d, dict):
    print("datakeys:", list(d.keys()))
