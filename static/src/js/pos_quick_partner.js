/** @odoo-module **/
// Copyright 2026 Revenax Digital Services
// Author: Mohamed A. Abdallah
// Website: https://www.revenax.com
//
// The register's create / edit customer opens the quick form (Name, Phone,
// Email + "More details"; views/res_partner_quick_views.xml) instead of
// Odoo's full contact form. Same flow as Odoo's PosStore.editPartner.
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { makeActionAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { patch } from "@web/core/utils/patch";

patch(PosStore.prototype, {
    async editPartner(partner) {
        const record = await makeActionAwaitable(
            this.action,
            "jewellery_evaluator.res_partner_action_edit_pos_quick",
            {
                props: { resId: partner?.id },
                additionalContext: this.editPartnerContext(partner),
            }
        );
        const newPartner = await this.data.read("res.partner", record.config.resIds);
        return newPartner[0];
    },
});
