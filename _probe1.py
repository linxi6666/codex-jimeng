# -*- coding: utf-8 -*-
import json, io
r = r'.data\shanshen-followup-correct\revision-plans'
want = {50:['1-19','1-20','1-21'], 60:['2-01','2-02','2-06'], 61:['1-03','1-04','1-09']}
for ep in sorted(want):
    d = json.load(io.open(rf'{r}\{ep}.json', encoding='utf-8'))
    for sh in want[ep]:
        s = [x for x in d['shots'] if x['shot'] == sh][0]
        print('#'*20, ep, sh, s['nodeId'], s['refs'])
        for i, l in enumerate(s['prompt'].split('\n')):
            print(f'{i:02d}|{l}')
        print()
