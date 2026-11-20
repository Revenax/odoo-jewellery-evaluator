# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

"""Acquisition Order (AO) totals: grams per karat, 21K equivalent, making fee, stones."""
import importlib.util
import os

import pytest

_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "jewellery_evaluator", "utils.py"))
_spec = importlib.util.spec_from_file_location("utils_ao", _path)
utils = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(utils)

LINES = [
    {"karat": "18K", "qty": 32, "grams": 480, "fee_per_gram": 120},   # gold bracelets, foreign
    {"karat": "18K", "qty": 10, "grams": 110, "fee_per_gram": 300},   # diamond rings, local
]


def test_owner_example():
    t = utils.acquisition_totals(LINES)
    assert t["pieces"] == 42
    assert t["grams"] == {"24K": 0.0, "21K": 0.0, "18K": 590.0}
    assert t["making_fee"] == 57600 + 33000


def test_21k_equivalent_uses_the_pricing_factors():
    t = utils.acquisition_totals([
        {"karat": "18K", "qty": 1, "grams": 7, "fee_per_gram": 0},    # 6 g of 21K
        {"karat": "24K", "qty": 1, "grams": 7, "fee_per_gram": 0},    # 8 g of 21K
        {"karat": "21K", "qty": 1, "grams": 1, "fee_per_gram": 0},
    ])
    assert t["grams_21k_eq"] == 15.0


def test_metal_value_at_the_21k_price():
    t = utils.acquisition_totals([{"karat": "18K", "qty": 1, "grams": 7, "fee_per_gram": 100}],
                                 gold_price_21k=5000)
    assert t["metal_value"] == 30000.0        # 6 g of 21K x 5,000
    assert t["total_egp"] == 30700.0          # + 7 g x 100 making fee


def test_stones_in_usd_and_egp():
    t = utils.acquisition_totals([], [{"qty": 46, "carats": 0.33, "price_per_carat_usd": 400},
                                      {"qty": 1, "carats": 0.52, "price_per_carat_usd": 2000}],
                                 usd_rate=50)
    assert t["stone_count"] == 47
    assert t["carats"] == 0.85
    assert t["stones_usd"] == 132.0 + 1040.0
    assert t["stones_egp"] == 1172.0 * 50
    assert t["total_egp"] == 58600.0


def test_negative_grams_refused():
    with pytest.raises(ValueError):
        utils.acquisition_totals([{"karat": "18K", "qty": 1, "grams": -1, "fee_per_gram": 0}])


def test_empty_order():
    t = utils.acquisition_totals([])
    assert t["pieces"] == 0 and t["total_egp"] == 0.0
