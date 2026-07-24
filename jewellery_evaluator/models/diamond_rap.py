# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import json

from odoo import _, api, models
from odoo.exceptions import UserError

# The Rapaport grid layout, mirroring the printed sheet. Two table formats:
#   * grouped  — the 0.23-0.29 bucket (colour groups DF..MN, clarity IF-VVS/VS/…)
#   * full     — 0.30 ct and up (colours D..M, full clarity columns)
# The editor renders one <table> per bucket in its native format; the lookup in
# utils.py (rap_keys) maps a stone's colour/clarity onto these same keys.
_GROUPED_COLS = ["IF-VVS", "VS", "SI1", "SI2", "SI3", "I1", "I2", "I3"]
_GROUPED_ROWS = ["DF", "GH", "IJ", "KL", "MN"]
_FULL_COLS = ["IF", "VVS1", "VVS2", "VS1", "VS2", "SI1", "SI2", "SI3", "I1", "I2", "I3"]
_FULL_ROWS = ["D", "E", "F", "G", "H", "I", "J", "K", "L", "M"]

# Ordered buckets shown in the editor (>= 0.25 ct only; below that uses tiers).
RAP_STRUCTURE = [
    {"bucket": "0.23-0.29", "grouped": True},
    {"bucket": "0.30-0.39", "grouped": False},
    {"bucket": "0.40-0.49", "grouped": False},
    {"bucket": "0.50-0.69", "grouped": False},
    {"bucket": "0.70-0.89", "grouped": False},
    {"bucket": "0.90-0.99", "grouped": False},
    {"bucket": "1.00-1.49", "grouped": False},
    {"bucket": "1.50-1.99", "grouped": False},
    {"bucket": "2.00-2.99", "grouped": False},
    {"bucket": "3.00-3.99", "grouped": False},
    {"bucket": "4.00-4.99", "grouped": False},
    {"bucket": "5.00-5.99", "grouped": False},
    {"bucket": "10.00-10.99", "grouped": False},
]


def _structure_payload():
    """Buckets with their row/col keys — drives the editor's table rendering."""
    out = []
    for s in RAP_STRUCTURE:
        out.append({
            "bucket": s["bucket"],
            "grouped": s["grouped"],
            "rows": _GROUPED_ROWS if s["grouped"] else _FULL_ROWS,
            "cols": _GROUPED_COLS if s["grouped"] else _FULL_COLS,
        })
    return out


class DiamondRapPrice(models.AbstractModel):
    """Read/write the two Rapaport price grids (config-param JSON) for the
    'Diamond Rap Prices' settings page. No table — just RPC endpoints."""

    _name = "diamond.rap.price"
    _description = "Diamond Rapaport Price Grid"

    def _icp(self):
        return self.env["ir.config_parameter"].sudo()

    def _load(self, sheet, suffix=""):
        raw = self._icp().get_param(f"jewellery_evaluator.diamond_rap_{sheet}{suffix}")
        try:
            data = json.loads(raw or "{}")
            return data if isinstance(data, dict) else {}
        except (TypeError, ValueError):
            return {}

    @api.model
    def rap_get(self):
        return {
            "round": self._load("round"),
            "exotic": self._load("exotic"),
            "round_disc": self._load("round", "_disc"),
            "exotic_disc": self._load("exotic", "_disc"),
            "structure": _structure_payload(),
        }

    def _clean_grid(self, grid, clamp_max=None):
        """Whitelist buckets/rows/cols against the structure; keep numeric cells
        only (blank/zero dropped). For the discount grid, ``clamp_max=100`` bounds
        each percent to 0..100."""
        valid = {s["bucket"]: s for s in _structure_payload()}
        clean = {}
        for bucket, rows in (grid or {}).items():
            spec = valid.get(bucket)
            if not spec or not isinstance(rows, dict):
                continue
            row_keys, col_keys = set(spec["rows"]), set(spec["cols"])
            cb = {}
            for r, cols in rows.items():
                if r not in row_keys or not isinstance(cols, dict):
                    continue
                cc = {}
                for c, val in cols.items():
                    if c not in col_keys:
                        continue
                    try:
                        num = float(val)
                    except (TypeError, ValueError):
                        continue
                    if clamp_max is not None:
                        num = max(0.0, min(clamp_max, num))
                    if num > 0:
                        cc[c] = num
                if cc:
                    cb[r] = cc
            if cb:
                clean[bucket] = cb
        return clean

    @api.model
    def rap_set(self, sheet, grid, disc=None):
        if sheet not in ("round", "exotic"):
            raise UserError(_("Unknown Rap sheet %s.") % sheet)
        self._icp().set_param(
            f"jewellery_evaluator.diamond_rap_{sheet}", json.dumps(self._clean_grid(grid))
        )
        if disc is not None:
            self._icp().set_param(
                f"jewellery_evaluator.diamond_rap_{sheet}_disc",
                json.dumps(self._clean_grid(disc, clamp_max=100.0)),
            )
        # Recompute stones so prices reflect the new grid/discount immediately (the
        # stored compute cannot @api.depends on a config param). Diamond product
        # prices depend on stone totals, so they cascade.
        stones = self.env["jewellery.stone"].sudo().search([])
        if stones:
            stones._compute_unit_price_usd()
        return True
