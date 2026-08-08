/** @odoo-module **/
/**
 * Copyright 2026 Revenax Digital Services
 * Author: Mohamed A. Abdallah
 * Website: https://www.revenax.com
 *
 * اليومية — the Daily Ledger inside the POS register, laid out like the paper
 * book the shop actually keeps: إفتتاح / إقفال in the header, then one row per
 * movement carrying BOTH money (وارد / منصرف) and gold weight (جرام / مللي),
 * with فئة / بيان / مصدر / ملاحظات.
 *
 * Read-only. Scoped to THIS register by default (what the cashier's own book
 * covers) with a toggle for the whole company. Data comes from
 * jewellery.ledger.ledger_rows; nothing is ever written.
 */
import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { Navbar } from "@point_of_sale/app/components/navbar/navbar";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

function localISO(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate()
  ).padStart(2, "0")}`;
}

export class LedgerPopup extends Component {
  static template = "jewellery_evaluator.LedgerPopup";
  static components = { Dialog };
  static props = {
    pos: { type: Object },
    close: { type: Function },
  };

  setup() {
    this.state = useState({
      loading: true,
      failed: false,
      date: localISO(new Date()),
      thisRegisterOnly: true,
      data: null,
    });
    onWillStart(() => this.load());
  }

  async load() {
    this.state.loading = true;
    try {
      const configId = this.state.thisRegisterOnly
        ? this.props.pos.config.id
        : false;
      this.state.data = await this.props.pos.data.call(
        "jewellery.ledger",
        "ledger_rows",
        [this.state.date, configId]
      );
      this.state.failed = false;
    } catch {
      this.state.failed = true;
    } finally {
      this.state.loading = false;
    }
  }

  setDate(value) {
    if (value) {
      this.state.date = value;
      this.load();
    }
  }

  shiftDay(delta) {
    const d = new Date(this.state.date + "T12:00:00");
    d.setDate(d.getDate() + delta);
    this.setDate(localISO(d));
  }

  toggleScope() {
    this.state.thisRegisterOnly = !this.state.thisRegisterOnly;
    this.load();
  }

  /** Money: grouped, no decimals — the book never writes piastres. */
  fmt(value) {
    if (!value) {
      return "";
    }
    return Math.round(value).toLocaleString("en-US");
  }

  /** Weight cells stay blank rather than printing 0, as in the book. */
  fmtCell(value) {
    return value ? String(value) : "";
  }

  print() {
    window.print();
  }
}

patch(Navbar.prototype, {
  async onClickDailyLedger() {
    this.pos.dialog.add(LedgerPopup, { pos: this.pos });
  },
});
