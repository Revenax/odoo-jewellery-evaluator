# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

from odoo import fields, models

from ..utils import sha1_hex


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
        return read_records
