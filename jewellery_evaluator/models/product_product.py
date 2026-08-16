# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import logging

from odoo import api, fields, models

from .. import pulse
from ..utils import is_serial_sku

_logger = logging.getLogger(__name__)


class ProductProduct(models.Model):
    _inherit = "product.product"

    # A unique jewellery piece = a single physical item with a serial SKU
    # (PREFIX-NNNN, optional A/B twin). Its on-hand is 0 or 1: the POS hides it
    # once sold and blocks re-selling it. Fungible weight/scrap SKUs are never
    # unique pieces. Stored + indexed so it can gate the POS product-load domain.
    is_unique_jewellery_piece = fields.Boolean(
        string="Unique Jewellery Piece",
        compute="_compute_is_unique_jewellery_piece",
        store=True,
        index=True,
        help="A single physical piece with a serial SKU (PREFIX-NNNN). On-hand "
             "is 0 or 1; the POS hides it when sold and blocks re-sale. Fungible "
             "weight/scrap SKUs are not unique pieces.",
    )

    @api.depends("default_code", "product_tmpl_id.jewellery_type")
    def _compute_is_unique_jewellery_piece(self):
        for product in self:
            product.is_unique_jewellery_piece = bool(
                product.product_tmpl_id.jewellery_type
            ) and is_serial_sku(product.default_code)

    @api.model
    def _load_pos_data_domain(self, data, config):
        domain = super()._load_pos_data_domain(data, config)
        # Hide already-sold unique pieces (serial SKU, stock-tracked, on-hand < 1)
        # from the register: a sold unique piece with no stock invites a
        # double-sale. Show it when it is not a unique piece, or does not track
        # stock at all (a non-storable consu can't be "sold out"), or still has
        # on-hand — so only genuinely-sold stock-tracked pieces disappear.
        return list(domain) + [
            "|", "|",
            ("is_unique_jewellery_piece", "=", False),
            ("is_storable", "=", False),
            ("qty_available", ">", 0),
        ]

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
            "diamond_min_sale_price",
            "gold_weight_g",
            "gold_purity",
            "gold_type",
            "is_gold_product",
            "is_diamond_jewellery_product",
            "is_silver_product",
            "is_unique_jewellery_piece",
        ]
        return list(dict.fromkeys([*fields, *jewellery_fields]))

    @api.model
    def _cron_check_unique_onhand(self):
        """Non-destructive watchdog for the unique-piece 0/1 on-hand invariant.

        Logs (loudly) any unique piece whose on-hand exceeds 1 so a human can
        investigate. It deliberately does NOT auto-clamp: a mis-flagged product
        could otherwise have legitimately-stacked stock silently destroyed.
        """
        pieces = self.search([("is_unique_jewellery_piece", "=", True)])
        bad = pieces.filtered(lambda p: p.qty_available > 1)
        if bad:
            details = ", ".join(
                f"{p.default_code or p.display_name}={p.qty_available}"
                for p in bad
            )
            _logger.warning(
                "jewellery_evaluator: %s unique piece(s) exceed the 0/1 on-hand "
                "invariant (on-hand > 1): %s", len(bad), details
            )
            # A one-of-a-kind piece showing 2+ on hand means either a bad stock
            # adjustment or the same piece registered twice — both let it be
            # sold more than once, so a human needs to look.
            pulse.notify(
                'suspicious-activity',
                'Unique piece stock invariant broken',
                f'{len(bad)} unique piece(s) have more than 1 on hand: '
                f'{details[:400]}',
                {'count': len(bad),
                 'skus': [p.default_code for p in bad if p.default_code][:20]},
                pulse.make_idempotency_key(
                    'unique-onhand', ','.join(sorted(str(p.id) for p in bad))),
                env=self.env,
            )
        return True
