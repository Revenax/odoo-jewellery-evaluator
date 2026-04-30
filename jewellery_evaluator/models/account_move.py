# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'
    _INVOICE_MOVE_TYPES = ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')

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
