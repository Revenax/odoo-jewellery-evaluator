# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

from odoo import _, models

from ..utils import format_carat, format_weight_g


class ProductTemplate(models.Model):
    """Add a `jewellery` block to the POS product-info payload so the
    ProductInfoPopup (Info button / long-press / the dedicated Details button)
    can show weight, purity, category and the per-stone table. Core builds
    get_product_info_pos to be overridden for exactly this."""

    _inherit = "product.template"

    def get_product_info_pos(self, price, quantity, pos_config_id, product_variant_id=False):
        info = super().get_product_info_pos(price, quantity, pos_config_id, product_variant_id)
        info["jewellery"] = self._jewellery_pos_info()
        return info

    def _sel_label(self, field_name, value):
        """Human label for a Selection value on this model (empty if unset)."""
        if not value:
            return ""
        return dict(self._fields[field_name].selection).get(value, value)

    def _jewellery_pos_info(self):
        """Customer-safe jewellery details for the POS popup: no pricing."""
        self.ensure_one()
        jtype = self.jewellery_type
        if not jtype:
            return {"is_jewellery": False}
        is_diamond = jtype == "diamond_jewellery"
        is_silver = jtype == "silver"

        def g(value):
            return "%s g" % format_weight_g(value)

        if is_diamond:
            weights = [
                {"label": _("Gold"), "value": g(self.net_gold_weight_g)},
                {"label": _("Stones"), "value": g(self.diamond_weight_g)},
                {"label": _("Gross"), "value": g(self.gross_jewellery_weight_g)},
            ]
        else:
            net = self.jewellery_weight_g or self.gold_weight_g
            weights = [{"label": _("Weight"), "value": g(net)}]

        purity = (
            self._sel_label("silver_purity", self.silver_purity)
            if is_silver
            else self._sel_label("gold_purity", self.gold_purity)
        )

        stones = []
        if is_diamond:
            Stone = self.env["jewellery.stone"]

            def slabel(fname, value):
                if not value:
                    return ""
                return dict(Stone._fields[fname].selection).get(value, value)

            for s in self.stone_ids:
                stones.append({
                    "carat": format_carat(s.carat),
                    "quantity": s.quantity,
                    "shape": slabel("shape", s.shape),
                    "color": slabel("color", s.color),
                    "clarity": slabel("clarity", s.clarity),
                })

        return {
            "is_jewellery": True,
            "sku": self.default_code or "",
            "category": self.categ_id.complete_name or self.categ_id.name or "",
            "type": self._sel_label("jewellery_type", jtype),
            "purity": purity or "",
            "weights": weights,
            "stones": stones,
        }
