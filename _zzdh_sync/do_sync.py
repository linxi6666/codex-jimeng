# -*- coding: utf-8 -*-
"""Execute the confirmed scene-image sync into zzdh (ZiziGenerator)."""
import os, sys, json, io, time, shutil, hashlib, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import api
from plan import local_dirs, MAP, LOCAL, PROJ

LOG = os.path.join(HERE, "sync_run.log")
_log = io.open(LOG, "w", encoding="utf-8")
def log(*a):
    s = " ".join(str(x) for x in a)
    _log.write(s + "\n"); _log.flush()

# user-confirmed: create NEW for these, instead of forcing onto an existing scene
NEW = {
    "04": ("深山小径", "场景名称“深山小径”，深山中的窄小山路，日间，两侧灌木落叶，路面仅容一人通过，深处幽暗"),
    "09": ("刘淑芳家卧室", "场景名称“刘淑芳家卧室”，刘淑芳家的土炕卧室，夜晚，油灯昏黄，土墙木窗，被褥朴素"),
    "11": ("林辰帐篷", "场景名称“林辰帐篷”，深山扎营地中林辰的简易帐篷，夜晚，帐内昏暗，铺盖与勘查用具散放"),
}

def refid(loc_id, idx, fn, path):
    return "entity-ref-image-%s-%d-%s-%s" % (loc_id, idx, fn, hashlib.md5(path.encode("utf-8")).hexdigest()[:12])

def entities():
    r = api.call("zzdh_get_entity_list", {"entity_type": "location"})
    return r["entities"]

def patch_file(targets, info):
    d = json.load(io.open(PROJ, "r", encoding="utf-8"))
    byname = {e["name"]: e for e in d["locations"]}
    for prefix, name in targets.items():
        e = byname.get(name)
        if e is None:
            log("PATCH MISS", prefix, name); continue
        items = []
        for i, p in enumerate([info[prefix]["main"], info[prefix]["rev"]]):
            if p and os.path.exists(p):
                items.append({"path": p, "media_type": "image",
                              "reference_id": refid(e["location_id"], i, os.path.basename(p), p)})
        e["reference_items"] = items
    tmp = PROJ + ".tmp-write"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PROJ)

def main():
    loc = local_dirs()
    info, targets = {}, {}
    for prefix, (label, target) in MAP.items():
        d = [x for x in loc if x.startswith(prefix + "_")][0]
        info[prefix] = {"dir": d, "main": loc[d]["main"], "rev": loc[d]["rev"]}
        targets[prefix] = NEW[prefix][0] if prefix in NEW else target

    shutil.copy2(PROJ, PROJ + ".bak-sync-" + time.strftime("%Y%m%d-%H%M%S"))

    # 1) create the 3 agreed-new locations
    for prefix, name in targets.items():
        if name not in {e["name"] for e in entities()}:
            r = api.call("zzdh_create_entity", {"entity_type": "location", "name": name,
                                                "description": NEW[prefix][1],
                                                "image_path": info[prefix]["main"]})
            log("CREATE", prefix, name, json.dumps(r, ensure_ascii=False)[:400])

    # 2) write refs (main + reverse) for all 16
    patch_file(targets, info)
    log("PATCHED", PROJ)

    # 3) officialise each one through the app's own update path
    done, failed = [], []
    for prefix, name in targets.items():
        e = [x for x in entities() if x["name"] == name]
        if not e:
            failed.append((prefix, name, "entity not found after create")); continue
        e = e[0]
        r = api.call("zzdh_update_entity", {"entity_type": "location",
                                            "entity_id": e["location_id"],
                                            "image_path": info[prefix]["main"]})
        if not r.get("success"):
            patch_file({prefix: name}, info)
            r = api.call("zzdh_update_entity", {"entity_type": "location",
                                                "entity_id": e["location_id"],
                                                "image_path": info[prefix]["main"]})
        if r.get("success"):
            done.append((e["location_id"], name, len(r["entity"].get("reference_items") or [])))
        else:
            failed.append((prefix, name, json.dumps(r, ensure_ascii=False)[:200]))
        log("UPDATE", prefix, e["location_id"], name, r.get("success"))

    # 4) final readback
    final = entities()
    log("=== FINAL READBACK ===")
    for e in final:
        if e["image_path"]:
            log("#%-3s %-16s main=%s | extra=%d" % (e["location_id"], e["name"],
                os.path.basename(e["image_path"]), len(e["extra_images"])))
    log("with image:", sum(1 for e in final if e["image_path"]), "/", len(final))
    log("DONE:", len(done), "FAILED:", len(failed))
    for f in failed:
        log("  FAIL", f)
    print("done=%d failed=%d" % (len(done), len(failed)))

if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("EXC", traceback.format_exc()); print("EXC"); sys.exit(1)
