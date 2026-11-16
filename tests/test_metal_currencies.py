# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
import pytest
from jewellery_evaluator_utils import metal_currency_rates


def test_gold_rates_follow_21k_base_and_purity():
    rates = metal_currency_rates(base_21k_egp=7000)
    assert set(rates) == {'G24', 'G21', 'G18'}
    assert 1 / rates['G21'] == pytest.approx(7000)
    assert 1 / rates['G24'] == pytest.approx(8000)
    assert 1 / rates['G18'] == pytest.approx(6000)


def test_silver_rate():
    rates = metal_currency_rates(silver_999_egp=80)
    assert rates == {'S99': pytest.approx(1 / 80)}


def test_missing_or_bad_prices_are_left_out():
    assert metal_currency_rates() == {}
    assert metal_currency_rates(base_21k_egp=0, silver_999_egp=-5) == {}
    assert set(metal_currency_rates(base_21k_egp=None, silver_999_egp=90)) == {'S99'}
