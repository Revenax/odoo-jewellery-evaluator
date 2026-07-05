/** @odoo-module **/
/* global Sha1 */
/**
 * Copyright 2026 Revenax Digital Services
 * Author: Mohamed A. Abdallah
 * Website: https://www.revenax.com
 */

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { Orderline } from "@point_of_sale/app/components/orderline/orderline";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";
import { ask } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { Component, onMounted, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

// Entries this length or shorter are tried as an employee PIN first; longer
// entries are treated as a scanned badge first. Either way both are attempted.
const PIN_MAX_LEN = 8;

/**
 * Show the manager PIN/badge dialog and resolve with {approverId, approverName}
 * when a valid PIN or badge is entered, or undefined if cancelled.
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
 * Gather the authorised approvers for this POS and prompt for a PIN/badge.
 * Returns {approverId, approverName} on success, or null on cancel/invalid.
 * With pos_hr: matches loaded manager employees' PIN/badge hashes; otherwise a
 * single master override PIN hash. All matching is offline (POS Sha1.hash).
 */
async function promptManagerOverride(pos, props) {
  const usesPosHr = !!pos.config.jewellery_override_uses_pos_hr;
  let managers = [];
  if (usesPosHr && pos.models["hr.employee"]) {
    managers = pos.models["hr.employee"]
      .filter((e) => e._role === "manager")
      .map((e) => ({ id: e.id, name: e.name, pin: e._pin, barcode: e._barcode }));
  }
  const masterHash = pos.config.jewellery_override_master_hash || "";
  const payload = await askManagerOverride(pos.dialog, {
    productName: props.productName,
    floor: props.floor,
    usesPosHr,
    managers,
    masterHash,
  });
  return payload && payload.approverId !== undefined ? payload : null;
}

/**
 * The minimum sale price (floor) for a line, with the legacy 20% fallback.
 * Returns 0 for non-jewellery lines (no floor).
 */
function jewelleryFloor(product, priceUnit) {
  if (!product || (!product.is_gold_product && !product.is_silver_product)) {
    return 0;
  }
  const minSalePrice = product.is_gold_product
    ? product.gold_min_sale_price || 0
    : product.silver_min_sale_price || 0;
  const listPrice = product.list_price || priceUnit || 0;
  return minSalePrice > 0 ? minSalePrice : listPrice * 0.8;
}

/**
 * Gate an order's below-minimum lines behind a single manager approval.
 * Returns true when nothing is below-min or approval is granted (flags stamped
 * on the below-min lines); false (caller should abort) when refused/cancelled.
 * Editing a price never triggers this — it runs once, when the cashier pays.
 */
async function ensureMinPriceApproval(pos, order) {
  const lines = (order.getOrderlines ? order.getOrderlines() : order.lines) || [];
  const belowMin = [];
  let firstName = "";
  let firstFloor = 0;
  for (const line of lines) {
    if (line.min_price_override) {
      continue; // already approved
    }
    const qty = line.getQuantity ? line.getQuantity() : line.qty;
    if (qty < 0) {
      continue; // refund/return line — the floor is for sales only
    }
    const product = line.getProduct && line.getProduct();
    const floor = jewelleryFloor(product, line.price_unit);
    if (floor <= 0) {
      continue;
    }
    const finalPrice = (line.price_unit || 0) * (1 - (line.discount || 0) / 100);
    if (finalPrice < floor) {
      belowMin.push({ line, floor });
      if (!firstName) {
        firstName = product.display_name;
        firstFloor = floor;
      }
    }
  }

  if (belowMin.length === 0) {
    return true;
  }

  const label =
    belowMin.length > 1 ? `${firstName} (+${belowMin.length - 1} more)` : firstName;
  const approved = await promptManagerOverride(pos, {
    productName: label,
    floor: firstFloor,
  });
  if (!approved) {
    pos.notification.add(
      _t("Manager approval is required to sell below the minimum price."),
      { type: "warning" },
    );
    return false;
  }
  for (const { line, floor } of belowMin) {
    line.min_price_override = true;
    line.override_approver_uid = approved.approverId;
    line.override_approver_name = approved.approverName;
    line.override_original_min = floor;
  }
  return true;
}

/**
 * PIN/badge popup that authorises selling below the minimum sale price.
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
 * Gate below-minimum sales at the "Pay" button (entering the payment screen),
 * and apply the configured invoicing default to new orders. Editing a price
 * never prompts or validates; the manager PIN/badge is asked once, on Pay.
 */
patch(PosStore.prototype, {
  async pay() {
    const order = this.getOrder();
    if (order && !(await ensureMinPriceApproval(this, order))) {
      return; // below-min approval refused — stay on the product screen
    }
    return super.pay(...arguments);
  },

  createNewOrder(data = {}) {
    const order = super.createNewOrder(...arguments);
    if (!("to_invoice" in data) && this.config.default_to_invoice) {
      order.setToInvoice(true);
    }
    return order;
  },
});

/**
 * Require customer before payment when pos.config.require_customer === "payment".
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
 * Highlight an order line's price in yellow while it is below its minimum sale
 * price (and not yet manager-approved), so the cashier sees before paying that
 * the Pay step will ask for a manager. Cleared once approved.
 */
patch(Orderline.prototype, {
  get isBelowMinimum() {
    if (this.props.mode !== "display") {
      return false;
    }
    const line = this.line;
    if (!line || line.min_price_override) {
      return false;
    }
    const qty = line.getQuantity ? line.getQuantity() : line.qty;
    if (qty < 0) {
      return false;
    }
    const product = line.getProduct && line.getProduct();
    const floor = jewelleryFloor(product, line.price_unit);
    if (floor <= 0) {
      return false;
    }
    const finalPrice = (line.price_unit || 0) * (1 - (line.discount || 0) / 100);
    return finalPrice < floor;
  },
});

/**
 * Require customer before order when pos.config.require_customer === "order".
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
