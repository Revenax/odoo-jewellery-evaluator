/** @odoo-module **/
/**
 * Copyright 2026 Revenax Digital Services
 * Author: Mohamed A. Abdallah
 * Website: https://www.revenax.com
 *
 * Cash helpers "Currency" + "Transfer to Owner" (Cash section of the burger menu,
 * on the shared HelperDialog, see pos_helpers.js).
 *   * Journals arrive on pos.config as JSON strings from _load_pos_data_read
 *     (pos_config.py): jewellery_vault_foreign_journals (currency),
 *     jewellery_owner_journals + jewellery_vault_boxes (owner). Each entry is
 *     {id, name[, ccy, foreign]}.
 *   * Backend posts real, two-way JEs: pos.session.post_currency_conversion /
 *     post_owner_transfer (models/pos_cash_ops.py). The EGP-Vault leg Cr/Dr's the
 *     Vault, so the pos.session Vault override folds it into the shift.
 *   * The cashier enters BOTH amounts (EGP + foreign); the rate shown is a
 *     read-only readout (EGP ÷ foreign), no rate maths on the server.
 *   * The backend WHITELISTS the journal/box, requires an open session and
 *     dedupes by an idempotency key made once per opening and REUSED across
 *     in-window retries (the window stays open, busy-guarded, on failure), so a
 *     lost-response retry never posts a second real cash movement.
 *   * Shown only when Odoo's own Cash In/Out is (never for the minimal role).
 */
import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import {
    HelperDialog,
    errMessage,
    fmtNumber,
    newIdempotencyKey,
    parseList,
    posHelpers,
} from "./pos_helpers";

// --- Currency conversion: two-way EGP <-> a foreign Vault box ---------------
export class CurrencyConvertPopup extends Component {
    static template = "jewellery_evaluator.CurrencyConvertPopup";
    static components = { HelperDialog };
    static props = ["journals", "onSubmit", "close"];
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
    get rateText() {
        const rate = this.egp > 0 && this.foreign > 0 ? this.egp / this.foreign : NaN;
        return Number.isFinite(rate) ? `${fmtNumber(rate)} EGP / ${this.selectedCcy}` : "";
    }
    get summary() {
        if (!(this.egp > 0) || !(this.foreign > 0)) {
            return "";
        }
        const args = { egp: fmtNumber(this.egp), fx: fmtNumber(this.foreign), ccy: this.selectedCcy };
        return this.state.direction === "buy"
            ? _t("%(egp)s EGP leaves the drawer, %(fx)s %(ccy)s goes into the box.", args)
            : _t("%(fx)s %(ccy)s leaves the box, %(egp)s EGP goes into the drawer.", args);
    }
    async confirm() {
        if (this.state.busy) {
            return;
        }
        if (!this.state.journalId || !(this.egp > 0) || !(this.foreign > 0)) {
            this.state.error = _t("Pick a currency and enter both amounts.");
            return;
        }
        this.state.busy = true;
        this.state.error = "";
        try {
            await this.props.onSubmit({
                direction: this.state.direction,
                journalId: this.state.journalId,
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

// --- Owner transfer: two-way, any box (EGP Vault or a foreign box) ----------
export class OwnerTransferPopup extends Component {
    static template = "jewellery_evaluator.OwnerTransferPopup";
    static components = { HelperDialog };
    static props = ["owners", "boxes", "onSubmit", "close"];
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
        return this.props.boxes.find((b) => String(b.id) === String(this.state.boxId)) || {};
    }
    get isForeign() {
        return Boolean(this.selectedBox.foreign);
    }
    get ccy() {
        return this.selectedBox.ccy || "EGP";
    }
    get amount() {
        return parseFloat(this.state.amount);
    }
    get egp() {
        // EGP box: the EGP value IS the amount. Foreign box: the entered value.
        return this.isForeign ? parseFloat(this.state.amountEgp) : this.amount;
    }
    get rateText() {
        const rate = this.isForeign && this.amount > 0 && this.egp > 0 ? this.egp / this.amount : NaN;
        return Number.isFinite(rate) ? `${fmtNumber(rate)} EGP / ${this.ccy}` : "";
    }
    get summary() {
        if (!(this.amount > 0) || !(this.egp > 0)) {
            return "";
        }
        const owner = this.props.owners.find((o) => String(o.id) === String(this.state.ownerId))?.name || "";
        const box = this.selectedBox.name || "";
        const money = this.isForeign
            ? `${fmtNumber(this.amount)} ${this.ccy} (${fmtNumber(this.egp)} EGP)`
            : `${fmtNumber(this.amount)} EGP`;
        return this.state.direction === "out"
            ? _t("%(owner)s takes %(money)s out of %(box)s.", { owner, money, box })
            : _t("%(owner)s puts %(money)s into %(box)s.", { owner, money, box });
    }
    async confirm() {
        if (this.state.busy) {
            return;
        }
        if (!this.state.ownerId || !this.state.boxId || !(this.amount > 0) || !(this.egp > 0)) {
            this.state.error = _t("Pick an owner and a box, and enter the amount.");
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

function recorded(nav, res, message) {
    nav.pos.notification.add(res?.duplicate ? _t("Already recorded, not posted twice.") : message, {
        type: "success",
    });
}

posHelpers.add("currency", {
    section: "cash",
    sequence: 20,
    icon: "fa-exchange",
    label: _t("Currency"),
    labelAr: "تحويل عملة",
    isVisible: (nav) => nav.jewelleryCanMoveCash,
    run(nav) {
        const journals = parseList(nav.pos.config.jewellery_vault_foreign_journals);
        if (!journals.length) {
            nav.pos.notification.add(_t("No foreign-currency boxes are set up for this branch."), {
                type: "warning",
            });
            return;
        }
        const key = newIdempotencyKey();
        nav.pos.dialog.add(CurrencyConvertPopup, {
            journals,
            onSubmit: async ({ direction, journalId, amountEgp, toAmount }) => {
                const res = await nav.pos.data.call("pos.session", "post_currency_conversion", [
                    nav.pos.session.id, direction, journalId, amountEgp, toAmount, key,
                ]);
                recorded(nav, res, _t("Currency conversion recorded."));
                return res;
            },
        });
    },
});

posHelpers.add("owner_transfer", {
    section: "cash",
    sequence: 30,
    icon: "fa-user-circle-o",
    label: _t("Transfer to Owner"),
    labelAr: "تحويل للمالك",
    isVisible: (nav) => nav.jewelleryCanMoveCash,
    run(nav) {
        const owners = parseList(nav.pos.config.jewellery_owner_journals);
        const boxes = parseList(nav.pos.config.jewellery_vault_boxes);
        if (!owners.length || !boxes.length) {
            nav.pos.notification.add(_t("No owner accounts or boxes are set up for this branch."), {
                type: "warning",
            });
            return;
        }
        const key = newIdempotencyKey();
        nav.pos.dialog.add(OwnerTransferPopup, {
            owners,
            boxes,
            onSubmit: async ({ direction, ownerId, boxId, amount, amountEgp }) => {
                const res = await nav.pos.data.call("pos.session", "post_owner_transfer", [
                    nav.pos.session.id, direction, ownerId, boxId, amount, amountEgp, key,
                ]);
                recorded(nav, res, _t("Owner transfer recorded."));
                return res;
            },
        });
    },
});
