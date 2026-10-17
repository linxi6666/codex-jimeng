import sys, json
sys.path.insert(0, r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync")
from api import call
d = call("zzdh_get_edit_view_data", {"unique_name":"26a3622011"}, timeout=60)
json.dump(d, open(r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync\_ev_p2.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
o=[]
for im in (d.get("images") or []):
    o.append(json.dumps({k:im.get(k) for k in ("path","exists","is_video","thumbnail_path","round") if k in im}, ensure_ascii=False))
o.append("---round_previews: " + json.dumps(d.get("round_previews"), ensure_ascii=False)[:500])
o.append("prompt=" + json.dumps(d.get("prompt"), ensure_ascii=False)[:200])
o.append("processed_prompt=" + json.dumps(d.get("processed_prompt"), ensure_ascii=False)[:200])
o.append("first_frame_prompt=" + json.dumps(d.get("first_frame_prompt"), ensure_ascii=False)[:200])
o.append("first_frame_image_path=" + json.dumps(d.get("first_frame_image_path"), ensure_ascii=False))
o.append("video_prompt_mode=%s batch_num=%s video_batch_num=%s" % (d.get("video_prompt_mode"), d.get("batch_num"), d.get("video_batch_num")))
o.append("reference_images=" + json.dumps(d.get("reference_images"), ensure_ascii=False)[:400])
open(r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync\_ev_p2_summary.txt","w",encoding="utf-8").write("\n".join(o))
print("ok")
