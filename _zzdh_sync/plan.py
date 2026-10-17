# -*- coding: utf-8 -*-
"""Analyze local scene assets vs existing zzdh locations. Dry-run plan."""
import os, json, io, sys

LOCAL = r"C:\Users\EDY\Desktop\重回80我有了山神系统\场景"
PROJ  = r"D:\字字动画_9_0_9(1)\字字动画_9_0_9\工作目录\默认\10月15日\locations.json"

# proposed: local_folder_prefix -> existing location name (or NEW)
MAP = {
    "01": ("深山老林（日）",        "深山老林"),
    "02": ("山底（日）",            "山底路口"),
    "03": ("刘淑芳家堂屋（日）",    "刘淑芳家屋内"),
    "04": ("深山小径（日）",        "山下小路"),
    "05": ("雪山（日）",            "雪山冰崖"),
    "06": ("林家院子（日）",        "林家院子"),
    "07": ("王建华办公室（日）",    "王建华办公室"),
    "08": ("山海珍酒店大堂（日）",  "山海珍酒店"),
    "09": ("刘淑芳家卧室（夜）",    "刘淑芳家屋内"),
    "10": ("林家堂屋（夜）",        "林家堂屋"),
    "11": ("林辰帐篷（夜）",        "吴长贵扎营地"),
    "12": ("吴长贵扎营地（夜）",    "吴长贵扎营地"),
    "13": ("迷障区（日）",          "迷障区"),
    "14": ("济世药房（内·日）",     "济世药房"),
    "15": ("镇卫生院走廊（日）",    "镇卫生院走廊"),
    "16": ("青山种植基地外围（夜）","青山种植基地"),
}

def local_dirs():
    out = {}
    for d in sorted(os.listdir(LOCAL)):
        full = os.path.join(LOCAL, d)
        if not os.path.isdir(full):
            continue
        files = sorted(os.listdir(full))
        pngs = [f for f in files if f.lower().endswith(".png")]
        main = [f for f in pngs if "反打" not in f]
        rev  = [f for f in pngs if "反打" in f]
        out[d] = {"main": os.path.join(full, main[0]) if main else None,
                  "rev":  os.path.join(full, rev[0]) if rev else None,
                  "extra": [f for f in pngs if f not in main and f not in rev]}
    return out

def existing():
    d = json.load(io.open(PROJ, "r", encoding="utf-8"))
    return {e["name"]: e for e in d["locations"]}, d

if __name__ == "__main__":
    loc = local_dirs()
    ex, raw = existing()
    rows = []
    newname_req = []
    print("LOCAL(%d)  ->  EXISTING(%d)" % (len(loc), len(ex)))
    print("-"*100)
    for prefix, (label, target) in sorted(MAP.items()):
        hitdir = [d for d in loc if d.startswith(prefix + "_")]
        if not hitdir:
            print("!! local folder missing for prefix", prefix); continue
        d = hitdir[0]
        img = loc[d]
        ok = target in ex
        e = ex.get(target)
        cur = len(e["reference_items"]) if e else 0
        rows.append({"prefix": prefix, "local_dir": d, "label": label,
                     "target": target, "target_id": e["location_id"] if e else None,
                     "main": img["main"], "rev": img["rev"], "exists": ok, "cur_refs": cur})
        print("%s %-24s -> #%s %-16s exists=%s refs=%d" % (
            prefix, d, (e["location_id"] if e else "--"), target, ok, cur))
        print("      main: %s" % os.path.basename(img["main"] or "MISSING"))
        print("      rev : %s" % os.path.basename(img["rev"] or "MISSING"))
    # duplicate targets
    from collections import Counter
    c = Counter(r["target"] for r in rows)
    dup = {k: v for k, v in c.items() if v > 1}
    print("-"*100)
    print("DUPLICATE TARGETS (need decision):")
    for k, v in dup.items():
        srcs = [r["label"] for r in rows if r["target"] == k]
        print("  #%s %s  <= %s" % (ex[k]["location_id"], k, " | ".join(srcs)))
    unused = [n for n in ex if n not in {r["target"] for r in rows}]
    print("UNUSED existing locations (%d):" % len(unused))
    for n in unused:
        print("   #%s %s" % (ex[n]["location_id"], n))
    json.dump(rows, io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "plan_rows.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
