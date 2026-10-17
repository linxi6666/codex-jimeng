# -*- coding: utf-8 -*-
import json, io, glob
ids = ['kvr0072cap','rmbxrbpdys','pbze6g6rjg','kee1qg47ed','c3xdxx86bv','dn5b0dwf80',
       'gp49m02rpd','ma4kqswj94','9kxbbgn5a0','r5eajg4ec4','23ma5sbwyr','rhjrmzws9e','n4kdjss74y']
hits = {i:0 for i in ids}
ex = {}
for f in sorted(glob.glob(r'.data\shanshen-followup-correct\revision-plans\*.json')):
    d = json.load(io.open(f, encoding='utf-8'))
    for s in d['shots']:
        if not s['refs']:
            continue
        for i in ids:
            k = '{{node:node_' + i + '}}'
            for l in s['prompt'].split('\n'):
                if k in l:
                    hits[i] += 1
                    ex.setdefault(i, []).append(str(d['episode']) + ' ' + s['shot'] + ': ' + l[:150])
for i in ids:
    print('==', i, hits[i])
    for e in ex.get(i, [])[:4]:
        print('   ', e)
