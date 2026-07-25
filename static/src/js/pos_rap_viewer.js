/** @odoo-module **/
/**
 * Copyright 2026 Revenax Digital Services
 * Author: Mohamed A. Abdallah
 * Website: https://www.revenax.com
 *
 * A READ-ONLY Diamond Rapaport price viewer inside the POS register. Adds a
 * "Diamond Rap Prices" item to the Navbar burger menu that opens a full-screen
 * lookup: Round / Exotic tabs, the < 0.25 ct flat tiers as cards, and the
 * >= 0.25 ct grids. Cells show the NET price per carat (list x (1 - discount));
 * type a carat and every cell switches to the TOTAL stone price for that weight
 * — a one-tap pricing tool at the counter. Data comes from the same
 * diamond.rap.price.rap_get RPC the backend editor uses (never writes).
 */
import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { Navbar } from "@point_of_sale/app/components/navbar/navbar";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

export class RapViewerPopup extends Component {
  static template = "jewellery_evaluator.RapViewerPopup";
  static components = { Dialog };
  static props = {
    data: { type: Object },
    close: { type: Function },
  };

  setup() {
    this.state = useState({ sheet: "round", caratInput: "" });
  }

  get structure() {
    return this.props.data.structure || [];
  }

  /** Parsed carat from the input; 0 (falsy) means "show per-carat prices". */
  get carat() {
    const c = parseFloat(this.state.caratInput);
    return c > 0 ? c : 0;
  }

  get unitLabel() {
    return this.carat > 0
      ? _t("total price @ %s ct", this.carat)
      : _t("$ per carat");
  }

  _list(bucket, row, col) {
    const grid = this.props.data[this.state.sheet] || {};
    const v = grid && grid[bucket] && grid[bucket][row] && grid[bucket][row][col];
    return v == null ? null : Number(v);
  }

  _disc(bucket, row, col) {
    const grid = this.props.data[`${this.state.sheet}_disc`] || {};
    const v = grid && grid[bucket] && grid[bucket][row] && grid[bucket][row][col];
    return v == null ? 0 : Number(v);
  }

  /** True when a grid cell carries a discount — used to accent it faintly. */
  hasDiscount(bucket, row, col) {
    return this._disc(bucket, row, col) > 0;
  }

  /** Display text for a >= 0.25 ct grid cell: net $/ct, or total $ if a carat
   *  is entered. Empty when the sheet has no value for this colour/clarity. */
  cellText(bucket, row, col) {
    const list = this._list(bucket, row, col);
    if (list == null) {
      return "";
    }
    const netPerCt = list * 100 * (1 - this._disc(bucket, row, col) / 100);
    return this._money(this.carat > 0 ? netPerCt * this.carat : netPerCt);
  }

  /** Display text for a < 0.25 ct flat tier card. `value` is already $/ct. */
  tierText(value) {
    const perCt = Number(value) || 0;
    return this._money(this.carat > 0 ? perCt * this.carat : perCt);
  }

  _money(v) {
    return `$${Math.round(v).toLocaleString("en-US")}`;
  }

  setSheet(sheet) {
    this.state.sheet = sheet;
  }
}

patch(Navbar.prototype, {
  async onClickRapPrices() {
    let data;
    try {
      data = await this.pos.data.call("diamond.rap.price", "rap_get", []);
    } catch {
      this.pos.notification.add(_t("Could not load Rap prices."), {
        type: "danger",
      });
      return;
    }
    this.pos.dialog.add(RapViewerPopup, { data });
  },
});
