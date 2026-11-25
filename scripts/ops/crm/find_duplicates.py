# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Find duplicate contacts from a JSON export: same number AND same person (complete
link, any script/spelling), or same exact name with no number. Numbers shared by
different names (families) are reported, never merged. See runbook 4.12."""
import json, re, collections, sys, difflib
sys.path.insert(0, sys.argv[3])
from cluster_lib import norm_phone, skeleton
rows = json.load(open(sys.argv[1])); extra = set(json.load(open(sys.argv[4])))
for r in rows:
    r['nphone'] = norm_phone(r['phone']); r['key'] = skeleton(r['name'])
    if r['id'] in extra: r['protected'] = True
cand = [r for r in rows if not r['protected'] and not r['is_company'] and r['key']]
def fw(a, b): return difflib.SequenceMatcher(None, a, b).ratio() >= 0.75
def same_person(a, b):
    ka, kb = a['key'].split(), b['key'].split()
    if ka == kb: return True
    if not fw(ka[0], kb[0]): return False
    short, long_ = (ka, kb) if len(ka) <= len(kb) else (kb, ka)
    if len(short) == 1: return False
    i = 0
    for w in short:
        while i < len(long_) and not fw(w, long_[i]): i += 1
        if i == len(long_): return False
        i += 1
    return True
clusters = []
byphone = collections.defaultdict(list)
for r in cand:
    if r['nphone']: byphone[r['nphone']].append(r)
for ph, g in byphone.items():
    local = []
    for r in sorted(g, key=lambda x: x['id']):
        for c in local:
            if all(same_person(r, m) for m in c):   # complete link: same person as EVERY member
                c.append(r); break
        else:
            local.append([r])
    clusters += local
# contacts with no number: attach only on an EXACT name key to exactly one cluster
nophone = [r for r in cand if not r['nphone']]
for r in nophone:
    hits = [c for c in clusters if any(m['key'] == r['key'] for m in c)]
    if len(hits) == 1 and len(r['key'].split()) >= 2:
        hits[0].append(r)
    else:
        clusters.append([r])
merge = [c for c in clusters if len(c) > 1]
shared = {ph: g for ph, g in byphone.items() if len([c for c in clusters if any(m['nphone'] == ph for m in c)]) > 1}
json.dump({'merge': [[m['id'] for m in c] for c in merge], 'shared': {k: [r['id'] for r in v] for k, v in shared.items()}}, open(sys.argv[2], 'w'), ensure_ascii=False)
print('merge groups', len(merge), 'contacts', sum(len(c) for c in merge), '-> fewer contacts:', sum(len(c)-1 for c in merge))
print('numbers shared by different people (left as they are)', len(shared))
for c in merge: print('  M ' + ' | '.join(f"{m['id']}:{m['name']}:{m['nphone']}" for m in c))
