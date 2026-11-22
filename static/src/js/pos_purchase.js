/** @odoo-module **/
/**
 * Copyright 2026 Revenax Digital Services
 * Author: Mohamed A. Abdallah
 * Website: https://www.revenax.com
 *
 * "Purchase" helper (Cash section of the burger menu, shared HelperDialog):
 * cash leaves the Vault to someone we buy from.
 *   1. Who: vendors with open Acquisition Orders are listed first; search any
 *      contact by name/phone, or add a new person (name + phone).
 *   2. What: pay one of their AOs (part or all: grams of 21K at a gold price,
 *      plus money for making fee / stones), or buy from them now (rows of
 *      category / karat / grams, one gold price), which creates a "customer"
 *      AO paid in full and puts the gold on hand as SCRAP-GOLD-<karat>.
 *   Every payment picks "Paid from": the register's Vault (default) or a bank
 *   journal; the server re-checks the choice.
 * Backend: pos.session.jewellery_ao_* (models/pos_acquisition.py). Every cash
 * out posts Dr vendor payable / Cr Vault, so the shift count includes it; one
 * idempotency key per window, reused across retries.
 */
import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { HelperDialog, errMessage, fmtNumber, newIdempotencyKey, posHelpers } from "./pos_helpers";

const PURITY = { "24K": 8 / 7, "21K": 1, "18K": 6 / 7 };

function num(value) {
    const n = parseFloat(value);
    return Number.isFinite(n) ? n : 0;
}

export class PurchasePopup extends Component {
    static template = "jewellery_evaluator.PurchasePopup";
    static components = { HelperDialog };
    static props = ["pos", "close"];

    setup() {
        this.key = newIdempotencyKey();
        this.state = useState({
            status: "loading",
            step: "who", // who | what | pay | buy | done
            query: "",
            partners: [],
            partner: null, // {id?, name, phone}
            newName: "",
            newPhone: "",
            showNew: false,
            orders: [],
            order: null,
            payGrams: "",
            payPrice: "",
            payMoney: "",
            lines: [],
            buyPrice: "",
            buyTotal: "",
            note: "",
            journalId: "",
            busy: false,
            error: "",
            result: null,
        });
        this.setupData = { gold_price_21k: 0, categories: [], karats: [], origins: [], journals: [] };
        onWillStart(async () => {
            try {
                const [setup, partners] = await Promise.all([
                    this.call("jewellery_ao_setup", [this.props.pos.session.id]),
                    this.call("jewellery_ao_partners", [""]),
                ]);
                this.setupData = setup;
                const vault = setup.journals.find((j) => j.vault) || setup.journals[0];
                this.state.journalId = vault ? String(vault.id) : "";
                this.state.partners = partners;
                this.state.status = "ready";
            } catch {
                this.state.status = "error";
            }
        });
    }

    call(method, args) {
        return this.props.pos.data.call("pos.session", method, args);
    }
    get employeeId() {
        const pos = this.props.pos;
        return pos.config.module_pos_hr ? pos.cashier?.id || false : false;
    }
    get journalName() {
        const j = this.setupData.journals.find((x) => String(x.id) === String(this.state.journalId));
        return j?.name || _t("the drawer");
    }
    get journalArg() {
        return this.state.journalId ? Number(this.state.journalId) : false;
    }
    fmtG(value) {
        return fmtNumber(value, 3);
    }
    fmtM(value) {
        return fmtNumber(value, 2);
    }

    // ── Step 1: who ─────────────────────────────────────────────────────────
    async search() {
        this.state.error = "";
        try {
            this.state.partners = await this.call("jewellery_ao_partners", [this.state.query]);
        } catch (error) {
            this.state.error = errMessage(error, _t("Search failed."));
        }
    }
    onSearchKey(ev) {
        if (ev.key === "Enter") {
            this.search();
        }
    }
    async pickPartner(partner) {
        this.state.partner = partner;
        this.state.error = "";
        this.state.orders = [];
        if (partner.id) {
            try {
                this.state.orders = await this.call("jewellery_ao_partner_orders", [partner.id]);
            } catch (error) {
                this.state.error = errMessage(error, _t("Could not load their orders."));
            }
        }
        this.state.step = this.state.orders.length ? "what" : "buy";
        if (this.state.step === "buy") {
            this.startBuy();
        }
    }
    pickNewPerson() {
        const name = this.state.newName.trim();
        if (!name) {
            this.state.error = _t("Enter the person's name.");
            return;
        }
        this.pickPartner({ name, phone: this.state.newPhone.trim() });
    }

    // ── Step 2a: pay an AO ──────────────────────────────────────────────────
    startPay(order) {
        // New target, new key; a retry inside this step reuses it.
        this.key = newIdempotencyKey();
        this.state.order = order;
        this.state.payGrams = "";
        this.state.payMoney = "";
        this.state.payPrice = String(this.setupData.gold_price_21k || "");
        this.state.error = "";
        this.state.step = "pay";
    }
    payInFull() {
        const o = this.state.order;
        this.state.payGrams = String(Math.max(o.grams_left, 0));
        this.state.payMoney = String(Math.max(o.money_left, 0));
    }
    get payTotal() {
        return Math.round((num(this.state.payGrams) * num(this.state.payPrice) + num(this.state.payMoney)) * 100) / 100;
    }
    async confirmPay() {
        if (this.state.busy) {
            return;
        }
        const grams = num(this.state.payGrams);
        const price = num(this.state.payPrice);
        const money = num(this.state.payMoney);
        if (grams < 0 || money < 0 || (grams > 0 && price <= 0) || this.payTotal <= 0) {
            this.state.error = _t("Enter grams with a positive gold price, and/or money.");
            return;
        }
        await this.submit("jewellery_ao_pay", [
            this.props.pos.session.id, this.state.order.id, grams, price, money, this.key, this.employeeId,
            this.journalArg,
        ]);
    }

    // ── Step 2b: buy now (customer) ─────────────────────────────────────────
    startBuy() {
        const firstGold = this.setupData.categories.find((c) => c.name.startsWith("Gold /"));
        this.key = newIdempotencyKey();
        this.state.lines = [this.newLine(firstGold?.id)];
        this.state.buyPrice = String(this.setupData.gold_price_21k || "");
        this.state.buyTotal = "";
        this.state.error = "";
        this.state.step = "buy";
    }
    newLine(categId) {
        const last = this.state.lines?.[this.state.lines.length - 1];
        return {
            uid: Math.random().toString(36).slice(2),
            categ_id: categId || last?.categ_id || this.setupData.categories[0]?.id || "",
            karat: last?.karat || "21K",
            origin: last?.origin || "local",
            qty: "1",
            grams: "",
        };
    }
    addLine() {
        this.state.lines.push(this.newLine());
    }
    removeLine(uid) {
        this.state.lines = this.state.lines.filter((l) => l.uid !== uid);
    }
    get buyGrams21() {
        return this.state.lines.reduce(
            (sum, l) => sum + (Math.round(num(l.grams) * 100) / 100) * (PURITY[l.karat] || 0),
            0
        );
    }
    lineAmount(line) {
        return num(line.grams) * (PURITY[line.karat] || 0) * num(this.state.buyPrice);
    }
    karatPrice(karat) {
        return num(this.state.buyPrice) * (PURITY[karat] || 0);
    }
    get buyAmount() {
        return Math.round(this.buyGrams21 * num(this.state.buyPrice) * 100) / 100;
    }
    onBuyTotal() {
        // Typing the total sets the 21K price that gives it.
        const total = num(this.state.buyTotal);
        if (total > 0 && this.buyGrams21 > 0) {
            this.state.buyPrice = String(Math.round((total / this.buyGrams21) * 100) / 100);
        }
    }
    onBuyPrice() {
        this.state.buyTotal = "";
    }
    async confirmBuy() {
        if (this.state.busy) {
            return;
        }
        const lines = this.state.lines
            .filter((l) => num(l.grams) > 0)
            .map((l) => ({
                categ_id: Number(l.categ_id),
                karat: l.karat,
                origin: l.origin,
                qty: Math.max(parseInt(l.qty) || 1, 1),
                grams: Math.round(num(l.grams) * 100) / 100,
            }));
        if (!lines.length || num(this.state.buyPrice) <= 0) {
            this.state.error = _t("Enter the grams of at least one row and a positive gold price.");
            return;
        }
        const p = this.state.partner;
        await this.submit("jewellery_ao_buy", [
            this.props.pos.session.id,
            p.id ? { id: p.id } : { name: p.name, phone: p.phone },
            lines,
            num(this.state.buyPrice),
            this.key,
            this.state.note,
            this.employeeId,
            this.journalArg,
        ]);
    }

    // ── Shared ──────────────────────────────────────────────────────────────
    async submit(method, args) {
        this.state.busy = true;
        this.state.error = "";
        try {
            this.state.result = await this.call(method, args);
            this.state.step = "done";
            this.props.pos.notification.add(
                this.state.result.duplicate
                    ? _t("Already recorded, not paid twice.")
                    : _t("%(amount)s EGP paid from %(from)s (%(order)s).", {
                          amount: this.fmtM(this.state.result.amount),
                          from: this.journalName,
                          order: this.state.result.order.name,
                      }),
                { type: "success" }
            );
        } catch (error) {
            this.state.error = errMessage(error, _t("The payment failed. Nothing was paid."));
        } finally {
            this.state.busy = false;
        }
    }
    back() {
        this.state.error = "";
        if (this.state.step === "pay" || (this.state.step === "buy" && this.state.orders.length)) {
            this.state.step = "what";
        } else {
            this.state.step = "who";
        }
    }
}

posHelpers.add("purchase", {
    section: "cash",
    sequence: 15,
    icon: "fa-shopping-basket",
    label: _t("Purchase"),
    isVisible: (nav) => nav.jewelleryCanMoveCash,
    run(nav) {
        nav.pos.dialog.add(PurchasePopup, { pos: nav.pos });
    },
});
