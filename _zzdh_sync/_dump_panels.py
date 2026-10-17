import json, os
HERE = r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync"
d = json.load(open(os.path.join(HERE,"panels_live.json"), encoding="utf-8"))
ps = d["panels"]
out=[]
for i in [2,4,5,6,7,8,9]:
    p = ps[i-1]
    out.append("="*70)
    out.append("idx=%d un=%s chars=%s locs=%s items=%s hasimg=%s" % (i,p["unique_name"],p.get("selected_character_ids"),p.get("selected_locations"),p.get("selected_items"),p.get("has_images")))
    out.append("--paperwork--")
    out.append((p.get("paperwork") or "").strip())
    out.append("--prompt(img)--")
    out.append((p.get("prompt") or "").strip()[:400])
open(os.path.join(HERE,"sample_panels_2_9.txt"),"w",encoding="utf-8").write("\n".join(out))
print("ok")
