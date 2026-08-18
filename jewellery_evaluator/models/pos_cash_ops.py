# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import logging

from odoo import _, api, models
from odoo.exceptions import UserError

from .. import pulse

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
    """POS cash operations that move money between the branch Vault, the foreign
    Vault Foreign boxes, and the owners, as real accounting entries (so the
    pos.session Vault override folds the EGP-Vault leg into the shift
    automatically — those legs credit/debit the Vault GL account and are not POS
    statement lines):

    * currency conversion — two-way. Buy foreign: Dr Vault-Foreign / Cr Vault
      (EGP); sell foreign: Dr Vault / Cr Vault-Foreign. The foreign leg carries
      the foreign amount in its own currency (amount_currency, signed to match
      the debit/credit).
    * transfer to an owner — two-way, any box. Owner takes out: Dr Owner / Cr
      Box; owner deposits in: Dr Box / Cr Owner. The box is the EGP Vault or any
      Vault Foreign; foreign boxes carry amount_currency.

    Both are backend methods called from the POS 'Currency' / 'Transfer to Owner'
    popups (frontend held separately). Posted via a general journal so the lines
    land directly on the cash accounts. Amounts are entered as two figures (the
    EGP value + the foreign amount) — no server-side rate maths.
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

    def _cash_ops_resolve_box(self, box_journal_id):
        """Resolve + WHITELIST a 'vault box' for owner transfers: either the
        session's EGP Vault (cash_journal_id) or one of the branch's Vault
        Foreign journals. Anything else is rejected."""
        self.ensure_one()
        Journal = self.env["account.journal"].sudo()
        allowed = self.cash_journal_id | Journal.search(
            vault_foreign_journal_domain(self.company_id)
        )
        journal = Journal.browse(int(box_journal_id))
        if journal not in allowed:
            raise UserError(_("That box is not permitted for this operation."))
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

    def _cash_ops_post(self, key, ref, lines):
        """Create + post a balanced general-journal entry for the given line
        dicts, tagging it with the idempotency key."""
        self.ensure_one()
        misc = self._cash_ops_misc_journal()
        move = self.env['account.move'].sudo().create({
            'journal_id': misc.id, 'move_type': 'entry',
            'jewellery_cash_ops_key': key or False, 'ref': ref,
            'line_ids': [(0, 0, ln) for ln in lines],
        })
        move.action_post()
        return {'move': move.name}

    @staticmethod
    def _cash_ops_leg(account, egp, is_debit, name, ccy=None, foreign_amount=0.0):
        """One move line. ``egp`` is the company-currency value on debit/credit;
        for a foreign leg, amount_currency is +foreign on a debit, −foreign on a
        credit (Odoo sign convention)."""
        line = {
            'account_id': account.id,
            'debit': egp if is_debit else 0.0,
            'credit': 0.0 if is_debit else egp,
            'name': name,
        }
        if ccy:
            line['currency_id'] = ccy.id
            line['amount_currency'] = foreign_amount if is_debit else -foreign_amount
        return line

    @api.model
    def post_currency_conversion(self, session_id, direction, journal_id,
                                 amount_egp, to_amount, key=None):
        """Two-way currency conversion between the EGP Vault and a foreign Vault
        Foreign box. ``direction`` is 'buy' (EGP → foreign) or 'sell' (foreign →
        EGP). ``amount_egp`` is the EGP that moves through the drawer;
        ``to_amount`` is the foreign amount that moves through the box. ``key`` is
        a client idempotency token. Returns the posted move name (and
        ``duplicate: True`` if it already existed)."""
        session = self.browse(session_id)
        session._cash_ops_check_session()
        existing = session._cash_ops_existing_move(key)
        if existing:
            return {"move": existing.name, "duplicate": True}
        if direction not in ("buy", "sell"):
            raise UserError(_("Invalid conversion direction."))
        amount_egp = float(amount_egp or 0.0)
        to_amount = float(to_amount or 0.0)
        if amount_egp <= 0 or to_amount <= 0:
            raise UserError(_("Enter positive amounts for the conversion."))
        vault_acct = session._cash_ops_vault_account()
        fx_journal = session._cash_ops_resolve_journal(journal_id, "foreign")
        fx_acct = fx_journal.default_account_id
        ccy = fx_journal.currency_id
        leg = session._cash_ops_leg
        if direction == "buy":
            # EGP leaves the drawer (Cr Vault); foreign enters the box (Dr Foreign).
            lines = [
                leg(fx_acct, amount_egp, True, _('Currency buy %s') % ccy.name,
                    ccy, to_amount),
                leg(vault_acct, amount_egp, False, _('Vault cash out (FX buy)')),
            ]
            ref = _('POS FX buy: %(egp)s EGP -> %(amt)s %(ccy)s') % {
                'egp': amount_egp, 'amt': to_amount, 'ccy': ccy.name}
        else:
            # Foreign leaves the box (Cr Foreign); EGP enters the drawer (Dr Vault).
            lines = [
                leg(vault_acct, amount_egp, True, _('Vault cash in (FX sell)')),
                leg(fx_acct, amount_egp, False, _('Currency sell %s') % ccy.name,
                    ccy, to_amount),
            ]
            ref = _('POS FX sell: %(amt)s %(ccy)s -> %(egp)s EGP') % {
                'amt': to_amount, 'ccy': ccy.name, 'egp': amount_egp}
        result = session._cash_ops_post(key, ref, lines)

        # Foreign currency crossing the drawer. Its own topic: unlike an owner
        # transfer the money does not leave the business, but the rate is struck
        # by hand at the counter, so it is worth a second pair of eyes.
        if not (result or {}).get('duplicate'):
            pulse.notify_in_background(
                'currency-exchanged',
                'Currency bought' if direction == 'buy' else 'Currency sold',
                f'{amount_egp:,.0f} EGP '
                f'{"->" if direction == "buy" else "<-"} '
                f'{to_amount:,.2f} {ccy.name} '
                f'(rate {(amount_egp / to_amount) if to_amount else 0:,.2f})',
                {
                    'direction': direction,
                    'amountEgp': amount_egp,
                    'amountForeign': to_amount,
                    'currency': ccy.name,
                    'rate': round(amount_egp / to_amount, 4) if to_amount else 0,
                    'move': (result or {}).get('move', ''),
                },
                pulse.make_idempotency_key(
                    'fx', (result or {}).get('move') or key),
                env=self.env,
            )
        return result

    @api.model
    def post_owner_transfer(self, session_id, direction, owner_journal_id,
                            box_journal_id, amount, amount_egp, key=None):
        """Two-way owner transfer between a vault box and an owner. ``direction``
        is 'out' (box → owner) or 'in' (owner → box). ``box_journal_id`` is the
        EGP Vault or a Vault Foreign box. ``amount`` is in the box currency;
        ``amount_egp`` is its EGP value (== ``amount`` for the EGP box). ``key``
        is a client idempotency token. Returns the posted move name (and
        ``duplicate: True`` if it already existed)."""
        session = self.browse(session_id)
        session._cash_ops_check_session()
        existing = session._cash_ops_existing_move(key)
        if existing:
            return {"move": existing.name, "duplicate": True}
        if direction not in ("out", "in"):
            raise UserError(_("Invalid transfer direction."))
        amount = float(amount or 0.0)
        amount_egp = float(amount_egp or 0.0)
        if amount <= 0 or amount_egp <= 0:
            raise UserError(_("Enter positive amounts."))
        owner_journal = session._cash_ops_resolve_journal(owner_journal_id, "owner")
        owner_acct = owner_journal.default_account_id
        box = session._cash_ops_resolve_box(box_journal_id)
        box_acct = box.default_account_id
        company_ccy = session.company_id.currency_id
        is_foreign = bool(box.currency_id) and box.currency_id != company_ccy
        ccy = box.currency_id if is_foreign else None
        if not is_foreign:
            # EGP box is single-currency: the EGP value is the amount itself.
            amount_egp = amount
        leg = session._cash_ops_leg
        if direction == "out":
            # Dr Owner / Cr Box — cash leaves the box, to the owner.
            lines = [
                leg(owner_acct, amount_egp, True,
                    _('Transfer to %s') % owner_journal.name, ccy, amount),
                leg(box_acct, amount_egp, False,
                    _('%s cash out (owner)') % box.name, ccy, amount),
            ]
            ref = _('POS owner out: %(name)s <- %(amt)s %(ccy)s') % {
                'name': owner_journal.name, 'amt': amount,
                'ccy': (ccy.name if ccy else company_ccy.name)}
        else:
            # Dr Box / Cr Owner — the owner deposits cash into the box.
            lines = [
                leg(box_acct, amount_egp, True,
                    _('%s cash in (owner)') % box.name, ccy, amount),
                leg(owner_acct, amount_egp, False,
                    _('Deposit from %s') % owner_journal.name, ccy, amount),
            ]
            ref = _('POS owner in: %(name)s -> %(amt)s %(ccy)s') % {
                'name': owner_journal.name, 'amt': amount,
                'ccy': (ccy.name if ccy else company_ccy.name)}
        result = session._cash_ops_post(key, ref, lines)

        # Cash moving between the drawer and an owner is the largest routine
        # non-sale movement in the shop. Skip the duplicate replay so a
        # double-click does not notify twice.
        if not (result or {}).get('duplicate'):
            currency = (ccy.name if ccy else company_ccy.name) or ''
            pulse.notify_in_background(
                'payout-sent',
                'Owner cash out' if direction == 'out' else 'Owner cash in',
                f'{owner_journal.name} '
                f'{"took" if direction == "out" else "deposited"} '
                f'{amount:,.0f} {currency} '
                f'{"from" if direction == "out" else "into"} {box.name}',
                {
                    'owner': owner_journal.name, 'box': box.name,
                    'direction': direction, 'amount': amount,
                    'amountEgp': amount_egp, 'currency': currency,
                    'move': (result or {}).get('move', ''),
                },
                pulse.make_idempotency_key(
                    'owner-transfer', (result or {}).get('move') or key),
                env=self.env,
            )
        return result
