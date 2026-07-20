/** @odoo-module **/
// Backend client action: the "Diamond Rap Prices" page — a PDF-style editable
// grid of the Rapaport price list (hundreds USD/carat) for stones >= 0.25 ct.
// Round / Pear tabs; one table per carat bucket in its native format (grouped
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
            discount: 0,
            grids: { round: {}, pear: {} },
            structure: [],
        });
        onWillStart(async () => {
            const d = await this.orm.call("diamond.rap.price", "rap_get", []);
            this.state.grids = { round: d.round || {}, pear: d.pear || {} };
            this.state.discount = d.discount || 0;
            this.state.structure = d.structure || [];
            this.state.loading = false;
        });
    }

    cell(bucket, row, col) {
        const g = this.state.grids[this.state.sheet];
        const v = g?.[bucket]?.[row]?.[col];
        return v == null ? "" : v;
    }

    onCell(bucket, row, col, ev) {
        const g = this.state.grids[this.state.sheet];
        if (!g[bucket]) {
            g[bucket] = {};
        }
        if (!g[bucket][row]) {
            g[bucket][row] = {};
        }
        const raw = (ev.target.value || "").trim();
        if (raw === "") {
            delete g[bucket][row][col];
        } else {
            const n = parseFloat(raw);
            if (n > 0) {
                g[bucket][row][col] = n;
            } else {
                delete g[bucket][row][col];
            }
        }
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
                this.state.discount,
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
