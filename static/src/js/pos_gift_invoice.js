/** @odoo-module **/
// Copyright 2026 Revenax Digital Services
// Receipt screen (after payment): Odoo's print buttons are removed
// (pos_gift_invoice.xml) and replaced by "Print A5", "Print A5 Gift" and a
// "Download Invoice" fallback (regular invoice PDF to this device). Each print
// asks the server (pos.session.jewellery_print_a5, models/pos_a5_print.py) to
// render the order's invoice and queue it at this branch's A5 printer through
// the operations app; the shop PC's print client prints it.
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { useState } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

patch(ReceiptScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.a5 = useState({ busy: "", sent: "" });
    },
    /** Fallback: download the regular invoice PDF to this device. */
    downloadInvoice() {
        const orderId = this.currentOrder?.id;
        if (!orderId || typeof orderId !== "number") {
            this.pos.notification.add(_t("This order is not saved yet. Try again in a moment."), { type: "warning" });
            return;
        }
        window.open(`/jewellery/invoice/${orderId}`, "_blank");
    },
    async printA5(kind) {
        if (this.a5.busy) {
            return;
        }
        const orderId = this.currentOrder?.id;
        if (!orderId || typeof orderId !== "number") {
            this.pos.notification.add(_t("This order is not saved yet. Try again in a moment."), { type: "warning" });
            return;
        }
        this.a5.busy = kind;
        try {
            const res = await this.pos.data.call("pos.session", "jewellery_print_a5", [
                this.pos.session.id, orderId, kind, this.pos.cashier?.name || "",
            ]);
            this.a5.sent = kind;
            this.pos.notification.add(
                kind === "gift"
                    ? _t("Gift copy of %s sent to the A5 printer.", res.invoice)
                    : _t("%s sent to the A5 printer.", res.invoice),
                { type: "success" }
            );
        } catch (error) {
            this.pos.notification.add(
                error?.data?.message || error?.message || _t("Printing failed. Try again."),
                { type: "danger" }
            );
        } finally {
            this.a5.busy = "";
        }
    },
});
