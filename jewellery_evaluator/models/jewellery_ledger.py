# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

"""The Daily Ledger — the digital twin of the shop's physical day book.

One page per day: opening cash, every sale (POS and manual invoices), every
other cash movement through the Vault (buy-backs, owner transfers, currency
conversions, deposits), and the closing count. Read-only: it assembles what is
already posted; it never writes.
"""

from datetime import datetime, time, timedelta

import pytz
from odoo import api, fields, models

# The shop's timezone when the user has none configured.
_FALLBACK_TZ = 'Africa/Cairo'


class JewelleryLedger(models.AbstractModel):
    _name = 'jewellery.ledger'
    _description = 'Daily Sales & Cash Ledger'

    def _day_window_utc(self, date_str):
        """(start, end) naive-UTC datetimes covering the LOCAL day."""
        day = fields.Date.from_string(date_str)
        tz = pytz.timezone(self.env.user.tz or _FALLBACK_TZ)
        start_local = tz.localize(datetime.combine(day, time.min))
        end_local = start_local + timedelta(days=1)
        return (
            start_local.astimezone(pytz.utc).replace(tzinfo=None),
            end_local.astimezone(pytz.utc).replace(tzinfo=None),
        )

    def _to_local(self, dt):
        if not dt:
            return ''
        tz = pytz.timezone(self.env.user.tz or _FALLBACK_TZ)
        return pytz.utc.localize(dt).astimezone(tz).strftime('%H:%M')

    @api.model
    def ledger_data(self, date_str):
        """Everything the physical day book records, for one local day."""
        start, end = self._day_window_utc(date_str)

        # ── POS sessions of the day (opening / closing cash) ────────────────
        sessions = self.env['pos.session'].sudo().search([
            ('start_at', '<', end),
            '|', ('stop_at', '>=', start), ('stop_at', '=', False),
        ], order='start_at')
        session_blocks = []
        for s in sessions:
            session_blocks.append({
                'id': s.id,
                'config': s.config_id.name,
                'state': s.state,
                'opened_by': s.user_id.name,
                'opened_at': self._to_local(s.start_at),
                'closed_at': self._to_local(s.stop_at),
                'opening_cash': s.cash_register_balance_start,
                # Includes the vault-sync fold-in (foreign cash movements), so
                # this matches the physical drawer, not just POS sales.
                'expected_close': s.cash_register_balance_end,
                'counted_close': (
                    s.cash_register_balance_end_real if s.state == 'closed' else False
                ),
                'difference': (
                    s.cash_register_difference if s.state == 'closed' else False
                ),
            })

        # ── Sales: POS orders of the day ─────────────────────────────────────
        orders = self.env['pos.order'].sudo().search([
            ('date_order', '>=', start), ('date_order', '<', end),
            ('state', '!=', 'cancel'),
        ], order='date_order')
        sale_rows = []
        method_totals = {}
        for o in orders:
            payments = []
            for p in o.payment_ids:
                label = p.payment_method_id.name
                payments.append(f'{label} {p.amount:.0f}')
                method_totals[label] = method_totals.get(label, 0.0) + p.amount
            sale_rows.append({
                'time': self._to_local(o.date_order),
                'ref': o.pos_reference or o.name,
                'customer': o.partner_id.name or '',
                'cashier': o.employee_id.name if o.employee_id else o.user_id.name,
                'items': ', '.join(
                    (ln.product_id.default_code or ln.product_id.name or '?')
                    + ('' if ln.qty == 1 else f' ×{ln.qty:g}')
                    for ln in o.lines
                ),
                'amount': o.amount_total,
                'payments': ', '.join(payments),
                'is_refund': o.amount_total < 0,
            })

        # ── Sales: manual (non-POS) invoices posted that day ────────────────
        invoices = self.env['account.move'].sudo().search([
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('state', '=', 'posted'),
            ('pos_order_ids', '=', False),
            ('invoice_date', '=', fields.Date.from_string(date_str)),
        ], order='name')
        invoice_rows = [{
            'ref': m.name,
            'customer': m.partner_id.name or '',
            'items': ', '.join(
                (ln.product_id.default_code or (ln.name or '')[:20])
                for ln in m.invoice_line_ids if ln.display_type == 'product'
            ),
            'amount': m.amount_total_signed,
            'state': m.payment_state,
        } for m in invoices]

        # ── Other cash movements through the Vault(s) ───────────────────────
        # Same exclusion rule as the vault sync (pos_session.py): keep posted
        # lines on a Vault cash account that are NOT POS statement lines, so
        # each buy-back / owner transfer / currency op / cash-invoice payment
        # appears exactly once and POS sales are never double-counted.
        vault_accounts = self.env['account.journal'].sudo().search([
            ('type', '=', 'cash'),
            ('company_id', '=', self.env.company.id),
        ]).default_account_id
        movements = []
        if vault_accounts:
            lines = self.env['account.move.line'].sudo().search([
                ('account_id', 'in', vault_accounts.ids),
                ('move_id.state', '=', 'posted'),
                '|',
                ('statement_line_id', '=', False),
                ('statement_line_id.pos_session_id', '=', False),
                ('move_id.create_date', '>=', start),
                ('move_id.create_date', '<', end),
            ], order='id')
            for line in lines:
                movements.append({
                    'time': self._to_local(line.move_id.create_date),
                    'journal': line.journal_id.name,
                    'label': line.move_id.ref or line.name or line.move_id.name,
                    'amount': line.balance,  # +into the drawer / −out of it
                })

        currency = self.env.company.currency_id
        return {
            'date': date_str,
            'currency': currency.symbol or currency.name,
            'sessions': session_blocks,
            'sales': sale_rows,
            'invoices': invoice_rows,
            'movements': movements,
            'totals': {
                'sales_count': len(sale_rows),
                'sales_total': sum(r['amount'] for r in sale_rows),
                'invoices_total': sum(r['amount'] for r in invoice_rows),
                'by_method': [
                    {'method': k, 'amount': v} for k, v in sorted(method_totals.items())
                ],
                'movements_net': sum(m['amount'] for m in movements),
            },
        }
