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
// The prompt is skipped when _pin is falsy, so we hide _pin on just the scanned
// employee for the duration of that call. The mixin's callback is a closure
// created inside a hook, so it cannot be patched directly — wrapping it as it
// is registered with the barcode reader is the available seam.

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

/**
 * Find the raw-data object backing a POS record.
 *
 * Server-supplied extras like `_pin` are exposed by model_classes.js as an
 * accessor over the record's raw data: the getter reads `this[RAW_SYMBOL][f]`
 * and the setter throws "`_pin` is read-only". The property is also declared
 * NON-configurable, so it cannot be redefined either — the raw object is the
 * only writable handle. RAW_SYMBOL is module-private, so locate it by shape.
 *
 * Returns null if the internals ever change, in which case we simply leave the
 * PIN in place and stock behaviour (prompt for it) applies. Failing closed here
 * is the safe direction.
 */
function rawDataOf(record, field) {
    try {
        for (const sym of Object.getOwnPropertySymbols(record)) {
            const value = record[sym];
            if (value && typeof value === "object" && field in value) {
                return value;
            }
        }
    } catch {
        return null;
    }
    return null;
}

patch(BarcodeReader.prototype, {
    register(cbMap, exclusive) {
        // Wrap once — LoginScreen and CashierName each register their own map,
        // and a map can be re-registered when a component remounts.
        if (cbMap && typeof cbMap.cashier === "function" && !cbMap._jewelleryBadgeSkipsPin) {
            const original = cbMap.cashier;
            cbMap.cashier = async function (code) {
                let raw = null;
                let savedPin = null;
                try {
                    const hash = Sha1.hash(code.code);
                    // Same lookup stock uses, so we touch exactly the employee
                    // the mixin is about to match — never anyone else.
                    const target = posRef?.models?.["hr.employee"]?.find(
                        (emp) => emp._barcode === hash
                    );
                    if (target && target._pin) {
                        raw = rawDataOf(target, "_pin");
                        if (raw) {
                            savedPin = raw._pin;
                            raw._pin = false;
                        }
                    }
                } catch {
                    raw = null;
                }
                try {
                    return await original.call(this, code);
                } finally {
                    // Always restore, so the cashier list keeps asking for a PIN
                    // even if the login threw or the user cancelled.
                    if (raw && savedPin !== null) {
                        raw._pin = savedPin;
                    }
                }
            };
            cbMap._jewelleryBadgeSkipsPin = true;
        }
        return super.register(cbMap, exclusive);
    },
});
