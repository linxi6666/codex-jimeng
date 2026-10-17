# -*- coding: utf-8 -*-
import io, json, hashlib, glob, os
t = io.open(r'.data\shanshen-followup-correct\pipeline.py', encoding='utf-8').read().split('\n')
for i, l in enumerate(t, 1):
    if any(k in l for k in ('def digest', 'def dump', 'def canonical', 'def nid', 'def read', 'ROOT =', 'ROOT=', 'SETTINGS')):
        print(i, '|', l)
