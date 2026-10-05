# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import json
import logging
import os

_logger = logging.getLogger(__name__)

_SEED_FILE = os.path.join(os.path.dirname(__file__), "data", "diamond_rap_seed.json")


def disable_pos_line_grouping(env):
    """Every piece is its own POS line: identical products never merge.

    Invoices hide the quantity on purpose, so a merged qty-3 line misreads as
    one piece. Odoo merges whenever the unit of measure has "Group Products in
    POS" on, which point_of_sale switches on for Units (all our products).
    Also applied to existing databases by migrations/19.0.4.0.1."""
    units = env.ref("uom.product_uom_unit", raise_if_not_found=False)
    if units and units.is_pos_groupable:
        units.is_pos_groupable = False


def post_init_hook(env):
    """On a fresh install: never merge POS lines (disable_pos_line_grouping),
    and seed the Rapaport LIST grids (round/fancy) from the bundled 03/2026 snapshot — but ONLY when the config param is empty, so it
    never clobbers prices edited via the Diamond Rap Prices page. Runs on install
    only (not on -u), so a normal upgrade never touches the live grids."""
    disable_pos_line_grouping(env)
    icp = env["ir.config_parameter"].sudo()
    try:
        with open(_SEED_FILE, encoding="utf-8") as fh:
            seed = json.load(fh)
    except (OSError, ValueError) as exc:
        _logger.warning("diamond rap seed unavailable: %s", exc)
        return
    for sheet in ("round", "fancy"):
        key = f"jewellery_evaluator.diamond_rap_{sheet}"
        current = (icp.get_param(key) or "").strip()
        if current in ("", "{}"):
            icp.set_param(key, json.dumps(seed.get(sheet, {}), separators=(",", ":")))
            _logger.info("seeded %s from bundled Rap snapshot", key)
