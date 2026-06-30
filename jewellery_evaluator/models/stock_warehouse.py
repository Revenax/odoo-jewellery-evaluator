# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

from odoo import fields, models


class StockWarehouse(models.Model):
    """Map each branch's warehouse to the cash journal that backs its physical
    Vault, so buy-back cash-outs (and future per-branch cash flows) post to the
    right Vault and surface in that branch's POS shift count."""

    _inherit = 'stock.warehouse'

    vault_journal_id = fields.Many2one(
        'account.journal',
        string='Vault (cash) journal',
        domain="[('type', '=', 'cash')]",
        help="Cash journal backing this branch's physical Vault. Buy-back cash "
             "payments post here so the branch POS shift count reflects them. "
             "Leave empty in a single-branch setup to fall back to the "
             "company's only cash journal.")

    def _vault_journal(self):
        """The Vault journal for this warehouse, falling back to the company's
        sole cash journal when unset (single-branch shops)."""
        self.ensure_one()
        if self.vault_journal_id:
            return self.vault_journal_id
        return self.env['account.journal'].search([
            ('type', '=', 'cash'),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
