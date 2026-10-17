import json
d = json.load(open(r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync\_ev_p1.json", encoding="utf-8"))
keys = ["unique_name","panel_index","scene_duration","generation_scene_duration","video_duration","leading_gap_seconds","trailing_gap_seconds","selected_character_ids","selected_locations","selected_item_ids","video_prompt_mode","batch_num","video_batch_num","generation_status","completed","srt_duration","audio_duration","lock_seed","lock_seed_type","generation_round"]
o=[]
for k in keys:
    o.append("%s = %s" % (k, json.dumps(d.get(k), ensure_ascii=False)[:200]))
o.append("video_prompt_mentions = " + json.dumps(d.get("video_prompt_mentions"), ensure_ascii=False)[:600])
o.append("inherit_prompt_mentions = " + json.dumps(d.get("inherit_prompt_mentions"), ensure_ascii=False)[:400])
o.append("processed_prompt_mentions = " + json.dumps(d.get("processed_prompt_mentions"), ensure_ascii=False)[:400])
o.append("images = " + json.dumps(d.get("images"), ensure_ascii=False)[:300])
o.append("lines = " + json.dumps(d.get("lines"), ensure_ascii=False)[:600])
o.append("processed_prompt = " + json.dumps(d.get("processed_prompt"), ensure_ascii=False)[:300])
o.append("inherit_prompt = " + json.dumps(d.get("inherit_prompt"), ensure_ascii=False)[:300])
o.append("negative_prompt = " + json.dumps(d.get("negative_prompt"), ensure_ascii=False)[:300])
open(r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync\_ev_p1_summary.txt","w",encoding="utf-8").write("\n".join(o))
print("ok")
