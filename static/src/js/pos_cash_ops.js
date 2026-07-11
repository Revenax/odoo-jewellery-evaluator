/** @odoo-module **/
// HELD — NOT registered in __manifest__.py point_of_sale._assets_pos yet.
// Touching the POS bundle can blank the register, so this ships only after
// staging verification on a POS copy. To activate: (1) load the Vault-Foreign
// + Owner journals into pos.config via _load_pos_data_read (pos_config.py),
// (2) add this file + pos_cash_ops.xml to the manifest assets, (3) test on a
// staging POS, (4) push in a POS-closed window.
//
// Backend methods are LIVE + verified: pos.session.post_currency_conversion
// and pos.session.post_owner_transfer (models/pos_cash_ops.py).

import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useState } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

// Await a popup that resolves its payload (mirrors askManagerOverride).
function askPopup(dialog, Popup, props) {
    return new Promise((resolve) => {
        dialog.add(
            Popup,
            { ...props, getPayload: resolve },
            { onClose: () => resolve(undefined) },
        );
    });
}

// --- Currency conversion popup: EGP out of Vault -> foreign Vault Foreign ---
export class CurrencyConvertPopup extends Component {
    static template = "jewellery_evaluator.CurrencyConvertPopup";
    static components = { Dialog };
    static props = ["journals", "getPayload", "close?"];
    setup() {
        this.state = useState({
            journalId: this.props.journals[0]?.id,
            amountEgp: 0,
            toAmount: 0,
        });
    }
    confirm() {
        const { journalId, amountEgp, toAmount } = this.state;
        if (journalId && amountEgp > 0 && toAmount > 0) {
            this.props.getPayload({
                journalId,
                amountEgp: parseFloat(amountEgp),
                toAmount: parseFloat(toAmount),
            });
        }
        this.props.close?.();
    }
}

// --- Transfer-to-owner popup: EGP out of Vault -> owner journal ---
export class OwnerTransferPopup extends Component {
    static template = "jewellery_evaluator.OwnerTransferPopup";
    static components = { Dialog };
    static props = ["journals", "getPayload", "close?"];
    setup() {
        this.state = useState({ journalId: this.props.journals[0]?.id, amount: 0 });
    }
    confirm() {
        const { journalId, amount } = this.state;
        if (journalId && amount > 0) {
            this.props.getPayload({ journalId, amount: parseFloat(amount) });
        }
        this.props.close?.();
    }
}

patch(ControlButtons.prototype, {
    // Journals expected on pos.config (loaded via _load_pos_data_read):
    //   this.pos.config.vault_foreign_journal_ids / owner_journal_ids
    get _vaultForeignJournals() {
        return this.pos.config.vault_foreign_journal_ids || [];
    },
    get _ownerJournals() {
        return this.pos.config.owner_journal_ids || [];
    },
    async onClickCurrency() {
        const payload = await askPopup(this.pos.dialog, CurrencyConvertPopup, {
            journals: this._vaultForeignJournals,
        });
        if (!payload) return;
        await this.pos.data.call("pos.session", "post_currency_conversion", [
            this.pos.session.id, payload.amountEgp, payload.journalId, payload.toAmount,
        ]);
        this.pos.notification.add(_t("Currency conversion recorded."), { type: "success" });
    },
    async onClickOwnerTransfer() {
        const payload = await askPopup(this.pos.dialog, OwnerTransferPopup, {
            journals: this._ownerJournals,
        });
        if (!payload) return;
        await this.pos.data.call("pos.session", "post_owner_transfer", [
            this.pos.session.id, payload.journalId, payload.amount,
        ]);
        this.pos.notification.add(_t("Owner transfer recorded."), { type: "success" });
    },
});
