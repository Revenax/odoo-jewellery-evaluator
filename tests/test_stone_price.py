# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import json
import os
import sys

try:
    from jewellery_evaluator_utils import (
        get_stone_price_usd,
        get_stone_tier_price,
        rap_bucket_for_carat,
        rap_keys,
    )
except ImportError:
    import importlib.util

    _utils_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "jewellery_evaluator", "utils.py")
    )
    sys.path.insert(0, os.path.dirname(_utils_path))
    spec = importlib.util.spec_from_file_location("utils", _utils_path)
    utils = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(utils)
    get_stone_price_usd = utils.get_stone_price_usd
    get_stone_tier_price = utils.get_stone_tier_price
    rap_bucket_for_carat = utils.rap_bucket_for_carat
    rap_keys = utils.rap_keys


class _FakeEnv(dict):
    def __init__(self, params=None):
        super().__init__()
        self._params = params or {}

    def __getitem__(self, model):
        if model == "ir.config_parameter":
            params = self._params

            class _Sudo:
                def get_param(self, key, default=""):
                    return params.get(key, default)

            class _Model:
                def sudo(self):
                    return _Sudo()

            return _Model()
        raise KeyError(model)


_ROUND = {
    "1.00-1.49": {"G": {"VS1": 54}, "D": {"IF": 150}},
    "0.23-0.29": {"GH": {"VS": 10.8}},
    "2.00-2.99": {"M": {"I3": 15}},
}
_EXOTIC = {"1.00-1.49": {"G": {"VS1": 40}}}


def env_with(discount="0"):
    return _FakeEnv({
        "jewellery_evaluator.diamond_rap_round": json.dumps(_ROUND),
        "jewellery_evaluator.diamond_rap_exotic": json.dumps(_EXOTIC),
        "jewellery_evaluator.diamond_rap_discount_pct": discount,
    })


_env = env_with()


class TestBuckets:
    def test_bucket_lookup(self):
        assert rap_bucket_for_carat(0.27) == ("0.23-0.29", True)
        assert rap_bucket_for_carat(1.20) == ("1.00-1.49", False)
        assert rap_bucket_for_carat(6.00) == ("5.00-5.99", False)  # 6-9.99 -> 5.99
        assert rap_bucket_for_carat(0.10) == (None, False)         # below grid

    def test_keys_full_and_grouped(self):
        assert rap_keys("G", "VS1", False) == ("G", "VS1")
        assert rap_keys("N", "P3", False) == ("M", "I3")           # N->M, P3->I3
        assert rap_keys("D", "LC", False) == ("D", "IF")           # LC->IF
        assert rap_keys("G", "VS1", True) == ("GH", "VS")          # grouped collapse
        # ungraded stone: '' colour must NOT match the 'DEFGHIJKLM' string (a
        # substring bug) — falls to the M row; '' clarity -> I3.
        assert rap_keys("", "VS1", False) == ("M", "VS1")
        assert rap_keys("G", "", False) == ("G", "I3")


class TestRouter:
    def test_below_025_uses_tier(self):
        assert get_stone_price_usd(_env, "Round", 0.20, "G", "VS1") == \
            get_stone_tier_price(_env, 0.20)

    def test_full_bucket_lookup(self):
        # 1.20 ct G VS1 = cell 54 -> $5,400/ct -> x1.20 = 6480
        assert get_stone_price_usd(_env, "Round", 1.20, "G", "VS1") == 6480.0

    def test_boundary_025_uses_rap(self):
        # 0.25 ct -> 0.23-0.29 grouped, G->GH, VS1->VS, cell 10.8 -> x100 x0.25
        assert get_stone_price_usd(_env, "Round", 0.25, "G", "VS1") == 270.0

    def test_lc_maps_to_if(self):
        assert get_stone_price_usd(_env, "Round", 1.20, "D", "LC") == 18000.0

    def test_colour_n_and_p3(self):
        # 2.5 ct N P3 -> M / I3 = 15 -> x100 x2.5 = 3750
        assert get_stone_price_usd(_env, "Round", 2.50, "N", "P3") == 3750.0

    def test_pear_uses_exotic_grid(self):
        assert get_stone_price_usd(_env, "Pear", 1.20, "G", "VS1") == 4800.0

    def test_all_non_round_use_exotic_grid(self):
        # Round uses the round grid; every other shape -> the exotic grid.
        assert get_stone_price_usd(_env, "Oval", 1.20, "G", "VS1") == 4800.0
        assert get_stone_price_usd(_env, "Marquise", 1.20, "G", "VS1") == 4800.0
        assert get_stone_price_usd(_env, "Round", 1.20, "G", "VS1") == 6480.0

    def test_missing_cell_falls_back_to_tier(self):
        # K/SI2 not in the test grid -> tier price for 1.20 ct
        assert get_stone_price_usd(_env, "Round", 1.20, "K", "SI2") == \
            get_stone_tier_price(_env, 1.20)

    def test_discount_applied(self):
        env = env_with(discount="0.25")
        assert get_stone_price_usd(env, "Round", 1.20, "G", "VS1") == 4860.0  # 6480 x 0.75
