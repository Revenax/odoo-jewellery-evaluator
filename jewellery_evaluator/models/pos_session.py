# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import logging

from odoo import api, models

from .. import pulse

_logger = logging.getLogger(__name__)


class PosSession(models.Model):
    """Make the POS shift count reflect the whole **Vault** (the cash journal),
    not just POS sales.

    Stock Odoo computes the expected drawer cash as
    ``opening + POS cash sales + POS cash-in/out`` and never looks at the cash
    journal's other entries. In this shop, real cash also moves through the same
    Vault via customer invoices paid in cash, buy-back/supplier payments, and
    transfers (bank deposit, branch-to-branch, petty cash). Each of those posts
    ONCE to the Vault as an ordinary payment/journal entry — so the right fix is
    to have the POS *read* those, not to re-key them as cash-in/out (which would
    double-count anything that already has a document behind it).

    We fold every such "foreign" Vault movement into both the backend balance
    (``_compute_cash_balance`` — so the close posts the correct cash difference,
    not a false profit/loss) and the cashier's close screen
    (``get_closing_control_data`` — so Expected matches the physical vault).
    """

    _inherit = 'pos.session'

    def _vault_foreign_move_lines(self):
        """Posted move lines that hit the Vault GL account during this session
        but are NOT POS-owned.

        The key filter excludes POS-owned cash, which is always an
        ``account.bank.statement.line`` tied to a POS session. We keep a line if
        it has NO statement line (a plain payment/journal move — how cash
        payments post once the Vault journal is configured to post direct to its
        account) OR its statement line is not a POS one (a manual cash statement).
        It must be an explicit OR: ``statement_line_id.pos_session_id = False``
        alone silently drops rows where ``statement_line_id`` itself is NULL
        (Odoo joins through the m2o), i.e. exactly the payment lines we want.
        This counts each foreign movement exactly once in BOTH states:
          * open   -> POS sales are still only in ``pos.payment`` (not yet on the
                      journal), so this returns foreign moves only;
          * closed -> POS sales are on the journal but via close statement lines,
                      which are excluded here.
        Window is ``[start_at, stop_at or now]`` by move creation time, so it
        tracks when the cash physically moved, not the (possibly back-dated)
        accounting date.
        """
        self.ensure_one()
        account = self.cash_journal_id.default_account_id
        if not account or not self.start_at:
            return self.env['account.move.line']
        domain = [
            ('account_id', '=', account.id),
            ('move_id.state', '=', 'posted'),
            '|',
            ('statement_line_id', '=', False),
            ('statement_line_id.pos_session_id', '=', False),
            ('move_id.create_date', '>=', self.start_at),
        ]
        if self.stop_at:
            domain.append(('move_id.create_date', '<=', self.stop_at))
        return self.env['account.move.line'].sudo().search(domain)

    @api.depends('payment_method_ids', 'order_ids', 'cash_register_balance_start')
    def _compute_cash_balance(self):
        super()._compute_cash_balance()
        for session in self:
            if not (session.cash_journal_id
                    and session.payment_method_ids.filtered('is_cash_count')):
                continue
            # balance = debit - credit = net cash into the Vault (cash-in
            # invoices add, buy-backs/deposits subtract).
            foreign = sum(session._vault_foreign_move_lines().mapped('balance'))
            if foreign:
                session.cash_register_balance_end += foreign
                session.cash_register_difference = (
                    session.cash_register_balance_end_real
                    - session.cash_register_balance_end
                )

    def get_closing_control_data(self):
        data = super().get_closing_control_data()
        self.ensure_one()
        cash = data.get('default_cash_details')
        if not cash:
            return data
        moves = []
        total = 0.0
        for line in self._vault_foreign_move_lines():
            total += line.balance
            name = (line.move_id.ref or line.move_id.name or line.name
                    or 'Vault movement')
            moves.append({
                'name': name,
                'amount': line.balance,
                'id': line.id,
                'date': line.move_id.create_date or line.date,
                'cashier_name': line.partner_id.name or '',
            })
        if moves:
            cash['amount'] += total
            cash['moves'] = (cash.get('moves') or []) + moves
        return data

    def _validate_session(self, balancing_account=False, amount_to_balance=0,
                          bank_payment_method_diffs=None):
        """Close the shift, then report the count.

        The whole point of the vault override above is that the cashier counts
        the WHOLE drawer, so the closing difference is the number that says
        whether the day reconciles. Sent after the close succeeds, so a
        notification can never be the reason a shift fails to close.
        """
        result = super()._validate_session(
            balancing_account=balancing_account,
            amount_to_balance=amount_to_balance,
            bank_payment_method_diffs=bank_payment_method_diffs,
        )
        for session in self:
            try:
                session._pulse_notify_closed()
            except Exception as exc:
                _logger.warning(
                    '[pulse] could not describe the close of session %s: %s',
                    session.id, exc)
        return result

    def _pulse_notify_closed(self):
        currency = self.currency_id.name or self.company_id.currency_id.name or ''
        expected = self.cash_register_balance_end
        counted = self.cash_register_balance_end_real
        diff = self.cash_register_difference
        register = self.config_id.name or ''
        # A difference is the interesting case, so it gets its own topic and can
        # be made urgent without every routine close paging anyone.
        topic = 'shift-closed-short' if abs(diff) >= 0.01 else 'shift-closed'
        pulse.notify_in_background(
            topic,
            'Shift closed short' if diff < -0.01 else (
                'Shift closed over' if diff > 0.01 else 'Shift closed'),
            f'{register} — counted {counted:,.0f} {currency} against expected '
            f'{expected:,.0f}'
            + (f', off by {diff:+,.0f}' if abs(diff) >= 0.01 else ', exact')
            + f'. Opened {self.cash_register_balance_start:,.0f}.',
            {
                'session': self.id,
                'register': register,
                'opening': self.cash_register_balance_start,
                'expected': expected,
                'counted': counted,
                'difference': diff,
                'currency': currency,
                'orders': len(self.order_ids),
            },
            pulse.make_idempotency_key('pos.session', self.id, 'closed'),
            env=self.env,
        )
