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


BANDS = (7, "21K", "foreign")
BRACELET = (9, "18K", "local")
PROGRESS_LINES = [{"key": BANDS, "qty": 12, "grams": 230}, {"key": BRACELET, "qty": 1, "grams": 123}]


def test_progress_matches_category_karat_origin():
    p = utils.acquisition_progress(PROGRESS_LINES, [
        {"category": 7, "karat": "21K", "origin": "foreign", "grams": 19.5},
        {"category": 7, "karat": "21K", "origin": "foreign", "grams": 20.1},
        {"category": 9, "karat": "18K", "origin": "local", "grams": 123},
    ])
    bands, bracelet = p["rows"]
    assert (bands["reg_qty"], bands["reg_grams"], bands["left_qty"], bands["left_grams"]) == (2, 39.6, 10, 190.4)
    assert (bracelet["left_qty"], bracelet["over"]) == (0, False)
    assert p["unmatched"] == [] and p["left_qty"] == 10 and p["reg_grams"] == 162.6


def test_progress_flags_unmatched_and_over():
    p = utils.acquisition_progress(PROGRESS_LINES, [
        {"category": 9, "karat": "18K", "origin": "local", "grams": 100},
        {"category": 9, "karat": "18K", "origin": "local", "grams": 30},      # a second bracelet: over
        {"category": 9, "karat": "21K", "origin": "local", "grams": 5},       # wrong karat: unmatched
        {"category": 3, "karat": "18K", "origin": None, "grams": 2},          # other category: unmatched
    ])
    assert p["rows"][1]["over"] is True
    assert p["unmatched"] == [2, 3]


def test_progress_piece_without_origin_matches_on_category_and_karat():
    p = utils.acquisition_progress([{"key": (4, "18K", "local"), "qty": 10, "grams": 110}],
                                   [{"category": 4, "karat": "18K", "origin": None, "grams": 11}])
    assert p["rows"][0]["reg_qty"] == 1 and p["unmatched"] == []


def test_progress_pools_identical_rows():
    p = utils.acquisition_progress([{"key": BANDS, "qty": 5, "grams": 100}, {"key": BANDS, "qty": 7, "grams": 130}], [])
    assert len(p["rows"]) == 1 and p["rows"][0]["qty"] == 12 and p["left_grams"] == 230.0


def test_payment_metal_and_money():
    p = utils.acquisition_payment(10, 5000, 1200)
    assert p == {"grams_21k": 10.0, "metal_amount": 50000.0, "money": 1200.0, "amount": 51200.0}


def test_payment_any_positive_price_and_rounding():
    p = utils.acquisition_payment(1.2345, 4999.99)
    assert p["grams_21k"] == 1.235
    assert p["metal_amount"] == 6174.99


def test_payment_rejects_bad_input():
    with pytest.raises(ValueError):
        utils.acquisition_payment(5, 0)
    with pytest.raises(ValueError):
        utils.acquisition_payment(-1, 5000)
    with pytest.raises(ValueError):
        utils.acquisition_payment(0, 5000, 0)


def test_balance_partial_and_settled():
    b = utils.acquisition_balance(505.714, 97200, [{"grams_21k": 300, "money": 50000}])
    assert b["grams_left"] == 205.714 and b["money_left"] == 47200.0 and not b["settled"]
    b = utils.acquisition_balance(505.714, 97200, [{"grams_21k": 300, "money": 50000},
                                                  {"grams_21k": 205.714, "money": 47200}])
    assert b["settled"] and b["grams_paid"] == 505.714


def test_balance_paid_ahead_goes_negative():
    b = utils.acquisition_balance(10, 0, [{"grams_21k": 12, "money": 0}])
    assert b["grams_left"] == -2.0 and b["settled"]


def test_gold_price_from_metal_rate():
    assert utils.gold_price_from_metal_rate(1 / 5000) == 5000.0
    assert utils.gold_price_from_metal_rate(0) == 0.0
