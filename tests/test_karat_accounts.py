# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

"""Chart of accounts by karat and the making-fee split of a sale."""
import importlib.util
import os

_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "jewellery_evaluator", "utils.py"))
_spec = importlib.util.spec_from_file_location("utils_karat", _path)
utils = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(utils)
codes = utils.jewellery_account_codes
split = utils.making_fee_split


def test_gold_jewellery_by_karat():
    assert codes('gold_foreign', '18K') == {
        'stock': '132113', 'income': '500113', 'expense': '400213', 'making_fee': '500121'}
    assert codes('gold_local', '21K')['income'] == '500112'
    assert codes('gold_local', '24K')['stock'] == '132111'


def test_bullion_shares_karat_metal_but_has_its_own_fee():
    bar = codes('gold_bars', '24K')
    assert bar['stock'] == codes('gold_local', '24K')['stock']
    assert bar['income'] == '500111'
    assert bar['making_fee'] == '500122'
    assert codes('gold_bars', '21K')['expense'] == '400212'


def test_silver():
    assert codes('silver', None) == {
        'stock': '132103', 'income': '500105', 'expense': '400203', 'making_fee': '500123'}


def test_not_by_karat():
    assert codes('diamond_jewellery', '18K') is None
    assert codes('center_stone', None) is None
    assert codes(None, None) is None
    assert codes('gold_foreign', None) is None
    assert codes('gold_foreign', '14K') is None


def test_split_sale():
    assert split(25000, 21000.004) == (21000.0, 4000.0)


def test_split_below_metal_value():
    assert split(20000, 21000) == (21000.0, -1000.0)


def test_split_refund():
    assert split(-25000, -21000) == (-21000.0, -4000.0)


def test_split_without_cost_keeps_metal():
    assert split(25000, 0) == (25000.0, 0.0)
    assert split(25000, None) == (25000.0, 0.0)
