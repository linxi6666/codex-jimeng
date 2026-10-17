import json, sys
sys.path.insert(0, r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync")
from api import call
r = call("zzdh_get_edit_view_data", {"unique_name": "twr4svhxpb"}, timeout=120)
def walk(o, path="", depth=0, out=None):
    if out is None: out = []
    if depth > 3: return out
    if isinstance(o, dict):
        for k, v in o.items():
            p = path + "/" + str(k)
            if isinstance(v, (dict, list)):
                walk(v, p, depth+1, out)
            else:
                out.append((p, v))
    elif isinstance(o, list):
        out.append((path + "[]", "list len=%d" % len(o)))
        if o: walk(o[0], path + "[0]", depth+1, out)
    return out
rows = walk(r)
keep = [x for x in rows if not any(s in x[0].lower() for s in ("base64","image_data"))]
for p, v in keep[:200]:
    s = str(v)
    if len(s) > 120: s = s[:120] + "..."
    print(p, "=", s)
print("TOTAL_KEYS", len(rows))