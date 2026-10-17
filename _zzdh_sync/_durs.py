import sys, json
sys.path.insert(0, r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync")
from api import call
o=[]
for un,idx in [("pzemx6uowa",3),("26a3622011",2),("crwdac4zuw",4),("nfq2q9jyrh",6)]:
    d = call("zzdh_get_edit_view_data", {"unique_name":un}, timeout=60)
    o.append("idx=%s un=%s scene_duration=%s video_duration=%s audio_duration=%s chars=%s locs=%s imgs=%d" % (
        idx, un, d.get("scene_duration"), d.get("video_duration"), d.get("audio_duration"),
        d.get("selected_character_ids"), d.get("selected_locations"), len(d.get("images") or [])))
open(r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync\_durs.txt","w",encoding="utf-8").write("\n".join(o))
print("ok")
