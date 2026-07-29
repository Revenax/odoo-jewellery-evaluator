# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import os
import sys

try:
    from jewellery_evaluator_utils import CARAT_DECIMALS, total_carat_for
except ImportError:
    import importlib.util

    _utils_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "jewellery_evaluator", "utils.py")
    )
    sys.path.insert(0, os.path.dirname(_utils_path))
    spec = importlib.util.spec_from_file_location("utils", _utils_path)
    utils = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(utils)
    total_carat_for = utils.total_carat_for
    CARAT_DECIMALS = utils.CARAT_DECIMALS


class TestTotalCarat:
    def test_the_canonical_example(self):
        # 0.02 per stone x 10 stones = 0.20 total.
        assert total_carat_for(0.02, 10) == 0.2

    def test_clears_division_float_noise(self):
        # The register wizard stores total/qty, so cps is a repeating decimal.
        # 0.5/85 x 85 = 0.49999999999999994 in float -> must read back as 0.5.
        assert total_carat_for(0.5 / 85, 85) == 0.5
        assert total_carat_for(0.29 / 17, 17) == 0.29

    def test_single_stone_is_its_own_total(self):
        assert total_carat_for(1.01, 1) == 1.01

    def test_six_decimal_precision_is_kept(self):
        # The new per-stone precision floor is 0.000001.
        assert total_carat_for(0.000001, 1) == 0.000001
        assert total_carat_for(0.000001, 22) == 0.000022

    def test_rounds_to_six_decimals(self):
        assert CARAT_DECIMALS == 6
        # 1/3 ct per stone x 3 = 1.0 (not 0.999999)
        assert total_carat_for(1 / 3, 3) == 1.0
        # a 7th decimal is rounded away
        assert total_carat_for(0.00000149, 1) == 0.000001

    def test_zero_and_negative_are_zero(self):
        assert total_carat_for(0, 10) == 0.0
        assert total_carat_for(-1.0, 5) == 0.0
        assert total_carat_for(1.0, 0) == 0.0
        assert total_carat_for(1.0, -3) == 0.0

    def test_non_numeric_is_zero(self):
        assert total_carat_for(None, 10) == 0.0
        assert total_carat_for("abc", 10) == 0.0
