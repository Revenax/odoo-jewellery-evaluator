# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Odoo-shell script: re-encode shop photos as progressive JPEG, quality 80, max 1920 px,
so every size Odoo serves is lighter. (The server's Pillow has no WebP encoder, so Odoo
cannot serve WebP product images.) Idempotent-ish: skips photos already re-encoded
(Adobe/progressive marker). Rolls back unless COMMIT=1.

    scripts/ops/run_odoo.sh scripts/website/optimize_shop_photos.py [COMMIT=1]
"""
import base64
import io
import os

from PIL import Image

done = before = after = 0
for img in env['product.image'].search([('jewellery_shop_photo', '=', True)]):
    raw = base64.b64decode(img.image_1920 or b'')
    if not raw:
        continue
    pil = Image.open(io.BytesIO(raw))
    if pil.info.get('progressive') or pil.info.get('progression'):
        continue
    pil = pil.convert('RGB')
    pil.thumbnail((1920, 1920))  # Odoo re-encodes anything larger at quality 95
    out = io.BytesIO()
    pil.save(out, 'JPEG', quality=80, optimize=True, progressive=True)
    if len(out.getvalue()) >= len(raw):
        continue
    before += len(raw)
    after += len(out.getvalue())
    img.image_1920 = base64.b64encode(out.getvalue())
    done += 1
print(f'converted {done}: {before/1e6:.1f} MB -> {after/1e6:.1f} MB')
if os.environ.get('COMMIT') == '1':
    env.cr.commit(); print('COMMITTED')
else:
    env.cr.rollback(); print('DRY RUN (add COMMIT=1)')
