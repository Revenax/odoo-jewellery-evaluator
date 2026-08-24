# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .. import pulse
from ..utils import format_payment_summary

_logger = logging.getLogger(__name__)

# Same selections as product.template for gold fields on order line
GOLD_PURITY_SELECTION = [
    ('24K', '24K'),
    ('21K', '21K'),
    ('18K', '18K'),
    ('14K', '14K'),
    ('10K', '10K'),
]
GOLD_TYPE_SELECTION = [
    ('jewellery_local', 'Jewellery - Local'),
    ('jewellery_foreign', 'Jewellery - Foreign'),
    ('bars', 'Bars'),
]
JEWELLERY_TYPE_SELECTION = [
    ('gold_local', 'Gold - Local'),
    ('gold_foreign', 'Gold - Foreign'),
    ('gold_bars', 'Gold Bars'),
    ('diamond_jewellery', 'Diamond Jewellery'),
    ('center_stone', 'Center Stone'),
    ('silver', 'Silver'),
]
SILVER_PURITY_SELECTION = [
    ('999.0', '999.0'),
    ('999.9', '999.9'),
]


def _override_uses_pos_hr(env):
    """True when pos_hr is installed — managers approve with employee PIN/badge."""
    return bool(
        env['ir.module.module'].sudo().search_count(
            [('name', '=', 'pos_hr'), ('state', '=', 'installed')]
        )
    )


def _override_master_pin(env):
    """The configured fallback master override PIN (used only when pos_hr is off)."""
    return (
        env['ir.config_parameter'].sudo().get_param(
            'jewellery_evaluator.override_master_pin'
        )
        or ''
    ).strip()


def _is_manager_employee(env, employee_id, config):
    """
    True when ``employee_id`` is a POS manager for this config — the same rule
    pos_hr uses to tag an employee 'manager': their user is in
    ``point_of_sale.group_pos_manager``, or the employee is in the config's
    advanced (manager-access) employee list.
    """
    if not employee_id:
        return False
    try:
        Employee = env['hr.employee'].sudo()
    except KeyError:
        # hr / pos_hr not installed — no employee model to check against.
        return False
    employee = Employee.browse(employee_id)
    if not employee.exists():
        return False
    if config and 'advanced_employee_ids' in config._fields:
        if employee_id in config.advanced_employee_ids.ids:
            return True
    mgr_group = env.ref('point_of_sale.group_pos_manager', raise_if_not_found=False)
    return bool(
        mgr_group
        and employee.user_id
        and mgr_group.id in employee.user_id.all_group_ids.ids
    )


def _override_is_authorised(env, uid, config):
    """
    Whether an approver id authorises a below-minimum sale.

    pos_hr on  -> uid must be a POS manager employee.
    pos_hr off -> master mode: allowed when a master override PIN is configured
                  (the register verified it offline; there is no per-user id).
    """
    if _override_uses_pos_hr(env):
        return _is_manager_employee(env, uid, config)
    return bool(_override_master_pin(env))


def _as_user_id(value):
    """Normalise a POS-sync payload (int / [id] / (id, name) / {'id':..}) to an int id."""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else 0
    if isinstance(value, dict):
        value = value.get('id', 0)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


class PosOrder(models.Model):
    _inherit = 'pos.order'

    require_customer = fields.Selection(
        related="session_id.config_id.require_customer",
    )

    @api.model
    def _process_order(self, order, existing_order):
        """Notify AFTER the order is fully built, payments included.

        The hook used to sit on create(), but core attaches payments later via
        _process_payment_lines, so the notification could only ever have
        reported a blank payment method. A re-synced order lands here again;
        the idempotency key is the order id, so Pulse collapses the repeat.
        """
        order_id = super()._process_order(order, existing_order)
        try:
            self.browse(order_id)._pulse_notify_sale()
        except Exception as exc:
            _logger.warning('[pulse] could not notify order %s: %s', order_id, exc)
        return order_id

    def _pulse_notify_sale(self):
        """Tell Revenax about a completed sale. Never blocks or breaks the sale.

        Fired in the background: the cashier is waiting on this request, and a
        notification is never worth a slower checkout — let alone a failed one.
        """
        try:
            currency = self.currency_id.name or ''
            total = self.amount_total
            reference = self.pos_reference or self.name
            register = self.session_id.config_id.name or ''
            customer = self.partner_id.name or 'Walk-in'
            paid_with = format_payment_summary(
                [(p.payment_method_id.name, p.amount) for p in self.payment_ids]
            )
            pieces = ', '.join(
                line.product_id.default_code or line.product_id.name
                for line in self.lines[:5] if line.product_id
            )

            # A wholly negative order is a return, not a sale.
            if total < 0:
                pulse.notify_in_background(
                    'refund-issued',
                    'Refund issued',
                    f'{reference} — {abs(total):,.0f} {currency}, {register}, '
                    f'{customer}' + (f' · {paid_with}' if paid_with else ''),
                    {
                        'reference': reference, 'amount': abs(total),
                        'currency': currency, 'register': register,
                        'paymentMethods': paid_with, 'posOrderId': self.id,
                    },
                    pulse.make_idempotency_key('pos.order', self.id, 'refunded'),
                    env=self.env,
                )
                return

            pulse.notify_in_background(
                'order-paid',
                'Order paid',
                f'{reference} — {total:,.0f} {currency}, {register}, {customer}'
                + (f' · {paid_with}' if paid_with else '')
                + (f' · {pieces}' if pieces else ''),
                {
                    'reference': reference, 'amount': total, 'currency': currency,
                    'register': register, 'paymentMethods': paid_with,
                    'posOrderId': self.id,
                },
                pulse.make_idempotency_key('pos.order', self.id, 'paid'),
                env=self.env,
            )

            # A separate topic so an unusually large sale can be made urgent on
            # Revenax's side without turning every routine sale into an alert.
            threshold = self._pulse_large_order_threshold()
            if threshold > 0 and total >= threshold:
                pulse.notify_in_background(
                    'order-large',
                    'Large order',
                    f'{reference} — {total:,.0f} {currency}, {register}, '
                    f'{customer}' + (f' · {paid_with}' if paid_with else ''),
                    {
                        'reference': reference, 'amount': total,
                        'currency': currency, 'threshold': threshold,
                        'register': register, 'paymentMethods': paid_with,
                        'posOrderId': self.id,
                    },
                    pulse.make_idempotency_key('pos.order', self.id, 'large'),
                    env=self.env,
                )
        except Exception as exc:
            # Gathering the message must not be able to fail a sale either.
            _logger.warning('[pulse] could not describe order %s: %s', self.id, exc)

    def _pulse_large_order_threshold(self):
        """EGP above which a sale is also announced as `order-large`."""
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'jewellery_evaluator.pulse_large_order_threshold', '250000')
        try:
            return float(raw or 0)
        except (TypeError, ValueError):
            return 0.0

    # Audit summary of below-minimum manager overrides on this order's lines.
    # The cashier who made the sale is pos_hr's own ``employee_id`` ("Cashier").
    has_min_price_override = fields.Boolean(
        string="Below-Min Override",
        compute="_compute_min_price_override_summary",
        help="At least one line on this order was sold below its minimum sale "
             "price with manager approval.",
    )
    override_approver_names = fields.Char(
        string="Below-Min Approved By",
        compute="_compute_min_price_override_summary",
        help="Manager(s) who approved selling a line below its minimum sale "
             "price on this order.",
    )

    @api.depends('lines.min_price_override', 'lines.override_approver_name')
    def _compute_min_price_override_summary(self):
        for order in self:
            overridden = order.lines.filtered('min_price_override')
            order.has_min_price_override = bool(overridden)
            names = {n for n in overridden.mapped('override_approver_name') if n}
            order.override_approver_names = ', '.join(sorted(names))

    # Audit summary of already-sold (over-sell) manager overrides on this order.
    has_stock_override = fields.Boolean(
        string="Already-Sold Override",
        compute="_compute_stock_override_summary",
        help="At least one line on this order sold a unique piece that had no "
             "available stock (already sold) with manager approval.",
    )
    stock_override_approver_names = fields.Char(
        string="Already-Sold Approved By",
        compute="_compute_stock_override_summary",
        help="Manager(s) who approved selling an already-sold piece on this order.",
    )

    @api.depends('lines.stock_override', 'lines.stock_override_approver_name')
    def _compute_stock_override_summary(self):
        for order in self:
            overridden = order.lines.filtered('stock_override')
            order.has_stock_override = bool(overridden)
            names = {
                n for n in overridden.mapped('stock_override_approver_name') if n
            }
            order.stock_override_approver_names = ', '.join(sorted(names))

    @api.constrains("partner_id", "session_id")
    def _check_partner(self):
        for rec in self:
            if rec.require_customer != "no" and not rec.partner_id:
                raise ValidationError(
                    _("Customer is required for this order and is missing.")
                )

    def _enrich_order_line_vals_with_gold(self, line_vals):
        """
        Add jewellery and gold-specific fields to a single order line vals dict.
        Used when building order from UI.
        """
        product_id = line_vals.get('product_id')
        if not product_id:
            return
        product = self.env['product.product'].browse(product_id)
        if not product.exists():
            return

        line_vals['jewellery_type'] = getattr(product, 'jewellery_type', False)
        line_vals['jewellery_weight_g'] = getattr(product, 'jewellery_weight_g', 0.0) or 0.0
        line_vals['silver_purity'] = getattr(product, 'silver_purity', False)

        if not getattr(product, 'is_gold_product', False):
            return
        line_vals['gold_purity'] = product.gold_purity
        line_vals['gold_weight_g'] = product.jewellery_weight_g or 0.0
        line_vals['gold_type'] = product.gold_type
        line_vals['making_fee'] = getattr(product, 'making_fee', 0.0) or 0.0
        try:
            gold_price_service = self.env['gold.price.service']
            line_vals['gold_price_per_gram'] = (
                gold_price_service.get_current_gold_price()
            )
        except Exception as e:
            raise ValidationError(
                _('Could not fetch gold price for order line. '
                  'Please check gold price settings. Details: %s') % str(e)
            ) from e

    @api.model
    def _order_fields(self, ui_order):
        """
        Override to validate gold product prices before order creation and to
        populate gold-specific fields on each order line from product and price
        service.
        """
        order_fields = super()._order_fields(ui_order)

        # POS config for this order — drives how a below-minimum override is
        # authorised (pos_hr manager employee vs the master-PIN fallback).
        session = self.env['pos.session'].browse(ui_order.get('pos_session_id'))
        override_config = (
            session.config_id if session.exists() else self.env['pos.config']
        )
        # uuid -> authorised override payload. Frontend-sent line fields are not
        # guaranteed to survive super()._order_fields, so we validate them here
        # against the raw ui_order lines and re-stamp them onto the persisted
        # lines below (matched by uuid).
        authorised_overrides = {}

        # Validate each line for gold/silver products
        lines_data = ui_order.get('lines', [])
        for line_data in lines_data:
            if len(line_data) < 3 or not isinstance(line_data[2], dict):
                continue
            line_vals = line_data[2]
            # A refund/return line has negative qty — it is not a sale, so the
            # minimum sale-price floor must NOT block returning a piece (its
            # original price can be below today's higher min after a gold move).
            _qty = line_vals.get('qty', 0)
            try:
                if float(_qty) < 0:
                    continue
            except (TypeError, ValueError):
                pass
            product_id = line_vals.get('product_id')
            price_unit = line_vals.get('price_unit', 0)
            discount = line_vals.get('discount', 0)

            if not product_id:
                continue
            product = self.env['product.product'].browse(product_id)
            if not product.exists():
                continue
            if getattr(product, 'is_gold_product', False):
                # Enforce minimum sale price; if none set, assume 20% max discount
                effective_min = product.gold_min_sale_price or (price_unit * 0.8)
            elif getattr(product, 'is_silver_product', False):
                effective_min = product.silver_min_sale_price or (price_unit * 0.8)
            elif getattr(product, 'is_diamond_jewellery_product', False):
                effective_min = product.diamond_min_sale_price or (price_unit * 0.8)
            else:
                continue
            if effective_min <= 0:
                continue
            final_price = price_unit * (1 - discount / 100.0)
            if final_price < effective_min:
                # Below the floor: allowed only with a valid manager override,
                # otherwise blocked exactly as before.
                override = self._validate_min_price_override(
                    line_vals, product, effective_min, final_price, override_config
                )
                uuid = line_vals.get('uuid')
                if uuid:
                    authorised_overrides[uuid] = override

        # Block re-selling an already-sold unique piece (over-sell) unless a
        # manager approved it. Returns the line uuids whose over-sell was
        # authorised, to stamp below (mirrors the below-minimum override flow).
        stock_authorised = self._check_storable_product_stock(ui_order, lines_data)

        # Populate gold fields on each order line from product and price service,
        # and stamp any authorised below-minimum / already-sold override for audit.
        for line_cmd in order_fields.get('lines') or []:
            if len(line_cmd) >= 3 and isinstance(line_cmd[2], dict):
                vals = line_cmd[2]
                self._enrich_order_line_vals_with_gold(vals)
                self._stamp_min_price_override(
                    vals, override_config, authorised_overrides
                )
                self._stamp_stock_override(vals, stock_authorised)

        return order_fields

    def _stamp_stock_override(self, vals, stock_authorised):
        """Persist only authorised already-sold (over-sell) overrides onto the
        saved line vals, keyed by uuid from ``_check_storable_product_stock``.

        Fail closed: any stock_override flag not backed by a validated approval
        is cleared, so the persisted-line stock cannot be silently over-sold.
        """
        override = stock_authorised.get(vals.get('uuid'))
        if override:
            vals['stock_override'] = True
            vals['stock_override_approver_uid'] = override['approver_uid']
            vals['stock_override_approver_name'] = override['approver_name']
            # A one-of-a-kind piece is being sold although stock says it is
            # already gone. Either the piece came back and nobody recorded it,
            # or the same piece is about to be sold twice — both need a look,
            # so this gets its own topic rather than sharing the price one.
            pulse.notify_in_background(
                'stock-override',
                'Sold a piece already out of stock',
                f'{vals.get("full_product_name") or vals.get("product_id") or "A piece"} '
                f'was sold with manager approval despite showing no stock — '
                f'approved by {override.get("approver_name") or "a manager"}',
                {
                    'productId': vals.get('product_id'),
                    'approverId': override.get('approver_uid'),
                    'uuid': vals.get('uuid'),
                },
                pulse.make_idempotency_key(
                    'stock-override', vals.get('uuid') or vals.get('product_id')),
                env=self.env,
            )
        else:
            vals['stock_override'] = False
            vals['stock_override_approver_uid'] = 0
            vals['stock_override_approver_name'] = False

    def _validate_min_price_override(self, line_vals, product, effective_min,
                                     final_price, config):
        """
        A line priced below its floor is allowed only with a valid manager override.

        Returns the authorised override payload dict, or raises ValidationError:
        - no override flag -> the original "below minimum price" block;
        - flag set but the approver is not authorised (with pos_hr: not a manager
          employee; without pos_hr: no master PIN configured) -> an "unauthorized
          override" block, so a forged frontend boolean cannot bypass the floor.
        """
        if line_vals.get('min_price_override'):
            uid = _as_user_id(line_vals.get('override_approver_uid'))
            if _override_is_authorised(self.env, uid, config):
                approver = (line_vals.get('override_approver_name') or '')[:120]
                price = line_vals.get('price_unit') or 0.0
                # Its own topic, not folded into order-paid: selling under the
                # floor is the one routine action that deliberately bypasses a
                # control, so Revenax may want it loud while sales stay quiet.
                pulse.notify_in_background(
                    'price-override',
                    'Sold below minimum',
                    f'{product.default_code or product.name} at {price:,.0f} '
                    f'(floor {effective_min:,.0f}) — approved by '
                    f'{approver or "a manager"}',
                    {
                        'sku': product.default_code or '',
                        'price': price,
                        'minimum': effective_min,
                        'approverId': uid,
                        'register': config.name if config else '',
                    },
                    pulse.make_idempotency_key(
                        'override', product.id, uid,
                        line_vals.get('uuid') or price,
                    ),
                    env=self.env,
                )
                return {
                    'override_approver_uid': uid,
                    'override_approver_name': approver or False,
                    'override_original_min': (
                        line_vals.get('override_original_min') or effective_min
                    ),
                    'override_reason': line_vals.get('override_reason') or False,
                }
            raise ValidationError(
                _(
                    'Unauthorized price override for %(name)s. '
                    'A valid manager approval is required.'
                )
                % {'name': product.name}
            )
        raise ValidationError(
            _(
                'Cannot sell %(name)s below minimum price of %(min).2f. '
                'Current price: %(price).2f'
            )
            % {
                'name': product.name,
                'min': effective_min,
                'price': final_price,
            }
        )

    def _stamp_min_price_override(self, vals, config, authorised_overrides):
        """
        Persist only authorised below-minimum overrides onto the saved line vals.

        The override payload is taken from ``authorised_overrides`` (matched by the
        line uuid, populated while validating the raw ui_order lines); as a
        fallback it is re-derived from the fields super() may already have copied
        onto ``vals`` — either way the approver is re-checked (manager employee, or
        master mode). Any stray/forged override flag not backed by a validated
        approval is cleared, so the price-floor constraint stays authoritative
        (fail closed).
        """
        override = authorised_overrides.get(vals.get('uuid'))
        if override is None and vals.get('min_price_override'):
            uid = _as_user_id(vals.get('override_approver_uid'))
            if _override_is_authorised(self.env, uid, config):
                override = {
                    'override_approver_uid': uid,
                    'override_approver_name': (
                        vals.get('override_approver_name') or False
                    ),
                    'override_original_min': vals.get('override_original_min') or 0.0,
                    'override_reason': vals.get('override_reason') or False,
                }
        if override:
            vals['min_price_override'] = True
            vals['override_approver_uid'] = override['override_approver_uid']
            vals['override_approver_name'] = override['override_approver_name']
            vals['override_original_min'] = override['override_original_min']
            vals['override_reason'] = override['override_reason']
        else:
            vals['min_price_override'] = False
            vals['override_approver_uid'] = 0
            vals['override_approver_name'] = False

    @api.model
    def _jewellery_location_available(self, location, product_id):
        """On-hand (quantity - reserved) of a product at a single location."""
        quants = self.env['stock.quant'].search([
            ('product_id', '=', product_id),
            ('location_id', '=', location.id),
        ])
        return sum(
            (q.quantity - getattr(q, 'reserved_quantity', 0)) for q in quants
        )

    @api.model
    def _check_storable_product_stock(self, ui_order, lines_data):
        """
        Block re-selling an already-sold UNIQUE jewellery piece.

        A unique piece (serial SKU, on-hand 0/1) requested beyond its available
        stock has already been sold; the sale is blocked unless a manager
        approved it (``stock_override`` set + the approver still authorised — a
        pos_hr manager employee, or master mode when pos_hr is off). Refund lines
        (qty < 0) and fungible/non-unique products are ignored.

        Returns ``{uuid: {approver_uid, approver_name}}`` for the lines whose
        over-sell was authorised, so ``_stamp_stock_override`` can persist them.
        Raises ValidationError for any unauthorised over-sell.

        NOTE: the earlier version filtered on the legacy ``type == 'product'``,
        which is never true in Odoo 19 (goods are ``consu`` + ``is_storable``),
        so the check was a silent no-op. It now uses ``is_storable`` and is
        scoped to unique pieces.
        """
        if not lines_data:
            return {}
        session_id = ui_order.get('pos_session_id')
        if not session_id:
            return {}
        session = self.env['pos.session'].browse(session_id)
        if not session.exists():
            return {}
        config = session.config_id
        picking_type = config.picking_type_id
        if not picking_type:
            return {}
        location = picking_type.default_location_src_id
        if not location:
            return {}

        # Group positive-qty lines per product (refunds qty < 0 excluded).
        product_lines: dict[int, list] = {}
        for line_data in lines_data:
            if len(line_data) < 3 or not isinstance(line_data[2], dict):
                continue
            line_vals = line_data[2]
            product_id = line_vals.get('product_id')
            try:
                qty = float(line_vals.get('qty', 0))
            except (TypeError, ValueError):
                qty = 0
            if product_id and qty > 0:
                product_lines.setdefault(product_id, []).append(line_vals)

        if not product_lines:
            return {}

        products = self.env['product.product'].browse(list(product_lines))
        # Scope: unique serial pieces that actually track stock. Fungible bars/
        # coins and non-jewellery products keep their existing behaviour.
        unique = products.filtered(
            lambda p: p.is_unique_jewellery_piece and p.is_storable
        )
        if not unique:
            return {}

        authorised: dict = {}
        for product in unique:
            product_line_vals = product_lines.get(product.id, [])
            requested = sum(
                float(lv.get('qty', 0)) for lv in product_line_vals
            )
            available = self._jewellery_location_available(location, product.id)
            if requested <= available:
                continue
            # Over-sell: allowed only when EVERY contributing line carries a
            # valid manager override (fail closed against a forged flag).
            all_authorised = all(
                lv.get('stock_override')
                and _override_is_authorised(
                    self.env,
                    _as_user_id(lv.get('stock_override_approver_uid')),
                    config,
                )
                for lv in product_line_vals
            )
            if all_authorised:
                for lv in product_line_vals:
                    uuid = lv.get('uuid')
                    if uuid:
                        authorised[uuid] = {
                            'approver_uid': _as_user_id(
                                lv.get('stock_override_approver_uid')
                            ),
                            'approver_name': (
                                (lv.get('stock_override_approver_name') or '')[:120]
                                or False
                            ),
                        }
                continue
            raise ValidationError(
                _(
                    '"%(name)s" is out of stock (requested %(requested)s, '
                    'available %(available)s). It may already be sold — a '
                    'manager approval is required to sell it.'
                )
                % {
                    'name': product.display_name,
                    'requested': requested,
                    'available': available,
                }
            )
        return authorised

    @api.model
    def _get_invoice_lines_values(self, line_values, pos_order_line, move_type):
        """
        Pass gold-specific fields from POS order line to invoice line so the
        invoice report can display them.
        """
        result = super()._get_invoice_lines_values(
            line_values, pos_order_line, move_type
        )
        jewellery_fields = [
            'jewellery_type', 'jewellery_weight_g', 'silver_purity',
        ]
        for fname in jewellery_fields:
            if hasattr(pos_order_line, fname):
                result[fname] = pos_order_line[fname]

        product = pos_order_line.product_id
        if not product or not getattr(product, 'is_gold_product', False):
            return result
        gold_fields = [
            'gold_purity', 'gold_weight_g', 'gold_type',
            'gold_price_per_gram', 'making_fee',
        ]
        for fname in gold_fields:
            if hasattr(pos_order_line, fname):
                result[fname] = pos_order_line[fname]
        return result

    def _process_saved_order(self, draft):
        """Require invoice for every order when finalizing (not draft)."""
        if not draft and not self.to_invoice:
            raise UserError(
                _(
                    "An invoice must be set for every order. "
                    "Please enable invoicing for this order before paying."
                )
            )
        return super()._process_saved_order(draft)


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    jewellery_type = fields.Selection(
        selection=JEWELLERY_TYPE_SELECTION,
        string='Jewellery Type',
        help='Jewellery type at order time (copied from product).',
    )
    jewellery_weight_g = fields.Float(
        string='Jewellery Weight (g)',
        digits=(16, 2),
        help='Jewellery weight in grams at order time (copied from product).',
    )
    silver_purity = fields.Selection(
        selection=SILVER_PURITY_SELECTION,
        string='Silver Purity',
        help='Silver purity at order time (copied from product).',
    )
    gold_purity = fields.Selection(
        selection=GOLD_PURITY_SELECTION,
        string='Gold Purity',
        help='Gold purity at order time (copied from product).',
    )
    gold_weight_g = fields.Float(
        string='Gold Weight (g)',
        digits=(16, 2),
        help='Gold weight in grams at order time (copied from product).',
    )
    gold_type = fields.Selection(
        selection=GOLD_TYPE_SELECTION,
        string='Gold Type',
        help='Gold type at order time (copied from product).',
    )
    gold_price_per_gram = fields.Float(
        string='Gold Price per Gram',
        digits=(16, 4),
        help='Gold price per gram at sale time (from price service).',
    )
    making_fee = fields.Float(
        string='Making Fee',
        digits=(16, 2),
        default=0.0,
        help='Making fee for this line (from product or overridden).',
    )
    # --- Below-minimum-price manager override (audit) ---
    min_price_override = fields.Boolean(
        string='Below-Min Price Approved',
        default=False,
        help='Set when a manager approved selling this line below its minimum '
             'sale price.',
    )
    override_approver_uid = fields.Integer(
        string='Override Approver ID',
        help='The approving manager employee id (pos_hr) that authorised this '
             'below-minimum sale, or 0 when the master fallback PIN was used.',
    )
    override_approver_name = fields.Char(
        string='Override Approver',
        help='Name of the manager (employee) who approved selling this line below '
             'its minimum sale price, or "Override PIN" for the master fallback.',
    )
    override_original_min = fields.Float(
        string='Original Minimum Price',
        digits=(16, 2),
        help='The minimum sale price that was bypassed by the manager override.',
    )
    override_reason = fields.Char(
        string='Override Reason',
        help='Optional reason recorded with a below-minimum price approval.',
    )
    # --- Already-sold (over-sell) manager override for unique pieces (audit) ---
    stock_override = fields.Boolean(
        string='Already-Sold Sale Approved',
        default=False,
        help='Set when a manager approved selling a unique piece that had no '
             'available stock (already sold / over-sell).',
    )
    stock_override_approver_uid = fields.Integer(
        string='Already-Sold Override Approver ID',
        help='The approving manager employee id (pos_hr) that authorised selling '
             'this already-sold piece, or 0 when the master fallback PIN was used.',
    )
    stock_override_approver_name = fields.Char(
        string='Already-Sold Override Approver',
        help='Name of the manager who approved selling this already-sold piece, '
             'or "Override PIN" for the master fallback.',
    )

    @api.model
    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        extra = [
            'min_price_override',
            'override_approver_uid',
            'override_approver_name',
            'override_original_min',
            'override_reason',
            'stock_override',
            'stock_override_approver_uid',
            'stock_override_approver_name',
        ]
        return list(dict.fromkeys([*fields_list, *extra]))

    @api.constrains('price_unit', 'discount')
    def _check_gold_minimum_price(self):
        """
        Constraint to ensure gold and silver products are not sold below minimum price.
        When no minimum sale price is set, assume 20% max discount (min = price_unit * 0.8).

        A line carrying a valid manager override (``min_price_override`` set and an
        approver still authorised — a pos_hr manager employee, or master mode when
        pos_hr is off) is exempt — this is the persisted-line mirror of the same
        check in ``_order_fields``.
        """
        for line in self:
            if line.qty < 0:
                continue  # refund/return line — the floor is for sales only
            if line.product_id.is_gold_product:
                effective_min = (
                    line.product_id.gold_min_sale_price or (line.price_unit * 0.8)
                )
            elif line.product_id.is_silver_product:
                effective_min = (
                    line.product_id.silver_min_sale_price or (line.price_unit * 0.8)
                )
            elif line.product_id.is_diamond_jewellery_product:
                effective_min = (
                    line.product_id.diamond_min_sale_price or (line.price_unit * 0.8)
                )
            else:
                continue
            if effective_min <= 0:
                continue
            final_price = line.price_unit * (1 - line.discount / 100.0)
            if final_price < effective_min:
                config = line.order_id.config_id
                if line.min_price_override and _override_is_authorised(
                    self.env, line.override_approver_uid, config
                ):
                    continue  # authorised manager override
                raise ValidationError(
                    _(
                        'Cannot sell %(name)s below minimum price of %(min).2f. '
                        'Current price: %(price).2f'
                    )
                    % {
                        'name': line.product_id.name,
                        'min': effective_min,
                        'price': final_price,
                    }
                )


class PosSession(models.Model):
    _inherit = 'pos.session'

    @api.model
    def jewellery_stock_availability(self, session_id, product_ids):
        """Live on-hand (per product id) at this session's source location.

        The register calls this at Pay time to detect an already-sold unique
        piece before checkout, so it can prompt for a manager override — using
        the exact same location + quant logic as the backend
        ``_check_storable_product_stock`` guard (no stale boot data). Returns
        ``{product_id: available_qty}``.
        """
        session = self.browse(session_id)
        if not session.exists() or not product_ids:
            return {}
        picking_type = session.config_id.picking_type_id
        location = picking_type.default_location_src_id if picking_type else False
        if not location:
            return {}
        PosOrder = self.env['pos.order']
        return {
            pid: PosOrder._jewellery_location_available(location, pid)
            for pid in product_ids
        }
