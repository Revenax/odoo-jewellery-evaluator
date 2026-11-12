/** @odoo-module **/
// Copyright 2026 Revenax Digital Services
// Browser tab titles: "<page> · Marjaan", or just "Marjaan" (Odoo's default is "Odoo").
import { registry } from "@web/core/registry";

const BRAND = "Marjaan";

export const marjaanTitleService = {
    start() {
        const titleCounters = {};
        const titleParts = {};

        function updateTitle() {
            const counter = Object.values(titleCounters).reduce((acc, count) => acc + count, 0);
            const page = Object.values(titleParts).join(" - ");
            const name = page ? `${page} · ${BRAND}` : BRAND;
            document.title = counter ? `(${counter}) ${name}` : name;
        }

        function apply(target, values) {
            for (const key in values) {
                if (values[key]) {
                    target[key] = values[key];
                } else {
                    delete target[key];
                }
            }
            updateTitle();
        }

        return {
            get current() {
                return document.title;
            },
            getParts: () => Object.assign({}, titleParts),
            setCounters: (counters) => apply(titleCounters, counters),
            setParts: (parts) => apply(titleParts, parts),
        };
    },
};

registry.category("services").add("title", marjaanTitleService, { force: true });
