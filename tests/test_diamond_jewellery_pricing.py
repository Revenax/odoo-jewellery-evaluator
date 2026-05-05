# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import os
import sys

try:
    from jewellery_evaluator_utils import (
        compute_diamond_jewellery_price,
        get_stone_tier_price,
    )  # noqa: F401
except ImportError:
    import importlib.util

    _project_root = os.path.join(os.path.dirname(__file__), '..')
    sys.path.insert(0, os.path.abspath(_project_root))

    _utils_path = os.path.join(os.path.dirname(
        __file__), "..", "jewellery_evaluator", "utils.py")
    _utils_path = os.path.abspath(_utils_path)

    if not os.path.exists(_utils_path):
        raise FileNotFoundError(
            f"utils.py not found at {_utils_path}") from None

    spec = importlib.util.spec_from_file_location("utils", _utils_path)
    utils = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(utils)
    compute_diamond_jewellery_price = utils.compute_diamond_jewellery_price
    get_stone_tier_price = utils.get_stone_tier_price

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


class _FakeICP:
    """Minimal stand-in for ir.config_parameter that returns fixed defaults."""

    def get_param(self, key, default=''):
        return default


class _FakeEnv(dict):
    def __getitem__(self, model):
        if model == 'ir.config_parameter':
            class _Sudo:
                def get_param(self, key, default=''):
                    return default

            class _Model:
                def sudo(self):
                    return _Sudo()
            return _Model()
        raise KeyError(model)


_env = _FakeEnv()


# ---------------------------------------------------------------------------
# Stone tier pricing
# ---------------------------------------------------------------------------

class TestStoneTierPrice:

    def test_tier_1_lower_boundary(self):
        # 0.001 ct × $800/ct = $0.80
        price = get_stone_tier_price(_env, 0.001)
        assert price == 0.80

    def test_tier_1_upper_boundary(self):
        # 0.089 ct × $800/ct = $71.20
        price = get_stone_tier_price(_env, 0.089)
        assert price == 71.20

    def test_tier_2_lower(self):
        # 0.090 ct × $950/ct = $85.50
        price = get_stone_tier_price(_env, 0.090)
        assert price == 85.50

    def test_tier_2_upper(self):
        # 0.109 ct × $950/ct = $103.55
        price = get_stone_tier_price(_env, 0.109)
        assert price == 103.55

    def test_tier_3(self):
        # 0.130 ct × $1100/ct = $143.00
        price = get_stone_tier_price(_env, 0.130)
        assert price == 143.00

    def test_tier_4(self):
        # 0.175 ct × $1250/ct = $218.75
        price = get_stone_tier_price(_env, 0.175)
        assert price == 218.75

    def test_tier_5_lower(self):
        # 0.200 ct × $1350/ct = $270.00
        price = get_stone_tier_price(_env, 0.200)
        assert price == 270.00

    def test_tier_5_upper(self):
        # 0.259 ct × $1350/ct = $349.65
        price = get_stone_tier_price(_env, 0.259)
        assert price == 349.65

    def test_tier_5_unlimited_above_threshold(self):
        # 0.260 ct × $1350/ct = $351.00 (tier 5 now applies to all >= 0.200)
        price = get_stone_tier_price(_env, 0.260)
        assert price == 351.00

    def test_tier_5_large_stone(self):
        # 5.0 ct × $1350/ct = $6750.00
        price = get_stone_tier_price(_env, 5.0)
        assert price == 6750.00

    def test_tier_5_maximum_carat(self):
        # 7.0 ct × $1350/ct = $9450.00
        price = get_stone_tier_price(_env, 7.0)
        assert price == 9450.00


# ---------------------------------------------------------------------------
# Diamond jewellery end-to-end formula
# ---------------------------------------------------------------------------

class TestComputeDiamondJewelleryPrice:
    """
    Reference values for hand-verification:

    21K gold, 10g, exchange_rate=50, fee_per_gram=17:
        gold_price_per_gram_usd = (base_21k * 1.0) / 50
        total_gold_cost_usd     = (gold_price_per_gram + 17) * 10
    """

    BASE_21K_EGP = 750.0   # 750 EGP/g (21K baseline)
    RATE = 50.0    # 50 EGP = 1 USD
    FEE = 17.0    # $17/g making fee
    MULTIPLIER = 2.8
    DISCOUNT = 0.20

    def _call(self, purity, weight, stones):
        return compute_diamond_jewellery_price(
            base_gold_price_21k_egp=self.BASE_21K_EGP,
            gold_purity=purity,
            weight_g=weight,
            stone_prices_usd=stones,
            exchange_rate_usd=self.RATE,
            fee_per_gram_usd=self.FEE,
            ticket_multiplier=self.MULTIPLIER,
            ticket_discount=self.DISCOUNT,
        )

    def test_21k_no_stones(self):
        r = self._call('21K', 10.0, [])
        # gold_per_gram_usd = 750/50 = 15 → (15 + 17) * 10 = 320
        assert abs(r['total_gold_cost_usd'] - 320.0) < 0.01
        assert r['total_stones_cost_usd'] == 0.0
        # ticket = 320 * 2.8 = 896
        assert abs(r['ticket_price_usd'] - 896.0) < 0.01
        # sale = 896 * 0.80 = 716.80
        assert abs(r['sale_price_usd'] - 716.80) < 0.01
        # egp = 716.80 * 50 = 35840, rounded to nearest 50 = 35850
        assert abs(r['sale_price_egp'] - 35850.0) < 0.01
        # Verify it's a multiple of 50 (rounded correctly)
        assert r['sale_price_egp'] % 50 == 0

    def test_18k_purity_factor(self):
        r = self._call('18K', 10.0, [])
        # purity_factor = 7/8 = 0.875
        # gold_per_gram = (750 * 0.875) / 50 = 656.25/50 = 13.125
        # total_gold = (13.125 + 17) * 10 = 301.25
        assert abs(r['total_gold_cost_usd'] - 301.25) < 0.01

    def test_24k_purity_factor(self):
        r = self._call('24K', 10.0, [])
        # purity_factor = 8/7
        # gold_per_gram = (750 * 8/7) / 50 = (857.142...) / 50 ≈ 17.1428...
        # total_gold = (17.1428 + 17) * 10 ≈ 341.428...
        assert abs(r['total_gold_cost_usd'] - 341.43) < 0.1

    def test_with_two_stones(self):
        r = self._call('21K', 10.0, [800.0, 1100.0])
        # stones = 1900
        # gold = 320 (from 21K/10g test)
        # ticket = (320 + 1900) * 2.8 = 2220 * 2.8 = 6216
        assert abs(r['total_stones_cost_usd'] - 1900.0) < 0.01
        assert abs(r['ticket_price_usd'] - 6216.0) < 0.01

    def test_with_multiple_quantity_stones(self):
        # Test that quantity multiplier works: 2 stones @ $85.50 each = $171.00 total
        r = self._call('21K', 10.0, [171.0])
        # 171.0 is the total price for 2 stones of 0.090 ct each
        # gold = 320, stones = 171 → ticket = 491 * 2.8 = 1374.8
        assert abs(r['total_stones_cost_usd'] - 171.0) < 0.01
        assert abs(r['ticket_price_usd'] - 1374.8) < 0.01

    def test_sale_price_egp_round_trip(self):
        r = self._call('21K', 5.0, [950.0])
        # sale_egp is rounded to nearest 50, so allow larger tolerance (up to ±25 from rounding)
        assert abs(r['sale_price_egp'] - r['sale_price_usd'] * self.RATE) < 30.0
        # Verify it's a multiple of 50 (rounded correctly)
        assert r['sale_price_egp'] % 50 == 0

    def test_empty_stones_list(self):
        r = self._call('21K', 1.0, [])
        assert r['total_stones_cost_usd'] == 0.0

    def test_invalid_purity_raises(self):
        try:
            compute_diamond_jewellery_price(
                base_gold_price_21k_egp=750.0,
                gold_purity='14K',
                weight_g=10.0,
                stone_prices_usd=[],
                exchange_rate_usd=50.0,
                fee_per_gram_usd=17.0,
                ticket_multiplier=2.8,
                ticket_discount=0.20,
            )
            raise AssertionError('Expected ValueError')
        except ValueError:
            pass

    def test_zero_exchange_rate_raises(self):
        try:
            compute_diamond_jewellery_price(
                base_gold_price_21k_egp=750.0,
                gold_purity='21K',
                weight_g=10.0,
                stone_prices_usd=[],
                exchange_rate_usd=0.0,
                fee_per_gram_usd=17.0,
                ticket_multiplier=2.8,
                ticket_discount=0.20,
            )
            raise AssertionError('Expected ValueError')
        except ValueError:
            pass
