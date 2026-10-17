import json
d = json.load(open(r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync\locations_now.json", encoding="utf-8"))
def walk(o):
    if isinstance(o, list): return o
    if isinstance(o, dict):
        for k in ("locations","items","data","entities"):
            if k in o and isinstance(o[k], list): return o[k]
    return []
L = walk(d)
print("type", type(d), "n", len(L))
out=[]
for e in L:
    out.append("%s|%s|%s|%s" % (e.get("id"), e.get("name") or e.get("entity_name") or e.get("title"), (e.get("image_path") or "")[:60], len(e.get("reference_items") or []) if isinstance(e.get("reference_items"), list) else e.get("reference_items")))
open(r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync\_loc_list.txt","w",encoding="utf-8").write("\n".join(out))
