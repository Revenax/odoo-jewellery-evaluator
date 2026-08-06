/** @odoo-module **/
/* global Sha1 */
// Badge scan logs an employee in WITHOUT asking for their PIN.
//
// Everyone keeps both credentials: the badge is enough on its own, and the PIN
// still guards the manual path (tapping a name in the cashier list). Clearing
// PINs would have achieved the badge half, but stock Odoo only prompts when
// employee._pin is set — so a blank PIN also makes the on-screen list
// credential-free, letting anyone tap any name. That is the wrong trade for a
// shop handling cash, hence this patch instead of a config change.
//
// Stock pos_hr (utils/select_cashier_mixin.js) gates the scan on:
//     employee && employee !== pos.getCashier() &&
//     (!employee._pin || (await checkPin(employee)))
// The PIN prompt is skipped when _pin is falsy, so we blank _pin on just the
// scanned employee for the duration of that call and restore it after. The
// mixin's callback is a closure created inside a hook, so it cannot be patched
// directly — wrapping it as it is registered with the barcode reader is the
// available seam.

import { patch } from "@web/core/utils/patch";
import { BarcodeReader } from "@point_of_sale/app/services/barcode_reader_service";
import { PosStore } from "@point_of_sale/app/services/pos_store";

// The barcode service has no `pos` dependency, so capture the store as it starts.
let posRef = null;

patch(PosStore.prototype, {
    async setup(...args) {
        await super.setup(...args);
        posRef = this;
    },
});

patch(BarcodeReader.prototype, {
    register(cbMap, exclusive) {
        // Wrap once — LoginScreen and CashierName each register their own map,
        // and a map can be re-registered when a component remounts.
        if (cbMap && typeof cbMap.cashier === "function" && !cbMap._jewelleryBadgeSkipsPin) {
            const original = cbMap.cashier;
            cbMap.cashier = async function (code) {
                let target = null;
                let savedPin = null;
                try {
                    const hash = Sha1.hash(code.code);
                    // Same lookup stock uses, so we blank the PIN of exactly the
                    // employee the mixin is about to match — never anyone else.
                    target = posRef?.models?.["hr.employee"]?.find(
                        (emp) => emp._barcode === hash
                    );
                } catch {
                    target = null;
                }
                if (target && target._pin) {
                    savedPin = target._pin;
                    target._pin = false;
                }
                try {
                    return await original.call(this, code);
                } finally {
                    // Always restore, so the cashier list keeps asking for a PIN
                    // even if the login threw or the user cancelled.
                    if (target && savedPin !== null) {
                        target._pin = savedPin;
                    }
                }
            };
            cbMap._jewelleryBadgeSkipsPin = true;
        }
        return super.register(cbMap, exclusive);
    },
});
