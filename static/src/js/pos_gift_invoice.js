/** @odoo-module **/
// Copyright 2026 Revenax Digital Services
// Receipt screen (after payment): Odoo's print buttons are removed
// (pos_gift_invoice.xml) and replaced by "Print A5", "Print A5 Gift" and a
// "Download Invoice" fallback (regular invoice PDF to this device). Each print
// asks the server (pos.session.jewellery_print_a5, models/pos_a5_print.py) to
// render the order's invoice and queue it at this branch's A5 printer through
// the operations app; the shop PC's print client prints it.
// The A5 invoice also prints AUTOMATICALLY once per sale when this screen opens
// (retrying while the order/invoice is still being saved); the buttons remain
// for a second copy or the gift copy. The Orders tab gets the same buttons.
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";
import { onMounted, useState } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

/** Queue an order's A5 invoice (kind "a5") or gift copy ("gift") at this
 * branch's printer. Shared by the receipt screen and the Orders tab. */
export async function sendA5(pos, orderId, kind) {
    if (!orderId || typeof orderId !== "number") {
        pos.notification.add(_t("This order is not saved yet. Try again in a moment."), { type: "warning" });
        return false;
    }
    try {
        const res = await pos.data.call("pos.session", "jewellery_print_a5", [
            pos.session.id, orderId, kind, pos.cashier?.name || "",
        ]);
        pos.notification.add(
            kind === "gift"
                ? _t("Gift copy of %s sent to the A5 printer.", res.invoice)
                : _t("%s sent to the A5 printer.", res.invoice),
            { type: "success" }
        );
        return true;
    } catch (error) {
        pos.notification.add(
            error?.data?.message || error?.message || _t("Printing failed. Try again."),
            { type: "danger" }
        );
        return false;
    }
}

/** Download the regular invoice PDF to this device. */
export function downloadInvoicePdf(pos, orderId) {
    if (!orderId || typeof orderId !== "number") {
        pos.notification.add(_t("This order is not saved yet. Try again in a moment."), { type: "warning" });
        return;
    }
    window.open(`/jewellery/invoice/${orderId}`, "_blank");
}

const AUTO_KEY = "jewellery_a5_auto_printed";
const AUTO_TRIES = 6;
const AUTO_DELAY_MS = 2500;

/** Orders already auto-printed on this device (survives a screen re-open/reload). */
function autoPrinted() {
    try {
        return new Set(JSON.parse(sessionStorage.getItem(AUTO_KEY) || "[]"));
    } catch {
        return new Set();
    }
}
function markAutoPrinted(uuid) {
    try {
        const done = [...autoPrinted(), uuid].slice(-200);
        sessionStorage.setItem(AUTO_KEY, JSON.stringify(done));
    } catch {
        // storage unavailable: worst case a re-opened screen prints again
    }
}

patch(ReceiptScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.a5 = useState({ busy: "", sent: "" });
        onMounted(() => this.autoPrintA5());
    },
    /** Print the A5 invoice once per sale without a click. */
    async autoPrintA5() {
        const order = this.currentOrder;
        const uuid = order?.uuid;
        if (!uuid || order.isRefund || autoPrinted().has(uuid)) {
            return;
        }
        markAutoPrinted(uuid);
        let lastError;
        for (let attempt = 0; attempt < AUTO_TRIES; attempt++) {
            const orderId = this.currentOrder?.id;
            if (orderId && typeof orderId === "number") {
                try {
                    this.a5.busy = "a5";
                    const res = await this.pos.data.call("pos.session", "jewellery_print_a5", [
                        this.pos.session.id, orderId, "a5", this.pos.cashier?.name || "",
                    ]);
                    this.a5.sent = "a5";
                    this.pos.notification.add(_t("%s sent to the A5 printer.", res.invoice), { type: "success" });
                    return;
                } catch (error) {
                    lastError = error;
                } finally {
                    this.a5.busy = "";
                }
            }
            await new Promise((resolve) => setTimeout(resolve, AUTO_DELAY_MS));
        }
        this.pos.notification.add(
            _t("The A5 invoice did not print automatically (%s). Press Print A5.",
               lastError?.data?.message || _t("order not saved yet")),
            { type: "warning", sticky: true }
        );
    },
    /** Fallback: download the regular invoice PDF to this device. */
    downloadInvoice() {
        downloadInvoicePdf(this.pos, this.currentOrder?.id);
    },
    async printA5(kind) {
        if (this.a5.busy) {
            return;
        }
        this.a5.busy = kind;
        try {
            if (await sendA5(this.pos, this.currentOrder?.id, kind)) {
                this.a5.sent = kind;
            }
        } finally {
            this.a5.busy = "";
        }
    },
});

// Orders tab (past orders): the same Print A5 / Print A5 Gift / Download Invoice
// in place of Odoo's "Print Receipt" and invoice button (pos_gift_invoice.xml).
patch(TicketScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.a5 = useState({ busy: "" });
    },
    async printA5(order, kind) {
        if (this.a5.busy) {
            return;
        }
        this.a5.busy = kind;
        try {
            await sendA5(this.pos, order?.id, kind);
        } finally {
            this.a5.busy = "";
        }
    },
    downloadInvoice(order) {
        downloadInvoicePdf(this.pos, order?.id);
    },
});

// Odoo downloads the invoice PDF after paying every invoiced order (and every
// order is invoiced here). The A5 printer replaces that download; a failed
// invoice still surfaces through the auto-print warning above.
patch(OrderPaymentValidation.prototype, {
    shouldDownloadInvoice() {
        return false;
    },
});
