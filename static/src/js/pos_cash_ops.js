/** @odoo-module **/
// POS "Currency" + "Transfer to Owner" control buttons.
//   * Journals arrive on pos.config as JSON strings from _load_pos_data_read
//     (pos_config.py): jewellery_vault_foreign_journals / jewellery_owner_journals,
//     each a list of {id, name} — same injected-Char pattern as the override hash.
//   * Backend posts real JEs: pos.session.post_currency_conversion /
//     post_owner_transfer (models/pos_cash_ops.py). Those Cr the Vault, so the
//     pos.session Vault override folds them into the shift automatically.
//   * The backend WHITELISTS the journal, requires an open session, and dedupes
//     by an idempotency key. The key is generated once per button click and
//     REUSED across in-popup retries, and the popup stays open (busy-guarded) on
//     failure — so a lost-response retry reuses the move instead of posting a
//     second real cash movement out of the Vault.
// Verified against Odoo 19 core: ControlButtons component + template
// "point_of_sale.ControlButtons" (div.control-buttons); this.pos.{dialog,data,
// notification,session} all exist on the store.

import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

// Parse a pos.config JSON-string journal list, tolerating empty/malformed data.
function parseJournals(raw) {
    try {
        const list = JSON.parse(raw || "[]");
        return Array.isArray(list) ? list : [];
    } catch {
        return [];
    }
}

// Extract a human message from an RPC error.
function errMessage(error, fallback) {
    return error?.data?.message || error?.message || fallback;
}

// --- Currency conversion popup: EGP out of Vault -> foreign Vault Foreign ---
export class CurrencyConvertPopup extends Component {
    static template = "jewellery_evaluator.CurrencyConvertPopup";
    static components = { Dialog };
    static props = ["journals", "onSubmit", "close?"];
    setup() {
        this.state = useState({
            journalId: this.props.journals[0]?.id,
            amountEgp: "",
            toAmount: "",
            busy: false,
            error: "",
        });
    }
    async confirm() {
        if (this.state.busy) {
            return;
        }
        const journalId = this.state.journalId;
        const amountEgp = parseFloat(this.state.amountEgp);
        const toAmount = parseFloat(this.state.toAmount);
        if (!journalId || !(amountEgp > 0) || !(toAmount > 0)) {
            this.state.error = _t("Pick a journal and enter positive amounts.");
            return;
        }
        this.state.busy = true;
        this.state.error = "";
        try {
            // On success the popup closes; on failure it STAYS OPEN so the retry
            // reuses this same instance (and its idempotency key on the caller).
            await this.props.onSubmit({ journalId, amountEgp, toAmount });
            this.props.close();
        } catch (error) {
            this.state.busy = false;
            this.state.error = errMessage(error, _t("Currency conversion failed."));
        }
    }
}

// --- Transfer-to-owner popup: EGP out of Vault -> owner journal ---
export class OwnerTransferPopup extends Component {
    static template = "jewellery_evaluator.OwnerTransferPopup";
    static components = { Dialog };
    static props = ["journals", "onSubmit", "close?"];
    setup() {
        this.state = useState({
            journalId: this.props.journals[0]?.id,
            amount: "",
            busy: false,
            error: "",
        });
    }
    async confirm() {
        if (this.state.busy) {
            return;
        }
        const journalId = this.state.journalId;
        const amount = parseFloat(this.state.amount);
        if (!journalId || !(amount > 0)) {
            this.state.error = _t("Pick an owner and enter a positive amount.");
            return;
        }
        this.state.busy = true;
        this.state.error = "";
        try {
            await this.props.onSubmit({ journalId, amount });
            this.props.close();
        } catch (error) {
            this.state.busy = false;
            this.state.error = errMessage(error, _t("Owner transfer failed."));
        }
    }
}

patch(ControlButtons.prototype, {
    // Journals loaded onto pos.config via _load_pos_data_read (pos_config.py) as
    // JSON strings: jewellery_vault_foreign_journals / jewellery_owner_journals.
    get _vaultForeignJournals() {
        return parseJournals(this.pos.config.jewellery_vault_foreign_journals);
    },
    get _ownerJournals() {
        return parseJournals(this.pos.config.jewellery_owner_journals);
    },
    // One idempotency token per button click, reused across in-popup retries.
    _newCashOpsKey() {
        return (
            globalThis.crypto?.randomUUID?.() ||
            `${Date.now()}-${Math.random().toString(36).slice(2)}`
        );
    },
    onClickCurrency() {
        const journals = this._vaultForeignJournals;
        if (!journals.length) {
            this.pos.notification.add(
                _t("No Vault Foreign journals are configured for this branch."),
                { type: "warning" },
            );
            return;
        }
        const key = this._newCashOpsKey();
        this.pos.dialog.add(CurrencyConvertPopup, {
            journals,
            onSubmit: async ({ journalId, amountEgp, toAmount }) => {
                const res = await this.pos.data.call("pos.session", "post_currency_conversion", [
                    this.pos.session.id, amountEgp, journalId, toAmount, key,
                ]);
                this.pos.notification.add(
                    res?.duplicate
                        ? _t("Already recorded — not posted twice.")
                        : _t("Currency conversion recorded."),
                    { type: "success" },
                );
                return res;
            },
        });
    },
    onClickOwnerTransfer() {
        const journals = this._ownerJournals;
        if (!journals.length) {
            this.pos.notification.add(
                _t("No owner journals are configured for this branch."),
                { type: "warning" },
            );
            return;
        }
        const key = this._newCashOpsKey();
        this.pos.dialog.add(OwnerTransferPopup, {
            journals,
            onSubmit: async ({ journalId, amount }) => {
                const res = await this.pos.data.call("pos.session", "post_owner_transfer", [
                    this.pos.session.id, journalId, amount, key,
                ]);
                this.pos.notification.add(
                    res?.duplicate
                        ? _t("Already recorded — not posted twice.")
                        : _t("Owner transfer recorded."),
                    { type: "success" },
                );
                return res;
            },
        });
    },
});
