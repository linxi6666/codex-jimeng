# -*- coding: utf-8 -*-
"""Apply scene-image sync into zzdh locations.json (reference_items).
Usage:
  python apply.py --only 02            # patch just local prefix 02
  python apply.py --all                # patch all mapped prefixes
  python apply.py --only 02 --dry      # show what would change
Always writes a timestamped backup first.
"""
import os, json, io, sys, time, hashlib, shutil, argparse

PROJ = r"D:\字字动画_9_0_9(1)\字字动画_9_0_9\工作目录\默认\10月15日\locations.json"
HERE = os.path.dirname(os.path.abspath(__file__))

def refid(loc_id, idx, filename, path):
    h = hashlib.md5(path.encode("utf-8")).hexdigest()[:12]
    return "entity-ref-image-%s-%d-%s-%s" % (loc_id, idx, filename, h)

def build(rows):
    d = json.load(io.open(PROJ, "r", encoding="utf-8"))
    byname = {e["name"]: e for e in d["locations"]}
    changes = []
    for r in rows:
        e = byname.get(r["target"])
        if e is None:
            changes.append({"row": r, "error": "target not found"}); continue
        items = []
        for i, p in enumerate([r["main"], r["rev"]]):
            if not p or not os.path.exists(p):
                continue
            items.append({"path": p, "media_type": "image",
                          "reference_id": refid(e["location_id"], i, os.path.basename(p), p)})
        old = e.get("reference_items") or []
        e["reference_items"] = items
        changes.append({"row": r, "loc_id": e["location_id"], "name": e["name"],
                        "old_refs": len(old), "new_refs": len(items),
                        "paths": [it["path"] for it in items]})
    return d, changes

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    rows = json.load(io.open(os.path.join(HERE, "plan_rows.json"), "r", encoding="utf-8"))
    sel = rows if a.all else [r for r in rows if r["prefix"] in a.only]
    if not sel:
        print("no rows selected"); sys.exit(2)
    d, changes = build(sel)
    for c in changes:
        if "error" in c:
            print("ERROR", c["row"]["label"], c["error"]); continue
        print("#%s %-16s refs %d -> %d" % (c["loc_id"], c["name"], c["old_refs"], c["new_refs"]))
        for p in c["paths"]:
            print("      +", p)
    if a.dry:
        print("[dry-run] no write"); sys.exit(0)
    bak = PROJ + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(PROJ, bak)
    tmp = PROJ + ".tmp-write"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PROJ)
    print("WROTE", PROJ)
    print("BACKUP", bak)
