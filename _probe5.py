# -*- coding: utf-8 -*-
import json, io
d = json.load(io.open(r'.data\shanshen-followup-correct\_refrepair-zero-detail.json', encoding='utf-8'))
BLOCK = {25:['1-12'],26:['2-04','2-07','2-10','2-11','2-12'],27:['1-04','1-05'],
 30:['1-02'],34:['2-02'],41:['1-10','1-13'],66:['1-10','1-11'],
 67:['2-04','2-13','2-14','2-15','2-18'],68:['1-12','2-10','2-11']}
by = {(it['ep'], it['shot']): it for it in d}
for ep in sorted(BLOCK):
    for sh in BLOCK[ep]:
        it = by[(ep, sh)]
        print(ep, sh, '|', it['title'])
        print('   keys:', json.dumps(it['assetKeys'], ensure_ascii=False))
        print('   text:', json.dumps(it['textAssets'], ensure_ascii=False))
        print('   cand:', json.dumps({k: v['live_titles'][:4] for k, v in it['candidates'].items()}, ensure_ascii=False)[:300])
