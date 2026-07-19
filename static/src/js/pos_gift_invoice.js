/** @odoo-module **/
// "Print Gift Invoice" button on the POS receipt screen (after a completed sale).
// Opens the gift invoice PDF — the gold A5 layout with prices stripped — served
// by /jewellery/gift_invoice/<order_id> (controllers/gift_invoice.py), which
// renders the report_gift_invoice report for the order's account.move. Every POS
// order is invoiced (pos.order._process_saved_order forces it), so the move
// always exists. `this.currentOrder.id` is the server order id (core uses it in a
// DB domain in invoice_button.js), matching the controller's <int:order_id>.

import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

patch(ReceiptScreen.prototype, {
    printGiftInvoice() {
        const orderId = this.currentOrder?.id;
        if (!orderId) {
            this.pos.notification?.add?.(_t("No saved order to print."), { type: "warning" });
            return;
        }
        // New tab -> the browser's PDF/print dialog (same as the normal A5 invoice).
        window.open(`/jewellery/gift_invoice/${orderId}`, "_blank");
    },
});
