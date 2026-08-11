# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import os
import sys

try:
    from jewellery_evaluator_utils import format_invoice_weight
except ImportError:
    import importlib.util

    _utils_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "jewellery_evaluator", "utils.py")
    )
    sys.path.insert(0, os.path.dirname(_utils_path))
    spec = importlib.util.spec_from_file_location("utils", _utils_path)
    utils = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(utils)
    format_invoice_weight = utils.format_invoice_weight


class TestFormatInvoiceWeight:
    def test_center_stone_is_blank(self):
        # THE exception: a Center Stone is a loose diamond with no gold, so the
        # invoice weight cell is empty — never "0.00".
        assert format_invoice_weight("center_stone", 0) == ""
        assert format_invoice_weight("center_stone", None) == ""
        # Blank even if some weight got stored on the piece.
        assert format_invoice_weight("center_stone", 1.23) == ""

    def test_gold_shows_two_decimals(self):
        assert format_invoice_weight("gold_bars", 10) == "10.00"
        assert format_invoice_weight("gold_local", 4.5) == "4.50"
        assert format_invoice_weight("gold_foreign", 12.345) == "12.35"

    def test_diamond_jewellery_still_shows_weight(self):
        # Only CENTER stone is exempt; a diamond ring has gold and keeps its weight.
        assert format_invoice_weight("diamond_jewellery", 3.2) == "3.20"

    def test_silver_shows_weight(self):
        assert format_invoice_weight("silver", 25.0) == "25.00"

    def test_zero_weight_on_a_gold_line_is_blank_too(self):
        # Nothing useful to print, and "0.00g" on an invoice looks like a bug.
        assert format_invoice_weight("gold_bars", 0) == ""
        assert format_invoice_weight("gold_bars", None) == ""

    def test_unknown_or_missing_type_behaves_normally(self):
        assert format_invoice_weight("", 5) == "5.00"
        assert format_invoice_weight(None, 5) == "5.00"

    def test_junk_weight_is_blank_not_an_error(self):
        assert format_invoice_weight("gold_bars", "abc") == ""
        assert format_invoice_weight("gold_bars", "7.5") == "7.50"
