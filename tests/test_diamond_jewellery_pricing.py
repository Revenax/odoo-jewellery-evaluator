# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

from jewellery_evaluator.utils import compute_diamond_jewellery_price, get_stone_tier_price


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
        price, manual = get_stone_tier_price(_env, 0.001)
        assert price == 800.0
        assert manual is False

    def test_tier_1_upper_boundary(self):
        price, manual = get_stone_tier_price(_env, 0.089)
        assert price == 800.0
        assert manual is False

    def test_tier_2_lower(self):
        price, manual = get_stone_tier_price(_env, 0.090)
        assert price == 950.0
        assert manual is False

    def test_tier_2_upper(self):
        price, manual = get_stone_tier_price(_env, 0.109)
        assert price == 950.0
        assert manual is False

    def test_tier_3(self):
        price, manual = get_stone_tier_price(_env, 0.130)
        assert price == 1100.0
        assert manual is False

    def test_tier_4(self):
        price, manual = get_stone_tier_price(_env, 0.175)
        assert price == 1250.0
        assert manual is False

    def test_tier_5_lower(self):
        price, manual = get_stone_tier_price(_env, 0.200)
        assert price == 1350.0
        assert manual is False

    def test_tier_5_upper(self):
        price, manual = get_stone_tier_price(_env, 0.259)
        assert price == 1350.0
        assert manual is False

    def test_manual_pricing_at_threshold(self):
        price, manual = get_stone_tier_price(_env, 0.260)
        assert price is None
        assert manual is True

    def test_manual_pricing_above_threshold(self):
        price, manual = get_stone_tier_price(_env, 1.5)
        assert price is None
        assert manual is True

    def test_manual_pricing_large_stone(self):
        price, manual = get_stone_tier_price(_env, 7.0)
        assert price is None
        assert manual is True


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
    RATE         = 50.0    # 50 EGP = 1 USD
    FEE          = 17.0    # $17/g making fee
    MULTIPLIER   = 2.8
    DISCOUNT     = 0.20

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
        # egp = 716.80 * 50 = 35840
        assert abs(r['sale_price_egp'] - 35840.0) < 0.01

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

    def test_sale_price_egp_round_trip(self):
        r = self._call('21K', 5.0, [950.0])
        # sale_egp should equal sale_usd * exchange_rate (within rounding)
        assert abs(r['sale_price_egp'] - r['sale_price_usd'] * self.RATE) < 1.0

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
            assert False, 'Expected ValueError'
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
            assert False, 'Expected ValueError'
        except ValueError:
            pass
