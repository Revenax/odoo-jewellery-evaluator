# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import os
import sys

# Import utils from conftest-loaded module or load directly
try:
    from jewellery_evaluator_utils import compute_gold_product_price  # noqa: F401
except ImportError:
    # Fallback: load directly
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
    compute_gold_product_price = utils.compute_gold_product_price


def test_compute_21k_price():
    """Test price computation for 21K gold."""
    cost, sale, min_sale = compute_gold_product_price(
        100.0, '21K', 10.0, 5.0
    )
    assert cost == 1000.0
    assert sale == 1050.0
    # min_sale = 1035 rounded to nearest 50 = 1050
    assert min_sale == 1050.0


def test_compute_24k_price():
    """Test price computation for 24K gold (24K = 8/7 of 21K)."""
    cost, sale, min_sale = compute_gold_product_price(
        100.0, '24K', 1.0, 10.0
    )
    # 24K factor 8/7: cost = 100 * 8/7 = 114.29, sale = 124.29 rounded to 50 = 100
    assert abs(cost - 114.29) < 0.01
    assert sale == 100.0


def test_compute_18k_price():
    """Test price computation for 18K gold (18K = 7/8 of 21K)."""
    cost, sale, min_sale = compute_gold_product_price(
        100.0, '18K', 8.0, 5.0
    )
    # 18K factor 7/8: cost = 700, sale = 740 rounded to 50 = 750, min_sale = 728 rounded to 50 = 750
    assert cost == 700.0
    assert sale == 750.0
    assert min_sale == 750.0


def test_zero_markup():
    """Test computation with zero markup."""
    cost, sale, min_sale = compute_gold_product_price(
        100.0, '21K', 10.0, 0.0
    )
    assert cost == 1000.0
    assert sale == 1000.0
    assert min_sale == 1000.0


def test_min_making_fee_sets_floor():
    """An explicit minimum making fee makes the floor = cost + min_fee × weight."""
    cost, sale, min_sale = compute_gold_product_price(
        100.0, '21K', 10.0, 50.0, min_markup_per_gram=30.0
    )
    assert cost == 1000.0
    assert sale == 1500.0          # cost + 50 × 10
    assert min_sale == 1300.0      # cost + 30 × 10 (NOT 70% of markup)


def test_min_making_fee_default_falls_back_to_70_percent():
    """No minimum making fee (default/0) keeps the legacy cost + 70% markup."""
    _, _, min_default = compute_gold_product_price(100.0, '21K', 10.0, 50.0)
    _, _, min_zero = compute_gold_product_price(
        100.0, '21K', 10.0, 50.0, min_markup_per_gram=0.0
    )
    # markup_total = 500; min = 1000 + 0.7 × 500 = 1350
    assert min_default == 1350.0
    assert min_zero == 1350.0


def test_invalid_purity_raises_error():
    """Test that invalid purity raises ValueError."""
    try:
        compute_gold_product_price(100.0, '99K', 10.0, 5.0)
        raise AssertionError("Should have raised ValueError")
    except ValueError as e:
        assert "Invalid purity" in str(e)


def test_legacy_14k_purity_raises_error():
    """Test that legacy 14K purity is no longer supported."""
    try:
        compute_gold_product_price(100.0, '14K', 10.0, 5.0)
        raise AssertionError("Should have raised ValueError")
    except ValueError as e:
        assert "Invalid purity" in str(e)


def test_zero_weight_raises_error():
    """Test that zero weight raises ValueError."""
    try:
        compute_gold_product_price(100.0, '21K', 0.0, 5.0)
        raise AssertionError("Should have raised ValueError")
    except ValueError as e:
        assert "Weight must be greater than 0" in str(e)


def test_negative_markup_raises_error():
    """Test that negative markup raises ValueError."""
    try:
        compute_gold_product_price(100.0, '21K', 10.0, -5.0)
        raise AssertionError("Should have raised ValueError")
    except ValueError as e:
        assert "Markup cannot be negative" in str(e)
