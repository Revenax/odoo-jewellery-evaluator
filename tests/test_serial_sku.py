# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

"""Unit tests for is_serial_sku — the classifier that marks a product as a
unique jewellery piece (a XXXX-NNNN serial SKU) vs a fungible weight SKU."""

import os
import sys

try:
    from jewellery_evaluator_utils import is_serial_sku
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
    is_serial_sku = utils.is_serial_sku


# --- unique register pieces (PREFIX-NNNN, optional twin letter) -> True --------

def test_gold_ring_serial():
    assert is_serial_sku("GRL1-0001") is True


def test_gold_foreign_serial():
    assert is_serial_sku("GBF8-0001") is True


def test_diamond_serial():
    assert is_serial_sku("DRL8-0001") is True


def test_center_stone_serial():
    # Center Stone SKUs are DS-NNNN (no origin/karat) — still unique.
    assert is_serial_sku("DS-0001") is True


def test_twin_ring_letter_suffix():
    # Paired pieces carry a trailing A/B after the serial.
    assert is_serial_sku("DRL8-0030A") is True
    assert is_serial_sku("DRL8-0030B") is True


def test_serial_coin_and_bar_with_serial():
    # A specifically-serialised coin/bar is a unique piece too.
    assert is_serial_sku("GC-BTC-0001") is True
    assert is_serial_sku("G-BAR-BTC-0002") is True


# --- fungible / non-serial SKUs -> False --------------------------------------

def test_weight_bar_not_serial():
    assert is_serial_sku("GB-BTC-1G") is False
    assert is_serial_sku("GB-KANZI-10.35G") is False


def test_scrap_not_serial():
    assert is_serial_sku("SCRAP-GOLD-24K") is False
    assert is_serial_sku("SCRAP-GOLD-18K") is False


def test_four_digit_gram_weight_not_serial():
    # Defensive: a 1000-gram bar (…-1000G) must NOT be mistaken for a serial
    # piece — the twin suffix is only A/B, never a weight unit like G.
    assert is_serial_sku("GB-BTC-1000G") is False


def test_empty_and_none():
    assert is_serial_sku("") is False
    assert is_serial_sku(None) is False
    assert is_serial_sku(False) is False


def test_three_digit_not_enough():
    # Serial must be at least 4 digits (NNNN) — a 3-digit tail is not a piece SKU.
    assert is_serial_sku("AB-123") is False


def test_two_letter_suffix_not_matched():
    # Only a single optional trailing letter is a valid twin suffix.
    assert is_serial_sku("DRL8-0030AB") is False


def test_lowercase_not_matched():
    # SKUs are uppercase; a lowercase tail is not a valid serial.
    assert is_serial_sku("grl1-0001x") is False
