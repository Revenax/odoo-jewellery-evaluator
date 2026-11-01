/** @odoo-module **/
/**
 * Copyright 2026 Revenax Digital Services
 * Author: Mohamed A. Abdallah
 * Website: https://www.revenax.com
 *
 * Price banner above the POS product grid: gold 24K / 21K / 18K and silver 999
 * per gram, and the shop's USD rate. Same values the till prices with
 * (pos.session.get_jewellery_price_board); refreshed every minute, like the
 * gold cron. Read-only.
 */
import { Component, onMounted, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { patch } from "@web/core/utils/patch";

const REFRESH_MS = 60 * 1000;

export class PriceBoard extends Component {
    static template = "jewellery_evaluator.PriceBoard";
    static props = {};

    setup() {
        this.pos = usePos();
        this.state = useState({ prices: null, failed: false });
        onWillStart(() => this.load());
        onMounted(() => {
            this.timer = setInterval(() => this.load(), REFRESH_MS);
        });
        onWillUnmount(() => clearInterval(this.timer));
    }

    async load() {
        try {
            this.state.prices = await this.pos.data.call(
                "pos.session", "get_jewellery_price_board", []
            );
            this.state.failed = false;
        } catch {
            this.state.failed = true;
        }
    }

    get tiles() {
        const p = this.state.prices || {};
        return [
            { key: "g24", label: "Gold 24K", price: p.gold_24k, unit: "EGP/g", kind: "gold" },
            { key: "g21", label: "Gold 21K", price: p.gold_21k, unit: "EGP/g", kind: "gold" },
            { key: "g18", label: "Gold 18K", price: p.gold_18k, unit: "EGP/g", kind: "gold" },
            { key: "s999", label: "Silver 999", price: p.silver_999, unit: "EGP/g", kind: "silver" },
            { key: "usd", label: "USD", price: p.usd_egp, unit: "EGP", kind: "usd", digits: 2 },
        ];
    }

    format(value, digits = 0) {
        if (!value) {
            return "—";
        }
        return value.toLocaleString("en-US", {
            minimumFractionDigits: digits,
            maximumFractionDigits: digits,
        });
    }
}

patch(ProductScreen, {
    components: { ...ProductScreen.components, PriceBoard },
});
