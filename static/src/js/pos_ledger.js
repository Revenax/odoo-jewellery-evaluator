/** @odoo-module **/
/**
 * Copyright 2026 Revenax Digital Services
 * Author: Mohamed A. Abdallah
 * Website: https://www.revenax.com
 *
 * Daily Ledger inside the register (Look-ups section, shared HelperDialog), in
 * English: opening / closing cash in the header, then one row per movement with
 * both money (in / out) and gold weight, karat, source and notes.
 *
 * Read-only. Scoped to THIS register by default, with a toggle for every
 * register. Data: jewellery.ledger.ledger_rows (never writes).
 */
import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { HelperDialog, fmtMoney, localISODate, posHelpers } from "./pos_helpers";

export class LedgerPopup extends Component {
    static template = "jewellery_evaluator.LedgerPopup";
    static components = { HelperDialog };
    static props = { pos: Object, close: Function };

    setup() {
        this.fmt = fmtMoney;
        this.state = useState({
            status: "loading",
            date: localISODate(),
            thisRegisterOnly: true,
            data: null,
        });
        this.load(); // not awaited: the window opens at once and shows "Loading…"
    }

    async load() {
        this.state.status = "loading";
        try {
            const configId = this.state.thisRegisterOnly ? this.props.pos.config.id : false;
            this.state.data = await this.props.pos.data.call("jewellery.ledger", "ledger_rows", [
                this.state.date,
                configId,
            ]);
            this.state.status = "ready";
        } catch {
            this.state.status = "error";
        }
    }

    get isToday() {
        return this.state.date === localISODate();
    }

    setDate(value) {
        if (value && value !== this.state.date) {
            this.state.date = value;
            this.load();
        }
    }

    goToday() {
        this.setDate(localISODate());
    }

    shiftDay(delta) {
        const d = new Date(`${this.state.date}T12:00:00`);
        d.setDate(d.getDate() + delta);
        this.setDate(localISODate(d));
    }

    setScope(thisRegisterOnly) {
        if (thisRegisterOnly !== this.state.thisRegisterOnly) {
            this.state.thisRegisterOnly = thisRegisterOnly;
            this.load();
        }
    }

    /** Grams + thousandths as one weight; blank rather than 0. */
    weight(grams, milli) {
        const g = (grams || 0) + (milli || 0) / 1000;
        return g ? g.toFixed(3) : "";
    }

    /** The backend's book sources, in English. */
    sourceLabel(row) {
        return { sale: "Sale", return: "Return", invoice: "Invoice" }[row.kind] || row.source || "";
    }

    print() {
        document.body.classList.add("o_mjh_printing_ledger");
        window.print();
        document.body.classList.remove("o_mjh_printing_ledger");
    }
}

posHelpers.add("daily_ledger", {
    section: "lookup",
    sequence: 10,
    icon: "fa-book",
    label: _t("Daily Ledger"),
    run: (nav) => nav.pos.dialog.add(LedgerPopup, { pos: nav.pos }),
});
