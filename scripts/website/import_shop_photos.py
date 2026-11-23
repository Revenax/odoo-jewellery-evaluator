# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Odoo-shell script: attach prepared studio photos to their pieces as shop photos.

    scripts/ops/run_odoo.sh scripts/website/import_shop_photos.py DIR=/opt/odoo/tmp/shop_photos [COMMIT=1]

DIR holds <SKU>__<ref>.jpg files (scripts/website/shop_photos_prepare.py). Each
becomes a product.image on the piece with jewellery_shop_photo set and source
"studio"; a file whose ref is already on the piece is skipped (re-runs are safe).
The product's own image (the ops-app snapshot, used by the POS) is not touched.
Then the catalogue sync runs, so pieces with a shop photo go live and pieces
without one leave the website.
"""
import base64
import os
from pathlib import Path

folder = Path(os.environ['DIR'])
PT = env['product.template'].with_context(active_test=False)
Img = env['product.image']
added, existing, unknown = [], 0, []
for f in sorted(folder.glob('*.jpg')):
    sku, _, ref = f.stem.partition('__')
    tmpl = PT.search([('default_code', '=', sku)], limit=1)
    if not tmpl:
        unknown.append(sku)
        continue
    if Img.search_count([('product_tmpl_id', '=', tmpl.id), ('jewellery_photo_ref', '=', ref)]):
        existing += 1
        continue
    seq = len(tmpl._jewellery_shop_photos()) + 1
    Img.create({
        'product_tmpl_id': tmpl.id,
        'name': tmpl.website_title or sku,
        'sequence': seq,
        'image_1920': base64.b64encode(f.read_bytes()),
        'jewellery_shop_photo': True,
        'jewellery_photo_source': 'studio',
        'jewellery_photo_ref': ref,
    })
    added.append(sku)
print('added', len(added), added)
print('already there', existing, '| SKU not in Odoo', unknown)
stats = env['product.template'].cron_sync_website_catalog()
print('catalogue', stats)
live = env['product.template'].search([('is_published', '=', True), ('website_catalog_managed', '=', True)])
print('live now', len(live), sorted(live.mapped('default_code')))
if os.environ.get('COMMIT') == '1':
    env.cr.commit(); print('COMMITTED')
else:
    env.cr.rollback(); print('DRY RUN (add COMMIT=1)')
