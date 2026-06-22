# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

"""Unit tests for jewellery weight helpers (diamond grams, weight reading, SKU prefix)."""

import os
import sys

try:
    from jewellery_evaluator_utils import (
        compute_diamond_weight_g,
        compute_sku_prefix,
        compute_weight_reading_g,
    )
except ImportError:
    import importlib.util
    _project_root = os.path.join(os.path.dirname(__file__), '..')
    sys.path.insert(0, os.path.abspath(_project_root))
    _utils_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..",
                     "jewellery_evaluator", "utils.py")
    )
    spec = importlib.util.spec_from_file_location("utils", _utils_path)
    utils = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(utils)
    compute_diamond_weight_g = utils.compute_diamond_weight_g
    compute_sku_prefix = utils.compute_sku_prefix
    compute_weight_reading_g = utils.compute_weight_reading_g


# --- compute_diamond_weight_g -------------------------------------------------

def test_diamond_weight_empty():
    assert compute_diamond_weight_g([]) == 0.0


def test_diamond_weight_single_stone():
    # 1.0 ct × 1 × 0.2 = 0.2 g
    assert compute_diamond_weight_g([(1.0, 1)]) == 0.2


def test_diamond_weight_quantity_multiplier():
    # 0.5 ct × 4 × 0.2 = 0.4 g
    assert compute_diamond_weight_g([(0.5, 4)]) == 0.4


def test_diamond_weight_multi_stone():
    # (0.5×2 + 0.25×4) × 0.2 = (1.0 + 1.0) × 0.2 = 0.4 g
    assert compute_diamond_weight_g([(0.5, 2), (0.25, 4)]) == 0.4


def test_diamond_weight_rounds_to_3dp():
    # 0.333 ct × 1 × 0.2 = 0.0666 → 0.067 g
    assert compute_diamond_weight_g([(0.333, 1)]) == 0.067


# --- compute_weight_reading_g -------------------------------------------------

def test_weight_reading_adds_ticket():
    assert compute_weight_reading_g(5.0, 0.06) == 5.06


def test_weight_reading_zero_gross():
    assert compute_weight_reading_g(0.0, 0.06) == 0.06


# --- compute_sku_prefix -------------------------------------------------------

def test_sku_prefix_basic():
    assert compute_sku_prefix('RING-18K-001') == 'RING'


def test_sku_prefix_single_dash():
    assert compute_sku_prefix('NECK-A') == 'NECK'


def test_sku_prefix_no_dash():
    assert compute_sku_prefix('PLAIN') == 'PLAIN'


def test_sku_prefix_leading_dash():
    assert compute_sku_prefix('-X') == ''


def test_sku_prefix_empty():
    assert compute_sku_prefix('') == ''


def test_sku_prefix_none():
    assert compute_sku_prefix(None) == ''
