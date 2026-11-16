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
        'stock': '132113', 'income': '500113', 'expense': '400213', 'making_fee': '500126'}
    assert codes('gold_local', '21K')['income'] == '500112'
    assert codes('gold_local', '21K')['making_fee'] == '500125'
    assert codes('gold_local', '24K')['making_fee'] == '500124'
    assert codes('gold_local', '24K')['stock'] == '132111'


def test_bullion_shares_karat_metal_but_has_its_own_fee():
    bar = codes('gold_bars', '24K')
    assert bar['stock'] == codes('gold_local', '24K')['stock']
    assert bar['income'] == '500111'
    assert bar['making_fee'] == '500127'
    assert codes('gold_bars', '21K')['expense'] == '400212'
    assert codes('gold_bars', '21K')['making_fee'] == '500128'
    assert codes('gold_bars', '18K')['making_fee'] == '500129'


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


def test_every_gold_account_is_split_by_karat():
    karats = set(utils.GOLD_KARAT_ACCOUNTS)
    assert set(utils.GOLD_MAKING_FEE_ACCOUNTS) == karats
    assert set(utils.GOLD_KARAT_OTHER_ACCOUNTS) == karats
    assert set(utils.GOLD_KARAT_CURRENCY) == karats
    kinds = {frozenset(v) for v in utils.GOLD_KARAT_OTHER_ACCOUNTS.values()}
    assert len(kinds) == 1


def test_account_codes_are_unique_and_six_digits():
    every = [c for d in utils.GOLD_KARAT_ACCOUNTS.values() for c in d.values()]
    every += [c for d in utils.GOLD_MAKING_FEE_ACCOUNTS.values() for c in d.values()]
    every += [c for d in utils.GOLD_KARAT_OTHER_ACCOUNTS.values() for c in d.values()]
    every += list(utils.SILVER_ACCOUNTS.values()) + [utils.SILVER_MAKING_FEE_ACCOUNT]
    every += list(utils.LEGACY_MAKING_FEE_ACCOUNTS.values())
    assert len(every) == len(set(every))
    assert all(len(c) == 6 and c.isdigit() for c in every)


def test_legacy_fee_accounts_get_nothing_new():
    legacy = set(utils.LEGACY_MAKING_FEE_ACCOUNTS.values())
    for jtype in ('gold_local', 'gold_foreign', 'gold_bars', 'silver'):
        for karat in ('24K', '21K', '18K'):
            assert codes(jtype, karat)['making_fee'] not in legacy
    assert legacy <= utils.ALL_MAKING_FEE_ACCOUNTS
