# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import json

from odoo import fields, models

from ..utils import sha1_hex
from .pos_cash_ops import owner_journal_domain, vault_foreign_journal_domain


class PosConfig(models.Model):
    _inherit = "pos.config"

    default_to_invoice = fields.Boolean(
        string="Default to Invoice",
        default=False,
        help="Default behaviour for new orders: to invoice.",
    )

    # Below-minimum-price override authorisation, computed per POS load:
    # - uses_pos_hr: when pos_hr is installed, the register authorises with a
    #   manager's employee PIN or badge (already loaded by pos_hr as sha1 hashes).
    # - master_hash: otherwise, the register falls back to a single master PIN,
    #   shipped here as a sha1 hash only (never the plaintext).
    jewellery_override_uses_pos_hr = fields.Boolean(
        compute="_compute_jewellery_override_auth",
    )
    jewellery_override_master_hash = fields.Char(
        compute="_compute_jewellery_override_auth",
    )

    def _compute_jewellery_override_auth(self):
        uses_pos_hr = bool(
            self.env["ir.module.module"].sudo().search_count(
                [("name", "=", "pos_hr"), ("state", "=", "installed")]
            )
        )
        master_pin = (
            self.env["ir.config_parameter"].sudo().get_param(
                "jewellery_evaluator.override_master_pin"
            )
            or ""
        ).strip()
        master_hash = "" if uses_pos_hr else sha1_hex(master_pin)
        for config in self:
            config.jewellery_override_uses_pos_hr = uses_pos_hr
            config.jewellery_override_master_hash = master_hash

    # Cash-ops popups (Currency / Transfer to Owner) need the branch's foreign
    # Vault Foreign journals and the owner journals, shipped to the register as
    # JSON [{"id","name"}] strings (same injected-Char pattern as the override
    # hash above — no relational model to load on the frontend). Detection is
    # convention-based and company-scoped:
    #   * Vault Foreign = cash journals in a NON-company currency (USD/SAR/AED);
    #   * Owner        = cash journals named "Owner …" (Owner - Anas Abbassi, …).
    # Currency popup uses the foreign list; the owner popup's Box select uses
    # jewellery_vault_boxes = the EGP Vault (the config's cash journal, foreign
    # False) plus every Vault Foreign box (foreign True). Each carries its
    # currency code for the read-only rate label.
    jewellery_vault_foreign_journals = fields.Char(
        compute="_compute_jewellery_cash_ops_journals",
    )
    jewellery_owner_journals = fields.Char(
        compute="_compute_jewellery_cash_ops_journals",
    )
    jewellery_vault_boxes = fields.Char(
        compute="_compute_jewellery_cash_ops_journals",
    )

    def _compute_jewellery_cash_ops_journals(self):
        Journal = self.env["account.journal"].sudo()
        for config in self:
            company = config.company_id or self.env.company
            vault_foreign = Journal.search(vault_foreign_journal_domain(company))
            owners = Journal.search(owner_journal_domain(company))
            # EGP Vault = this config's cash payment-method journal (the same
            # journal pos.session.cash_journal_id resolves to, which the backend
            # whitelists as a valid box).
            egp_vault = config.payment_method_ids.filtered(
                lambda m: m.journal_id and m.journal_id.type == "cash"
            ).journal_id[:1]
            foreign_list = [
                {"id": j.id, "name": j.name, "ccy": j.currency_id.name}
                for j in vault_foreign
            ]
            boxes = []
            if egp_vault:
                boxes.append({
                    "id": egp_vault.id, "name": egp_vault.name,
                    "foreign": False, "ccy": company.currency_id.name,
                })
            boxes += [dict(f, foreign=True) for f in foreign_list]
            config.jewellery_vault_foreign_journals = json.dumps(foreign_list)
            config.jewellery_owner_journals = json.dumps(
                [{"id": j.id, "name": j.name} for j in owners]
            )
            config.jewellery_vault_boxes = json.dumps(boxes)

    require_customer = fields.Selection(
        [
            ("no", "Optional"),
            ("payment", "Required before paying"),
            ("order", "Required before starting the order"),
        ],
        string="Require Customer",
        default="no",
        help="Require customer for orders in this point of sale:\n"
        "* 'Optional' (customer is optional);\n"
        "* 'Required before paying';\n"
        "* 'Required before starting the order';",
    )

    def _load_pos_data_read(self, records, config):
        read_records = super()._load_pos_data_read(records, config)
        pos_configs = self.browse([r["id"] for r in read_records])
        for record, pos_config in zip(read_records, pos_configs, strict=True):
            record["default_to_invoice"] = pos_config.default_to_invoice
            record["require_customer"] = pos_config.require_customer
            record["jewellery_override_uses_pos_hr"] = (
                pos_config.jewellery_override_uses_pos_hr
            )
            record["jewellery_override_master_hash"] = (
                pos_config.jewellery_override_master_hash
            )
            record["jewellery_vault_foreign_journals"] = (
                pos_config.jewellery_vault_foreign_journals
            )
            record["jewellery_owner_journals"] = (
                pos_config.jewellery_owner_journals
            )
            record["jewellery_vault_boxes"] = (
                pos_config.jewellery_vault_boxes
            )
        return read_records
