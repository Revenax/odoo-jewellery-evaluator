# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Contact de-duplication (2026-11-26): phone normaliser + a name skeleton that
matches Arabic and Latin spellings (vowels, doubled letters, el/al, abd- dropped)."""
import json, re, collections, sys
AR_DIG = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')

def norm_phone(raw):
    """Egyptian numbers -> 0XXXXXXXXXX; others kept as +<digits>; '' if junk."""
    s = (raw or '').translate(AR_DIG)
    d = re.sub(r'\D', '', s)
    if not d:
        return ''
    if d.startswith('0020'): d = d[4:]
    elif d.startswith('20') and len(d) in (11, 12): d = d[2:]
    elif d.startswith('00'): return '+' + d[2:]
    if len(d) == 10 and d[0] == '1': d = '0' + d          # 1012345678 -> 01012345678
    if len(d) == 9 and d[0] in '23456789': d = '0' + d     # landline without 0
    if d.startswith('0'): return d
    return '+' + d

# --- name skeleton: same key for Arabic and Latin spellings ---
AR2LAT = {'ا':'a','أ':'a','إ':'a','آ':'a','ء':'','ؤ':'','ئ':'','ب':'b','ت':'t','ث':'s','ج':'g','ح':'h','خ':'kh','د':'d','ذ':'z','ر':'r','ز':'z','س':'s','ش':'sh','ص':'s','ض':'d','ط':'t','ظ':'z','ع':'a','غ':'gh','ف':'f','ق':'k','ك':'k','ل':'l','م':'m','ن':'n','ه':'h','ة':'a','و':'w','ي':'y','ى':'a','ـ':'',' ':' '}
def skeleton(name):
    n = (name or '').strip().lower()
    n = re.sub(r'[ً-ْ]', '', n)            # Arabic diacritics
    n = ''.join(AR2LAT.get(c, c) for c in n)
    n = re.sub(r'[^a-z ]', ' ', n)
    n = n.replace('ph', 'f').replace('q', 'k').replace('j', 'g').replace('ou', 'o').replace('ee','i')
    n = re.sub(r'\bal\b|\bel\b', ' ', n)                    # article "el"/"al"
    n = re.sub(r'\b(abd|abdel|abdul|abdal|abdl)\s*', 'abd', n)
    words = []
    for w in n.split():
        w = re.sub(r'(.)\1+', r'\1', w)                  # oo -> o, mm -> m
        c = re.sub(r'[aeiouyw]', '', w[1:])              # drop vowels/weak letters after the first char
        w = (w[0] if w[0] not in 'aeiouyw' else 'a') + c
        if w: words.append(w)
    return ' '.join(words)

