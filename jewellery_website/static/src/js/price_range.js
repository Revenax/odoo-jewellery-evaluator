import multirange from "@website/../lib/multirange/multirange_custom";
import { patch } from "@web/core/utils/patch";

/**
 * The shop's price-range slider always prints two decimals ("3,500.00").
 * Jewellery prices are whole pounds (rounded to 50), so inputs marked
 * data-whole-prices (jewellery_website.filter_products_price_label) print
 * "3,500 EGP" like the product cards.
 */
patch(multirange.Multirange.prototype, {
    formatNumber(number) {
        if (!this.input.dataset.wholePrices) {
            return super.formatNumber(number);
        }
        const lang = (document.documentElement.getAttribute("lang") || "en-US").replaceAll("_", "-");
        const amount = Math.round(number).toLocaleString(lang, { maximumFractionDigits: 0 });
        if (!this.currency.length) {
            return amount;
        }
        return this.currencyPosition === "after" ? `${amount} ${this.currency}` : `${this.currency} ${amount}`;
    },
});
