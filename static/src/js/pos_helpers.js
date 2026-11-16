/** @odoo-module **/
/**
 * Copyright 2026 Revenax Digital Services
 * Author: Mohamed A. Abdallah
 * Website: https://www.revenax.com
 *
 * Shared base for the register's helpers (burger menu): ONE look, ONE menu list.
 *
 *  * `posHelpers` registry: every helper registers {section, sequence, icon,
 *    label, labelAr, isVisible(navbar), run(navbar)}. The Navbar renders them
 *    grouped by section right where Odoo's Cash In/Out sits (pos_helpers.xml),
 *    so new helpers just register; nobody edits the menu template again.
 *  * `HelperDialog`: the window every helper opens. Marjaan header (icon tile,
 *    English + Arabic title, close), optional toolbar, a body with built-in
 *    loading / error / empty states, and a footer. Styling: pos_helpers.scss.
 *  * Small shared utilities (money formatting, RPC error text, idempotency key).
 */
import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { Navbar } from "@point_of_sale/app/components/navbar/navbar";
import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

export const posHelpers = registry.category("jewellery_pos_helpers");

/** Menu sections, in display order. */
export const HELPER_SECTIONS = [
    { id: "cash", label: _t("Cash"), labelAr: "الخزنة" },
    { id: "stock", label: _t("Stock"), labelAr: "البضاعة" },
    { id: "lookup", label: _t("Look-ups"), labelAr: "استعلام" },
];

// ── Utilities ───────────────────────────────────────────────────────────────

/** Thousands-separated number; blank for non-numbers. */
export function fmtNumber(value, decimals = 2) {
    const n = Number(value);
    return Number.isFinite(n)
        ? n.toLocaleString("en-US", { maximumFractionDigits: decimals })
        : "";
}

/** Whole-pound money (the shop never writes piastres); blank for 0/empty. */
export function fmtMoney(value) {
    const n = Number(value);
    return n ? Math.round(n).toLocaleString("en-US") : "";
}

/** Human message from an RPC error. */
export function errMessage(error, fallback) {
    return error?.data?.message || error?.message || fallback;
}

/** Parse a pos.config JSON-string list, tolerating empty/malformed data. */
export function parseList(raw) {
    try {
        const list = JSON.parse(raw || "[]");
        return Array.isArray(list) ? list : [];
    } catch {
        return [];
    }
}

/** One idempotency token per helper opening, reused across in-window retries. */
export function newIdempotencyKey() {
    return (
        globalThis.crypto?.randomUUID?.() ||
        `${Date.now()}-${Math.random().toString(36).slice(2)}`
    );
}

/** YYYY-MM-DD in the register's LOCAL day (toISOString would give UTC). */
export function localISODate(d = new Date()) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// ── The shared window ───────────────────────────────────────────────────────

export class HelperDialog extends Component {
    static template = "jewellery_evaluator.HelperDialog";
    static components = { Dialog };
    static props = {
        title: String,
        titleAr: { type: String, optional: true },
        icon: { type: String, optional: true },
        // "md" for forms, "xl" for wide tables.
        size: { type: String, optional: true },
        // "ready" | "loading" | "error" | "empty"
        status: { type: String, optional: true },
        statusText: { type: String, optional: true },
        close: Function,
        slots: { type: Object, optional: true },
    };
    static defaultProps = { size: "md", status: "ready", icon: "fa-star" };

    get statusText() {
        if (this.props.statusText) {
            return this.props.statusText;
        }
        return {
            loading: _t("Loading…"),
            error: _t("Could not load. Check the connection and try again."),
            empty: _t("Nothing to show."),
        }[this.props.status];
    }
}

// ── The menu ────────────────────────────────────────────────────────────────

patch(Navbar.prototype, {
    /** Same rule as Odoo's own Cash In/Out: never for the minimal cashier role. */
    get jewelleryCanMoveCash() {
        return Boolean(this.showCashMoveButton && this.pos.cashier?._role !== "minimal");
    },
    get jewelleryHelperSections() {
        const items = posHelpers
            .getEntries()
            .map(([id, helper]) => ({ id, ...helper }))
            .filter((h) => !h.isVisible || h.isVisible(this))
            .sort((a, b) => (a.sequence || 0) - (b.sequence || 0));
        return HELPER_SECTIONS.map((section) => ({
            ...section,
            items: items.filter((h) => h.section === section.id),
        })).filter((section) => section.items.length);
    },
    runJewelleryHelper(helper) {
        return helper.run(this);
    },
});

// Odoo's own Cash In/Out joins the Cash section (its stock entry is hidden in
// pos_helpers.xml), so all drawer operations sit together with one rule.
posHelpers.add("cash_move", {
    section: "cash",
    sequence: 10,
    icon: "fa-money",
    label: _t("Cash In / Out"),
    labelAr: "وارد / منصرف",
    isVisible: (nav) => nav.jewelleryCanMoveCash,
    run: (nav) => nav.pos.cashMove(),
});
