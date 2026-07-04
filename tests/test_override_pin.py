# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import hashlib
import os
import sys

# Import utils from conftest-loaded module or load directly
try:
    from jewellery_evaluator_utils import sha1_hex
except ImportError:
    # Fallback: load directly
    import importlib.util

    _project_root = os.path.join(os.path.dirname(__file__), '..')
    sys.path.insert(0, os.path.abspath(_project_root))

    _utils_path = os.path.join(os.path.dirname(
        __file__), "..", "jewellery_evaluator", "utils.py")
    _utils_path = os.path.abspath(_utils_path)

    spec = importlib.util.spec_from_file_location("utils", _utils_path)
    utils = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(utils)
    sha1_hex = utils.sha1_hex


def test_sha1_hex_matches_plain_sha1():
    # Must equal the POS Sha1.hash() scheme: unsalted sha1 hex of the raw string.
    assert sha1_hex("1234") == hashlib.sha1(b"1234").hexdigest()


def test_sha1_hex_is_hex_and_40_chars():
    h = sha1_hex("1234567890123456")
    assert len(h) == 40
    assert all(c in "0123456789abcdef" for c in h)


def test_sha1_hex_strips_whitespace():
    # A badge scanner / keypad may append whitespace; the register trims too.
    assert sha1_hex("  1234  ") == sha1_hex("1234")


def test_sha1_hex_empty_returns_empty():
    assert sha1_hex("") == ""
    assert sha1_hex("   ") == ""
    assert sha1_hex(None) == ""


def test_sha1_hex_distinct_inputs_distinct_hashes():
    assert sha1_hex("1234") != sha1_hex("4321")
