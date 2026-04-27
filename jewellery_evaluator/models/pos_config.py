# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    default_to_invoice = fields.Boolean(
        string="Default to Invoice",
        default=False,
        help="Default behaviour for new orders: to invoice.",
    )

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
        for record, pos_config in zip(read_records, pos_configs):
            record["default_to_invoice"] = pos_config.default_to_invoice
            record["require_customer"] = pos_config.require_customer
        return read_records
