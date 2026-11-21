# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Register "Purchase" helper: pay a vendor's Acquisition Order, or buy gold from
a customer over the counter, in cash out of the branch Vault.

Both go through ``jewellery.acquisition.order._register_payment``, which posts
Dr vendor payable / Cr Vault (so the shift's Vault sync folds the cash out in)
and is idempotent per the window's key. A customer purchase is a new AO of kind
"customer", confirmed and paid in full in one call, then marked Done (it never
appears in the operations app's open-AO picker). The AO never moves stock.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .acquisition_order import KARAT_SELECTION, ORIGIN_SELECTION

CATEGORY_ROOTS = ('Gold / %', 'Silver / %', 'Diamond / %')


class PosSessionAcquisition(models.Model):
    _inherit = 'pos.session'

    # ------------------------------------------------------------------ helpers
    def _ao_session(self, session_id):
        session = self.browse(int(session_id)).exists()
        if not session or session.state != 'opened':
            raise UserError(_('Purchases need an open register session.'))
        if not session.cash_journal_id.default_account_id:
            raise UserError(_('This register has no Vault (cash) journal.'))
        return session

    def _ao_employee(self, employee_id):
        if employee_id:
            employee = self.env['hr.employee'].sudo().browse(int(employee_id)).exists()
            if employee:
                return employee
        return self.env.user.employee_id

    @staticmethod
    def _ao_summary(order):
        return {
            'id': order.id, 'name': order.name, 'state': order.state,
            'date': fields.Datetime.to_string(order.date_order), 'vendor_ref': order.vendor_ref or '',
            'pieces': order.total_pieces, 'grams_21k_eq': order.grams_21k_eq,
            'grams_left': order.grams_left, 'money_due': order.money_due, 'money_left': order.money_left,
            'amount_paid': order.amount_paid, 'gold_price_21k': order.gold_price_21k,
            'grams': {'24K': order.grams_24k, '21K': order.grams_21k, '18K': order.grams_18k},
            'payment_state': order.payment_state,
        }

    # ------------------------------------------------------------------ RPCs
    @api.model
    def jewellery_ao_setup(self):
        """Live 21K price and the categories a counter purchase can use."""
        AO = self.env['jewellery.acquisition.order']
        cats = self.env['product.category'].sudo().search(
            ['|', '|'] + [('complete_name', '=like', root) for root in CATEGORY_ROOTS], order='complete_name')
        return {
            'gold_price_21k': AO._gold_price_at(fields.Datetime.now()),
            'categories': [{'id': c.id, 'name': c.complete_name} for c in cats],
            'karats': [k for k, _label in KARAT_SELECTION],
            'origins': [{'id': k, 'name': label} for k, label in ORIGIN_SELECTION],
        }

    @api.model
    def jewellery_ao_partners(self, query=''):
        """People to buy from / pay. Empty query: vendors with open AOs."""
        AO = self.env['jewellery.acquisition.order'].sudo()
        open_domain = [('state', 'in', ('draft', 'confirmed')), ('kind', '=', 'vendor')]
        Partner = self.env['res.partner'].sudo()
        query = (query or '').strip()
        if query:
            partners = Partner.search(['|', '|', ('name', 'ilike', query), ('phone', 'ilike', query),
                                       ('ref', 'ilike', query)], limit=20)
        else:
            partners = AO.search(open_domain).mapped('partner_id')[:30]
        counts = {}
        if partners:
            for partner, count in AO._read_group(open_domain + [('partner_id', 'in', partners.ids)],
                                                 ['partner_id'], ['__count']):
                counts[partner.id] = count
        rows = [{'id': p.id, 'name': p.display_name, 'phone': p.phone or '', 'open_aos': counts.get(p.id, 0)}
                for p in partners]
        rows.sort(key=lambda r: (-r['open_aos'], r['name'].lower()))
        return rows

    @api.model
    def jewellery_ao_partner_orders(self, partner_id):
        """A vendor's AOs that still owe something or are not closed."""
        orders = self.env['jewellery.acquisition.order'].sudo().search([
            ('partner_id', '=', int(partner_id)), ('state', 'in', ('draft', 'confirmed', 'done')),
            '|', ('state', '!=', 'done'), ('payment_state', '!=', 'paid')], limit=30)
        return [self._ao_summary(o) for o in orders]

    @api.model
    def jewellery_ao_pay(self, session_id, order_id, grams_21k, gold_price_21k, money, key, employee_id=None):
        """Pay part or all of an AO in cash from this register's Vault."""
        session = self._ao_session(session_id)
        order = self.env['jewellery.acquisition.order'].sudo().browse(int(order_id)).exists()
        if not order:
            raise UserError(_('That acquisition order no longer exists.'))
        payment = order._register_payment(
            session.cash_journal_id, grams_21k, gold_price_21k, money, session=session,
            employee=self._ao_employee(employee_id), note=_('Paid at %s', session.config_id.name), key=key)
        return {'order': self._ao_summary(order), 'amount': payment.amount, 'move': payment.move_id.name}

    @api.model
    def jewellery_ao_buy(self, session_id, partner, lines, gold_price_21k, key, note='', employee_id=None):
        """Buy from a customer at the counter: one AO, confirmed, paid in full.

        ``partner``: ``{id}`` or ``{name, phone}`` for a new person. ``lines``:
        ``{categ_id, karat, origin, qty, grams}``. Idempotent per ``key``.
        """
        session = self._ao_session(session_id)
        AO = self.env['jewellery.acquisition.order'].sudo()
        if key:
            done = self.env['jewellery.acquisition.payment'].sudo().search([('key', '=', key)], limit=1)
            if done:
                return {'order': self._ao_summary(done.order_id), 'amount': done.amount,
                        'move': done.move_id.name, 'duplicate': True}
        Partner = self.env['res.partner'].sudo()
        if partner.get('id'):
            person = Partner.browse(int(partner['id'])).exists()
        else:
            name = (partner.get('name') or '').strip()
            if not name:
                raise UserError(_("Enter the person's name."))
            person = Partner.create({'name': name, 'phone': (partner.get('phone') or '').strip() or False})
        if not person:
            raise UserError(_('Pick who you are buying from.'))
        karats = {k for k, _label in KARAT_SELECTION}
        origins = {k for k, _label in ORIGIN_SELECTION}
        allowed = set(self.env['product.category'].sudo().search(
            ['|', '|'] + [('complete_name', '=like', root) for root in CATEGORY_ROOTS]).ids)
        vals_lines = []
        for line in lines or []:
            grams = float(line.get('grams') or 0)
            if grams <= 0:
                continue
            categ_id = int(line.get('categ_id') or 0)
            if categ_id not in allowed or line.get('karat') not in karats:
                raise UserError(_('Every row needs a category and a karat.'))
            vals_lines.append((0, 0, {
                'categ_id': categ_id, 'karat': line['karat'],
                'origin': line.get('origin') if line.get('origin') in origins else 'local',
                'qty': max(int(line.get('qty') or 1), 0), 'grams': grams,
            }))
        if not vals_lines:
            raise UserError(_('Enter at least one row with grams.'))
        price = float(gold_price_21k or 0)
        if price <= 0:
            raise UserError(_('Enter a positive gold price.'))
        employee = self._ao_employee(employee_id)
        order = AO.create({
            'partner_id': person.id, 'kind': 'customer', 'employee_id': employee.id or False,
            'warehouse_id': session.config_id.picking_type_id.warehouse_id.id or False,
            'gold_price_21k': price, 'pos_session_id': session.id, 'line_ids': vals_lines,
            'note': note or False,
        })
        order.action_confirm()
        payment = order._register_payment(
            session.cash_journal_id, order.grams_21k_eq, price, 0.0, session=session, employee=employee,
            note=_('Bought at %s', session.config_id.name), key=key)
        order.action_done()
        return {'order': self._ao_summary(order), 'amount': payment.amount, 'move': payment.move_id.name}
