# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'
    _INVOICE_MOVE_TYPES = ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')

    jewellery_stock_deducted = fields.Boolean(
        string='Jewellery stock deducted', default=False, copy=False,
        help="Set once a manual (non-POS) customer invoice has taken its sold "
             "storable pieces out of on-hand stock, so a re-post never "
             "double-counts.")

    jewellery_cash_ops_key = fields.Char(
        string='POS cash-op idempotency key', index=True, copy=False,
        help="Client token for a POS Currency/Owner-transfer entry. Lets the "
             "backend reuse an already-posted move on a retry instead of "
             "double-posting cash out of the Vault. See models/pos_cash_ops.py.")

    # Belt-and-suspenders against concurrent double-submit: Postgres treats NULLs
    # as distinct, so the (vast majority) keyless moves are unaffected; only two
    # cash-ops entries sharing a token collide — the second insert fails instead
    # of double-posting.
    _sql_constraints = [
        (
            'jewellery_cash_ops_key_uniq',
            'unique(jewellery_cash_ops_key)',
            'A POS cash operation with this idempotency key already exists.',
        ),
    ]

    def _post(self, soft=True):
        """A manual customer invoice (created in Invoicing, not the POS) must take
        the sold piece out of stock — otherwise a unique qty-1 jewellery piece
        stays on-hand while sold (phantom stock). Stock Odoo never moves stock
        from an invoice, so we reduce on-hand ourselves on post."""
        posted = super()._post(soft=soft)
        for move in posted:
            move._deduct_jewellery_stock()
        return posted

    def _deduct_jewellery_stock(self):
        """Reduce on-hand for the storable product lines of a posted manual
        customer invoice. Skipped for:
          * non ``out_invoice`` moves (only real sales reduce stock here);
          * POS invoices (the session already delivered — would double-count);
          * lines linked to a sale order (the SO delivers them);
          * non-storable products (e.g. sell-by-weight items — nothing to track).
        Idempotent via ``jewellery_stock_deducted`` (a re-post never re-deducts)
        and isolated in a savepoint, so a stock hiccup logs but never blocks the
        invoice. Refunds are NOT handled here (a return should add stock back —
        left for a dedicated flow).
        """
        self.ensure_one()
        if (self.move_type != 'out_invoice' or self.pos_order_ids
                or self.jewellery_stock_deducted):
            return
        has_sale = 'sale_line_ids' in self.env['account.move.line']._fields
        specs = [
            (ln.product_id, ln.quantity)
            for ln in self.invoice_line_ids
            if ln.product_id and ln.product_id.is_storable and ln.quantity > 0
            and not (has_sale and ln.sale_line_ids)
        ]
        if not specs:
            return
        try:
            with self.env.cr.savepoint():
                for product, qty in specs:
                    self._jewellery_reduce_onhand(product, qty)
                self.jewellery_stock_deducted = True
        except Exception as e:
            _logger.error(
                "Invoice %s: could not deduct jewellery stock (%s). Invoice is "
                "posted; stock NOT reduced — reduce on-hand manually.", self.name, e)

    def _jewellery_reduce_onhand(self, product, qty):
        """Take ``qty`` of a storable product out of on-hand via an inventory
        adjustment (clean for serial and non-serial alike — same primitive as
        ``init_jewellery_stock``). Walks the on-hand internal quants; logs if
        there is not enough stock rather than going negative."""
        quants = self.env['stock.quant'].sudo().search(
            [('product_id', '=', product.id),
             ('location_id.usage', '=', 'internal'),
             ('quantity', '>', 0)], order='quantity desc')
        remaining = qty
        for quant in quants:
            if remaining <= 0:
                break
            take = min(quant.quantity, remaining)
            qc = quant.with_context(inventory_mode=True)
            qc.inventory_quantity = quant.quantity - take
            qc.action_apply_inventory()
            remaining -= take
        if remaining > 0:
            _logger.warning(
                "Invoice %s: %s short by %s — not enough on-hand to deduct.",
                self.name, product.default_code or product.display_name, remaining)

    def default_get(self, fields_list):
        """
        Set invoice date defaults only when creating a new invoice record.
        This affects the "New" action flow and does not alter existing drafts.
        """
        values = super().default_get(fields_list)
        move_type = values.get('move_type') or self.env.context.get('default_move_type')
        if move_type in self._INVOICE_MOVE_TYPES:
            today = fields.Date.context_today(self)
            values['invoice_date'] = today
            # Keep accounting date aligned on new draft invoices unless caller set it.
            if 'date' in fields_list and not self.env.context.get('default_date'):
                values['date'] = today
        return values

    def _get_gold_invoice_lines(self):
        """
        Return invoice lines that have jewellery data (for report).
        Used by the gold invoice report template.
        Excludes section/note/rounding lines; includes product lines
        (display_type 'product' or False) that have jewellery data.
        """
        self.ensure_one()
        return self.invoice_line_ids.filtered(
            lambda line: line.display_type not in (
                'line_section', 'line_note', 'rounding'
            )
            and (
                line.jewellery_type
                or line.jewellery_weight_g
                or line.gold_purity
                or line.silver_purity
            )
        )
