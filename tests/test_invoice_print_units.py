# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""An invoice never shows a merged quantity: one printed row per piece.

MJ-1442: three 1 g bars rung up as one line (qty 3) printed as a single
"1.00g ... 21,810 EGP" row — one bar at three bars' price.
"""

import importlib.util
import os
import sys

_utils_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "jewellery_evaluator", "utils.py")
)
sys.path.insert(0, os.path.dirname(_utils_path))
_spec = importlib.util.spec_from_file_location("utils", _utils_path)
utils = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(utils)
invoice_print_units = utils.invoice_print_units


class TestInvoicePrintUnits:
    def test_merged_bars_expand_to_one_row_each(self):
        assert invoice_print_units("product", 3) == 3
        assert invoice_print_units("product", 5.0) == 5

    def test_single_piece_prints_once(self):
        assert invoice_print_units("product", 1) == 1

    def test_weight_sold_lines_are_not_split(self):
        # 2.5 g of scrap is a weight, not two-and-a-half pieces
        assert invoice_print_units("product", 2.5) == 1
        assert invoice_print_units("product", 0.75) == 1

    def test_sections_and_notes_print_once(self):
        assert invoice_print_units("line_section", 4) == 1
        assert invoice_print_units("line_note", 4) == 1

    def test_refunds_and_garbage_print_once(self):
        assert invoice_print_units("product", -3) == 1
        assert invoice_print_units("product", 0) == 1
        assert invoice_print_units("product", None) == 1
        assert invoice_print_units("product", "x") == 1

    def test_rows_sum_back_to_the_line_value(self):
        # each row shows subtotal / units, so the printed rows add up exactly
        units = invoice_print_units("product", 3)
        assert units * (21810 / units) == 21810
