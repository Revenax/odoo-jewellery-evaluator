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

export const RESOLUTIONS = {
    lost: { label: "Lost", cls: "text-bg-danger", icon: "fa-ban" },
    sold_no_invoice: { label: "Sold without invoice", cls: "text-bg-secondary", icon: "fa-shopping-bag" },
    other_location: { label: "In another location", cls: "text-bg-info", icon: "fa-map-marker" },
    keep: { label: "Leave in stock", cls: "text-bg-light", icon: "fa-archive" },
};

/**
 * The stock-count scan screen. Full width: the count on the left, a side
 * panel on the right showing the last scanned piece, or any SKU clicked in
 * the lists. A missing piece is decided from the panel (lost, sold without
 * invoice, in another location, leave in stock); the count closes only
 * with an admin badge, which applies those decisions to stock.
 */
export class StockCountScanner extends Component {
    static template = "jewellery_inventory_management.StockCountScanner";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.scanRef = useRef("scan");
        this.badgeRef = useRef("badge");
        const p = (this.props.action && (this.props.action.params || this.props.action.context)) || {};
        this.countId = p.count_id || p.active_id;
        this.resolutions = RESOLUTIONS;
        this.state = useState({
            loaded: false,
            name: "",
            prefix: "",
            scope: "",
            countState: "in_progress",
            approvedBy: "",
            stats: { expected: 0, found: 0, missing: 0, unexpected: 0, progress: 0, unresolved: 0 },
            lines: [],
            last: null,
            piece: null,
            pieceLoading: false,
            locations: null,
            pickLocation: false,
            locationId: "",
            approving: false,
            approveError: "",
            busy: false,
        });
        onMounted(() => this.load());
    }

    get open() {
        return this.state.countState === "in_progress";
    }

    async load() {
        const data = await this.orm.call(MODEL, "get_scan_state", [[this.countId]]);
        this._apply(data);
        this.state.name = data.name;
        this.state.prefix = data.sku_prefix;
        this.state.scope = data.scope;
        this.state.loaded = true;
        this.focus();
    }

    _apply(data) {
        this.state.stats = data.stats;
        this.state.lines = data.lines;
        if (data.state) {
            this.state.countState = data.state;
            this.state.approvedBy = data.approved_by || "";
        }
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
        this.state.piece = res.piece || null;
        this.state.pickLocation = false;
        this.focus();
    }

    async showLine(line) {
        this.state.pieceLoading = true;
        this.state.pickLocation = false;
        try {
            this.state.piece = await this.orm.call(MODEL, "get_piece", [[this.countId], line.product_id]);
        } finally {
            this.state.pieceLoading = false;
        }
    }

    async _refreshPiece() {
        if (this.state.piece) {
            this.state.piece = await this.orm.call(MODEL, "get_piece", [
                [this.countId],
                this.state.piece.product_id,
            ]);
        }
    }

    async resolve(resolution) {
        const line = this.state.piece && this.state.piece.line;
        if (!line) {
            return;
        }
        if (resolution === "other_location") {
            if (!this.state.locations) {
                this.state.locations = await this.orm.call(MODEL, "other_locations", [[this.countId]]);
            }
            this.state.pickLocation = true;
            this.state.locationId = "";
            return;
        }
        await this._setResolution(line.id, resolution, false);
    }

    async confirmLocation() {
        const line = this.state.piece && this.state.piece.line;
        if (!line || !this.state.locationId) {
            return;
        }
        await this._setResolution(line.id, "other_location", parseInt(this.state.locationId, 10));
        this.state.pickLocation = false;
    }

    async _setResolution(lineId, resolution, locationId) {
        this.state.busy = true;
        try {
            const data = await this.orm.call(MODEL, "set_resolution", [
                [this.countId],
                lineId,
                resolution,
                locationId,
            ]);
            this._apply(data);
            await this._refreshPiece();
        } finally {
            this.state.busy = false;
            this.focus();
        }
    }

    // --- closing with an admin badge -----------------------------------------

    startApprove() {
        if (this.state.stats.unresolved) {
            this.notification.add(
                `${this.state.stats.unresolved} missing piece(s) still need a decision. Click each one under "Still to find".`,
                { type: "warning" }
            );
            return;
        }
        this.state.approving = true;
        this.state.approveError = "";
        Promise.resolve().then(() => this.badgeRef.el && this.badgeRef.el.focus());
    }

    cancelApprove() {
        this.state.approving = false;
        this.focus();
    }

    async onBadgeKeydown(ev) {
        if (ev.key === "Enter") {
            await this.approve();
        }
    }

    async approve() {
        const badge = (this.badgeRef.el && this.badgeRef.el.value || "").trim();
        if (!badge) {
            return;
        }
        this.state.busy = true;
        try {
            const data = await this.orm.call(MODEL, "action_approve", [[this.countId], badge]);
            this._apply(data);
            this.state.approving = false;
            this.notification.add(`Count approved by ${data.approved_by}. Stock updated.`, { type: "success" });
        } catch (err) {
            this.state.approveError =
                (err && err.data && err.data.message) || "Could not approve the count.";
            if (this.badgeRef.el) {
                this.badgeRef.el.value = "";
                this.badgeRef.el.focus();
            }
        } finally {
            this.state.busy = false;
        }
    }

    openForm() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: MODEL,
            res_id: this.countId,
            views: [[false, "form"]],
            target: "main",
        });
    }

    fmt(value, digits = 2) {
        return (value || 0).toFixed(digits);
    }
}

registry.category("actions").add("jewellery_stock_count_scanner", StockCountScanner);
