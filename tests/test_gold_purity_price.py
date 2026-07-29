# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import os
import sys

try:
    from jewellery_evaluator_utils import gold_price_for_purity
except ImportError:
    import importlib.util

    _utils_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "jewellery_evaluator", "utils.py")
    )
    sys.path.insert(0, os.path.dirname(_utils_path))
    spec = importlib.util.spec_from_file_location("utils", _utils_path)
    utils = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(utils)
    gold_price_for_purity = utils.gold_price_for_purity


# The live 21K base on prod at the time this was written, so the expected
# values below are the real numbers the dashboard must display.
_BASE_21K = 5865.0


class TestGoldPriceForPurity:
    def test_21k_is_the_base_itself(self):
        # The API quotes 21K/gram, so 21K is the identity (factor 1).
        assert gold_price_for_purity(_BASE_21K, "21K") == 5865.0

    def test_24k_is_eight_sevenths(self):
        # 5865 x 8/7 = 6702.857142... -> 6702.86
        assert gold_price_for_purity(_BASE_21K, "24K") == 6702.86

    def test_18k_is_seven_eighths(self):
        # 5865 x 7/8 = 5131.875 -> ROUND_HALF_UP -> 5131.88
        assert gold_price_for_purity(_BASE_21K, "18K") == 5131.88

    def test_ordering_holds(self):
        p18 = gold_price_for_purity(_BASE_21K, "18K")
        p21 = gold_price_for_purity(_BASE_21K, "21K")
        p24 = gold_price_for_purity(_BASE_21K, "24K")
        assert p18 < p21 < p24

    def test_unknown_purity_is_zero(self):
        # 14K/10K are not offered; an unknown purity must not silently price.
        assert gold_price_for_purity(_BASE_21K, "14K") == 0.0
        assert gold_price_for_purity(_BASE_21K, "") == 0.0

    def test_unconfigured_base_is_zero(self):
        # A never-configured gold source yields base 0 -> every purity is 0,
        # so the dashboard shows an obviously-broken 0 rather than a wrong price.
        assert gold_price_for_purity(0.0, "24K") == 0.0

    def test_negative_base_is_zero(self):
        assert gold_price_for_purity(-100.0, "21K") == 0.0

    def test_lowercase_purity_is_accepted(self):
        assert gold_price_for_purity(_BASE_21K, "24k") == 6702.86
