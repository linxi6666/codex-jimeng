import json,os
p=r"C:\Users\EDY\.codex\sessions\2026\10\15\rollout-2026-10-15T17-42-06-01a13ef0-bd22-7452-9864-6c8c4fb7da96.jsonl"
out=[]
for l in open(p,"r",encoding="utf-8",errors="replace"):
    l=l.strip()
    if not l: continue
    try: o=json.loads(l)
    except Exception: continue
    t=o.get("type"); pl=o.get("payload") or {}
    if t=="response_item" and pl.get("type")=="message":
        role=pl.get("role")
        txt="\n".join(c.get("text","") for c in pl.get("content",[]) if c.get("type") in ("output_text","input_text"))
        if txt: out.append((o.get("timestamp"),role,txt))
    elif t=="event_msg" and pl.get("type") in ("user_message","agent_message"):
        txt=pl.get("message") or ""
        if txt: out.append((o.get("timestamp"),"USER" if pl.get("type")=="user_message" else "AGENT",txt))
with open(r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync\_tail_dump.txt","w",encoding="utf-8") as g:
    for ts,role,txt in out[-16:]:
        g.write("="*8+" "+str(ts)+" ["+str(role)+"] len="+str(len(txt))+"\n")
        g.write(txt[:3000]+"\n\n")
print("done",len(out))