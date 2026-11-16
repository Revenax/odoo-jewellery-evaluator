/** @odoo-module **/
/**
 * Copyright 2026 Revenax Digital Services
 * Author: Mohamed A. Abdallah
 * Website: https://www.revenax.com
 *
 * A READ-ONLY Diamond Rapaport price viewer inside the POS register (Look-ups
 * section, shared HelperDialog): Round / Fancy tabs, the < 0.25 ct flat tiers as cards, and the
 * >= 0.25 ct grids. Cells show the NET price per carat (list x (1 - discount));
 * type a carat and every cell switches to the TOTAL stone price for that weight
 * — a one-tap pricing tool at the counter. Data comes from the same
 * diamond.rap.price.rap_get RPC the backend editor uses (never writes).
 */
import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { HelperDialog, posHelpers } from "./pos_helpers";

export class RapViewerPopup extends Component {
    static template = "jewellery_evaluator.RapViewerPopup";
    static components = { HelperDialog };
    static props = {
        pos: { type: Object },
        close: { type: Function },
    };

    setup() {
        this.state = useState({ sheet: "round", caratInput: "", status: "loading" });
        this.data = {};
        this.load(); // not awaited: the window opens at once and shows "Loading…"
    }

    async load() {
        try {
            this.data = await this.props.pos.data.call("diamond.rap.price", "rap_get", []);
            this.state.status = (this.data.structure || []).length ? "ready" : "empty";
        } catch {
            this.state.status = "error";
        }
    }

    get structure() {
        return this.data.structure || [];
    }

    /** Parsed carat from the input; 0 (falsy) means "show per-carat prices". */
    get carat() {
        const c = parseFloat(this.state.caratInput);
        return c > 0 ? c : 0;
    }

    get unitLabel() {
        return this.carat > 0
            ? _t("total price @ %s ct", this.carat)
            : _t("$ per carat");
    }

    _list(bucket, row, col) {
        const grid = this.data[this.state.sheet] || {};
        const v = grid && grid[bucket] && grid[bucket][row] && grid[bucket][row][col];
        return v == null ? null : Number(v);
    }

    _disc(bucket, row, col) {
        const grid = this.data[`${this.state.sheet}_disc`] || {};
        const v = grid && grid[bucket] && grid[bucket][row] && grid[bucket][row][col];
        return v == null ? 0 : Number(v);
    }

    /** True when a grid cell carries a discount — used to accent it faintly. */
    hasDiscount(bucket, row, col) {
        return this._disc(bucket, row, col) > 0;
    }

    /** Display text for a >= 0.25 ct grid cell: net $/ct, or total $ if a carat
   *  is entered. Empty when the sheet has no value for this colour/clarity. */
    cellText(bucket, row, col) {
        const list = this._list(bucket, row, col);
        if (list == null) {
            return "";
        }
        const netPerCt = list * 100 * (1 - this._disc(bucket, row, col) / 100);
        return this._money(this.carat > 0 ? netPerCt * this.carat : netPerCt);
    }

    /** Display text for a < 0.25 ct flat tier card. `value` is already $/ct. */
    tierText(value) {
        const perCt = Number(value) || 0;
        return this._money(this.carat > 0 ? perCt * this.carat : perCt);
    }

    _money(v) {
        return `$${Math.round(v).toLocaleString("en-US")}`;
    }

    setSheet(sheet) {
        this.state.sheet = sheet;
    }
}

posHelpers.add("rap_prices", {
    section: "lookup",
    sequence: 20,
    icon: "fa-diamond",
    label: _t("Diamond Rap Prices"),
    run: (nav) => nav.pos.dialog.add(RapViewerPopup, { pos: nav.pos }),
});
