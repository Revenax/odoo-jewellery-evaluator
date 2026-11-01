# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

"""inventory_cost_egp: what a piece is carried at and costed at when sold."""
import importlib.util
import os

_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "jewellery_evaluator", "utils.py"))
_spec = importlib.util.spec_from_file_location("utils_cost", _path)
utils = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(utils)
cost = utils.inventory_cost_egp


def test_gold_uses_metal_cost():
    assert cost('gold_local', metal_cost_egp=25000.456) == 25000.46
    assert cost('gold_bars', metal_cost_egp=100000) == 100000.0


def test_silver_uses_metal_cost():
    assert cost('silver', metal_cost_egp=900) == 900.0


def test_zero_metal_cost_is_unknown():
    assert cost('gold_foreign', metal_cost_egp=0) is None


def test_diamond_is_gold_at_purity_plus_stones():
    # 18K = 6/7 of 21K: 4200 * 6/7 = 3600/g * 2 g = 7200, stones 100 USD * 50 = 5000
    assert cost('diamond_jewellery', base_gold_price_21k=4200, gold_purity='18K',
                gold_weight_g=2, stones_cost_usd=100, usd_rate=50) == 12200.0


def test_center_stone_is_stone_only():
    assert cost('center_stone', base_gold_price_21k=4000, gold_purity='18K',
                gold_weight_g=2, stones_cost_usd=300, usd_rate=50) == 15000.0


def test_diamond_without_gold_price_is_unknown():
    assert cost('diamond_jewellery', base_gold_price_21k=0, gold_purity='18K',
                gold_weight_g=2, stones_cost_usd=100, usd_rate=50) is None


def test_stones_without_rate_are_unknown():
    assert cost('center_stone', stones_cost_usd=100, usd_rate=0) is None


def test_other_products_have_no_jewellery_cost():
    assert cost(None, metal_cost_egp=500) is None
    assert cost('service') is None


def test_pegged_rates_follow_usd():
    rates = utils.pegged_currency_rates(50)
    assert rates['USD'] == 0.02
    assert abs(rates['SAR'] - 0.075) < 1e-12
    assert abs(1 / rates['AED'] - 50 / 3.6725) < 1e-9


def test_pegged_rates_reject_zero():
    import pytest
    with pytest.raises(ValueError):
        utils.pegged_currency_rates(0)
