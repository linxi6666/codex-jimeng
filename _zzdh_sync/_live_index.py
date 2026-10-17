import json, os, sys
HERE = r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync"
sys.path.insert(0, HERE)
import api
r = api.call("zzdh_get_panels", {}, timeout=120)
with open(os.path.join(HERE, "panels_live.json"), "w", encoding="utf-8") as f:
    json.dump(r, f, ensure_ascii=False, indent=1)
ps = r.get("panels") or []
lines = []
for i, p in enumerate(ps, 1):
    pw = (p.get("paperwork") or "").replace("\n", "/")
    vp = p.get("video_prompt") or ""
    lines.append("idx=%d un=%s vp=%d | %s" % (i, p.get("unique_name"), len(vp), pw[:70]))
with open(os.path.join(HERE, "index_live.txt"), "w", encoding="utf-8") as f:
    f.write("total=%d\n" % r.get("total", len(ps)) + "\n".join(lines))
print("ok", r.get("total"), len(ps))
