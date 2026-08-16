# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..utils import (
    compute_gold_product_price,
    get_markup_per_gram,
    get_min_markup_per_gram,
)

_logger = logging.getLogger(__name__)


class ProductTemplatePurchase(models.Model):
    """Batched purchasing: create ONE purchase order + ONE validated incoming
    receipt (WRO) for a list of products in a single server-side call — the
    bulk-buy / bars-coins / scrap counterpart to the per-piece buy-back
    (``init_jewellery_from_customer``). Products are matched by SKU and must
    already exist (the ops app creates piece products first, then calls this;
    bars/coins/scrap products are pre-seeded). Reuses the exact receipt
    assign/pick/validate mechanics of the buy-back flow, batched over N lines.
    """

    _inherit = 'product.template'

    @api.model
    def create_purchase_receipt(self, items, warehouse_code=None, origin=None,
                                vendor_ref=None, settle_from_vault=False):
        """One PO + one validated receipt for ``items`` (already-existing
        products, matched by SKU). Idempotent per ``origin`` (the ticket ref):
        a re-call with the same origin returns the same batch, never duplicates.

        :param items: ``[{'sku': str, 'price': float, 'qty': float=1.0}, ...]``
        :param warehouse_code: e.g. 'SM' (default: first warehouse)
        :param origin: batch/ticket reference used as the PO origin (idempotency)
        :param vendor_ref: xmlid of the supplier partner (default: Bulk Supplier)
        :param settle_from_vault: pay the vendor bill out of the branch Vault
            (cash-out reflected in the POS shift); default False = bill left unpaid
        :return: ``[{'sku', 'product_id', 'name', 'qty'}, ...]`` for eyeball match
        """
        if not items:
            return []
        Product = self.env['product.product']
        Warehouse = self.env['stock.warehouse']
        warehouse = (Warehouse.search([('code', '=', warehouse_code)], limit=1)
                     if warehouse_code else Warehouse.browse())
        if not warehouse:
            warehouse = Warehouse.search([], limit=1)
        picking_type = warehouse.in_type_id or self.env['stock.picking.type'].search(
            [('code', '=', 'incoming'), ('warehouse_id', '=', warehouse.id)], limit=1)
        if not (warehouse and picking_type):
            raise UserError(_("No incoming picking type for warehouse %s.") % warehouse_code)

        if vendor_ref:
            partner = self.env.ref(vendor_ref)
        else:
            partner = self.env.ref('jewellery_evaluator.partner_bulk_supplier')
        if not partner.property_stock_supplier:
            partner = partner.with_company(self.env.company)
            partner.property_stock_supplier = self.env.ref('stock.stock_location_suppliers')

        origin = origin or f'BULK-{fields.Datetime.to_string(fields.Datetime.now())}'

        # Resolve every SKU up front (fail the whole batch if any is unknown —
        # atomic, no half-receipt).
        resolved = []
        po_lines = []
        for it in items:
            sku = (it.get('sku') or '').strip()
            prod = (Product.search([('default_code', '=', sku)], limit=1)
                    if sku else Product.browse())
            if not prod:
                raise UserError(_("Purchase batch: unknown SKU %s.") % sku)
            prod.product_tmpl_id.write({'is_storable': True})
            qty = float(it.get('qty') or 1.0)
            price = float(it.get('price') or 0.0)
            resolved.append((prod, qty))
            po_lines.append((0, 0, {
                'product_id': prod.id,
                'product_qty': qty,
                'price_unit': price,
                'name': prod.display_name,
            }))

        PO = self.env['purchase.order']
        po = PO.search([('origin', '=', origin), ('state', '!=', 'cancel')], limit=1)
        if not po:
            po = PO.create({
                'partner_id': partner.id,
                'picking_type_id': picking_type.id,
                'origin': origin,
                'order_line': po_lines,
            })
        if po.state in ('draft', 'sent'):
            po.button_confirm()
        if po.state == 'to approve':
            raise UserError(_(
                "Purchase %s is stuck awaiting approval; the Odoo user must be "
                "in the Purchase Manager group.") % po.name)

        picking = po.picking_ids.filtered(lambda p: p.state != 'cancel')[:1]
        if picking and picking.state != 'done':
            if picking.state == 'draft':
                picking.action_confirm()
            picking.action_assign()
            for move in picking.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
                move.quantity = move.product_uom_qty
                move.picked = True
                if move.product_id.tracking == 'serial':
                    ml = move.move_line_ids[:1] or self.env['stock.move.line'].create({
                        'move_id': move.id, 'picking_id': picking.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                    })
                    if not ml.lot_id and not ml.lot_name:
                        ml.lot_name = move.product_id.default_code
                    ml.quantity = move.product_uom_qty
                    ml.picked = True
            picking.with_context(
                skip_backorder=True, picking_ids_not_to_backorder=picking.ids,
            ).button_validate()
            if picking.state != 'done':
                picking.move_ids._action_done()

        if settle_from_vault and picking and picking.state == 'done':
            # Reuse the buy-back settlement: posts the PO's vendor bill and pays
            # the full amount out of the branch Vault (Cr Vault) — folds into the
            # POS shift automatically. Best-effort/idempotent (never blocks stock).
            self._settle_buyback_to_vault(po, warehouse, po.amount_total)

        # NOTE: deliberately NOT notified here. The ops app owns this event —
        # its /api/purchase/* endpoints wrap this method and already emit
        # `purchase-received` with the operator and warehouse. Emitting from
        # both sides would report one physical receipt twice.

        return [{'sku': p.default_code, 'product_id': p.id,
                 'name': p.display_name, 'qty': q} for p, q in resolved]

    @api.model
    def jewellery_market_value(self, grams, purity='21K', gold_type='jewellery_local'):
        """Reference market value for a gold quantity, using the SAME calc as
        product pricing — so the ops app can show operators a market value for
        anything being bought (bulk, bars, scrap). Returns cost/sale/min per the
        live 21K base + purity + markup.
        """
        try:
            grams = float(grams or 0.0)
        except (TypeError, ValueError):
            grams = 0.0
        if grams <= 0:
            return {'base_21k': 0.0, 'cost': 0.0, 'sale': 0.0, 'min_sale': 0.0}
        base = self.env['gold.price.service'].get_current_gold_price()
        weight_for_markup = grams if gold_type == 'bars' else None
        markup = get_markup_per_gram(self.env, gold_type, weight_g=weight_for_markup)
        min_markup = get_min_markup_per_gram(self.env, gold_type)
        cost, sale, min_sale = compute_gold_product_price(
            base, purity, grams, markup, min_markup)
        return {'base_21k': base, 'cost': cost, 'sale': sale, 'min_sale': min_sale}
