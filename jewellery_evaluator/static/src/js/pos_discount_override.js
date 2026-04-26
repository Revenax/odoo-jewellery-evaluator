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
   * Maximum discount is limited to 50% of markup value.
   */
  setDiscount(discount) {
    const product = this.getProduct();
    const isGold = product && product.is_gold_product;
    const isSilver = product && product.is_silver_product;
    if (!product || (!isGold && !isSilver)) {
      return super.setDiscount(...arguments);
    }

    const currentPrice = this.price_unit;
    const listPrice = product.list_price || currentPrice;
    const costPrice = isGold
      ? product.gold_cost_price || 0
      : product.silver_cost_price || 0;
    const weight = product.jewellery_weight_g || product.gold_weight_g || 0;
    const minSalePrice = isGold
      ? product.gold_min_sale_price || 0
      : product.silver_min_sale_price || 0;
    // When no minimum sale price is set, assume 20% max discount
    const effectiveMin = minSalePrice > 0 ? minSalePrice : currentPrice * 0.8;

    let maxDiscountPercent = 20;
    if (costPrice > 0 && weight > 0 && listPrice > 0) {
      const markupTotal = listPrice - costPrice;
      maxDiscountPercent = ((markupTotal * 0.5) / listPrice) * 100;
    }
    const clampedDiscount = Math.min(discount, maxDiscountPercent);
    let finalPrice = currentPrice * (1 - clampedDiscount / 100.0);

    if (finalPrice < effectiveMin) {
      const maxDiscountForMinPrice =
        currentPrice > 0
          ? ((currentPrice - effectiveMin) / currentPrice) * 100
          : 0;
      const finalDiscount = Math.max(
        0,
        Math.min(clampedDiscount, maxDiscountForMinPrice),
      );

      if (finalDiscount < discount) {
        this.pos.notification.add(
          _t(
            `Discount for ${
              product.display_name
            } cannot exceed ${finalDiscount.toFixed(
              2,
            )}% to maintain minimum sale price of ${effectiveMin.toFixed(2)}.`,
          ),
          { type: "warning" },
        );
      }

      return super.setDiscount(finalDiscount);
    }

    if (clampedDiscount < discount) {
      this.pos.notification.add(
        _t(
          `Maximum discount for ${product.display_name} is ${maxDiscountPercent.toFixed(2)}%.`,
        ),
        { type: "warning" },
      );
    }

    return super.setDiscount(clampedDiscount);
  },

  /**
   * Override set_unit_price to prevent setting price below minimum.
   */
  setUnitPrice(price) {
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
      const listPrice = product.list_price || currentPrice;
      const costPrice = product.is_gold_product
        ? product.gold_cost_price || 0
        : product.silver_cost_price || 0;
      const effectiveMin = minSalePrice > 0 ? minSalePrice : currentPrice * 0.8;

      if (effectiveMin > 0 && currentPrice > 0) {
        let maxDiscountPercent = 20;
        if (costPrice > 0 && listPrice > 0) {
          const markupTotal = listPrice - costPrice;
          maxDiscountPercent = ((markupTotal * 0.5) / listPrice) * 100;
        }
        const maxDiscountForMinPrice =
          ((currentPrice - effectiveMin) / currentPrice) * 100;
        const actualMaxDiscount = Math.min(
          maxDiscountPercent,
          maxDiscountForMinPrice,
        );

        if (actualMaxDiscount <= 0) {
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
