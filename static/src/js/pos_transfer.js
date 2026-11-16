/** @odoo-module **/
/**
 * Copyright 2026 Revenax Digital Services
 * Author: Mohamed A. Abdallah
 * Website: https://www.revenax.com
 *
 * "Transfer" helper (Stock section of the burger menu): move pieces between
 * this register and an owner (OW/*), another branch, or On Memo (OM/Stock),
 * as a real, validated internal transfer. Three steps on the shared
 * HelperDialog:
 *   1. Who: Send / Receive and the other party (+ the person's name for On Memo).
 *      The register's own stock is the other end automatically.
 *   2. Scan: every piece, with photo and details as it is scanned (like the
 *      stock counter). A piece not on hand where it must leave from is refused
 *      with where Odoo has it. Any line can be removed.
 *   3. Confirm: every piece with qty and weights + totals by karat, to match on
 *      the scale; the cashier ticks "weights checked" and confirms.
 * While the window is open it takes the POS barcode reader EXCLUSIVELY, so a
 * scan never lands in the sale order. The server re-checks everything and is
 * idempotent per window (pos_transfer.py).
 */
import { Component, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useBarcodeReader } from "@point_of_sale/app/hooks/barcode_reader_hook";
import { HelperDialog, errMessage, fmtMoney, newIdempotencyKey, posHelpers } from "./pos_helpers";

let audio;
function buzz() {
    try {
        audio = audio || new (window.AudioContext || window.webkitAudioContext)();
        if (audio.state === "suspended") {
            audio.resume();
        }
        const now = audio.currentTime;
        const gain = audio.createGain();
        gain.gain.setValueAtTime(0.25, now);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.45);
        gain.connect(audio.destination);
        for (const freq of [140, 147]) {
            const osc = audio.createOscillator();
            osc.type = "square";
            osc.frequency.setValueAtTime(freq, now);
            osc.connect(gain);
            osc.start(now);
            osc.stop(now + 0.45);
        }
    } catch {
        // No audio: the red message is enough.
    }
}

const KIND_ORDER = ["owner", "branch", "memo"];

export class TransferPopup extends Component {
    static template = "jewellery_evaluator.TransferPopup";
    static components = { HelperDialog };
    static props = { pos: Object, close: Function };

    setup() {
        this.fmtMoney = fmtMoney;
        this.scanRef = useRef("scan");
        this.key = newIdempotencyKey();
        this.lastScan = { code: "", at: 0 };
        this.state = useState({
            status: "loading",
            step: 1,
            here: null,
            parties: [],
            direction: "send",
            partyId: null,
            memoPerson: "",
            pieces: [],
            currentId: null,
            preview: null, // a refused piece shown in the panel
            message: null, // {kind: ok|warn|error, text}
            busy: false,
            error: "",
            weightsChecked: false,
            result: null,
        });
        const onScan = (parsed) => this.scan(parsed?.base_code || parsed?.code);
        useBarcodeReader(
            {
                product: onScan, error: onScan, client: onScan, cashier: onScan,
                weight: onScan, price: onScan, discount: onScan,
            },
            true
        );
        this.loadSetup();
    }

    async loadSetup() {
        try {
            const res = await this.props.pos.data.call("pos.session", "jewellery_transfer_setup", [
                this.props.pos.session.id,
            ]);
            this.state.here = res.here;
            this.state.parties = res.parties;
            this.state.status = res.parties.length ? "ready" : "empty";
        } catch (error) {
            this.state.status = "error";
            this.state.error = errMessage(error, "");
        }
    }

    // ── Step 1 ──────────────────────────────────────────────────────────────
    get groups() {
        const labels = { owner: _t("Owners"), branch: _t("Branches"), memo: _t("On Memo") };
        return KIND_ORDER.map((kind) => ({
            kind,
            label: labels[kind],
            parties: this.state.parties.filter((p) => p.kind === kind),
        })).filter((g) => g.parties.length);
    }
    get party() {
        return this.state.parties.find((p) => p.id === this.state.partyId) || null;
    }
    get isMemo() {
        return this.party?.kind === "memo";
    }
    get partyText() {
        const p = this.party;
        if (!p) {
            return "";
        }
        return this.isMemo && this.state.memoPerson.trim()
            ? `${p.label} · ${this.state.memoPerson.trim()}`
            : p.label;
    }
    get fromText() {
        return this.state.direction === "send" ? this.state.here?.location : this.party?.location;
    }
    get toText() {
        return this.state.direction === "send" ? this.party?.location : this.state.here?.location;
    }
    get step1Ready() {
        return Boolean(this.party) && (!this.isMemo || this.state.memoPerson.trim().length >= 2);
    }
    setDirection(direction) {
        if (direction !== this.state.direction) {
            this.state.direction = direction;
            this.state.pieces = []; // availability depends on the source
            this.state.currentId = null;
        }
    }
    pickParty(id) {
        if (id !== this.state.partyId) {
            this.state.partyId = id;
            this.state.pieces = [];
            this.state.currentId = null;
        }
    }

    // ── Step 2 ──────────────────────────────────────────────────────────────
    get current() {
        return this.state.pieces.find((p) => p.product_id === this.state.currentId) || this.state.preview || null;
    }
    onScanKey(ev) {
        if (ev.key === "Enter") {
            const code = ev.target.value;
            ev.target.value = "";
            this.scan(code);
        }
    }
    async scan(rawCode) {
        const code = (rawCode || "").trim();
        if (this.state.step !== 2 || !code) {
            return;
        }
        // A wedge scanner into the focused field can also fire the barcode
        // service: the same code twice within a second is one scan.
        const now = Date.now();
        if (code === this.lastScan.code && now - this.lastScan.at < 1000) {
            return;
        }
        this.lastScan = { code, at: now };
        let res;
        try {
            res = await this.props.pos.data.call("pos.session", "jewellery_transfer_piece", [
                this.props.pos.session.id, this.state.direction, this.state.partyId, code,
            ]);
        } catch (error) {
            this.flash("error", errMessage(error, _t("Could not check %s.", code)));
            return;
        }
        if (res.status !== "ok") {
            this.state.preview = res.piece ? { ...res.piece, refused: true } : null;
            this.state.currentId = null;
            this.flash("error", res.message);
            return;
        }
        const piece = res.piece;
        const existing = this.state.pieces.find((p) => p.product_id === piece.product_id);
        if (existing) {
            this.state.currentId = existing.product_id;
            if (existing.unique || existing.qty + 1 > piece.available) {
                this.flash("warn", _t("%s is already in this transfer.", piece.sku));
                return;
            }
            existing.qty += 1;
            this.flash("ok", _t("%(sku)s ×%(qty)s", { sku: piece.sku, qty: existing.qty }));
            return;
        }
        this.state.pieces.unshift({ ...piece, qty: 1, scanned_at: new Date().toISOString() });
        this.state.preview = null;
        this.state.currentId = piece.product_id;
        this.flash("ok", _t("%s added.", piece.sku));
    }
    flash(kind, text) {
        this.state.message = { kind, text };
        if (kind !== "ok") {
            buzz();
        }
    }
    select(piece) {
        this.state.preview = null;
        this.state.currentId = piece.product_id;
    }
    remove(piece) {
        this.state.pieces = this.state.pieces.filter((p) => p.product_id !== piece.product_id);
        if (this.state.currentId === piece.product_id) {
            this.state.currentId = this.state.pieces[0]?.product_id || null;
        }
        this.flash("ok", _t("%s removed.", piece.sku));
    }
    focusScan() {
        this.scanRef.el?.focus();
    }

    // ── Step 3 ──────────────────────────────────────────────────────────────
    get totals() {
        const t = { pieces: this.state.pieces.length, units: 0, jewellery: 0, net_gold: 0, stones: 0, reading: 0 };
        for (const p of this.state.pieces) {
            t.units += p.qty;
            t.jewellery += p.qty * (p.jewellery || 0);
            t.net_gold += p.qty * (p.net_gold || 0);
            t.stones += p.qty * (p.stones_g || 0);
            t.reading += p.qty * (p.reading || 0);
        }
        return t;
    }
    get byKarat() {
        const map = {};
        for (const p of this.state.pieces) {
            const k = p.karat || "—";
            map[k] = map[k] || { karat: k, units: 0, jewellery: 0, net_gold: 0 };
            map[k].units += p.qty;
            map[k].jewellery += p.qty * (p.jewellery || 0);
            map[k].net_gold += p.qty * (p.net_gold || 0);
        }
        return Object.values(map).sort((a, b) => String(a.karat).localeCompare(String(b.karat)));
    }
    w(value) {
        return value ? Number(value).toFixed(3) : "—";
    }
    stonesText(piece) {
        return (piece.stones || [])
            .map((s) => `${s.qty}× ${s.shape} ${Number(s.carat).toFixed(3)}ct ${s.color}/${s.clarity}`)
            .join(" · ");
    }

    // ── Navigation ──────────────────────────────────────────────────────────
    next() {
        this.state.error = "";
        if (this.state.step === 1 && this.step1Ready) {
            this.state.step = 2;
            this.state.message = null;
            setTimeout(() => this.focusScan(), 50);
        } else if (this.state.step === 2 && this.state.pieces.length) {
            this.state.step = 3;
        }
    }
    back() {
        this.state.error = "";
        if (this.state.step > 1 && this.state.step < 4) {
            this.state.step -= 1;
            if (this.state.step === 2) {
                setTimeout(() => this.focusScan(), 50);
            }
        }
    }
    async confirm() {
        if (this.state.busy || !this.state.weightsChecked || !this.state.pieces.length) {
            return;
        }
        this.state.busy = true;
        this.state.error = "";
        const pos = this.props.pos;
        try {
            const res = await pos.data.call("pos.session", "jewellery_transfer_create", [
                pos.session.id,
                {
                    direction: this.state.direction,
                    party_id: this.state.partyId,
                    memo_person: this.isMemo ? this.state.memoPerson.trim() : "",
                    weights_checked: this.state.weightsChecked,
                    employee_id: pos.config.module_pos_hr ? pos.cashier?.id : false,
                    cashier_name: pos.cashier?.name || "",
                    lines: this.state.pieces.map((p) => ({
                        product_id: p.product_id, qty: p.qty, scanned_at: p.scanned_at,
                    })),
                },
                this.key,
            ]);
            this.state.result = res;
            this.state.step = 4;
            pos.notification.add(
                res.duplicate ? _t("Already recorded as %s.", res.name) : _t("Transfer %s done.", res.name),
                { type: "success" }
            );
        } catch (error) {
            this.state.error = errMessage(error, _t("The transfer could not be saved."));
        } finally {
            this.state.busy = false;
        }
    }
    startAgain() {
        this.key = newIdempotencyKey();
        Object.assign(this.state, {
            step: 1, pieces: [], currentId: null, preview: null, message: null,
            weightsChecked: false, result: null, error: "", memoPerson: "",
        });
    }
}

posHelpers.add("transfer", {
    section: "stock",
    sequence: 10,
    icon: "fa-truck",
    label: _t("Transfer"),
    isVisible: (nav) => nav.pos.cashier?._role !== "minimal",
    run: (nav) => nav.pos.dialog.add(TransferPopup, { pos: nav.pos }),
});
