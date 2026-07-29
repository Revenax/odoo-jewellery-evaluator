# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import json
import logging

from odoo import _, api, models
from odoo.exceptions import UserError

from ..utils import _STONE_TIERS

_logger = logging.getLogger(__name__)

# The Rapaport grid layout, mirroring the printed sheet. Two table formats:
#   * grouped  — the 0.23-0.29 bucket (colour groups DF..MN, clarity IF-VVS/VS/…)
#   * full     — 0.30 ct and up (colours D..M, full clarity columns)
# The editor renders one <table> per bucket in its native format; the lookup in
# utils.py (rap_keys) maps a stone's colour/clarity onto these same keys.
_GROUPED_COLS = ["IF-VVS", "VS", "SI1", "SI2", "SI3", "I1", "I2", "I3"]
_GROUPED_ROWS = ["DF", "GH", "IJ", "KL", "MN"]
_FULL_COLS = ["IF", "VVS1", "VVS2", "VS1", "VS2", "SI1", "SI2", "SI3", "I1", "I2", "I3"]
_FULL_ROWS = ["D", "E", "F", "G", "H", "I", "J", "K", "L", "M"]

# Default per-carat USD for each < 0.25 ct tier, keyed by its config-param
# suffix — the source of truth is utils._STONE_TIERS (kept DRY: one place).
_TIER_DEFAULTS = {param: default for _lo, _hi, param, default in _STONE_TIERS}

# Ordered buckets shown in the editor. The first five are the legacy 5 carat
# TIERS (< 0.25 ct). A tier is a SINGLE flat per-carat price (colour/clarity do
# not matter), so each is rendered as one READ-ONLY cell reflecting the live
# tier config param — the real source of truth for sub-0.25 pricing
# (utils._STONE_TIERS / get_stone_tier_price). The editor never writes them;
# sub-0.25 prices are edited only in Settings, and this editor never changes
# them. Buckets >= 0.25 ct are the editable Rap grid (grouped small / full big).
# Annotated so the mixed-shape entries (tier vs grid) unify as one dict type —
# mypy follows this module via the package graph even though it only targets
# utils.py, and would otherwise widen each entry to bare ``object``.
RAP_STRUCTURE: list[dict[str, object]] = [
    {"bucket": "0.001-0.089", "tier": "diamond_stone_tier_1_usd"},
    {"bucket": "0.090-0.109", "tier": "diamond_stone_tier_2_usd"},
    {"bucket": "0.110-0.149", "tier": "diamond_stone_tier_3_usd"},
    {"bucket": "0.150-0.199", "tier": "diamond_stone_tier_4_usd"},
    {"bucket": "0.200-0.249", "tier": "diamond_stone_tier_5_usd"},
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


def _structure_payload(env=None):
    """Buckets with their row/col keys — drives the editor's table rendering.

    ``env`` (optional) is used to read the live per-carat value of the five
    < 0.25 ct tiers so each renders as one read-only ``single`` cell. Called
    without ``env`` for whitelist cleaning (values not needed there).
    """
    icp = env["ir.config_parameter"].sudo() if env is not None else None
    out = []
    for s in RAP_STRUCTURE:
        tier = s.get("tier")
        if tier:
            tier = str(tier)
            value = _TIER_DEFAULTS.get(tier, 0.0)
            if icp is not None:
                try:
                    live = float(icp.get_param(f"jewellery_evaluator.{tier}"))
                    if live > 0:
                        value = live
                except (TypeError, ValueError):
                    pass
            out.append({
                "bucket": s["bucket"],
                "single": True,
                "rows": [],
                "cols": [],
                "value": value,
            })
        else:
            out.append({
                "bucket": s["bucket"],
                "single": False,
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

    # Legacy sheet name -> current one. The non-round sheet was renamed
    # "pear" -> "exotic" -> "fancy"; the grids are hand-populated from the
    # Rapaport PDFs and live ONLY in these config params, so a rename must
    # carry the data across or ~1560 cells are silently orphaned.
    _LEGACY_SHEET_KEYS = {"fancy": ("exotic", "pear")}

    def _register_hook(self):
        super()._register_hook()
        if self._name != "diamond.rap.price":
            return
        # NEVER let a data migration stop the server from booting: _register_hook
        # runs during registry load, so an exception here would take Odoo down.
        # A failed migration just leaves the legacy key in place to retry next
        # boot; pricing meanwhile falls back to the tier price, never to zero.
        try:
            self._migrate_legacy_sheet_params()
        except Exception:
            _logger.exception(
                "Rap grid legacy-key migration failed; leaving legacy params intact"
            )

    def _migrate_legacy_sheet_params(self):
        """Rename legacy sheet config params in place. Idempotent: only copies
        when the current key is absent/empty and a legacy one has content, so
        re-running (every server boot) is a no-op once migrated."""
        icp = self._icp()
        for sheet, legacy_names in self._LEGACY_SHEET_KEYS.items():
            for suffix in ("", "_disc"):
                new_key = f"jewellery_evaluator.diamond_rap_{sheet}{suffix}"
                if (icp.get_param(new_key) or "").strip() not in ("", "{}"):
                    continue  # already migrated / already populated
                for legacy in legacy_names:
                    old_key = f"jewellery_evaluator.diamond_rap_{legacy}{suffix}"
                    old_val = icp.get_param(old_key)
                    if not old_val or old_val.strip() in ("", "{}"):
                        continue
                    icp.set_param(new_key, old_val)
                    # Drop the stale key so the old name cannot resurface.
                    old = icp.search([("key", "=", old_key)], limit=1)
                    if old:
                        old.unlink()
                    _logger.info(
                        "Rap grid migrated: %s -> %s (%d bytes)",
                        old_key, new_key, len(old_val),
                    )
                    break

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
            "fancy": self._load("fancy"),
            "round_disc": self._load("round", "_disc"),
            "fancy_disc": self._load("fancy", "_disc"),
            "structure": _structure_payload(self.env),
        }

    def _clean_grid(self, grid, clamp_max=None):
        """Whitelist buckets/rows/cols against the structure; keep numeric cells
        only (blank/zero dropped). For the discount grid, ``clamp_max=100`` bounds
        each percent to 0..100."""
        valid = {s["bucket"]: s for s in _structure_payload()}
        clean = {}
        for bucket, rows in (grid or {}).items():
            spec = valid.get(bucket)
            # Tier buckets are read-only (single cell from the live tier param);
            # never store grid data for them, and drop any orphaned old cells.
            if not spec or spec.get("single") or not isinstance(rows, dict):
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
        if sheet not in ("round", "fancy"):
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
