# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import logging

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


# Single source of truth for which journals the cash-ops popups may target,
# shared by pos.config (to ship the dropdown lists to the register) and the
# pos.session RPCs (to WHITELIST the journal server-side — the frontend list is
# not trusted). Company-scoped. Vault Foreign = cash journals in a non-company
# currency; Owner = cash journals named "Owner …".
def vault_foreign_journal_domain(company):
    return [
        ("company_id", "=", company.id),
        ("type", "=", "cash"),
        ("currency_id", "!=", False),
        ("currency_id", "!=", company.currency_id.id),
    ]


def owner_journal_domain(company):
    return [
        ("company_id", "=", company.id),
        ("type", "=", "cash"),
        ("name", "=like", "Owner%"),
    ]


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

    def _cash_ops_check_session(self):
        """The RPCs are POS-user callable, so verify server-side that the
        target session exists and is OPEN — never trust the client to only call
        against a live shift (a closed/other session must not absorb cash)."""
        self.ensure_one()
        if not self.exists() or self.state != "opened":
            raise UserError(_("Cash operations require an open POS session."))

    def _cash_ops_resolve_journal(self, journal_id, kind):
        """Resolve + WHITELIST the target journal server-side. The frontend
        dropdown is only a convenience; here we recompute the allowed set from
        the same domain and reject anything outside it, so a crafted RPC cannot
        move Vault cash to an arbitrary account. ``kind`` is 'foreign'|'owner'."""
        self.ensure_one()
        Journal = self.env["account.journal"].sudo()
        domain = (
            vault_foreign_journal_domain(self.company_id)
            if kind == "foreign"
            else owner_journal_domain(self.company_id)
        )
        allowed = Journal.search(domain)
        journal = Journal.browse(int(journal_id))
        if journal not in allowed:
            raise UserError(_("That journal is not permitted for this operation."))
        if not journal.default_account_id:
            raise UserError(_("Journal %s has no account.") % journal.display_name)
        return journal

    def _cash_ops_existing_move(self, key):
        """Idempotency: return an already-posted move for this client key, so a
        retry after a lost response (or a double-click) reuses it instead of
        posting a second real cash movement out of the Vault."""
        if not key:
            return self.env["account.move"]
        return self.env["account.move"].sudo().search(
            [("jewellery_cash_ops_key", "=", key)], limit=1
        )

    def _cash_ops_misc_journal(self):
        self.ensure_one()
        misc = self.env["account.journal"].sudo().search(
            [("type", "=", "general"), ("company_id", "=", self.company_id.id)],
            limit=1,
        )
        if not misc:
            raise UserError(_("No general journal found to post the entry."))
        return misc

    @api.model
    def post_currency_conversion(self, session_id, amount_egp, to_journal_id, to_amount, key=None):
        """Convert EGP out of the Vault into a foreign-currency Vault Foreign
        journal. ``amount_egp`` leaves the Vault (Cr); ``to_amount`` (in the
        target journal's currency) enters Vault Foreign (Dr). Rate is implicit
        in the two amounts. ``key`` is a client idempotency token. Returns the
        posted move name (and ``duplicate: True`` if it already existed).
        """
        session = self.browse(session_id)
        session._cash_ops_check_session()
        existing = session._cash_ops_existing_move(key)
        if existing:
            return {"move": existing.name, "duplicate": True}
        amount_egp = float(amount_egp or 0.0)
        to_amount = float(to_amount or 0.0)
        if amount_egp <= 0 or to_amount <= 0:
            raise UserError(_("Enter positive amounts for the conversion."))
        vault_acct = session._cash_ops_vault_account()
        to_journal = session._cash_ops_resolve_journal(to_journal_id, "foreign")
        fx_acct = to_journal.default_account_id
        ccy = to_journal.currency_id
        misc = session._cash_ops_misc_journal()
        fx_line = {'account_id': fx_acct.id, 'debit': amount_egp, 'credit': 0.0,
                   'name': _('Currency buy %s') % ccy.name}
        if ccy:
            fx_line.update({'currency_id': ccy.id, 'amount_currency': to_amount})
        move = self.env['account.move'].sudo().create({
            'journal_id': misc.id, 'move_type': 'entry',
            'jewellery_cash_ops_key': key or False,
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
    def post_owner_transfer(self, session_id, owner_journal_id, amount, key=None):
        """Move ``amount`` EGP cash from the Vault to an owner journal
        (Dr Owner / Cr Vault). ``key`` is a client idempotency token. Returns
        the posted move name (and ``duplicate: True`` if it already existed).
        """
        session = self.browse(session_id)
        session._cash_ops_check_session()
        existing = session._cash_ops_existing_move(key)
        if existing:
            return {"move": existing.name, "duplicate": True}
        amount = float(amount or 0.0)
        if amount <= 0:
            raise UserError(_("Enter a positive amount."))
        vault_acct = session._cash_ops_vault_account()
        owner_journal = session._cash_ops_resolve_journal(owner_journal_id, "owner")
        owner_acct = owner_journal.default_account_id
        misc = session._cash_ops_misc_journal()
        move = self.env['account.move'].sudo().create({
            'journal_id': misc.id, 'move_type': 'entry',
            'jewellery_cash_ops_key': key or False,
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
