# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

from odoo import fields, models, tools


class JewelleryWeightInventoryReport(models.Model):
    """Read-only SQL-view report: one row per product that is currently in
    stock *or* was ever sold (plus a row per internal location it sits in).

    Building the view from product_product (LEFT JOIN stock_quant) rather than
    from stock_quant keeps sold pieces visible at on-hand 0 instead of silently
    disappearing when Odoo prunes their zero quant row. Products that were never
    stocked and never sold are excluded.

    Per-piece weights are stored on product.template; this view multiplies them
    by the on-hand quantity so every column aggregates with SUM in list/pivot/graph.
    The warehouse is resolved from each location via the materialized parent_path.
    """

    _name = 'jewellery.weight.inventory.report'
    _description = 'Jewellery Weight Inventory Report'
    _auto = False
    _rec_name = 'product_id'
    _order = 'product_id'

    # --- dimensions ---
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    product_tmpl_id = fields.Many2one('product.template', string='Product Template', readonly=True)
    categ_id = fields.Many2one('product.category', string='Category', readonly=True)
    location_id = fields.Many2one('stock.location', string='Location', readonly=True)
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse', readonly=True)
    sku_prefix = fields.Char(string='SKU Prefix', readonly=True)
    default_code = fields.Char(string='Internal Reference', readonly=True)
    jewellery_type = fields.Selection(
        selection=lambda self: self.env['product.template']._fields['jewellery_type'].selection,
        string='Jewellery Type',
        readonly=True,
    )

    # --- measures (SUM-aggregated) ---
    on_hand_qty = fields.Float(
        string='On Hand Qty', readonly=True, aggregator='sum')
    total_net_gold_weight_g = fields.Float(
        string='Net Gold Weight (g)', readonly=True, aggregator='sum', digits=(16, 3))
    total_diamond_weight_g = fields.Float(
        string='Diamond Weight (g)', readonly=True, aggregator='sum', digits=(16, 3))
    total_gross_weight_g = fields.Float(
        string='Jewellery Weight (g)', readonly=True, aggregator='sum', digits=(16, 3))
    total_weight_reading_g = fields.Float(
        string='Weight Reading (g)', readonly=True, aggregator='sum', digits=(16, 3))

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        # Built from product_product with a LEFT JOIN onto internal-location
        # quants, so a product still produces a (zero) row after its quant is
        # pruned on sale. The WHERE keeps only products that have stock now or
        # were ever delivered to a customer (never-stocked, never-sold catalogue
        # entries are dropped). Warehouse is resolved per location with a LIMIT 1
        # scalar subquery (the most-specific matching warehouse) rather than a
        # JOIN, so a location can never multiply quant rows and double-count.
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    row_number() OVER (ORDER BY sub.product_id, sub.location_id) AS id,
                    sub.*
                FROM (
                    SELECT
                        pp.id                              AS product_id,
                        pp.product_tmpl_id                 AS product_tmpl_id,
                        pt.categ_id                        AS categ_id,
                        q.location_id                      AS location_id,
                        (
                            SELECT w.id
                            FROM stock_warehouse w
                            JOIN stock_location wl ON wl.id = w.view_location_id
                            WHERE loc.parent_path LIKE wl.parent_path || '%'
                            ORDER BY length(wl.parent_path) DESC
                            LIMIT 1
                        )                                  AS warehouse_id,
                        split_part(COALESCE(pp.default_code, ''), '-', 1) AS sku_prefix,
                        pp.default_code                    AS default_code,
                        pt.jewellery_type                  AS jewellery_type,
                        COALESCE(SUM(q.quantity), 0)                                              AS on_hand_qty,
                        COALESCE(SUM(q.quantity * COALESCE(pt.net_gold_weight_g, 0.0)), 0)        AS total_net_gold_weight_g,
                        COALESCE(SUM(q.quantity * COALESCE(pt.diamond_weight_g, 0.0)), 0)         AS total_diamond_weight_g,
                        COALESCE(SUM(q.quantity * COALESCE(pt.gross_jewellery_weight_g, 0.0)), 0) AS total_gross_weight_g,
                        COALESCE(SUM(q.quantity * COALESCE(pt.weight_reading_g, 0.0)), 0)         AS total_weight_reading_g
                    FROM product_product pp
                    JOIN product_template pt ON pt.id = pp.product_tmpl_id
                    LEFT JOIN stock_quant q ON q.product_id = pp.id
                         AND q.location_id IN (
                             SELECT id FROM stock_location WHERE usage = 'internal')
                    LEFT JOIN stock_location loc ON loc.id = q.location_id
                    WHERE EXISTS (
                              SELECT 1 FROM stock_quant q2
                              JOIN stock_location l2 ON l2.id = q2.location_id
                              WHERE q2.product_id = pp.id AND l2.usage = 'internal')
                       OR EXISTS (
                              SELECT 1 FROM stock_move sm
                              JOIN stock_location dl ON dl.id = sm.location_dest_id
                              WHERE sm.product_id = pp.id AND dl.usage = 'customer'
                                AND sm.state = 'done')
                    GROUP BY
                        pp.id, pp.product_tmpl_id, pt.categ_id, q.location_id,
                        loc.parent_path, pp.default_code, pt.jewellery_type
                ) sub
            )
        """)
