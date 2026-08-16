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

import logging
from datetime import datetime, time, timedelta

import pytz
from odoo import api, fields, models

from .. import pulse

_logger = logging.getLogger(__name__)

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

    # Arabic day names, indexed by Python weekday() (Mon=0).
    _AR_DAYS = ('الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس',
                'الجمعة', 'السبت', 'الأحد')

    @staticmethod
    def _split_weight(grams):
        """Grams -> (whole grams, thousandths) for the جرام / مللي columns.

        The book writes 12.500 g as جرام=12, مللي=500. Carrying 1000 up keeps a
        rounded 4.9996 from ever printing as "4 g 1000 mg".
        """
        grams = grams or 0.0
        whole = int(grams)
        milli = int(round((grams - whole) * 1000))
        if milli >= 1000:
            whole += 1
            milli -= 1000
        return whole, milli

    @staticmethod
    def _karat_of(product):
        """The فئة column: the karat number (21/18/24) or silver fineness."""
        if not product:
            return ''
        tmpl = product.product_tmpl_id
        if tmpl.gold_purity:
            return tmpl.gold_purity.replace('K', '')
        if tmpl.silver_purity:
            return tmpl.silver_purity
        return ''

    def _line_weight(self, product):
        """Weight for the جرام/مللي columns, matching the printed invoice rule:
        diamond pieces are weighed GROSS, everything else plain."""
        if not product:
            return 0.0
        tmpl = product.product_tmpl_id
        if tmpl.jewellery_type in ('diamond_jewellery', 'center_stone'):
            return tmpl.gross_jewellery_weight_g or 0.0
        return tmpl.jewellery_weight_g or 0.0

    @api.model
    def ledger_rows(self, date_str, config_id=None):
        """The day book as the shop keeps it on paper.

        One row per movement, carrying BOTH money and gold weight, in the
        physical column order: وارد (in) / منصرف (out) / مللي / جرام / فئة /
        بيان / مصدر / ملاحظات. `config_id` scopes it to one register (the POS
        view); omit for the whole company (the backend view).
        """
        start, end = self._day_window_utc(date_str)
        day = fields.Date.from_string(date_str)

        session_domain = [
            ('start_at', '<', end),
            '|', ('stop_at', '>=', start), ('stop_at', '=', False),
        ]
        if config_id:
            session_domain.append(('config_id', '=', int(config_id)))
        sessions = self.env['pos.session'].sudo().search(session_domain, order='start_at')

        rows = []
        total_in = total_out = 0.0
        weight_in = weight_out = 0.0

        # ── Sales / refunds from the register ───────────────────────────────
        order_domain = [
            ('date_order', '>=', start), ('date_order', '<', end),
            ('state', '!=', 'cancel'),
        ]
        if config_id:
            order_domain.append(('config_id', '=', int(config_id)))
        for order in self.env['pos.order'].sudo().search(order_domain, order='date_order'):
            methods = ', '.join(p.payment_method_id.name for p in order.payment_ids)
            notes = ' · '.join(x for x in (order.partner_id.name, methods) if x)
            for line in order.lines:
                if not line.qty:
                    continue
                weight = self._line_weight(line.product_id) * abs(line.qty)
                amount = line.price_subtotal_incl
                # A negative qty is a return: the piece comes back in and the
                # money goes out, so it lands in منصرف, not وارد.
                is_return = line.qty < 0
                grams, milli = self._split_weight(weight)
                rows.append({
                    'time': self._to_local(order.date_order),
                    'in': 0.0 if is_return else amount,
                    'out': abs(amount) if is_return else 0.0,
                    'grams': grams,
                    'milli': milli,
                    'karat': self._karat_of(line.product_id),
                    'desc': (line.product_id.default_code
                             or line.product_id.name or ''),
                    'qty': abs(line.qty),
                    'source': 'مرتجع' if is_return else 'محل',
                    'notes': notes,
                    'ref': order.pos_reference or order.name,
                    'kind': 'return' if is_return else 'sale',
                })
                if is_return:
                    total_out += abs(amount)
                    weight_out += weight
                else:
                    total_in += amount
                    weight_in += weight

        # ── Non-POS invoices (only company-wide; a register has none) ───────
        if not config_id:
            for move in self.env['account.move'].sudo().search([
                ('move_type', 'in', ('out_invoice', 'out_refund')),
                ('state', '=', 'posted'),
                ('pos_order_ids', '=', False),
                ('invoice_date', '=', day),
            ], order='name'):
                for line in move.invoice_line_ids:
                    if line.display_type != 'product':
                        continue
                    weight = self._line_weight(line.product_id) * abs(line.quantity)
                    grams, milli = self._split_weight(weight)
                    credit_note = move.move_type == 'out_refund'
                    amount = abs(line.price_subtotal)
                    rows.append({
                        'time': '',
                        'in': 0.0 if credit_note else amount,
                        'out': amount if credit_note else 0.0,
                        'grams': grams, 'milli': milli,
                        'karat': self._karat_of(line.product_id),
                        'desc': (line.product_id.default_code
                                 or (line.name or '')[:30]),
                        'qty': abs(line.quantity),
                        'source': 'فاتورة',
                        'notes': move.partner_id.name or '',
                        'ref': move.name,
                        'kind': 'invoice',
                    })
                    if credit_note:
                        total_out += amount
                        weight_out += weight
                    else:
                        total_in += amount
                        weight_in += weight

        # ── Other Vault cash movements (buy-backs, owner, currency) ─────────
        # Same exclusion rule as the vault sync so POS cash is never counted twice.
        journal_domain = [('type', '=', 'cash'), ('company_id', '=', self.env.company.id)]
        if config_id:
            cfg = self.env['pos.config'].sudo().browse(int(config_id))
            if cfg.journal_id and cfg.journal_id.type == 'cash':
                journal_domain = [('id', '=', cfg.journal_id.id)]
            else:
                cash_methods = cfg.payment_method_ids.filtered('is_cash_count')
                jids = cash_methods.journal_id.ids
                if jids:
                    journal_domain = [('id', 'in', jids)]
        accounts = self.env['account.journal'].sudo().search(journal_domain).default_account_id
        if accounts:
            for line in self.env['account.move.line'].sudo().search([
                ('account_id', 'in', accounts.ids),
                ('move_id.state', '=', 'posted'),
                '|',
                ('statement_line_id', '=', False),
                ('statement_line_id.pos_session_id', '=', False),
                ('move_id.create_date', '>=', start),
                ('move_id.create_date', '<', end),
            ], order='id'):
                amount = line.balance
                rows.append({
                    'time': self._to_local(line.move_id.create_date),
                    'in': amount if amount > 0 else 0.0,
                    'out': -amount if amount < 0 else 0.0,
                    'grams': 0, 'milli': 0, 'karat': '',
                    'desc': line.move_id.ref or line.name or line.move_id.name,
                    'qty': '',
                    'source': line.journal_id.name,
                    'notes': '',
                    'ref': line.move_id.name,
                    'kind': 'cash',
                })
                if amount > 0:
                    total_in += amount
                else:
                    total_out += -amount

        rows.sort(key=lambda r: r['time'] or '')

        opening = sum(s.cash_register_balance_start for s in sessions)
        expected = sum(s.cash_register_balance_end for s in sessions)
        counted = sum(
            s.cash_register_balance_end_real for s in sessions if s.state == 'closed'
        )
        closed_all = bool(sessions) and all(s.state == 'closed' for s in sessions)
        g_in, m_in = self._split_weight(weight_in)
        g_out, m_out = self._split_weight(weight_out)
        currency = self.env.company.currency_id

        return {
            'date': date_str,
            'day_name': self._AR_DAYS[day.weekday()],
            'serial': ' / '.join(str(s.id) for s in sessions) or '—',
            'registers': ', '.join(s.config_id.name for s in sessions) or '—',
            'currency': currency.symbol or currency.name,
            'opening': opening,
            'expected_close': expected,
            'counted_close': counted if closed_all else False,
            'difference': (counted - expected) if closed_all else False,
            'open_session': any(s.state != 'closed' for s in sessions),
            'rows': rows,
            'totals': {
                'in': total_in,
                'out': total_out,
                'net': total_in - total_out,
                'grams_in': g_in, 'milli_in': m_in,
                'grams_out': g_out, 'milli_out': m_out,
                'count': len(rows),
            },
        }

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
        method_totals: dict[str, float] = {}
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

    @api.model
    def cron_notify_daily_summary(self):
        """End-of-day totals to Revenax. Reports YESTERDAY, so it can run in the
        early hours and always cover a whole, closed day.

        Reuses ``ledger_rows`` — the same numbers the shop reads off the paper
        day book, so the notification and the book can never disagree.
        """
        try:
            tz = pytz.timezone(self.env.user.tz or 'Africa/Cairo')
            yesterday = (datetime.now(tz) - timedelta(days=1)).date()
            date_str = fields.Date.to_string(yesterday)
            book = self.ledger_rows(date_str)
        except Exception as exc:
            _logger.warning('[pulse] could not build the daily summary: %s', exc)
            return False

        totals = book['totals']
        currency = book['currency']
        weight = ''
        if totals['grams_in'] or totals['milli_in']:
            weight = (f" · {totals['grams_in']}g "
                      f"{totals['milli_in']}mg gold out")

        pulse.notify(
            'daily-summary',
            f'Day totals — {book["day_name"]} {date_str}',
            f'In {totals["in"]:,.0f} {currency} · Out {totals["out"]:,.0f} · '
            f'Net {totals["net"]:,.0f} across {totals["count"]} movement(s)'
            f'{weight}. Closing {book["counted_close"] or book["expected_close"]:,.0f}.',
            {
                'date': date_str,
                'in': totals['in'], 'out': totals['out'], 'net': totals['net'],
                'movements': totals['count'],
                'opening': book['opening'],
                'closingCounted': book['counted_close'],
                'closingExpected': book['expected_close'],
                'currency': currency,
            },
            # One summary per day, however many times the cron is retried.
            pulse.make_idempotency_key('daily-summary', date_str),
            env=self.env,
        )
        return True
