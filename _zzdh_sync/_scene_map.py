import re, json, os
HERE = r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync"
d = json.load(open(os.path.join(HERE,"panels_live.json"), encoding="utf-8"))
ps = d["panels"]
filled = [i for i,p in enumerate(ps,1) if (p.get("video_prompt") or "").strip()]
print("filled vp:", filled)
hdr = []
for i,p in enumerate(ps,1):
    pw = p.get("paperwork") or ""
    m = re.search(r"第[一二三四五六七八九十百零\d]+集", pw)
    if m:
        hdr.append((i, pw.replace("\n","/")[:60]))
print("headers:", len(hdr))
for i,t in hdr[:20]: print(" ", i, t)
print("...")
for i,t in hdr[-4:]: print(" ", i, t)
