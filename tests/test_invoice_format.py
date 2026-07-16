# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import os
import sys

try:
    from jewellery_evaluator_utils import format_diamond_note, format_weight_g
except ImportError:
    import importlib.util

    _utils_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "jewellery_evaluator", "utils.py")
    )
    sys.path.insert(0, os.path.dirname(_utils_path))
    spec = importlib.util.spec_from_file_location("utils", _utils_path)
    utils = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(utils)
    format_diamond_note = utils.format_diamond_note
    format_weight_g = utils.format_weight_g


class TestFormatWeight:
    def test_trims_trailing_zeros(self):
        assert format_weight_g(2.70) == "2.7"
        assert format_weight_g(0.200) == "0.2"
        assert format_weight_g(1.010) == "1.01"

    def test_whole_number(self):
        assert format_weight_g(3.0) == "3"

    def test_zero_and_none(self):
        assert format_weight_g(0) == "0"
        assert format_weight_g(None) == "0"

    def test_keeps_three_decimals(self):
        assert format_weight_g(0.362) == "0.362"


class TestDiamondNote:
    def test_single_stone(self):
        # matches the invoice: 'Diamond 1.01 CR'
        assert format_diamond_note([{"carat": 1.01, "quantity": 1}]) == "Diamond 1.01 CR"

    def test_group_of_identical_stones(self):
        # matches the invoice: 'Diamond 15 DR. 0.362'
        assert (
            format_diamond_note([{"carat": 0.362, "quantity": 15}])
            == "Diamond 15 DR. 0.362"
        )

    def test_multiple_groups_joined(self):
        assert (
            format_diamond_note(
                [{"carat": 1.01, "quantity": 1}, {"carat": 0.362, "quantity": 15}]
            )
            == "Diamond 1.01 CR + 15 DR. 0.362"
        )

    def test_no_stones_is_empty(self):
        assert format_diamond_note([]) == ""

    def test_missing_quantity_defaults_to_one(self):
        assert format_diamond_note([{"carat": 0.5}]) == "Diamond 0.5 CR"
