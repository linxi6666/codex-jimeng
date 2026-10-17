import json, sys, time
sys.path.insert(0, r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync")
from api import call
un = "26a3622011"
for i in range(20):
    time.sleep(15)
    d = call("zzdh_get_edit_view_data", {"unique_name": un}, timeout=120)
    vp = d.get("video_prompt") or ""
    print("t=%ds vp_len=%d pp_len=%d dur=%s" % ((i+1)*15, len(vp), len(d.get("prompt") or ""), d.get("scene_duration")), flush=True)
    if vp:
        open(r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync\_infer_p2.json","w",encoding="utf-8").write(json.dumps(d,ensure_ascii=False,indent=1))
        open(r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync\_infer_p2_vp.txt","w",encoding="utf-8").write(vp)
        break