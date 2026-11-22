# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Register "Purchase" helper: pay a vendor's Acquisition Order, or buy gold from
a customer over the counter, in cash out of the branch Vault.

Both go through ``jewellery.acquisition.order._register_payment`` and are
idempotent per the window's key. "Paid from" is the register's Vault or a bank
journal (``_ao_paid_from_journals``, whitelisted server-side).

* Paying a vendor's AO: Dr vendor payable / Cr the journal (a Vault: the shift's
  Vault sync folds it in). Pieces get their stock when registered in ops.
* Buying from a customer at the counter: a new AO of kind "customer", confirmed,
  paid in full and Done (never in the ops open-AO picker). The gold is received
  on the spot as grams of SCRAP-GOLD-<karat> into the register's stock location,
  and the payment debits those SKUs' karat inventory accounts instead of the
  customer's payable (nothing is owed to or by them afterwards).
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..utils import GOLD_PURITY_FACTORS, allocate_amount
from .acquisition_order import KARAT_SELECTION, ORIGIN_SELECTION

_logger = logging.getLogger(__name__)
SCRAP_SKU = 'SCRAP-GOLD-%s'

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

    def _ao_paid_from_journals(self):
        """Where a register may pay from: its own Vault, then the company's bank
        journals in EGP (never another branch's Vault, an owner or a foreign box)."""
        self.ensure_one()
        banks = self.env['account.journal'].sudo().search([
            ('company_id', '=', self.company_id.id), ('type', '=', 'bank'),
            '|', ('currency_id', '=', False), ('currency_id', '=', self.company_id.currency_id.id)])
        return self.cash_journal_id | banks

    def _ao_journal(self, journal_id):
        self.ensure_one()
        allowed = self._ao_paid_from_journals()
        journal = allowed.browse(int(journal_id or 0)) if journal_id else self.cash_journal_id
        if journal not in allowed:
            raise UserError(_('This register cannot pay from that account.'))
        return journal

    def _ao_receive_scrap(self, order):
        """Put the bought gold on hand as grams of SCRAP-GOLD-<karat> in this
        register's stock location. Returns {karat: product.product}."""
        self.ensure_one()
        location = self.config_id.picking_type_id.default_location_src_id
        if not location:
            raise UserError(_('This register has no stock location for the bought gold.'))
        grams: dict[str, float] = {}
        for line in order.line_ids:
            grams[line.karat] = grams.get(line.karat, 0.0) + line.grams
        Product = self.env['product.product'].sudo()
        Quant = self.env['stock.quant'].sudo()
        products = {}
        for karat, qty in grams.items():
            product = Product.search([('default_code', '=', SCRAP_SKU % karat)], limit=1)
            if not product:
                raise UserError(_('The scrap product %s is missing.', SCRAP_SKU % karat))
            if not product.is_storable:
                product.product_tmpl_id.is_storable = True
            quant = Quant.search([('product_id', '=', product.id), ('location_id', '=', location.id),
                                  ('lot_id', '=', False)], limit=1)
            on_hand = quant.quantity if quant else 0.0
            if not quant:
                quant = Quant.with_context(inventory_mode=True).create(
                    {'product_id': product.id, 'location_id': location.id, 'inventory_quantity': on_hand + qty})
            else:
                quant.with_context(inventory_mode=True).inventory_quantity = on_hand + qty
            quant.with_context(inventory_mode=True, inventory_name=order.name).action_apply_inventory()
            products[karat] = product
        order.message_post(body=_('Received into %(loc)s: %(what)s', loc=location.display_name, what=', '.join(
            f'{qty:,.3f} g {SCRAP_SKU % karat}' for karat, qty in grams.items())))
        return products

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
    def jewellery_ao_setup(self, session_id=None):
        """Live 21K price, the categories a counter purchase can use and the
        accounts this register may pay from (its Vault first)."""
        AO = self.env['jewellery.acquisition.order']
        session = self.browse(int(session_id)).exists() if session_id else self.browse()
        journals = session._ao_paid_from_journals() if session else self.env['account.journal']
        cats = self.env['product.category'].sudo().search(
            ['|', '|'] + [('complete_name', '=like', root) for root in CATEGORY_ROOTS], order='complete_name')
        return {
            'gold_price_21k': AO._gold_price_at(fields.Datetime.now()),
            'categories': [{'id': c.id, 'name': c.complete_name} for c in cats],
            'karats': [k for k, _label in KARAT_SELECTION],
            'origins': [{'id': k, 'name': label} for k, label in ORIGIN_SELECTION],
            'journals': [{'id': j.id, 'name': j.name, 'vault': j == session.cash_journal_id} for j in journals],
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
    def jewellery_ao_pay(self, session_id, order_id, grams_21k, gold_price_21k, money, key, employee_id=None,
                         journal_id=None):
        """Pay part or all of an AO from this register's Vault or a bank journal."""
        session = self._ao_session(session_id)
        journal = session._ao_journal(journal_id)
        order = self.env['jewellery.acquisition.order'].sudo().browse(int(order_id)).exists()
        if not order:
            raise UserError(_('That acquisition order no longer exists.'))
        payment = order._register_payment(
            journal, grams_21k, gold_price_21k, money, session=session,
            employee=self._ao_employee(employee_id), note=_('Paid at %s', session.config_id.name), key=key)
        return {'order': self._ao_summary(order), 'amount': payment.amount, 'move': payment.move_id.name}

    @api.model
    def jewellery_ao_buy(self, session_id, partner, lines, gold_price_21k, key, note='', employee_id=None,
                         journal_id=None):
        """Buy from a customer at the counter: one AO, confirmed, paid in full.

        ``partner``: ``{id}`` or ``{name, phone}`` for a new person. ``lines``:
        ``{categ_id, karat, origin, qty, grams}``. Idempotent per ``key``.
        """
        session = self._ao_session(session_id)
        journal = session._ao_journal(journal_id)
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
            # The scrap SKUs count in units rounded to 0.01, so the grams paid
            # for are rounded the same way: stock always equals what was paid.
            grams = round(float(line.get('grams') or 0), 2)
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
            'gold_price_21k': price, 'pos_session_id': session.id, 'line_ids': vals_lines,
            'note': note or False,
        })
        order.action_confirm()
        products = session._ao_receive_scrap(order)
        # Debit each karat's inventory account with its share of the price.
        shares: dict[str, float] = {}
        for line in order.line_ids:
            shares[line.karat] = shares.get(line.karat, 0.0) + line.grams * float(GOLD_PURITY_FACTORS[line.karat])
        total = round(order.grams_21k_eq * price, 2)
        debit_accounts: dict = {}
        for karat, amount in allocate_amount(total, shares).items():
            account = products[karat].product_tmpl_id._get_product_accounts()['stock_valuation']
            debit_accounts[account] = debit_accounts.get(account, 0.0) + amount
        payment = order._register_payment(
            journal, order.grams_21k_eq, price, 0.0, session=session, employee=employee,
            note=_('Bought at %s', session.config_id.name), key=key, debit_accounts=debit_accounts)
        order.action_done()
        return {'order': self._ao_summary(order), 'amount': payment.amount, 'move': payment.move_id.name}
