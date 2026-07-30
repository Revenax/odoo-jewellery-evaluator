# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import os
import sys

try:
    from jewellery_evaluator_utils import jewellery_line_description
except ImportError:
    import importlib.util

    _utils_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "jewellery_evaluator", "utils.py")
    )
    sys.path.insert(0, os.path.dirname(_utils_path))
    spec = importlib.util.spec_from_file_location("utils", _utils_path)
    utils = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(utils)
    jewellery_line_description = utils.jewellery_line_description


class TestJewelleryLineDescription:
    def test_flat_category_name_with_slash(self):
        # PROD SHAPE: a single category literally NAMED "Gold / Coin" whose
        # parent_id is None. The old report walked parent_id, got None, and
        # printed the raw "[SKU] SKU" line name on a customer invoice.
        assert jewellery_line_description("Gold / Coin") == "Gold Coin"
        assert jewellery_line_description("Gold / Bar") == "Gold Bar"
        assert jewellery_line_description("Diamond / Twin Ring") == "Diamond Twin Ring"
        assert jewellery_line_description("Silver / Ring") == "Silver Ring"

    def test_real_two_level_hierarchy(self):
        # complete_name is identical for a genuine parent/child tree, so the
        # same rule covers both shapes.
        assert jewellery_line_description("Gold / Earrings") == "Gold Earrings"

    def test_deeper_nesting_uses_the_last_two_levels(self):
        assert jewellery_line_description("All / Saleable / Gold / Coin") == "Gold Coin"

    def test_non_jewellery_category_returns_none(self):
        # Falls back to the normal Odoo line name for anything not ours.
        assert jewellery_line_description("All") is None
        assert jewellery_line_description("Services / Consulting") is None
        assert jewellery_line_description("Expenses") is None

    def test_blank_and_none(self):
        assert jewellery_line_description("") is None
        assert jewellery_line_description(None) is None

    def test_whitespace_tolerant(self):
        assert jewellery_line_description("Gold /Coin") == "Gold Coin"
        assert jewellery_line_description("  Gold / Coin  ") == "Gold Coin"

    def test_material_alone_is_not_enough(self):
        # "Gold" with no shape gives nothing to describe.
        assert jewellery_line_description("Gold") is None
