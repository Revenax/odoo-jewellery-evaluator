# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import os
import sys

try:
    from jewellery_evaluator_utils import (
        format_carat,
        format_diamond_note,
        format_weight_g,
    )
except ImportError:
    import importlib.util

    _utils_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "jewellery_evaluator", "utils.py")
    )
    sys.path.insert(0, os.path.dirname(_utils_path))
    spec = importlib.util.spec_from_file_location("utils", _utils_path)
    utils = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(utils)
    format_carat = utils.format_carat
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

    def test_grams_round_to_two_decimals(self):
        # diamond-weight grams are shown to 2 dp like the gold column
        assert format_weight_g(0.202) == "0.2"
        assert format_weight_g(0.076) == "0.08"


class TestFormatCarat:
    def test_keeps_three_decimals(self):
        assert format_carat(0.362) == "0.362"
        assert format_carat(0.024) == "0.024"
        assert format_carat(1.010) == "1.01"


class TestDiamondNote:
    """Format: ``<qty> D<shape> <total>CT``.

    D is diamond, the letter after it is the shape (R = round), and the carat
    is the LINE TOTAL, not the per-stone weight. The old note read
    "15 DR. 0.362", where "DR." was just an abbreviation and 0.362 was the
    weight of ONE stone — so a 15-stone line looked like a 0.362 ct piece.
    """

    def test_the_shape_from_the_real_invoice(self):
        # DBL8-0001 on prod: 17 round stones, 0.017059 ct each, 0.29 ct total.
        assert (
            format_diamond_note(
                [{"carat": 0.017059, "quantity": 17, "shape": "Round"}]
            )
            == "17 DR 0.29CT"
        )

    def test_carat_is_the_total_not_the_per_stone_weight(self):
        # 50 x 0.025 = 1.25 total.
        assert (
            format_diamond_note([{"carat": 0.025, "quantity": 50, "shape": "Round"}])
            == "50 DR 1.25CT"
        )

    def test_single_stone(self):
        assert (
            format_diamond_note([{"carat": 1.01, "quantity": 1, "shape": "Round"}])
            == "1 DR 1.01CT"
        )

    def test_every_shape_has_a_letter(self):
        codes = {
            "Round": "R", "Oval": "O", "Marquise": "M", "Pear": "P",
            "Heart": "H", "Emerald": "E",
            # Two letters ONLY where one would be ambiguous.
            "Princess": "PR", "Radiant": "RA",
        }
        for shape, code in codes.items():
            assert (
                format_diamond_note([{"carat": 1, "quantity": 1, "shape": shape}])
                == f"1 D{code} 1CT"
            )

    def test_pear_and_princess_are_distinguishable(self):
        # Both are in live data (25 and 3 stones); a bare "P" for each would
        # make the invoice ambiguous.
        pear = format_diamond_note([{"carat": 1, "quantity": 2, "shape": "Pear"}])
        princess = format_diamond_note(
            [{"carat": 1, "quantity": 2, "shape": "Princess"}]
        )
        assert pear != princess
        assert pear == "2 DP 2CT"
        assert princess == "2 DPR 2CT"

    def test_round_and_radiant_are_distinguishable(self):
        rnd = format_diamond_note([{"carat": 1, "quantity": 1, "shape": "Round"}])
        rad = format_diamond_note([{"carat": 1, "quantity": 1, "shape": "Radiant"}])
        assert rnd != rad

    def test_multiple_groups_joined(self):
        assert (
            format_diamond_note(
                [
                    {"carat": 1.01, "quantity": 1, "shape": "Round"},
                    {"carat": 0.362, "quantity": 15, "shape": "Pear"},
                ]
            )
            == "1 DR 1.01CT + 15 DP 5.43CT"
        )

    def test_unknown_or_missing_shape_still_renders(self):
        # Never lose the stone off the invoice just because the shape is unset.
        assert format_diamond_note([{"carat": 0.5, "quantity": 2}]) == "2 D 1CT"
        assert (
            format_diamond_note([{"carat": 0.5, "quantity": 2, "shape": "Trilliant"}])
            == "2 D 1CT"
        )

    def test_no_stones_is_empty(self):
        assert format_diamond_note([]) == ""

    def test_missing_quantity_defaults_to_one(self):
        assert format_diamond_note([{"carat": 0.5, "shape": "Round"}]) == "1 DR 0.5CT"
