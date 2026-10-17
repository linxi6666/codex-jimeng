import json, os, re
HERE = r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync"
d = json.load(open(os.path.join(HERE,"panels_live.json"), encoding="utf-8"))
ps = d["panels"]
o=[]
for i in (1,3):
    vp = ps[i-1]["video_prompt"]
    o.append("#"*30 + " idx=%d len=%d" % (i, len(vp)))
    for seg in vp.split("\n"):
        if seg.startswith(("主题：","角色：","声音设计","固定物品","场景：","人物位置关系","色调：","【镜头")):
            o.append(seg[:420])
open(os.path.join(HERE,"_p1p3_fields.txt"),"w",encoding="utf-8").write("\n".join(o))
print("ok")
