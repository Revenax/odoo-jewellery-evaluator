/** @odoo-module **/
// POS "Currency" + "Transfer to Owner" menu items — live in the Navbar burger
// menu right next to "Cash In/Out" (all Vault cash operations together).
//   * Journals arrive on pos.config as JSON strings from _load_pos_data_read
//     (pos_config.py): jewellery_vault_foreign_journals (currency popup),
//     jewellery_owner_journals + jewellery_vault_boxes (owner popup). Each entry
//     is {id, name[, ccy, foreign]} — same injected-Char pattern as the override
//     hash.
//   * Backend posts real, two-way JEs: pos.session.post_currency_conversion /
//     post_owner_transfer (models/pos_cash_ops.py). The EGP-Vault leg Cr/Dr's the
//     Vault, so the pos.session Vault override folds it into the shift.
//   * The cashier enters BOTH amounts (EGP + foreign); the rate shown is a
//     read-only sanity readout (EGP ÷ foreign) — no rate maths on the server.
//   * The backend WHITELISTS the journal/box, requires an open session, and
//     dedupes by an idempotency key generated once per menu click and REUSED
//     across in-popup retries (the popup stays open, busy-guarded, on failure) —
//     so a lost-response retry reuses the move instead of posting a second real
//     cash movement out of the Vault.
// Verified against Odoo 19 core: Navbar component + template
// "point_of_sale.Navbar" (Cash In/Out DropdownItem); this.pos.{dialog,data,
// notification,session,config} all exist on the store.

import { Navbar } from "@point_of_sale/app/components/navbar/navbar";
import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

// Parse a pos.config JSON-string list, tolerating empty/malformed data.
function parseList(raw) {
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

// Format a number with thousands separators (blank when not a finite number).
function fmt(n) {
    return Number.isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "";
}

// --- Currency conversion popup: two-way EGP <-> foreign Vault Foreign box ---
export class CurrencyConvertPopup extends Component {
    static template = "jewellery_evaluator.CurrencyConvertPopup";
    static components = { Dialog };
    static props = ["journals", "onSubmit", "close?"];
    setup() {
        this.state = useState({
            direction: "buy", // buy: EGP -> foreign ; sell: foreign -> EGP
            journalId: this.props.journals[0]?.id,
            amountEgp: "",
            toAmount: "",
            busy: false,
            error: "",
        });
    }
    get selectedCcy() {
        // <select> t-model yields a string; compare id-as-string.
        const j = this.props.journals.find((x) => String(x.id) === String(this.state.journalId));
        return j?.ccy || _t("foreign");
    }
    get egp() {
        return parseFloat(this.state.amountEgp);
    }
    get foreign() {
        return parseFloat(this.state.toAmount);
    }
    get rate() {
        return this.egp > 0 && this.foreign > 0 ? this.egp / this.foreign : NaN;
    }
    get rateText() {
        return Number.isFinite(this.rate) ? `${fmt(this.rate)} EGP/${this.selectedCcy}` : "";
    }
    get summary() {
        if (!(this.egp > 0) || !(this.foreign > 0)) {
            return "";
        }
        const ccy = this.selectedCcy;
        const egp = fmt(this.egp);
        const fx = fmt(this.foreign);
        const rate = fmt(this.rate);
        return this.state.direction === "buy"
            ? _t("Take %(egp)s EGP out of the drawer, add %(fx)s %(ccy)s to the box (≈ %(rate)s EGP/%(ccy)s).",
                  { egp, fx, ccy, rate })
            : _t("Take %(fx)s %(ccy)s out of the box, add %(egp)s EGP to the drawer (≈ %(rate)s EGP/%(ccy)s).",
                  { egp, fx, ccy, rate });
    }
    async confirm() {
        if (this.state.busy) {
            return;
        }
        const journalId = this.state.journalId;
        if (!journalId || !(this.egp > 0) || !(this.foreign > 0)) {
            this.state.error = _t("Pick a currency and enter both positive amounts.");
            return;
        }
        this.state.busy = true;
        this.state.error = "";
        try {
            // On success the popup closes; on failure it STAYS OPEN so the retry
            // reuses this same instance (and its idempotency key on the caller).
            await this.props.onSubmit({
                direction: this.state.direction,
                journalId,
                amountEgp: this.egp,
                toAmount: this.foreign,
            });
            this.props.close();
        } catch (error) {
            this.state.busy = false;
            this.state.error = errMessage(error, _t("Currency conversion failed."));
        }
    }
}

// --- Transfer-to-owner popup: two-way, any box (EGP Vault or a foreign box) ---
export class OwnerTransferPopup extends Component {
    static template = "jewellery_evaluator.OwnerTransferPopup";
    static components = { Dialog };
    static props = ["owners", "boxes", "onSubmit", "close?"];
    setup() {
        this.state = useState({
            direction: "out", // out: box -> owner ; in: owner -> box
            ownerId: this.props.owners[0]?.id,
            boxId: this.props.boxes[0]?.id,
            amount: "",
            amountEgp: "",
            busy: false,
            error: "",
        });
    }
    get selectedBox() {
        // <select> t-model yields a string; compare id-as-string.
        return this.props.boxes.find((b) => String(b.id) === String(this.state.boxId)) || {};
    }
    get isForeign() {
        return !!this.selectedBox.foreign;
    }
    get ccy() {
        return this.selectedBox.ccy || "";
    }
    get amount() {
        return parseFloat(this.state.amount);
    }
    get egp() {
        // EGP box: the EGP value IS the amount. Foreign box: the entered value.
        return this.isForeign ? parseFloat(this.state.amountEgp) : this.amount;
    }
    get rate() {
        return this.isForeign && this.amount > 0 && this.egp > 0
            ? this.egp / this.amount
            : NaN;
    }
    get rateText() {
        return Number.isFinite(this.rate) ? `${fmt(this.rate)} EGP/${this.ccy}` : "";
    }
    get summary() {
        if (!(this.amount > 0) || !(this.egp > 0)) {
            return "";
        }
        const owner = this.props.owners.find((o) => String(o.id) === String(this.state.ownerId))?.name || "";
        const box = this.selectedBox.name || "";
        const money = this.isForeign
            ? `${fmt(this.amount)} ${this.ccy} (${fmt(this.egp)} EGP)`
            : `${fmt(this.amount)} EGP`;
        return this.state.direction === "out"
            ? _t("%(owner)s takes %(money)s out of %(box)s.", { owner, money, box })
            : _t("%(owner)s deposits %(money)s into %(box)s.", { owner, money, box });
    }
    async confirm() {
        if (this.state.busy) {
            return;
        }
        if (!this.state.ownerId || !this.state.boxId || !(this.amount > 0) || !(this.egp > 0)) {
            this.state.error = _t("Pick an owner and box, and enter positive amounts.");
            return;
        }
        this.state.busy = true;
        this.state.error = "";
        try {
            await this.props.onSubmit({
                direction: this.state.direction,
                ownerId: this.state.ownerId,
                boxId: this.state.boxId,
                amount: this.amount,
                amountEgp: this.egp,
            });
            this.props.close();
        } catch (error) {
            this.state.busy = false;
            this.state.error = errMessage(error, _t("Owner transfer failed."));
        }
    }
}

patch(Navbar.prototype, {
    get _vaultForeignJournals() {
        return parseList(this.pos.config.jewellery_vault_foreign_journals);
    },
    get _ownerJournals() {
        return parseList(this.pos.config.jewellery_owner_journals);
    },
    get _vaultBoxes() {
        return parseList(this.pos.config.jewellery_vault_boxes);
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
            onSubmit: async ({ direction, journalId, amountEgp, toAmount }) => {
                const res = await this.pos.data.call("pos.session", "post_currency_conversion", [
                    this.pos.session.id, direction, journalId, amountEgp, toAmount, key,
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
        const owners = this._ownerJournals;
        const boxes = this._vaultBoxes;
        if (!owners.length || !boxes.length) {
            this.pos.notification.add(
                _t("No owner journals or vault boxes are configured for this branch."),
                { type: "warning" },
            );
            return;
        }
        const key = this._newCashOpsKey();
        this.pos.dialog.add(OwnerTransferPopup, {
            owners,
            boxes,
            onSubmit: async ({ direction, ownerId, boxId, amount, amountEgp }) => {
                const res = await this.pos.data.call("pos.session", "post_owner_transfer", [
                    this.pos.session.id, direction, ownerId, boxId, amount, amountEgp, key,
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
