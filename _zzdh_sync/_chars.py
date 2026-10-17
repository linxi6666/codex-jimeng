import json,io
p=r"D:\字字动画_9_0_9(1)\字字动画_9_0_9\工作目录\默认\10月15日\characters.json"
d=json.load(io.open(p,encoding="utf-8"))
out=[]
def walk(o):
    if isinstance(o,dict):
        if "name" in o: out.append((o.get("name"), (o.get("description") or "")[:60]))
        for v in o.values(): walk(v)
    elif isinstance(o,list):
        for v in o: walk(v)
walk(d)
io.open(r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync\_chars.txt","w",encoding="utf-8").write("count=%d\n"%len(out)+"\n".join("%s\t%s"%x for x in out))
print("chars", len(out))
