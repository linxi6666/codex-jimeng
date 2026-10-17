import json
base=r"D:\字字动画_9_0_9(1)\字字动画_9_0_9\工作目录\默认\10月15日"
for n in ["project_settings.json","video_model_setting.json","model_setting.json","project_info.json","post_process_setting.json"]:
    p=base+"\\"+n
    try:
        d=json.load(open(p,encoding="utf-8"))
    except Exception as e:
        print(n,"ERR",e); continue
    print("="*10,n)
    if isinstance(d,dict):
        for k,v in d.items():
            s=json.dumps(v,ensure_ascii=False)
            if len(s)>300: s=s[:300]+"...(%d)"%len(s)
            print("  ",k,"=",s)