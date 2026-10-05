# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
from odoo import models
from odoo.addons.jewellery_evaluator.jewellery_evaluator import pulse

from ..website_utils import web_order_summary


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_confirm(self):
        res = super().action_confirm()
        self.filtered('website_id')._pulse_web_order_placed()
        return res

    def _pulse_web_order_placed(self):
        """Tell the boutique a web order is waiting: the piece has to be set
        aside before someone sells it over the counter, and there is no email
        until outgoing mail is configured. Pay-on-site orders are confirmed by
        website_sale_collect and gateway orders on payment, so both pass here.
        Sent after commit, so a rolled-back confirmation never notifies."""
        for order in self:
            lines = order.order_line.filtered(lambda line: not line.is_delivery and line.product_id)
            # In-store pickup sets the order's warehouse to the chosen store.
            store = order.warehouse_id.name if order.carrier_id.delivery_type == 'in_store' else ''
            payment = ', '.join(order.transaction_ids.provider_id.mapped('name'))
            body = web_order_summary(
                order.name, order.amount_total, order.currency_id.name,
                order.carrier_id.name or '', store or '', payment,
                [line.product_id.default_code or line.product_id.name for line in lines],
                order.partner_id.name or '',
            )
            data = {
                'reference': order.name, 'amount': order.amount_total,
                'currency': order.currency_id.name, 'delivery': order.carrier_id.name or '',
                'store': store or '', 'payment': payment, 'saleOrderId': order.id,
            }
            credentials = pulse._credentials(self.env)
            key = pulse.make_idempotency_key('sale.order', order.id, 'web-confirmed')
            self.env.cr.postcommit.add(
                lambda body=body, data=data, key=key, credentials=credentials: pulse.notify_in_background(
                    'web-order-placed', 'Web order', body, data, key, credentials=credentials,
                )
            )
