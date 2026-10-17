import json
p=r"C:\Users\EDY\.codex\sessions\2026\10\15\rollout-2026-10-15T17-42-06-01a13ef0-bd22-7452-9864-6c8c4fb7da96.jsonl"
rows=[]
for l in open(p,"r",encoding="utf-8",errors="replace"):
    l=l.strip()
    if not l: continue
    try: o=json.loads(l)
    except Exception: continue
    ts=str(o.get("timestamp") or "")
    if ts < "2026-10-16T00:00": continue
    t=o.get("type"); pl=o.get("payload") or {}
    txt=None; role=None
    if t=="response_item" and pl.get("type")=="message":
        role=pl.get("role")
        txt="\n".join(c.get("text","") for c in pl.get("content",[]) if c.get("type") in ("output_text","input_text"))
    elif t=="event_msg" and pl.get("type")=="user_message":
        role="USER"; txt=pl.get("message") or ""
    if txt and role in ("user","USER","assistant"):
        rows.append((ts,role,txt))
with open(r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync\_tail_dump2.txt","w",encoding="utf-8") as g:
    for ts,role,txt in rows:
        g.write("="*8+" "+ts+" ["+role+"] len="+str(len(txt))+"\n"+txt[:1800]+"\n\n")
print("rows",len(rows))