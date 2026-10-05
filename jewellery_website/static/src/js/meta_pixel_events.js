/**
 * Forward the shop's own ecommerce events to the Meta pixel.
 *
 * Odoo already raises these for Google Analytics: `view_item_event` on the
 * product page, `add_to_cart_event` from the cart service, and the purchase
 * payload on the order confirmation page. Listening in the capture phase
 * catches them whatever element dispatches them (they do not bubble) and
 * whenever the shop's own scripts start. When the visitor has not accepted
 * optional cookies the pixel is not loaded and every call here is a no-op.
 */
(function () {
    "use strict";

    function track(eventName, params, options) {
        if (window.fbq) {
            window.fbq("track", eventName, params, options || {});
        }
    }

    function contentParams(items, currency, value) {
        return {
            content_type: "product",
            content_ids: items.map((item) => String(item.item_id)),
            content_name: items.map((item) => item.item_name).join(", "),
            currency: currency,
            value: value,
        };
    }

    document.addEventListener("view_item_event", (ev) => {
        const item = ev.detail || {};
        track("ViewContent", contentParams([item], item.currency, item.price));
    }, true);

    document.addEventListener("add_to_cart_event", (ev) => {
        const items = ev.detail || [];
        if (!items.length) {
            return;
        }
        const value = items.reduce((sum, item) => sum + item.price * (item.quantity || 1), 0);
        track("AddToCart", contentParams(items, items[0].currency, value));
    }, true);

    document.addEventListener("click", (ev) => {
        if (ev.target.closest && ev.target.closest('a[href^="/shop/checkout"]')) {
            track("InitiateCheckout", {});
        }
    }, true);

    function trackPurchase() {
        const el = document.querySelector('div[name="order_confirmation"]');
        if (!el || !el.dataset.orderTrackingInfo) {
            return;
        }
        const order = JSON.parse(el.dataset.orderTrackingInfo);
        // eventID lets Meta drop the repeat when the confirmation page is reloaded.
        track(
            "Purchase",
            contentParams(order.items || [], order.currency, order.value),
            { eventID: "order-" + order.transaction_id }
        );
    }

    // The pixel may load before this file runs or only after the visitor
    // accepts cookies on the confirmation page; cover both.
    document.addEventListener("jewelleryMetaPixelLoaded", trackPurchase);
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", trackPurchase);
    } else {
        trackPurchase();
    }
})();
