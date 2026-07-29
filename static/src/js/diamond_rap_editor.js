/** @odoo-module **/
// Backend client action: the "Diamond Rap Prices" page — a PDF-style editable
// grid of the Rapaport price list (hundreds USD/carat) for stones >= 0.25 ct.
// Round / Fancy tabs; one table per carat bucket in its native format (grouped
// small / full large). Reads + writes the two config-param JSON grids via
// diamond.rap.price.rap_get / rap_set (models/diamond_rap.py).

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class DiamondRapEditor extends Component {
    static template = "jewellery_evaluator.DiamondRapEditor";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            saving: false,
            sheet: "round",
            grids: { round: {}, fancy: {} },   // Rapaport LIST (hundreds USD/ct)
            discs: { round: {}, fancy: {} },   // per-cell discount % (0..100)
            structure: [],
        });
        onWillStart(async () => {
            const d = await this.orm.call("diamond.rap.price", "rap_get", []);
            this.state.grids = { round: d.round || {}, fancy: d.fancy || {} };
            this.state.discs = { round: d.round_disc || {}, fancy: d.fancy_disc || {} };
            this.state.structure = d.structure || [];
            this.state.loading = false;
        });
    }

    // Generic read/write over the active sheet of either map (list or discount).
    _val(map, bucket, row, col) {
        const v = map[this.state.sheet]?.[bucket]?.[row]?.[col];
        return v == null ? "" : v;
    }
    _set(map, bucket, row, col, ev, max) {
        const g = map[this.state.sheet];
        if (!g[bucket]) {
            g[bucket] = {};
        }
        if (!g[bucket][row]) {
            g[bucket][row] = {};
        }
        const raw = (ev.target.value || "").trim();
        let n = raw === "" ? NaN : parseFloat(raw);
        if (max != null && n > max) {
            n = max;
        }
        if (n > 0) {
            g[bucket][row][col] = n;
        } else {
            delete g[bucket][row][col];
        }
    }

    cell(bucket, row, col) {
        return this._val(this.state.grids, bucket, row, col);
    }
    onCell(bucket, row, col, ev) {
        this._set(this.state.grids, bucket, row, col, ev);
    }
    disc(bucket, row, col) {
        // Empty/absent discount shows (and prices) as 0 — see rap_stone_price_usd.
        const v = this.state.discs[this.state.sheet]?.[bucket]?.[row]?.[col];
        return v == null ? 0 : v;
    }
    onDisc(bucket, row, col, ev) {
        this._set(this.state.discs, bucket, row, col, ev, 100);
    }

    async save() {
        if (this.state.saving) {
            return;
        }
        this.state.saving = true;
        try {
            await this.orm.call("diamond.rap.price", "rap_set", [
                this.state.sheet,
                this.state.grids[this.state.sheet],
                this.state.discs[this.state.sheet],
            ]);
            this.notification.add(_t("Rap prices saved."), { type: "success" });
        } catch (e) {
            this.notification.add(_t("Save failed."), { type: "danger" });
            throw e;
        } finally {
            this.state.saving = false;
        }
    }
}

registry.category("actions").add("jewellery_evaluator.diamond_rap_editor", DiamondRapEditor);
