# -*- coding: utf-8 -*-
import io
t = io.open(r'.data\shanshen-followup-correct\pipeline.py', encoding='utf-8').read().split('\n')
for i, l in enumerate(t[54:70], 55):
    print(i, '|', l)
