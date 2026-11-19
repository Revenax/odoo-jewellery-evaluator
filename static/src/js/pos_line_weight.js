/** @odoo-module **/
// Copyright 2026 Revenax Digital Services
// Author: Mohamed A. Abdallah
// Website: https://www.revenax.com
//
// Register cart, per line:
//  * the piece's karat and weight under its name (pos_line_weight.xml), so the
//    cashier sees what was scanned without opening the product;
//  * the keypad defaults to PRICE instead of Odoo's QTY (Odoo switches back to
//    QTY on every line selection, and unique pieces are always qty 1, so typing
//    a number silently changed the quantity).
import { Orderline } from "@point_of_sale/app/components/orderline/orderline";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";

const DEFAULT_NUMPAD_MODE = "price";

patch(PosStore.prototype, {
    async setup() {
        await super.setup(...arguments);
        this.numpadMode = DEFAULT_NUMPAD_MODE;
    },
    selectOrderLine(order, line) {
        super.selectOrderLine(order, line);
        this.numpadMode = DEFAULT_NUMPAD_MODE;
    },
});

patch(Orderline.prototype, {
    /** "18K · 2.430 g" (diamond pieces: gross weight + net gold), or "" for
     *  products with no jewellery weight. */
    get jewelleryWeightText() {
        const p = this.props.line?.product_id;
        if (!p) {
            return "";
        }
        const gross = p.gross_jewellery_weight_g || p.jewellery_weight_g || 0;
        if (!gross) {
            return "";
        }
        const karat = p.gold_purity || p.silver_purity || "";
        let text = `${karat ? karat + " · " : ""}${Number(gross).toFixed(3)} g`;
        const net = p.jewellery_weight_g || 0;
        if (p.is_diamond_jewellery_product && net && Math.abs(net - gross) > 0.0005) {
            text += ` · gold ${Number(net).toFixed(3)} g`;
        }
        return text;
    },
});
