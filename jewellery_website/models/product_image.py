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
from odoo import api, fields, models


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
