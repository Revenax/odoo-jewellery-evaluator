/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, useRef, onMounted } from "@odoo/owl";
import { scanBarcode } from "@web/core/barcode/barcode_dialog";
import { isBarcodeScannerSupported } from "@web/core/barcode/barcode_video_scanner";

const MODEL = "jewellery.stock.count";
const TAKE = "jewellery.stock.take";

/** Mini-count method -> its "scan together" twin on the full count. */
const GROUP_METHOD = {
    get_scan_state: "get_group_scan_state",
    process_scan: "group_process_scan",
    get_piece: "group_get_piece",
    set_resolution: "group_set_resolution",
    other_locations: "group_other_locations",
    action_approve: "group_approve",
};

const BANNER = {
    found: { cls: "o_jsc_ok", icon: "fa-check-circle" },
    moved: { cls: "o_jsc_ok", icon: "fa-exchange" },
    routed: { cls: "o_jsc_note", icon: "fa-share" },
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
    transfer_here: { label: "Transfer to this location", cls: "text-bg-primary", icon: "fa-exchange" },
};

/**
 * A buzzer for every scan that is not a clean match (already counted, moved
 * here from elsewhere, unexpected, unknown), so the person scanning looks up
 * at the screen. Web Audio, no sound file; the context is created on the
 * first scan, which follows a key press, so browsers allow it.
 */
let audio = null;
export function buzz() {
    try {
        audio = audio || new (window.AudioContext || window.webkitAudioContext)();
        if (audio.state === "suspended") {
            audio.resume();
        }
        const now = audio.currentTime;
        const gain = audio.createGain();
        gain.gain.setValueAtTime(0.25, now);
        gain.gain.setValueAtTime(0.25, now + 0.42);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.5);
        gain.connect(audio.destination);
        for (const freq of [140, 147]) {
            const osc = audio.createOscillator();
            osc.type = "square";
            osc.frequency.setValueAtTime(freq, now);
            osc.connect(gain);
            osc.start(now);
            osc.stop(now + 0.5);
        }
    } catch {
        // No audio on this device; the coloured banner still shows.
    }
}

/** What can be decided for a piece that was not found. */
export const MISSING_DECISIONS = ["lost", "sold_no_invoice", "other_location", "keep"];

/**
 * The stock-count scan screen. Full width: the count on the left, a side
 * panel on the right showing the last scanned piece, or any SKU clicked in
 * the lists. A missing piece is decided from the panel (lost, sold without
 * invoice, in another location, leave in stock); the count closes only
 * with an admin badge, which applies those decisions to stock.
 *
 * Opened with a ``take_id`` instead of a ``count_id`` it is the full count's
 * optional "scan together" screen: several mini counts at once (chips at the
 * top pick which), every scan filed into its own prefix's mini, combined
 * lists, and one badge approving all the selected minis.
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
        this.takeId = p.take_id || false;
        this.countId = this.takeId ? false : p.count_id || p.active_id;
        this.resolutions = RESOLUTIONS;
        this.missingDecisions = MISSING_DECISIONS;
        this.cameraSupported = isBarcodeScannerSupported();
        this.state = useState({
            loaded: false,
            name: "",
            prefix: "",
            scope: "",
            countState: "in_progress",
            approvedBy: "",
            take: false,
            stats: { total: 0, expected: 0, found: 0, missing: 0, extra: 0, unexpected: 0, progress: 0, unresolved: 0 },
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
            minis: [],
            selectedIds: [],
        });
        onMounted(() => this.load());
    }

    get together() {
        return Boolean(this.takeId);
    }

    /** Call a mini-count method, or its full-count twin on the together screen. */
    call(method, ...args) {
        if (this.together) {
            return this.orm.call(TAKE, GROUP_METHOD[method], [[this.takeId], this.state.selectedIds, ...args]);
        }
        return this.orm.call(MODEL, method, [[this.countId], ...args]);
    }

    get openMinis() {
        return this.state.minis.filter((m) => m.state === "in_progress");
    }
    get doneMinis() {
        return this.state.minis.filter((m) => m.state !== "in_progress");
    }

    async toggleMini(mini) {
        const ids = this.state.selectedIds.includes(mini.id)
            ? this.state.selectedIds.filter((id) => id !== mini.id)
            : [...this.state.selectedIds, mini.id];
        if (!ids.length) {
            this.notification.add("Keep at least one mini count in the scan.", { type: "warning" });
            return;
        }
        this.state.selectedIds = ids;
        this._apply(await this.call("get_scan_state"));
        this.focus();
    }

    async selectAllMinis() {
        this.state.selectedIds = this.openMinis.map((m) => m.id);
        this._apply(await this.call("get_scan_state"));
        this.focus();
    }

    get open() {
        return this.state.countState === "in_progress";
    }

    async load() {
        const data = await this.call("get_scan_state");
        this._apply(data);
        this.state.name = data.name;
        this.state.prefix = data.sku_prefix || "";
        this.state.scope = data.scope;
        this.state.loaded = true;
        this.focus();
    }

    _apply(data) {
        this.state.stats = data.stats;
        this.state.lines = data.lines;
        if (data.minis) {
            this.state.minis = data.minis;
            this.state.selectedIds = data.selected_ids;
        }
        if (data.state) {
            this.state.countState = data.state;
            this.state.approvedBy = data.approved_by || "";
            this.state.take = data.take || false;
        }
    }

    focus() {
        Promise.resolve().then(() => this.scanRef.el && this.scanRef.el.focus());
    }

    get toFind() {
        return this.state.lines.filter((l) => l.status === "to_find");
    }
    /** Every piece scanned here: on Odoo's list or extra. Newest first. */
    get found() {
        return this.state.lines
            .filter((l) => l.status === "found" || l.status === "unexpected")
            .sort((a, b) => (a.scanned_at < b.scanned_at ? 1 : -1));
    }
    /** Found / Missing / Total rows of the weights table. */
    get weightRows() {
        const st = this.state.stats;
        const w = st.weights || {};
        const zero = { net_gold: 0, stones: 0, jewellery: 0, readings: 0 };
        return [
            { key: "found", label: "Found", pieces: st.found, w: w.found || zero, cls: "text-success" },
            { key: "missing", label: "Missing", pieces: st.missing, w: w.missing || zero, cls: "text-warning-emphasis" },
            { key: "total", label: "Total", pieces: st.total, w: w.total || zero, cls: "fw-bold o_jsc_wtotal" },
        ];
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
        await this.submitScan(code);
    }

    /** Read a code with the device camera (Odoo's own scanner dialog). */
    async _camera() {
        try {
            return ((await scanBarcode(this.env)) || "").trim();
        } catch (err) {
            if (err && err.message) {
                this.notification.add(err.message, { type: "danger" });
            }
            return "";
        }
    }

    async scanWithCamera() {
        const code = await this._camera();
        if (code) {
            await this.submitScan(code);
        }
    }

    async submitScan(code) {
        if (!code) {
            return;
        }
        const res = await this.call("process_scan", code);
        if (res.result !== "found") {
            buzz();
        }
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
            this.state.piece = await this.call("get_piece", line.product_id);
        } finally {
            this.state.pieceLoading = false;
        }
    }

    async _refreshPiece() {
        if (this.state.piece) {
            this.state.piece = await this.call("get_piece", this.state.piece.product_id);
        }
    }

    async resolve(resolution) {
        const line = this.state.piece && this.state.piece.line;
        if (!line) {
            return;
        }
        if (resolution === "other_location") {
            if (!this.state.locations) {
                this.state.locations = await this.call("other_locations");
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
            const data = await this.call("set_resolution", lineId, resolution, locationId);
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

    /** What approval will do, for the dialog. */
    get approvalSummary() {
        const toFind = this.toFind;
        const n = (key) => toFind.filter((l) => l.resolution === key).length;
        return [
            { key: "found", label: "Found", value: this.state.stats.found, icon: "fa-check", cls: "text-success" },
            { key: "extra", label: "of which extra (stock unchanged)", value: this.state.stats.extra, icon: "fa-exclamation-triangle", cls: "text-danger" },
            { key: "lost", label: "Lost (off stock, Inventory Loss)", value: n("lost"), icon: "fa-ban", cls: "text-danger" },
            { key: "sold", label: "Sold without invoice (off stock)", value: n("sold_no_invoice"), icon: "fa-shopping-bag", cls: "text-secondary" },
            { key: "other", label: "Moved to another location", value: n("other_location"), icon: "fa-map-marker", cls: "text-info" },
            { key: "keep", label: "Left in stock", value: n("keep"), icon: "fa-archive", cls: "text-muted" },
        ].filter((row) => row.value);
    }

    async badgeWithCamera() {
        const code = await this._camera();
        if (code && this.badgeRef.el) {
            this.badgeRef.el.value = code;
            await this.approve();
        }
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
            const data = await this.call("action_approve", badge);
            this._apply(data);
            this.state.approving = false;
            const what = data.approved ? data.approved.join(", ") : "Count";
            this.notification.add(`${what} approved by ${data.approved_by}. Stock updated.`, { type: "success" });
        } catch (err) {
            buzz();
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

    openTake() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "jewellery.stock.take",
            res_id: this.state.take.id,
            views: [[false, "form"]],
            target: "main",
        });
    }

    openForm() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: this.together ? TAKE : MODEL,
            res_id: this.together ? this.takeId : this.countId,
            views: [[false, "form"]],
            target: "main",
        });
    }

    fmt(value, digits = 2) {
        return (value || 0).toFixed(digits);
    }
}

registry.category("actions").add("jewellery_stock_count_scanner", StockCountScanner);
