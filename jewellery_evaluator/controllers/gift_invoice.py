# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

from odoo import http
from odoo.http import request


class JewelleryGiftInvoice(http.Controller):
    """Serve the gift invoice PDF (gold layout, prices stripped) for a POS order,
    so the POS receipt screen can open it in the browser print dialog."""

    @http.route("/jewellery/gift_invoice/<int:order_id>", type="http", auth="user")
    def gift_invoice(self, order_id, **kw):
        # Read the order under the user's own rights (record rules apply), then
        # company-scope it. Rendering runs sudo (reports touch many models), but
        # only after the caller is confirmed allowed to see this order.
        order = request.env["pos.order"].browse(order_id).exists()
        if not order or order.company_id.id not in request.env.user.company_ids.ids:
            return request.not_found()
        move = order.sudo().account_move
        if not move:
            return request.not_found()
        pdf = (
            request.env["ir.actions.report"]
            .sudo()
            ._render_qweb_pdf("jewellery_evaluator.report_gift_invoice", move.ids)[0]
        )
        return request.make_response(
            pdf,
            headers=[
                ("Content-Type", "application/pdf"),
                ("Content-Disposition", 'inline; filename="gift-invoice.pdf"'),
                ("Content-Length", len(pdf)),
            ],
        )
