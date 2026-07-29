# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import json
import logging
import os

_logger = logging.getLogger(__name__)

_SEED_FILE = os.path.join(os.path.dirname(__file__), "data", "diamond_rap_seed.json")


def post_init_hook(env):
    """On a fresh install, seed the Rapaport LIST grids (round/fancy) from the
    bundled 03/2026 snapshot — but ONLY when the config param is empty, so it
    never clobbers prices edited via the Diamond Rap Prices page. Runs on install
    only (not on -u), so a normal upgrade never touches the live grids."""
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
