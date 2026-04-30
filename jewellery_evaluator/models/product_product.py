# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

from odoo import api, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.model
    def _load_pos_data_fields(self, config):
        fields = super()._load_pos_data_fields(config)
        jewellery_fields = [
            "jewellery_type",
            "jewellery_weight_g",
            "list_price",
            "silver_purity",
            "gold_min_sale_price",
            "gold_cost_price",
            "silver_min_sale_price",
            "silver_cost_price",
            "gold_weight_g",
            "gold_purity",
            "gold_type",
            "is_gold_product",
            "is_diamond_jewellery_product",
            "is_silver_product",
        ]
        return list(dict.fromkeys([*fields, *jewellery_fields]))
