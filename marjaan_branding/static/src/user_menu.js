/** @odoo-module **/
// Copyright 2026 Revenax Digital Services
// Drop Odoo's own "Help" and "My Odoo.com account" entries from the user menu.
import { registry } from "@web/core/registry";

const items = registry.category("user_menuitems");
for (const key of ["support", "odoo_account"]) {
    if (items.contains(key)) {
        items.remove(key);
    }
}
