/** @odoo-module **/
// Backend client action: the "Jewellery" app home page. Shows the three live
// per-gram gold prices (24K / 21K / 18K) derived from the 21K base the price
// API quotes, plus when that price last changed, and a shortcut into the
// Diamond Rap Prices editor for managers.
//
// Read-only: it calls gold.price.service.dashboard_data() and renders. It never
// writes, and it never triggers a price fetch — the cron owns that.

import { Component, onMounted, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

// The dashboard polls so an open tab does not go stale. The gold cron runs far
// more often than this; 60s is a display refresh, not a price fetch.
const REFRESH_MS = 60000;

export class JewelleryDashboard extends Component {
    static template = "jewellery_evaluator.JewelleryDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            failed: false,
            prices: [],
            currency: "EGP",
            changedAt: false,
            configured: true,
            isManager: false,
        });

        onWillStart(async () => {
            await this.load();
        });

        // Start polling only once mounted, and always clear on unmount. Starting
        // it in setup() would leak the interval forever if the component were
        // destroyed before mounting (onWillUnmount only fires for mounted ones).
        this.timer = null;
        onMounted(() => {
            this.timer = setInterval(() => this.load(), REFRESH_MS);
        });
        onWillUnmount(() => {
            if (this.timer) {
                clearInterval(this.timer);
                this.timer = null;
            }
        });
    }

    async load() {
        try {
            const d = await this.orm.call("gold.price.service", "dashboard_data", []);
            this.state.prices = d.prices || [];
            this.state.currency = d.currency || "EGP";
            this.state.changedAt = d.changed_at || false;
            this.state.configured = !!d.configured;
            this.state.isManager = !!d.is_manager;
            this.state.failed = false;
        } catch {
            // A failed refresh must not blank an already-rendered dashboard —
            // keep the last known values and flag them as possibly stale.
            this.state.failed = true;
        } finally {
            this.state.loading = false;
        }
    }

    /** "5,865.00" — grouped, always 2 dp. */
    formatPrice(value) {
        return (value || 0).toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    /** Server sends a naive UTC string; render it in the browser's timezone. */
    get changedAtLabel() {
        if (!this.state.changedAt) {
            return "never";
        }
        const d = new Date(this.state.changedAt.replace(" ", "T") + "Z");
        if (isNaN(d.getTime())) {
            return this.state.changedAt;
        }
        const mins = Math.floor((Date.now() - d.getTime()) / 60000);
        let ago;
        if (mins < 1) {
            ago = "just now";
        } else if (mins < 60) {
            ago = `${mins} minute${mins === 1 ? "" : "s"} ago`;
        } else if (mins < 1440) {
            const h = Math.floor(mins / 60);
            ago = `${h} hour${h === 1 ? "" : "s"} ago`;
        } else {
            const days = Math.floor(mins / 1440);
            ago = `${days} day${days === 1 ? "" : "s"} ago`;
        }
        return `${ago} · ${d.toLocaleString()}`;
    }

    openRap() {
        this.action.doAction("jewellery_evaluator.action_diamond_rap_editor");
    }
}

registry.category("actions").add("jewellery_evaluator.dashboard", JewelleryDashboard);
