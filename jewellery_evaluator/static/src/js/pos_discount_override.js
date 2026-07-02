/** @odoo-module **/
/**
 * Copyright 2026 Revenax Digital Services
 * Author: Mohamed A. Abdallah
 * Website: https://www.revenax.com
 */

import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";
import { ask } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { onMounted } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

/**
 * Override POS discount functionality to enforce jewellery evaluator rules.
 * This prevents discounts that would violate minimum sale price requirements.
 */
patch(PosOrderline.prototype, {
  /**
   * Override set_discount to enforce gold product pricing rules.
   * Discounts are clamped so the price never drops below the minimum sale
   * price (cost + minimum making fee × weight).
   */
  setDiscount(discount) {
    // A refund/return line (negative qty) is not a sale — never clamp it to the
    // minimum sale price (its original price may be below today's higher min).
    if (this.qty < 0) {
      return super.setDiscount(...arguments);
    }
    const product = this.getProduct();
    const isGold = product && product.is_gold_product;
    const isSilver = product && product.is_silver_product;
    if (!product || (!isGold && !isSilver)) {
      return super.setDiscount(...arguments);
    }

    const currentPrice = this.price_unit;
    const minSalePrice = isGold
      ? product.gold_min_sale_price || 0
      : product.silver_min_sale_price || 0;
    // The minimum sale price (cost + minimum making fee × weight) is the single
    // floor. When none is set, fall back to a 20% max discount.
    const effectiveMin = minSalePrice > 0 ? minSalePrice : currentPrice * 0.8;

    const maxDiscountForMin =
      currentPrice > 0
        ? ((currentPrice - effectiveMin) / currentPrice) * 100
        : 0;
    const finalDiscount = Math.max(0, Math.min(discount, maxDiscountForMin));

    if (finalDiscount < discount) {
      this.pos.notification.add(
        _t(
          `Discount for ${
            product.display_name
          } cannot exceed ${finalDiscount.toFixed(
            2,
          )}% to maintain the minimum sale price of ${effectiveMin.toFixed(2)}.`,
        ),
        { type: "warning" },
      );
    }

    return super.setDiscount(finalDiscount);
  },

  /**
   * Override set_unit_price to prevent setting price below minimum.
   */
  setUnitPrice(price) {
    // Refund/return lines (negative qty) bypass the minimum-price floor.
    if (this.qty < 0) {
      return super.setUnitPrice(price);
    }
    const product = this.getProduct();

    if (product && (product.is_gold_product || product.is_silver_product)) {
      const minSalePrice = product.is_gold_product
        ? product.gold_min_sale_price || 0
        : product.silver_min_sale_price || 0;
      const listPrice = product.list_price || price;
      const effectiveMin = minSalePrice > 0 ? minSalePrice : listPrice * 0.8;

      if (effectiveMin > 0 && price < effectiveMin) {
        this.pos.notification.add(
          _t(
            `Price for ${
              product.display_name
            } cannot be below minimum sale price of ${effectiveMin.toFixed(2)}.`,
          ),
          { type: "danger" },
        );
        price = effectiveMin;
      }
    }

    return super.setUnitPrice(price);
  },
});

/**
 * Require customer before payment when pos.config.require_customer === "payment".
 * The current POS validation flow goes through OrderPaymentValidation, not the screen.
 */
patch(OrderPaymentValidation.prototype, {
  async _askForCustomerIfRequired() {
    if (
      this.pos.config.require_customer === "payment" &&
      !this.order.getPartner()
    ) {
      const confirmed = await ask(this.pos.dialog, {
        title: _t("An anonymous order cannot be confirmed"),
        body: _t("Please select a customer for this order."),
      });
      if (confirmed) {
        await this.pos.selectPartner();
      }
      return false;
    }

    return super._askForCustomerIfRequired(...arguments);
  },
});

/**
 * Apply the configured invoicing default to every new POS order.
 */
patch(PosStore.prototype, {
  createNewOrder(data = {}) {
    const order = super.createNewOrder(...arguments);
    if (!("to_invoice" in data) && this.config.default_to_invoice) {
      order.setToInvoice(true);
    }
    return order;
  },
});

/**
 * Override ProductScreen: require customer before order when
 * pos.config.require_customer === "order", and add discount validation for gold.
 */
patch(ProductScreen.prototype, {
  setup() {
    super.setup(...arguments);

    onMounted(async () => {
      const currentOrder = this.pos.getOrder();
      if (
        this.pos.config.require_customer === "order" &&
        currentOrder &&
        !currentOrder.getPartner()
      ) {
        await this.pos.selectPartner(currentOrder);
      }
    });
  },

  /**
   * Override clickDiscount to add validation for gold products.
   */
  async clickDiscount() {
    const order = this.pos.getOrder();
    const selectedLine = order.getSelectedOrderline();

    if (
      selectedLine &&
      selectedLine.getProduct() &&
      (selectedLine.getProduct().is_gold_product ||
        selectedLine.getProduct().is_silver_product)
    ) {
      const product = selectedLine.getProduct();
      const minSalePrice = product.is_gold_product
        ? product.gold_min_sale_price || 0
        : product.silver_min_sale_price || 0;
      const currentPrice = selectedLine.price_unit;
      const effectiveMin = minSalePrice > 0 ? minSalePrice : currentPrice * 0.8;

      if (effectiveMin > 0 && currentPrice > 0) {
        const maxDiscountForMinPrice =
          ((currentPrice - effectiveMin) / currentPrice) * 100;
        if (maxDiscountForMinPrice <= 0) {
          this.pos.notification.add(
            _t(
              `Cannot apply discount to ${product.display_name}. Price is already at minimum.`,
            ),
            { type: "warning" },
          );
          return;
        }
      }
    }

    return super.clickDiscount(...arguments);
  },
});
