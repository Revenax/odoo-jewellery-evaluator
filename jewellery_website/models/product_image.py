# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Shop photos: the only photos the website shows.

The product's main image (image_1920) is the ops-app snapshot taken at
registration; the POS and backend keep using it to recognise the piece. The
website shows only extra images flagged as shop photos: professional studio
shots (imported from the photo sheets) or approved photos from the AI photo
workflow. A piece with no shop photo is not published.
"""
import base64
import io
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Odoo encodes every resized copy at JPEG quality 95 (tools/image.py), so a 1024 px
# shop tile weighed ~70 kB. Quality 80 progressive is visually the same at screen
# size and about half the weight. (The server's Pillow has no WebP encoder.)
SIZES = ('image_1024', 'image_512', 'image_256', 'image_128')
QUALITY = 80


class ProductImage(models.Model):
    _inherit = 'product.image'

    jewellery_shop_photo = fields.Boolean(
        string='Shop Photo', index=True,
        help='Shown on the website. The website shows only shop photos, never '
             'the operations-app snapshot.')
    jewellery_photo_source = fields.Selection(
        [('studio', 'Studio photo'), ('ai', 'AI photo workflow')],
        string='Photo Source')
    jewellery_photo_ref = fields.Char(
        string='Photo Reference', index=True, copy=False,
        help='Where the photo came from (sheet row / file id), so an import '
             'never adds the same photo twice.')

    @api.model_create_multi
    def create(self, vals_list):
        images = super().create(vals_list)
        images.filtered('jewellery_shop_photo')._jewellery_compress_sizes()
        return images

    def write(self, vals):
        res = super().write(vals)
        if 'image_1920' in vals or vals.get('jewellery_shop_photo'):
            self.filtered('jewellery_shop_photo')._jewellery_compress_sizes()
        return res

    def _jewellery_compress_sizes(self):
        """Re-encode the resized copies of shop photos at quality 80, progressive."""
        from PIL import Image
        Attachment = self.env['ir.attachment'].sudo()
        for att in Attachment.search([('res_model', '=', 'product.image'), ('res_id', 'in', self.ids),
                                      ('res_field', 'in', SIZES), ('mimetype', '=', 'image/jpeg')]):
            try:
                raw = base64.b64decode(att.datas)
                pil = Image.open(io.BytesIO(raw))
                if pil.info.get('progressive') or pil.info.get('progression'):
                    continue
                out = io.BytesIO()
                pil.convert('RGB').save(out, 'JPEG', quality=QUALITY, optimize=True, progressive=True)
                if len(out.getvalue()) < len(raw):
                    att.datas = base64.b64encode(out.getvalue())
            except Exception:  # noqa: BLE001 - a photo that won't recompress keeps Odoo's copy
                _logger.warning('shop photo %s: %s not recompressed', att.res_id, att.res_field, exc_info=True)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    jewellery_shop_photo_count = fields.Integer(
        string='Shop Photos', compute='_compute_jewellery_shop_photo_count')

    @api.depends('product_template_image_ids.jewellery_shop_photo')
    def _compute_jewellery_shop_photo_count(self):
        for tmpl in self:
            tmpl.jewellery_shop_photo_count = len(tmpl._jewellery_shop_photos())

    def _jewellery_shop_photos(self):
        self.ensure_one()
        return self.product_template_image_ids.filtered('jewellery_shop_photo').sorted(
            lambda i: (i.sequence, i.id))

    def _get_images(self):
        photos = self._jewellery_shop_photos()
        return list(photos) if photos else super()._get_images()

    def _get_image_holder(self):
        photos = self._jewellery_shop_photos()
        return photos[:1] if photos else super()._get_image_holder()


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _get_images(self):
        photos = self.product_tmpl_id._jewellery_shop_photos()
        return list(photos) if photos else super()._get_images()
