# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import logging

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PosSessionCashOps(models.Model):
    """POS cash operations that move money out of the branch Vault as real
    accounting entries (so the pos.session Vault override folds them into the
    shift automatically — they credit the Vault GL account and are not POS
    statement lines):

    * currency conversion — Dr Vault-Foreign-<ccy> / Cr Vault (EGP), the foreign
      leg carrying the foreign amount in its own currency;
    * transfer to an owner — Dr Owner-journal account / Cr Vault.

    Both are backend methods called from the POS 'Currency' / 'Transfer to Owner'
    popups (frontend held separately). Posted via a general journal so the lines
    land directly on the cash accounts.
    """

    _inherit = 'pos.session'

    def _cash_ops_vault_account(self):
        self.ensure_one()
        acct = self.cash_journal_id.default_account_id
        if not acct:
            raise UserError(_("This POS has no Vault (cash) account."))
        return acct

    @api.model
    def post_currency_conversion(self, session_id, amount_egp, to_journal_id, to_amount):
        """Convert EGP out of the Vault into a foreign-currency Vault Foreign
        journal. ``amount_egp`` leaves the Vault (Cr); ``to_amount`` (in the
        target journal's currency) enters Vault Foreign (Dr). Rate is implicit
        in the two amounts. Returns the posted move name.
        """
        session = self.browse(session_id)
        amount_egp = float(amount_egp or 0.0)
        to_amount = float(to_amount or 0.0)
        if amount_egp <= 0 or to_amount <= 0:
            raise UserError(_("Enter positive amounts for the conversion."))
        vault_acct = session._cash_ops_vault_account()
        to_journal = self.env['account.journal'].browse(int(to_journal_id))
        fx_acct = to_journal.default_account_id
        ccy = to_journal.currency_id
        if not fx_acct:
            raise UserError(_("Vault Foreign journal %s has no account.") % to_journal.display_name)
        misc = self.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', session.company_id.id)], limit=1)
        fx_line = {'account_id': fx_acct.id, 'debit': amount_egp, 'credit': 0.0,
                   'name': _('Currency buy %s') % ccy.name}
        if ccy:
            fx_line.update({'currency_id': ccy.id, 'amount_currency': to_amount})
        move = self.env['account.move'].sudo().create({
            'journal_id': misc.id, 'move_type': 'entry',
            'ref': _('POS FX: %(egp)s EGP -> %(amt)s %(ccy)s') % {
                'egp': amount_egp, 'amt': to_amount, 'ccy': ccy.name or ''},
            'line_ids': [
                (0, 0, fx_line),
                (0, 0, {'account_id': vault_acct.id, 'debit': 0.0, 'credit': amount_egp,
                        'name': _('Vault cash out (FX)')}),
            ],
        })
        move.action_post()
        return {'move': move.name}

    @api.model
    def post_owner_transfer(self, session_id, owner_journal_id, amount):
        """Move ``amount`` EGP cash from the Vault to an owner journal
        (Dr Owner / Cr Vault). Returns the posted move name.
        """
        session = self.browse(session_id)
        amount = float(amount or 0.0)
        if amount <= 0:
            raise UserError(_("Enter a positive amount."))
        vault_acct = session._cash_ops_vault_account()
        owner_journal = self.env['account.journal'].browse(int(owner_journal_id))
        owner_acct = owner_journal.default_account_id
        if not owner_acct:
            raise UserError(_("Owner journal %s has no account.") % owner_journal.display_name)
        misc = self.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', session.company_id.id)], limit=1)
        move = self.env['account.move'].sudo().create({
            'journal_id': misc.id, 'move_type': 'entry',
            'ref': _('POS transfer to %s') % owner_journal.name,
            'line_ids': [
                (0, 0, {'account_id': owner_acct.id, 'debit': amount, 'credit': 0.0,
                        'name': _('Transfer to %s') % owner_journal.name}),
                (0, 0, {'account_id': vault_acct.id, 'debit': 0.0, 'credit': amount,
                        'name': _('Vault cash out (owner)')}),
            ],
        })
        move.action_post()
        return {'move': move.name}
