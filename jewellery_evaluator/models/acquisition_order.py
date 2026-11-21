# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Acquisition Order (AO): buying jewellery and stones from a vendor.

A jewellery-specific purchase document. Unlike a purchase order it never
receives stock: every piece gets its on-hand 1 when it is registered in the
operations app (the inventory invariant), and the AO only links those pieces.
What the AO records is the deal itself, by category / karat / origin and weight,
with the making fee per gram, plus the loose stones bought, and (later phases)
the payments and returns that settle the vendor's balance.

Totals are computed by ``utils.acquisition_totals`` (tested).
"""

from markupsafe import Markup
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..utils import (
    acquisition_balance,
    acquisition_payment,
    acquisition_progress,
    acquisition_totals,
    gold_price_from_metal_rate,
)
from .jewellery_stone import STONE_CLARITY_SELECTION, STONE_COLOR_SELECTION, STONE_SHAPE_SELECTION

KARAT_SELECTION = [('24K', '24K'), ('21K', '21K'), ('18K', '18K')]
ORIGIN_SELECTION = [('local', 'Local'), ('foreign', 'Foreign')]
KIND_SELECTION = [('vendor', 'Vendor'), ('customer', 'Customer')]
PAYMENT_JOURNAL_TYPES = ('cash', 'bank')


class JewelleryAcquisitionOrder(models.Model):
    _name = 'jewellery.acquisition.order'
    _description = 'Acquisition Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_order desc, id desc'

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True, default='New', index=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('done', 'Done'),
        ('cancel', 'Cancelled'),
    ], default='draft', required=True, tracking=True, copy=False)
    partner_id = fields.Many2one('res.partner', string='Vendor', required=True, tracking=True, index=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', tracking=True,
        default=lambda self: self.env.user.employee_id)
    confirmed_by_id = fields.Many2one('res.users', string='Confirmed by', readonly=True, copy=False)
    confirmed_on = fields.Datetime(readonly=True, copy=False)
    date_order = fields.Datetime(string='Date', required=True, default=fields.Datetime.now, tracking=True)
    warehouse_id = fields.Many2one('stock.warehouse', string='Branch', tracking=True,
                                   help='Where the pieces will be registered.')
    vendor_ref = fields.Char(string='Vendor reference', tracking=True)
    kind = fields.Selection(KIND_SELECTION, string='Bought from', required=True, default='vendor', tracking=True,
                            help='Customer = bought over the counter at the register.')
    pos_session_id = fields.Many2one('pos.session', string='Register session', readonly=True, copy=False)
    duplicate_warning = fields.Char(compute='_compute_duplicate_warning')
    note = fields.Html(string='Notes')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    usd_currency_id = fields.Many2one('res.currency', default=lambda self: self.env.ref('base.USD'))

    gold_price_21k = fields.Monetary(
        string='Gold price 21K / g', currency_field='currency_id', tracking=True,
        default=lambda self: self._default_gold_price(),
        help='Used for the metal value. Suggested from the live price; any positive value is accepted.')
    usd_rate = fields.Float(
        string='USD rate', digits=(12, 4), tracking=True,
        default=lambda self: self._default_usd_rate(),
        help='EGP per USD for the stones. Suggested from the live rate.')

    line_ids = fields.One2many('jewellery.acquisition.line', 'order_id', string='Jewellery', copy=True)
    stone_ids = fields.One2many('jewellery.acquisition.stone', 'order_id', string='Stones', copy=True)
    product_ids = fields.One2many('product.template', 'acquisition_order_id', string='SKUs')

    # Totals (utils.acquisition_totals)
    total_pieces = fields.Integer(compute='_compute_totals', store=True)
    grams_24k = fields.Float(string='24K grams', digits=(12, 3), compute='_compute_totals', store=True)
    grams_21k = fields.Float(string='21K grams', digits=(12, 3), compute='_compute_totals', store=True)
    grams_18k = fields.Float(string='18K grams', digits=(12, 3), compute='_compute_totals', store=True)
    grams_21k_eq = fields.Float(string='21K equivalent (g)', digits=(12, 3), compute='_compute_totals', store=True)
    making_fee_total = fields.Monetary(string='Making fee', compute='_compute_totals', store=True)
    metal_value = fields.Monetary(compute='_compute_totals', store=True)
    stone_count = fields.Integer(compute='_compute_totals', store=True)
    stone_carats = fields.Float(string='Carats', digits=(12, 3), compute='_compute_totals', store=True)
    stones_usd = fields.Monetary(string='Stones (USD)', currency_field='usd_currency_id',
                                 compute='_compute_totals', store=True)
    stones_egp = fields.Monetary(string='Stones (EGP)', compute='_compute_totals', store=True)
    total_egp = fields.Monetary(string='Total', compute='_compute_totals', store=True)

    # Payments (utils.acquisition_balance)
    payment_ids = fields.One2many('jewellery.acquisition.payment', 'order_id', string='Payments', copy=False)
    money_due = fields.Monetary(string='Money due', compute='_compute_totals', store=True,
                                help='Making fee + stones, paid in money.')
    grams_paid = fields.Float(string='Grams paid (21K eq.)', digits=(12, 3), compute='_compute_balance', store=True)
    grams_left = fields.Float(string='Grams owed (21K eq.)', digits=(12, 3), compute='_compute_balance', store=True)
    money_paid = fields.Monetary(compute='_compute_balance', store=True)
    money_left = fields.Monetary(string='Money owed', compute='_compute_balance', store=True)
    amount_paid = fields.Monetary(string='Cash paid', compute='_compute_balance', store=True)
    payment_state = fields.Selection([('not_paid', 'Not paid'), ('partial', 'Partly paid'), ('paid', 'Paid')],
                                     compute='_compute_balance', store=True, string='Payment')

    # SKUs registered against the order (utils.acquisition_progress)
    progress_html = fields.Html(string='Registration progress', compute='_compute_registered', sanitize=False)
    unmatched_count = fields.Integer(string='Not in any row', compute='_compute_registered')
    registered_count = fields.Integer(string='Registered', compute='_compute_registered')
    unregistered_count = fields.Integer(string='Not registered yet', compute='_compute_registered')
    registered_grams = fields.Float(string='Registered grams', digits=(12, 3), compute='_compute_registered')
    unregistered_grams = fields.Float(string='Grams not registered yet', digits=(12, 3),
                                      compute='_compute_registered')

    # ------------------------------------------------------------------ defaults
    @api.model
    def _default_gold_price(self):
        try:
            return float(self.env['ir.config_parameter'].sudo().get_param('jewellery_evaluator.fallback_price') or 0)
        except (TypeError, ValueError):
            return 0.0

    @api.model
    def _default_usd_rate(self):
        icp = self.env['ir.config_parameter'].sudo()
        for key in ('jewellery_evaluator.feed_usd_egp', 'jewellery_evaluator.diamond_exchange_rate_usd'):
            try:
                value = float(icp.get_param(key) or 0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                return value
        return 0.0

    # ------------------------------------------------------------------ computes
    @api.depends('line_ids.karat', 'line_ids.qty', 'line_ids.grams', 'line_ids.fee_per_gram',
                 'stone_ids.qty', 'stone_ids.carats', 'stone_ids.price_per_carat_usd',
                 'gold_price_21k', 'usd_rate')
    def _compute_totals(self):
        for order in self:
            t = acquisition_totals(
                [{'karat': line.karat, 'qty': line.qty, 'grams': line.grams, 'fee_per_gram': line.fee_per_gram}
                 for line in order.line_ids],
                [{'qty': s.qty, 'carats': s.carats, 'price_per_carat_usd': s.price_per_carat_usd}
                 for s in order.stone_ids],
                order.gold_price_21k, order.usd_rate)
            order.update({
                'total_pieces': t['pieces'],
                'grams_24k': t['grams']['24K'],
                'grams_21k': t['grams']['21K'],
                'grams_18k': t['grams']['18K'],
                'grams_21k_eq': t['grams_21k_eq'],
                'making_fee_total': t['making_fee'],
                'metal_value': t['metal_value'],
                'stone_count': t['stone_count'],
                'stone_carats': t['carats'],
                'stones_usd': t['stones_usd'],
                'stones_egp': t['stones_egp'],
                'total_egp': t['total_egp'],
                'money_due': t['making_fee'] + t['stones_egp'],
            })

    @api.depends('grams_21k_eq', 'money_due', 'payment_ids.state', 'payment_ids.grams_21k',
                 'payment_ids.money', 'payment_ids.amount')
    def _compute_balance(self):
        for order in self:
            live = order.payment_ids.filtered(lambda p: p.state == 'posted')
            b = acquisition_balance(order.grams_21k_eq, order.money_due,
                                    [{'grams_21k': p.grams_21k, 'money': p.money} for p in live])
            order.grams_paid = b['grams_paid']
            order.grams_left = b['grams_left']
            order.money_paid = b['money_paid']
            order.money_left = b['money_left']
            order.amount_paid = sum(live.mapped('amount'))
            order.payment_state = ('paid' if b['settled'] and (order.grams_21k_eq or order.money_due)
                                   else 'partial' if live else 'not_paid')

    @api.depends('partner_id', 'vendor_ref')
    def _compute_duplicate_warning(self):
        for order in self:
            ref = (order.vendor_ref or '').strip()
            other = self.env['jewellery.acquisition.order']
            if order.partner_id and ref:
                other = other.search([
                    ('partner_id', '=', order.partner_id.id), ('vendor_ref', '=ilike', ref),
                    ('state', '!=', 'cancel'), ('id', '!=', order._origin.id or 0)], limit=3)
            order.duplicate_warning = (
                _('%(vendor)s reference %(ref)s is already on %(orders)s. Check this is not the same purchase twice.',
                  vendor=order.partner_id.name, ref=ref, orders=', '.join(other.mapped('name')))
                if other else False)

    @api.depends('product_ids', 'line_ids.categ_id', 'line_ids.karat', 'line_ids.origin',
                 'line_ids.qty', 'line_ids.grams')
    def _compute_registered(self):
        origin_of = {'gold_local': 'local', 'gold_foreign': 'foreign'}
        for order in self:
            products = order.product_ids
            p = acquisition_progress(
                [{'key': (line.categ_id.id, line.karat, line.origin), 'qty': line.qty, 'grams': line.grams}
                 for line in order.line_ids],
                [{'category': prod.categ_id.id, 'karat': prod.gold_purity,
                  'origin': origin_of.get(prod.jewellery_type), 'grams': prod.gross_jewellery_weight_g}
                 for prod in products])
            order.registered_count = p['reg_qty']
            order.registered_grams = p['reg_grams']
            order.unregistered_count = p['left_qty']
            order.unregistered_grams = p['left_grams']
            order.unmatched_count = len(p['unmatched'])
            order.progress_html = order._progress_table(p, products)

    def _progress_table(self, p, products):
        """Expected vs registered, per jewellery row, plus pieces that fit no row."""
        categ = self.env['product.category'].browse
        origin_label = dict(ORIGIN_SELECTION)

        def g(value):
            return f'{value:,.3f}'

        rows = []
        for r in p['rows']:
            cat_id, karat, origin = r['key']
            pct = min(100, round(100 * r['reg_qty'] / r['qty'])) if r['qty'] else 0
            state = ('text-danger' if r['over'] else 'text-success' if not r['left_qty'] else '')
            rows.append(Markup(
                '<tr><td>{cat}</td><td>{karat}</td><td>{origin}</td>'
                '<td class="text-end">{rq} / {q}</td><td class="text-end">{rg} / {gr}</td>'
                '<td class="text-end {state}">{lq} pcs · {lg} g{over}</td>'
                '<td style="min-width:120px"><div class="progress" style="height:8px">'
                '<div class="progress-bar {bar}" style="width:{pct}%"></div></div></td></tr>').format(
                cat=categ(cat_id).display_name or '', karat=karat or '', origin=origin_label.get(origin, ''),
                rq=r['reg_qty'], q=r['qty'], rg=g(r['reg_grams']), gr=g(r['grams']), state=state,
                lq=r['left_qty'], lg=g(r['left_grams']),
                over=Markup(' · <b>more than bought</b>') if r['over'] else '',
                bar='bg-danger' if r['over'] else 'bg-success', pct=pct))
        unmatched = ''
        if p['unmatched']:
            items = [products[i] for i in p['unmatched']]
            unmatched = Markup(
                '<div class="alert alert-warning mt-2 mb-0 py-2"><b>{n} registered piece(s) fit no row</b> '
                '(category or karat not on this AO): {skus}</div>').format(
                n=len(items), skus=', '.join(f'{x.default_code} ({x.categ_id.display_name}, {x.gold_purity or "-"})'
                                            for x in items))
        return Markup(
            '<table class="table table-sm o_ao_progress mb-0"><thead><tr>'
            '<th>Category</th><th>Karat</th><th>Origin</th><th class="text-end">Pieces</th>'
            '<th class="text-end">Grams</th><th class="text-end">Still to register</th><th/></tr></thead>'
            '<tbody>{rows}</tbody><tfoot><tr class="fw-bold"><td colspan="3">Total</td>'
            '<td class="text-end">{rq} / {q}</td><td class="text-end">{rg} / {gr}</td>'
            '<td class="text-end">{lq} pcs · {lg} g</td><td/></tr></tfoot></table>{unmatched}').format(
            rows=Markup('').join(rows) if rows else Markup('<tr><td colspan="7" class="text-muted">'
                                                            'Add jewellery rows first.</td></tr>'),
            rq=p['reg_qty'], q=p['qty'], rg=g(p['reg_grams']), gr=g(p['grams']),
            lq=p['left_qty'], lg=g(p['left_grams']), unmatched=unmatched)

    # ------------------------------------------------------------------ lifecycle
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('jewellery.acquisition.order') or 'New'
        return super().create(vals_list)

    def action_confirm(self):
        for order in self:
            if order.state != 'draft':
                continue
            if not order.line_ids and not order.stone_ids:
                raise UserError(_('Add at least one jewellery or stone line before confirming %s.', order.name))
            if order.line_ids and order.gold_price_21k <= 0:
                raise UserError(_('Set a positive gold price on %s.', order.name))
            if order.stone_ids and order.usd_rate <= 0:
                raise UserError(_('Set a positive USD rate on %s.', order.name))
        self.filtered(lambda o: o.state == 'draft').write({
            'state': 'confirmed', 'confirmed_by_id': self.env.uid, 'confirmed_on': fields.Datetime.now()})

    def action_done(self):
        self.filtered(lambda o: o.state == 'confirmed').write({'state': 'done'})

    def action_cancel(self):
        for order in self:
            if order.product_ids:
                raise UserError(_('%s already has registered pieces; it cannot be cancelled.', order.name))
            if order.payment_ids.filtered(lambda p: p.state == 'posted'):
                raise UserError(_('%s has payments; cancel them first.', order.name))
        self.write({'state': 'cancel'})

    def action_draft(self):
        self.filtered(lambda o: o.state in ('confirmed', 'cancel')).write({'state': 'draft'})

    # ------------------------------------------------------------------ payments
    @api.model
    def _gold_price_at(self, when=None):
        """21K EGP/g at ``when``: the G21 metal-currency rate of that day (the
        gold cron writes one per day), else the live price."""
        currency = self.env.ref('jewellery_evaluator.currency_gold_21k', raise_if_not_found=False)
        if currency and when:
            rate = self.env['res.currency.rate'].sudo().search([
                ('currency_id', '=', currency.id), ('name', '<=', fields.Date.to_date(when)),
                ('company_id', 'in', (self.env.company.id, False))], order='name desc', limit=1)
            price = gold_price_from_metal_rate(rate.rate)
            if price > 0 and (fields.Date.to_date(when) - rate.name).days <= 7:
                return price
        return self._default_gold_price()

    def _register_payment(self, journal, grams_21k=0.0, gold_price_21k=0.0, money=0.0, date=None,
                          session=None, employee=None, note=None, key=None):
        """Pay the vendor: ``grams_21k`` of metal at ``gold_price_21k`` plus ``money``
        EGP, out of ``journal`` (a cash/bank journal). Posts Dr vendor payable /
        Cr the journal's account (a Vault journal: the shift's Vault sync folds it
        in). Idempotent per ``key``. Refuses paying more than is owed."""
        self.ensure_one()
        Payment = self.env['jewellery.acquisition.payment'].sudo()
        if key:
            existing = Payment.search([('key', '=', key)], limit=1)
            if existing:
                return existing
        if self.state == 'cancel':
            raise UserError(_('%s is cancelled.', self.name))
        if self.state == 'draft':
            self.action_confirm()
        if journal.type not in PAYMENT_JOURNAL_TYPES or journal.company_id != self.company_id:
            raise UserError(_('Pay from a cash or bank journal of %s.', self.company_id.name))
        account = journal.default_account_id
        if not account:
            raise UserError(_('Journal %s has no account.', journal.display_name))
        try:
            pay = acquisition_payment(grams_21k, gold_price_21k, money)
        except ValueError as exc:
            raise UserError(str(exc)) from None
        if pay['grams_21k'] > self.grams_left + 0.001:
            raise UserError(_('%(order)s owes %(left).3f g (21K eq.); %(g).3f g is more than that.',
                              order=self.name, left=max(self.grams_left, 0), g=pay['grams_21k']))
        if pay['money'] > self.money_left + 1:
            raise UserError(_('%(order)s owes %(left)s EGP in money; %(m)s is more than that.',
                              order=self.name, left=f'{max(self.money_left, 0):,.2f}', m=f'{pay["money"]:,.2f}'))
        when = date or fields.Datetime.now()
        partner = self.partner_id.commercial_partner_id
        payable = partner.with_company(self.company_id).property_account_payable_id
        if not payable:
            raise UserError(_('%s has no payable account.', partner.display_name))
        parts = []
        if pay['grams_21k']:
            parts.append(f"{pay['grams_21k']:,.3f} g 21K @ {float(gold_price_21k):,.2f}")
        if pay['money']:
            parts.append(f"{pay['money']:,.2f} EGP")
        label = _('%(order)s payment: %(what)s', order=self.name, what=' + '.join(parts))
        misc = self.env['account.journal'].sudo().search(
            [('type', '=', 'general'), ('company_id', '=', self.company_id.id)], limit=1)
        if not misc:
            raise UserError(_('No general journal found to post the payment.'))
        move = self.env['account.move'].sudo().create({
            'journal_id': misc.id, 'move_type': 'entry', 'date': fields.Date.to_date(when),
            'ref': label, 'jewellery_cash_ops_key': key or False,
            'line_ids': [
                (0, 0, {'account_id': payable.id, 'partner_id': partner.id, 'name': label,
                        'debit': pay['amount'], 'credit': 0.0}),
                (0, 0, {'account_id': account.id, 'partner_id': partner.id, 'name': label,
                        'debit': 0.0, 'credit': pay['amount']}),
            ],
        })
        move.action_post()
        payment = Payment.create({
            'order_id': self.id, 'date': when, 'journal_id': journal.id, 'move_id': move.id,
            'grams_21k': pay['grams_21k'], 'gold_price_21k': float(gold_price_21k or 0),
            'metal_amount': pay['metal_amount'], 'money': pay['money'], 'amount': pay['amount'],
            'pos_session_id': session.id if session else False,
            'employee_id': (employee or self.env.user.employee_id).id or False,
            'note': note or False, 'key': key or False,
        })
        self.message_post(body=Markup('<b>{}</b>: {} EGP {} {}').format(
            _('Paid'), f"{pay['amount']:,.2f}", _('from'), journal.display_name) + Markup('<br/>') + label)
        return payment

    def action_open_payment_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Pay %s', self.name),
            'res_model': 'jewellery.acquisition.payment.wizard', 'view_mode': 'form', 'target': 'new',
            'context': {'default_order_id': self.id},
        }

    @api.model
    def jewellery_ops_open_orders(self):
        """Open AOs for the operations app's register form, newest first."""
        orders = self.search([('state', 'in', ('draft', 'confirmed')), ('kind', '=', 'vendor')], limit=200)
        return [{
            'id': o.id, 'name': o.name, 'state': o.state,
            'partner_id': o.partner_id.id, 'partner_name': o.partner_id.display_name,
            'date': fields.Datetime.to_string(o.date_order), 'vendor_ref': o.vendor_ref or '',
            'warehouse_code': o.warehouse_id.code or '', 'pieces': o.total_pieces,
            'registered': o.registered_count, 'grams_21k_eq': o.grams_21k_eq,
            'lines': [{'category': ln.categ_id.display_name, 'karat': ln.karat, 'origin': ln.origin,
                       'qty': ln.qty, 'grams': ln.grams} for ln in o.line_ids],
        } for o in orders]

    def unlink(self):
        if any(o.state not in ('draft', 'cancel') for o in self):
            raise UserError(_('Only draft or cancelled acquisition orders can be deleted.'))
        if self.mapped('product_ids'):
            raise UserError(_('An acquisition order with registered pieces cannot be deleted.'))
        return super().unlink()


class JewelleryAcquisitionLine(models.Model):
    _name = 'jewellery.acquisition.line'
    _description = 'Acquisition Order jewellery line'
    _order = 'order_id, sequence, id'

    order_id = fields.Many2one('jewellery.acquisition.order', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    categ_id = fields.Many2one(
        'product.category', string='Category', required=True,
        domain="['|', '|', ('complete_name', '=like', 'Gold / %'), ('complete_name', '=like', 'Diamond / %'),"
               " ('complete_name', '=like', 'Silver / %')]")
    karat = fields.Selection(KARAT_SELECTION, required=True, default='18K')
    origin = fields.Selection(ORIGIN_SELECTION, required=True, default='local')
    qty = fields.Integer(string='Qty', required=True, default=1)
    grams = fields.Float(digits=(12, 3), required=True)
    fee_per_gram = fields.Monetary(string='Making fee / g', currency_field='currency_id')
    fee_total = fields.Monetary(string='Making fee', currency_field='currency_id',
                                compute='_compute_fee_total', store=True)
    currency_id = fields.Many2one(related='order_id.currency_id')

    @api.onchange('order_id')
    def _onchange_carry_over(self):
        """A new row starts with the karat, origin and making fee of the row above."""
        for line in self:
            if line._origin.id or not line.order_id:
                continue
            previous = [other for other in line.order_id.line_ids if other != line and other.karat]
            if previous:
                above = previous[-1]
                line.karat = above.karat
                line.origin = above.origin
                line.fee_per_gram = above.fee_per_gram

    @api.depends('grams', 'fee_per_gram')
    def _compute_fee_total(self):
        for line in self:
            line.fee_total = round(line.grams * line.fee_per_gram, 2)

    @api.constrains('qty', 'grams', 'fee_per_gram')
    def _check_positive(self):
        for line in self:
            if line.qty < 0 or line.grams < 0 or line.fee_per_gram < 0:
                raise UserError(_('Quantity, grams and making fee cannot be negative.'))


class JewelleryAcquisitionStone(models.Model):
    _name = 'jewellery.acquisition.stone'
    _description = 'Acquisition Order stone line'
    _order = 'order_id, sequence, id'

    order_id = fields.Many2one('jewellery.acquisition.order', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    shape = fields.Selection(STONE_SHAPE_SELECTION, required=True, default='Round')
    color = fields.Selection(STONE_COLOR_SELECTION)
    clarity = fields.Selection(STONE_CLARITY_SELECTION)
    qty = fields.Integer(string='Stones', required=True, default=1)
    carats = fields.Float(string='Total carats', digits=(12, 3), required=True)
    price_per_carat_usd = fields.Monetary(string='USD / ct', currency_field='usd_currency_id')
    total_usd = fields.Monetary(string='Total USD', currency_field='usd_currency_id',
                                compute='_compute_total', store=True)
    usd_currency_id = fields.Many2one(related='order_id.usd_currency_id')
    note = fields.Char()

    @api.depends('carats', 'price_per_carat_usd')
    def _compute_total(self):
        for stone in self:
            stone.total_usd = round(stone.carats * stone.price_per_carat_usd, 2)

    @api.constrains('qty', 'carats', 'price_per_carat_usd')
    def _check_positive(self):
        for stone in self:
            if stone.qty < 0 or stone.carats < 0 or stone.price_per_carat_usd < 0:
                raise UserError(_('Stones, carats and price cannot be negative.'))


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    acquisition_order_id = fields.Many2one(
        'jewellery.acquisition.order', string='Acquisition Order', index=True, copy=False,
        help='The AO this piece was bought on (set when it is registered).')


    def _jewellery_clean_ao_vals(self, vals):
        """The operations app sends the AO picked at registration. A stale id (AO
        deleted or cancelled meanwhile) is dropped, never allowed to fail the
        sync: the piece must reach Odoo either way."""
        ao_id = vals.get('acquisition_order_id')
        if ao_id:
            ao = self.env['jewellery.acquisition.order'].sudo().browse(int(ao_id)).exists()
            if not ao or ao.state == 'cancel':
                vals.pop('acquisition_order_id')
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._jewellery_clean_ao_vals(vals)
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('acquisition_order_id'):
            vals = self._jewellery_clean_ao_vals(dict(vals))
        return super().write(vals)


class JewelleryAcquisitionPayment(models.Model):
    _name = 'jewellery.acquisition.payment'
    _description = 'Acquisition Order payment'
    _order = 'date desc, id desc'

    order_id = fields.Many2one('jewellery.acquisition.order', required=True, ondelete='restrict', index=True)
    partner_id = fields.Many2one(related='order_id.partner_id', store=True)
    company_id = fields.Many2one(related='order_id.company_id', store=True)
    currency_id = fields.Many2one(related='order_id.currency_id')
    state = fields.Selection([('posted', 'Paid'), ('cancel', 'Cancelled')], default='posted', required=True)
    date = fields.Datetime(required=True, default=fields.Datetime.now)
    journal_id = fields.Many2one('account.journal', string='Paid from', required=True)
    move_id = fields.Many2one('account.move', string='Entry', readonly=True)
    grams_21k = fields.Float(string='Grams (21K eq.)', digits=(12, 3))
    gold_price_21k = fields.Monetary(string='Gold price 21K / g')
    metal_amount = fields.Monetary(string='For metal')
    money = fields.Monetary(string='For making fee / stones')
    amount = fields.Monetary(string='Cash paid')
    pos_session_id = fields.Many2one('pos.session', string='Register session')
    employee_id = fields.Many2one('hr.employee', string='Paid by')
    note = fields.Char()
    key = fields.Char(copy=False, index=True)

    _key_uniq = models.Constraint('unique(key)', 'This payment was already recorded.')

    def action_cancel_payment(self):
        """Reverse the entry and take the payment off the balance."""
        for payment in self.filtered(lambda p: p.state == 'posted'):
            if payment.move_id and payment.move_id.state == 'posted':
                payment.move_id.sudo()._reverse_moves(
                    [{'ref': _('Cancelled: %s', payment.move_id.ref or '')}], cancel=True)
            payment.state = 'cancel'
            payment.order_id.message_post(body=_('Payment of %s EGP cancelled.', f'{payment.amount:,.2f}'))

    def unlink(self):
        if self.filtered(lambda p: p.state == 'posted'):
            raise UserError(_('Cancel a payment instead of deleting it.'))
        return super().unlink()


class JewelleryAcquisitionPaymentWizard(models.TransientModel):
    _name = 'jewellery.acquisition.payment.wizard'
    _description = 'Pay an Acquisition Order'

    order_id = fields.Many2one('jewellery.acquisition.order', required=True)
    currency_id = fields.Many2one(related='order_id.currency_id')
    grams_left = fields.Float(related='order_id.grams_left')
    money_left = fields.Monetary(related='order_id.money_left')
    journal_id = fields.Many2one(
        'account.journal', string='Paid from', required=True,
        domain="[('type', 'in', ('cash', 'bank')), ('company_id', '=', company_id)]")
    company_id = fields.Many2one(related='order_id.company_id')
    date = fields.Datetime(required=True, default=fields.Datetime.now)
    grams_21k = fields.Float(string='Grams (21K eq.)', digits=(12, 3))
    gold_price_21k = fields.Monetary(string='Gold price 21K / g',
                                     help='Suggested from the price on that date; any positive value is accepted.')
    money = fields.Monetary(string='Making fee / stones (EGP)')
    amount = fields.Monetary(string='Cash paid', compute='_compute_amount')
    note = fields.Char()

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        order = self.env['jewellery.acquisition.order'].browse(res.get('order_id'))
        if order:
            res.setdefault('grams_21k', max(order.grams_left, 0.0))
            res.setdefault('money', max(order.money_left, 0.0))
            res.setdefault('gold_price_21k', order._gold_price_at(fields.Datetime.now()))
            if order.warehouse_id:
                vault = order.warehouse_id._vault_journal()
                if vault:
                    res.setdefault('journal_id', vault.id)
        return res

    @api.onchange('date')
    def _onchange_date(self):
        if self.date and self.order_id:
            self.gold_price_21k = self.order_id._gold_price_at(self.date)

    @api.depends('grams_21k', 'gold_price_21k', 'money')
    def _compute_amount(self):
        for wiz in self:
            wiz.amount = round((wiz.grams_21k or 0) * (wiz.gold_price_21k or 0), 2) + (wiz.money or 0)

    def action_pay(self):
        self.ensure_one()
        self.order_id._register_payment(self.journal_id, self.grams_21k, self.gold_price_21k, self.money,
                                        date=self.date, note=self.note)
        return {'type': 'ir.actions.act_window_close'}


class ResPartner(models.Model):
    _inherit = 'res.partner'

    acquisition_order_ids = fields.One2many('jewellery.acquisition.order', 'partner_id', string='Acquisition Orders')
    acquisition_count = fields.Integer(string='Acquisitions', compute='_compute_acquisition_stats')
    acquisition_grams_21k_eq = fields.Float(string='Bought (21K eq. g)', digits=(12, 3),
                                            compute='_compute_acquisition_stats')
    acquisition_making_fee = fields.Monetary(string='Making fee paid', compute='_compute_acquisition_stats',
                                             currency_field='acquisition_currency_id')
    acquisition_currency_id = fields.Many2one('res.currency', compute='_compute_acquisition_stats')

    def _compute_acquisition_stats(self):
        data = {}
        if self.ids:
            groups = self.env['jewellery.acquisition.order']._read_group(
                [('partner_id', 'in', self.ids), ('state', '!=', 'cancel')], ['partner_id'],
                ['__count', 'grams_21k_eq:sum', 'making_fee_total:sum'])
            data = {partner.id: (count, grams, fee) for partner, count, grams, fee in groups}
        for partner in self:
            count, grams, fee = data.get(partner.id, (0, 0.0, 0.0))
            partner.acquisition_count = count
            partner.acquisition_grams_21k_eq = grams
            partner.acquisition_making_fee = fee
            partner.acquisition_currency_id = self.env.company.currency_id

    def action_view_acquisitions(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('jewellery_evaluator.action_acquisition_order')
        action['domain'] = [('partner_id', '=', self.id)]
        action['context'] = {'default_partner_id': self.id, 'search_default_open': 0}
        return action
