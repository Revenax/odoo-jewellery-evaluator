# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Download the studio photos listed in a photo sheet and size them for the shop.

    python3 scripts/website/shop_photos_prepare.py "<sheet.csv>" [<sheet2.csv> ...] OUT_DIR

A sheet has (at least) the columns "Image Name", "Image" (a Google Drive share
link) and "Odoo SKU". Rows without an Odoo SKU (sold out / not registered) are
skipped. Each photo is saved as OUT_DIR/<SKU>__<drive id>.jpg, at most 2000 px on
the long side (the camera originals are ~6000 px and 5 MB). Then copy OUT_DIR to
the server and run scripts/website/import_shop_photos.py.
"""
import csv
import io
import re
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageOps

MAX_SIDE = 2000


def drive_id(url):
    m = re.search(r'/d/([A-Za-z0-9_-]+)', url or '') or re.search(r'[?&]id=([A-Za-z0-9_-]+)', url or '')
    return m.group(1) if m else None


def main(sheets, out):
    out.mkdir(parents=True, exist_ok=True)
    done, skipped = 0, []
    for sheet in sheets:
        with open(sheet, newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                sku = (row.get('Odoo SKU') or '').strip().upper()
                fid = drive_id(row.get('Image'))
                if not sku or not fid:
                    continue
                target = out / f'{sku}__{fid}.jpg'
                if target.exists():
                    done += 1
                    continue
                try:
                    url = f'https://drive.google.com/uc?export=download&id={fid}'
                    data = urllib.request.urlopen(url, timeout=120).read()
                    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert('RGB')
                except Exception as e:  # noqa: BLE001 - report and carry on
                    skipped.append((sku, row.get('Image Name'), str(e)[:80]))
                    continue
                img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
                img.save(target, 'JPEG', quality=88, optimize=True, progressive=True)
                done += 1
                print('ok', sku, row.get('Image Name'), img.size)
    print('photos ready', done, 'skipped', skipped)


if __name__ == '__main__':
    main(sys.argv[1:-1], Path(sys.argv[-1]))
