# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

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

        # Validate storable product quantities do not exceed available stock
        self._check_storable_product_stock(ui_order, lines_data)

        # Populate gold fields on each order line from product and price service,
        # and stamp any authorised below-minimum override for audit.
        for line_cmd in order_fields.get('lines') or []:
            if len(line_cmd) >= 3 and isinstance(line_cmd[2], dict):
                vals = line_cmd[2]
                self._enrich_order_line_vals_with_gold(vals)
                self._stamp_min_price_override(
                    vals, override_config, authorised_overrides
                )

        return order_fields

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
                return {
                    'override_approver_uid': uid,
                    'override_approver_name': (
                        (line_vals.get('override_approver_name') or '')[:120] or False
                    ),
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
    def _check_storable_product_stock(self, ui_order, lines_data):
        """
        Raise ValidationError if any storable product line requests more than
        available stock at the POS location. Consumables and services are ignored.
        """
        if not lines_data:
            return
        session_id = ui_order.get('pos_session_id')
        if not session_id:
            return
        session = self.env['pos.session'].browse(session_id)
        if not session.exists():
            return
        picking_type = session.config_id.picking_type_id
        if not picking_type:
            return
        location = picking_type.default_location_src_id
        if not location:
            return

        # Aggregate requested quantity per product (positive qty only; refunds excluded)
        product_qty: dict[int, float] = {}
        for line_data in lines_data:
            if len(line_data) < 3 or not isinstance(line_data[2], dict):
                continue
            line_vals = line_data[2]
            product_id = line_vals.get('product_id')
            qty = line_vals.get('qty', 0)
            try:
                qty = float(qty)
            except (TypeError, ValueError):
                qty = 0
            if product_id and qty > 0:
                product_qty[product_id] = product_qty.get(product_id, 0) + qty

        if not product_qty:
            return

        products = self.env['product.product'].browse(product_qty.keys())
        storable = products.filtered(lambda p: p.type == 'product')
        if not storable:
            return

        StockQuant = self.env['stock.quant']
        for product in storable:
            requested = product_qty.get(product.id, 0)
            if requested <= 0:
                continue
            quants = StockQuant.search([
                ('product_id', '=', product.id),
                ('location_id', '=', location.id),
            ])
            available = sum(
                (q.quantity - getattr(q, 'reserved_quantity', 0)) for q in quants
            )
            if requested > available:
                raise ValidationError(
                    _(
                        'Not enough stock for "%(name)s". Requested: %(requested)s, '
                        'available: %(available)s.'
                    )
                    % {
                        'name': product.display_name,
                        'requested': requested,
                        'available': available,
                    }
                )

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

    @api.model
    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        extra = [
            'min_price_override',
            'override_approver_uid',
            'override_approver_name',
            'override_original_min',
            'override_reason',
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
