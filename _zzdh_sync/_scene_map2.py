import json, re, os
HERE = r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync"
d = json.load(open(os.path.join(HERE,"panels_live.json"), encoding="utf-8"))
ps = d["panels"]
out = []
out.append("total=%d" % d.get("total") or len(ps))
filled = [i for i,p in enumerate(ps,1) if (p.get("video_prompt") or "").strip()]
out.append("filled video_prompt at: %s" % filled)
# episode markers
ep = re.compile(r"第([一二三四五六七八九十百零\d]+)集")
sc = re.compile(r"(\d+)(日|夜)(内|外)([^\n]{0,20})")
hdr = []
for i,p in enumerate(ps,1):
    pw = p.get("paperwork") or ""
    m = ep.search(pw)
    s = sc.search(pw)
    if m or s:
        hdr.append((i, m.group(0) if m else "", s.group(0) if s else "", (pw.replace("\n","/")[:50])))
out.append("markers=%d" % len(hdr))
for i,e,sn,t in hdr:
    out.append("%4d | %-6s | %-18s | %s" % (i,e,sn,t))
open(os.path.join(HERE,"scene_map.txt"),"w",encoding="utf-8").write("\n".join(out))
print("done", len(hdr))
