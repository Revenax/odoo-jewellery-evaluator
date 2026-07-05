/** @odoo-module **/
/* global Sha1 */
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
import { Component, onMounted, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

// Entries this length or shorter are tried as an employee PIN first; longer
// entries are treated as a scanned badge first. Either way both are attempted,
// so a mis-sized value still authorises.
const PIN_MAX_LEN = 8;

/**
 * Show the manager PIN/badge dialog and resolve with {approverId, approverName}
 * when a valid PIN or badge is entered, or undefined if cancelled. Implemented
 * directly on the dialog service so it does not depend on makeAwaitable's export.
 */
function askManagerOverride(dialog, props) {
  return new Promise((resolve) => {
    dialog.add(
      ManagerOverridePopup,
      { ...props, getPayload: resolve },
      { onClose: () => resolve(undefined) },
    );
  });
}

/**
 * PIN/badge popup that authorises selling a jewellery line below its minimum
 * sale price. When pos_hr is on, it matches the entry (via the POS Sha1.hash)
 * against the loaded manager employees' PIN and badge hashes; otherwise it
 * matches a single master override PIN hash. All hashes are compared offline —
 * the register needs no network.
 */
export class ManagerOverridePopup extends Component {
  static template = "jewellery_evaluator.ManagerOverridePopup";
  static components = { Dialog };
  static props = {
    productName: { type: String, optional: true },
    floor: { type: Number, optional: true },
    usesPosHr: { type: Boolean, optional: true },
    managers: { type: Array, optional: true },
    masterHash: { type: String, optional: true },
    getPayload: { type: Function },
    close: { type: Function },
  };
  static defaultProps = {
    productName: "",
    floor: 0,
    usesPosHr: false,
    managers: [],
    masterHash: "",
  };

  setup() {
    this.state = useState({ pin: "", error: "" });
  }

  get title() {
    return _t("Manager Approval");
  }

  get floorLabel() {
    return Number(this.props.floor || 0).toFixed(2);
  }

  onKeydown(ev) {
    if (ev.key === "Enter") {
      this.confirm();
    }
  }

  confirm() {
    const entry = (this.state.pin || "").trim();
    if (!entry) {
      this.state.error = _t("Enter a PIN or scan a badge.");
      return;
    }
    let hash;
    try {
      hash = Sha1.hash(entry);
    } catch {
      this.state.error = _t("Could not verify on this device.");
      return;
    }

    if (this.props.usesPosHr) {
      const managers = this.props.managers || [];
      const byPin = managers.find((m) => m.pin && m.pin === hash);
      const byBadge = managers.find((m) => m.barcode && m.barcode === hash);
      // Short entry → PIN first; longer entry → badge first. Both are attempted.
      const approver =
        entry.length <= PIN_MAX_LEN ? byPin || byBadge : byBadge || byPin;
      if (approver) {
        this.props.getPayload({
          approverId: approver.id,
          approverName: approver.name,
        });
        this.props.close();
      } else {
        this.state.error = _t("PIN or badge not recognised, or not a manager.");
        this.state.pin = "";
      }
      return;
    }

    // Fallback: pos_hr is off — a single master override PIN.
    if (this.props.masterHash && hash === this.props.masterHash) {
      this.props.getPayload({ approverId: 0, approverName: _t("Override PIN") });
      this.props.close();
    } else {
      this.state.error = _t("Incorrect override PIN.");
      this.state.pin = "";
    }
  }

  cancel() {
    this.props.close();
  }
}

/**
 * Override POS discount/price to enforce jewellery evaluator minimum sale prices.
 *
 * A cashier attempting a sub-floor price/discount is clamped to the floor by
 * default; a manager PIN or badge (verified offline) approves that one line and
 * lifts the floor for it. The approval is carried to the backend on the line for
 * audit and re-verification (see models/pos_order.py).
 */
patch(PosOrderline.prototype, {
  /** Minimum sale price for this line, with the legacy 20% fallback. */
  _jewelleryPriceFloor(fallbackPrice) {
    const product = this.getProduct();
    if (!product) {
      return 0;
    }
    const minSalePrice = product.is_gold_product
      ? product.gold_min_sale_price || 0
      : product.silver_min_sale_price || 0;
    const listPrice = product.list_price || fallbackPrice;
    return minSalePrice > 0 ? minSalePrice : listPrice * 0.8;
  },

  /**
   * Pop the manager PIN/badge dialog. On approval, set the audit fields on the
   * line and resolve true; on cancel/invalid, resolve false. Re-entrancy guarded
   * so a single below-floor edit cannot open two dialogs.
   */
  async _promptMinPriceOverride(effectiveMin) {
    if (this._overridePromptOpen) {
      return false;
    }
    this._overridePromptOpen = true;
    try {
      const usesPosHr = !!this.pos.config.jewellery_override_uses_pos_hr;
      let managers = [];
      if (usesPosHr && this.pos.models["hr.employee"]) {
        managers = this.pos.models["hr.employee"]
          .filter((e) => e._role === "manager")
          .map((e) => ({
            id: e.id,
            name: e.name,
            pin: e._pin,
            barcode: e._barcode,
          }));
      }
      const masterHash = this.pos.config.jewellery_override_master_hash || "";
      const product = this.getProduct();
      const payload = await askManagerOverride(this.pos.dialog, {
        productName: product ? product.display_name : "",
        floor: effectiveMin,
        usesPosHr,
        managers,
        masterHash,
      });
      if (payload && payload.approverId !== undefined) {
        this.min_price_override = true;
        this.override_approver_uid = payload.approverId;
        this.override_approver_name = payload.approverName;
        this.override_original_min = effectiveMin;
        this.pos.notification.add(
          _t("Below-minimum price approved by %s.", payload.approverName),
          { type: "success" },
        );
        return true;
      }
      return false;
    } finally {
      this._overridePromptOpen = false;
    }
  },

  /**
   * Override set_discount to enforce gold/silver minimum sale prices. A discount
   * that would drop the line below its floor is clamped, then a manager PIN/badge
   * can approve the requested discount for that line.
   */
  setDiscount(discount) {
    // A refund/return line (negative qty) is not a sale — never clamp it.
    if (this.qty < 0) {
      return super.setDiscount(...arguments);
    }
    const product = this.getProduct();
    const isGold = product && product.is_gold_product;
    const isSilver = product && product.is_silver_product;
    if (!product || (!isGold && !isSilver)) {
      return super.setDiscount(...arguments);
    }
    // Manager-approved line: the floor is lifted, apply as requested.
    if (this.min_price_override) {
      return super.setDiscount(discount);
    }

    const currentPrice = this.price_unit;
    const minSalePrice = isGold
      ? product.gold_min_sale_price || 0
      : product.silver_min_sale_price || 0;
    const effectiveMin = minSalePrice > 0 ? minSalePrice : currentPrice * 0.8;

    const maxDiscountForMin =
      currentPrice > 0
        ? ((currentPrice - effectiveMin) / currentPrice) * 100
        : 0;
    const finalDiscount = Math.max(0, Math.min(discount, maxDiscountForMin));

    if (finalDiscount < discount) {
      // Clamp now (safe default), then offer manager override for the requested
      // discount.
      const desired = discount;
      const clamped = super.setDiscount(finalDiscount);
      this._promptMinPriceOverride(effectiveMin).then((approved) => {
        if (approved) {
          // Re-enter: min_price_override is now set, so this applies as requested.
          this.setDiscount(desired);
        }
      });
      return clamped;
    }

    return super.setDiscount(finalDiscount);
  },

  /**
   * Override set_unit_price to enforce the minimum sale price. A sub-floor price
   * is clamped to the floor, then a manager PIN/badge can approve the requested
   * price.
   */
  setUnitPrice(price) {
    // Refund/return lines (negative qty) bypass the minimum-price floor.
    if (this.qty < 0) {
      return super.setUnitPrice(price);
    }
    const product = this.getProduct();
    if (!product || (!product.is_gold_product && !product.is_silver_product)) {
      return super.setUnitPrice(price);
    }
    // Manager-approved line: the floor is lifted, apply as requested.
    if (this.min_price_override) {
      return super.setUnitPrice(price);
    }

    const effectiveMin = this._jewelleryPriceFloor(price);
    if (effectiveMin > 0 && price < effectiveMin) {
      // Clamp now (safe default), then offer manager override for the requested
      // price.
      const desired = price;
      const clamped = super.setUnitPrice(effectiveMin);
      this._promptMinPriceOverride(effectiveMin).then((approved) => {
        if (approved) {
          // Re-enter: min_price_override is now set, so this applies as requested.
          this.setUnitPrice(desired);
        }
      });
      return clamped;
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
 * pos.config.require_customer === "order".
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
});
