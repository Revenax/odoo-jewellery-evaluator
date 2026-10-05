# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
import logging
from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models

from ..website_utils import (
    NEW_ARRIVAL_DAYS,
    PUBLIC_TREE,
    public_category_keys,
    should_publish,
    website_title,
)

_logger = logging.getLogger(__name__)

_XMLID_PREFIX = 'public_categ_'


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    website_title = fields.Char(
        string='Website Title',
        compute='_compute_website_title',
        store=True,
        help='What customers see in the shop. Products are named by SKU for the '
             'till, so this is built from the category, karat, weight and stones. '
             'Falls back to the product name.',
    )
    website_catalog_managed = fields.Boolean(
        string='Auto-publish on Website',
        default=True,
        help='On: the website catalogue sync publishes this piece while it is in '
             'stock with a photo and a price, takes it off when it sells, and keeps '
             'its eCommerce categories in step with its internal category. '
             'Off: publish and categorise it by hand.',
    )

    @api.depends('name', 'categ_id.complete_name', 'jewellery_type', 'gold_purity',
                 'jewellery_weight_g', 'stone_ids.total_carat', 'default_code')
    def _compute_website_title(self):
        for tmpl in self:
            tmpl.website_title = website_title(
                tmpl.categ_id.complete_name,
                tmpl.jewellery_type,
                tmpl.gold_purity,
                tmpl.jewellery_weight_g,
                sum(tmpl.stone_ids.mapped('total_carat')),
                tmpl.default_code,
            ) or tmpl.name

    @api.model
    def _search_get_detail(self, website, order, options):
        """Let customers find pieces by what they are ("gold ring"), not just SKU,
        and show the title rather than the SKU in search suggestions."""
        detail = super()._search_get_detail(website, order, options)
        detail['search_fields'] = list(detail['search_fields']) + ['website_title']
        detail['fetch_fields'] = list(detail['fetch_fields']) + ['website_title']
        detail['mapping']['name'] = {'name': 'website_title', 'type': 'text', 'match': True}
        return detail

    def _get_google_analytics_data(self, product, combination_info):
        """Analytics item = what the customer saw (title, SKU, full category),
        not the till name, so reports read "Diamond Ring · 18K Gold · 0.52 ct"."""
        data = super()._get_google_analytics_data(product, combination_info)
        data['item_id'] = product.default_code or data['item_id']
        data['item_name'] = self.website_title or data['item_name']
        data['item_category'] = self.categ_id.complete_name or data['item_category']
        return data

    # ── catalogue sync ──────────────────────────────────────────────────

    @api.model
    def _website_public_categories(self):
        """key -> product.public.category, creating the tree on first use.

        Each node gets an xmlid in this module so later runs find it even if the
        owner renames it. An existing top-level node with the same name (the
        theme shipped Rings/Necklaces/Earrings/Bracelets) is adopted, not
        duplicated."""
        Category = self.env['product.public.category'].sudo()
        Data = self.env['ir.model.data'].sudo()
        nodes = {}
        for key, name, parent_key, sequence in PUBLIC_TREE:
            rec = self.env.ref(f'jewellery_website.{_XMLID_PREFIX}{key}', raise_if_not_found=False)
            if not rec:
                parent = nodes.get(parent_key)
                rec = Category.search([
                    ('name', '=', name),
                    ('parent_id', '=', parent.id if parent else False),
                ], limit=1) or Category.create({
                    'name': name,
                    'parent_id': parent.id if parent else False,
                    'sequence': sequence,
                })
                Data.create({
                    'module': 'jewellery_website',
                    'name': f'{_XMLID_PREFIX}{key}',
                    'model': 'product.public.category',
                    'res_id': rec.id,
                    'noupdate': True,
                })
            nodes[key] = rec
        return nodes

    @api.model
    def cron_sync_website_catalog(self):
        """Publish what can be bought, unpublish what cannot, and keep the managed
        eCommerce categories in step. Writes only what changed, so a quiet run is
        a handful of reads."""
        nodes = self._website_public_categories()
        managed_category_ids = {rec.id for rec in nodes.values()}
        templates = self.with_context(active_test=False).search([
            ('website_catalog_managed', '=', True),
            ('default_code', '!=', False),
        ])
        if not templates:
            return {}

        # Free stock, not on-hand: a piece reserved by a confirmed web order (or
        # an inter-branch transfer) is already spoken for and must leave the shop.
        free = defaultdict(float)
        for product, qty, reserved in self.env['stock.quant'].sudo()._read_group(
            [('location_id.usage', '=', 'internal'),
             ('product_id.product_tmpl_id', 'in', templates.ids)],
            ['product_id'], ['quantity:sum', 'reserved_quantity:sum'],
        ):
            free[product.product_tmpl_id.id] += qty - reserved

        # Existence check only: reading image_1920 for every product would pull
        # the binaries off disk.
        self.env.cr.execute("""
            SELECT res_id FROM ir_attachment
             WHERE res_model = 'product.template' AND res_field = 'image_1920'
               AND res_id = ANY(%s)""", [templates.ids])
        with_image = {row[0] for row in self.env.cr.fetchall()}

        new_since = fields.Datetime.now() - timedelta(days=NEW_ARRIVAL_DAYS)
        stats = defaultdict(int)
        for tmpl in templates:
            keys = public_category_keys(tmpl.categ_id.complete_name, is_new=tmpl.create_date >= new_since)
            wanted = {nodes[k].id for k in keys}
            publish = should_publish(
                tmpl.active, tmpl.sale_ok, tmpl.id in with_image,
                tmpl.list_price, free[tmpl.id], bool(keys),
            )
            current = set(tmpl.public_categ_ids.ids)
            # Keep any category the owner added by hand; only ours are managed.
            target = (current - managed_category_ids) | wanted
            vals = {}
            if target != current:
                vals['public_categ_ids'] = [(6, 0, sorted(target))]
            if tmpl.is_published != publish:
                vals['is_published'] = publish
                stats['published' if publish else 'unpublished'] += 1
            if not tmpl.seo_name and tmpl.website_title and tmpl.website_title != tmpl.name:
                # URL slug: /shop/18k-gold-ring-4-45-g-grf8-0131-123 instead of
                # /shop/grf8-0131-grf8-0131-123. Set once, so URLs stay stable
                # and a hand-edited SEO name is never overwritten.
                vals['seo_name'] = f'{tmpl.website_title} {tmpl.default_code}'
            if tmpl.allow_out_of_stock_order:
                # A one-of-a-kind piece must never be sold twice online.
                vals['allow_out_of_stock_order'] = False
            if vals:
                tmpl.with_context(tracking_disable=True).sudo().write(vals)
                stats['written'] += 1
            stats['live' if publish else 'hidden'] += 1
        _logger.info('[website-catalog] %s', dict(stats))
        return dict(stats)
