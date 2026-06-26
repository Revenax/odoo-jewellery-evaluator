/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, useRef, onMounted } from "@odoo/owl";

const MODEL = "jewellery.stock.count";

const BANNER = {
    found: { cls: "o_jsc_ok", icon: "fa-check-circle" },
    already: { cls: "o_jsc_note", icon: "fa-refresh" },
    unexpected: { cls: "o_jsc_warn", icon: "fa-exclamation-triangle" },
    unknown: { cls: "o_jsc_err", icon: "fa-times-circle" },
    empty: { cls: "o_jsc_note", icon: "fa-info-circle" },
};

export class StockCountScanner extends Component {
    static template = "jewellery_inventory_management.StockCountScanner";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.scanRef = useRef("scan");
        const p = (this.props.action && (this.props.action.params || this.props.action.context)) || {};
        this.countId = p.count_id || p.active_id;
        this.state = useState({
            loaded: false,
            name: "",
            prefix: "",
            scope: "",
            countState: "in_progress",
            stats: { expected: 0, found: 0, missing: 0, unexpected: 0, progress: 0 },
            lines: [],
            last: null,
        });
        onMounted(() => this.load());
    }

    async load() {
        const data = await this.orm.call(MODEL, "get_scan_state", [[this.countId]]);
        this._apply(data);
        this.state.name = data.name;
        this.state.prefix = data.sku_prefix;
        this.state.scope = data.scope;
        this.state.countState = data.state;
        this.state.loaded = true;
        this.focus();
    }

    _apply(data) {
        this.state.stats = data.stats;
        this.state.lines = data.lines;
    }

    focus() {
        Promise.resolve().then(() => this.scanRef.el && this.scanRef.el.focus());
    }

    get toFind() {
        return this.state.lines.filter((l) => l.status === "to_find");
    }
    get found() {
        return this.state.lines
            .filter((l) => l.status === "found")
            .sort((a, b) => (a.scanned_at < b.scanned_at ? 1 : -1));
    }
    get unexpected() {
        return this.state.lines.filter((l) => l.status === "unexpected");
    }
    get banner() {
        return (this.state.last && BANNER[this.state.last.result]) || BANNER.empty;
    }

    async onKeydown(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        const code = (this.scanRef.el.value || "").trim();
        this.scanRef.el.value = "";
        if (!code) {
            return;
        }
        const res = await this.orm.call(MODEL, "process_scan", [[this.countId], code]);
        this.state.last = res;
        this._apply(res);
        this.focus();
    }

    async finish() {
        await this.orm.call(MODEL, "action_finish", [[this.countId]]);
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: MODEL,
            res_id: this.countId,
            views: [[false, "form"]],
            target: "main",
        });
    }
}

registry.category("actions").add("jewellery_stock_count_scanner", StockCountScanner);
