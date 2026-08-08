/** @odoo-module **/
// "Daily Ledger" — the digital twin of the shop's physical day book. One page
// per day: opening cash, every sale, every other cash movement through the
// Vault, and the closing count. Read-only; Print uses the browser dialog with
// a print stylesheet that strips the app chrome.

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

function todayLocalISO() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
        d.getDate()
    ).padStart(2, "0")}`;
}

export class JewelleryLedger extends Component {
    static template = "jewellery_evaluator.JewelleryLedger";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            loading: true,
            failed: false,
            date: todayLocalISO(),
            data: null,
        });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call("jewellery.ledger", "ledger_data", [
                this.state.date,
            ]);
            this.state.failed = false;
        } catch {
            this.state.failed = true;
        } finally {
            this.state.loading = false;
        }
    }

    setDate(value) {
        if (!value) {
            return;
        }
        this.state.date = value;
        this.load();
    }

    shiftDay(delta) {
        const d = new Date(this.state.date + "T12:00:00");
        d.setDate(d.getDate() + delta);
        this.setDate(
            `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
                d.getDate()
            ).padStart(2, "0")}`
        );
    }

    fmt(value) {
        return (value || 0).toLocaleString(undefined, {
            minimumFractionDigits: 0,
            maximumFractionDigits: 0,
        });
    }

    print() {
        window.print();
    }
}

registry.category("actions").add("jewellery_evaluator.ledger", JewelleryLedger);
