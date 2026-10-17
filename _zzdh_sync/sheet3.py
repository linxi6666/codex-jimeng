# -*- coding: utf-8 -*-
import os, sys, traceback
from PIL import Image
LOCAL = r"C:\Users\EDY\Desktop\重回80我有了山神系统\场景"
OUT = r"C:\Users\EDY\Documents\ChatGPT\即梦\_zzdh_sync\scenes_contact_sheet.jpg"
try:
    dirs = sorted([d for d in os.listdir(LOCAL) if os.path.isdir(os.path.join(LOCAL, d))])
    cw, ch = 460, 300
    cols = 4
    rows = (len(dirs) + cols - 1) // cols
    img = Image.new("RGB", (cols * cw, rows * ch), (12, 12, 16))
    for i, name in enumerate(dirs):
        full = os.path.join(LOCAL, name)
        pngs = sorted([x for x in os.listdir(full) if x.lower().endswith(".png")])
        main = [x for x in pngs if "反打" not in x]
        th = Image.open(os.path.join(full, main[0] if main else pngs[0])).convert("RGB")
        th.thumbnail((cw - 12, ch - 12))
        x = (i % cols) * cw + (cw - th.width) // 2
        y = (i // cols) * ch + (ch - th.height) // 2
        img.paste(th, (x, y))
    img.save(OUT, quality=86)
    print("OK", OUT, os.path.getsize(OUT), img.size)
    print("ORDER:")
    for i, n in enumerate(dirs):
        print("  %2d (r%d,c%d) %s" % (i + 1, i // cols + 1, i % cols + 1, n))
except Exception:
    traceback.print_exc(); sys.exit(1)
