# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Backfill past daily rates of the metal currencies (G24/G21/G18/S99).

Run inside the Odoo shell (scripts/ops/run_odoo.sh). Rolls back unless COMMIT=1.

Each day's rate is that day's LAST price (Cairo day), the same thing the live
crons leave behind (they update today's row in place all day). Sources, best
first for a given moment:
  1. the local price feed history (/var/lib/marjaan-price-feed/prices.db,
     from 2026-10-11): 21K ask and silver 999 ask, the side the shop prices on;
  2. the gold and silver cron logs (ir.logging, gold from 2026-06-26, silver
     from 2026-08-17): the accepted price of every run that repriced products.
Gold karats follow the 21K price x purity factor, as live. Days with no
data get no row (Odoo uses the latest earlier rate). Existing rows are never
touched (today's is the live cron's). Prints one CSV line per day:
DAY,date,g21,g24,g18,s99,gold_source,silver_source.
"""
import datetime
import json
import os
import re
import sqlite3

import pytz
from odoo.addons.jewellery_evaluator.jewellery_evaluator.utils import metal_currency_rates

COMMIT = os.environ.get('COMMIT') == '1'
FEED_DB = os.environ.get('FEED_DB', '/var/lib/marjaan-price-feed/prices.db')
TZ = pytz.timezone('Africa/Cairo')
today = datetime.datetime.now(TZ).date()


def cairo_day(dt_utc):
    return pytz.utc.localize(dt_utc).astimezone(TZ).date()


gold = {}    # day -> (utc time, price, source)
silver = {}


def keep(book, day, when, price, source):
    if price and price > 0 and day < today and (day not in book or when >= book[day][0]):
        book[day] = (when, price, source)


GOLD_RE = re.compile(r'-> ([0-9.]+) EGP/g|base ([0-9.]+)/g')
SILVER_RE = re.compile(r'base ([0-9.]+)/g')
env.cr.execute("""SELECT create_date, func, message FROM ir_logging
                   WHERE level = 'INFO' AND func IN ('update_all_gold_product_prices',
                                                     'update_all_silver_product_prices')""")
unparsed = 0
for when, func, message in env.cr.fetchall():
    if func == 'update_all_gold_product_prices':
        m = GOLD_RE.search(message)
        if m:
            keep(gold, cairo_day(when), when, float(m.group(1) or m.group(2)), 'cron log')
        else:
            unparsed += 1
    else:
        m = SILVER_RE.search(message)
        if m:
            keep(silver, cairo_day(when), when, float(m.group(1)), 'cron log')

# The feed is the primary source where it exists: a log line is only written
# when products were repriced, the feed has every minute.
feed_rows = 0
db = sqlite3.connect(f'file:{FEED_DB}?mode=ro', uri=True)
for scraped_at, payload in db.execute('SELECT scraped_at, payload FROM snapshots ORDER BY id'):
    snap = json.loads(payload)
    when = datetime.datetime.fromisoformat(scraped_at).astimezone(pytz.utc).replace(tzinfo=None)
    day = cairo_day(when)
    feed_rows += 1
    g21 = (snap.get('gold_21k') or {}).get('ask')
    s99 = (snap.get('silver_999') or {}).get('ask')
    if g21 and (day not in gold or gold[day][2] != 'price feed' or when >= gold[day][0]):
        if day < today and g21 > 0:
            gold[day] = (when, float(g21), 'price feed')
    if s99 and (day not in silver or silver[day][2] != 'price feed' or when >= silver[day][0]):
        if day < today and s99 > 0:
            silver[day] = (when, float(s99), 'price feed')

Currency = env['res.currency'].with_context(active_test=False)
codes = {c.name: c for c in Currency.search([('name', 'in', ['G24', 'G21', 'G18', 'S99'])])}
assert len(codes) == 4, f'metal currencies missing: {sorted(codes)}'
Rate = env['res.currency.rate'].sudo()
companies = env['res.company'].search([])
created = 0
for day in sorted(set(gold) | set(silver)):
    g = gold.get(day)
    s = silver.get(day)
    rates = metal_currency_rates(g[1] if g else None, s[1] if s else None)
    for code, rate in rates.items():
        for company in companies:
            if not Rate.search_count([('currency_id', '=', codes[code].id), ('name', '=', day),
                                      ('company_id', '=', company.id)]):
                Rate.create({'currency_id': codes[code].id, 'name': day,
                             'company_id': company.id, 'rate': rate})
                created += 1
    print('DAY,%s,%s,%s,%s,%s,%s,%s' % (
        day,
        g[1] if g else '', round(1 / rates['G24'], 2) if g else '', round(1 / rates['G18'], 2) if g else '',
        s[1] if s else '', g[2] if g else '', s[2] if s else ''))

print(f'SUMMARY gold days {len(gold)} silver days {len(silver)} feed snapshots {feed_rows} '
      f'unparsed gold log lines {unparsed} rate rows created {created}')
if COMMIT:
    env.cr.commit()
    print('COMMITTED')
else:
    env.cr.rollback()
    print('ROLLED BACK (dry run)')
