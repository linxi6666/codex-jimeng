import json, sys, time
sys.path.insert(0, r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync")
from api import call
un = "26a3622011"
t0 = time.time()
try:
    r = call("zzdh_prompt_infer", {"unique_name": un}, timeout=900)
    print("infer_result:", json.dumps(r, ensure_ascii=False)[:800])
except Exception as e:
    print("infer_error:", repr(e)[:800])
print("elapsed %.1fs" % (time.time()-t0))
d = call("zzdh_get_edit_view_data", {"unique_name": un}, timeout=180)
vp = d.get("video_prompt") or ""
pp = d.get("prompt") or ""
open(r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync\_infer_p2.json","w",encoding="utf-8").write(json.dumps(d,ensure_ascii=False,indent=1))
print("video_prompt_len", len(vp), "prompt_len", len(pp))
print("scene_duration", d.get("scene_duration"), "generation_scene_duration", d.get("generation_scene_duration"))
print("selected_character_ids", d.get("selected_character_ids"), "selected_locations", d.get("selected_locations"))
print("--- video_prompt ---")
print(vp[:1200])