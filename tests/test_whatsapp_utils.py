# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""utils.whatsapp_mobile / format_egp_amount: POS invoice WhatsApp messages."""
import importlib.util
import os

import pytest

_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "jewellery_evaluator", "utils.py"))
_spec = importlib.util.spec_from_file_location("utils_wa", _path)
utils = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(utils)


@pytest.mark.parametrize("raw,expected", [
    ("01063864994", "201063864994"),
    ("+20 106 386 4994", "201063864994"),
    ("0020 106-386-4994", "201063864994"),
    ("201007709545", "201007709545"),
    ("1155555555", "201155555555"),
    ("01255555555", "201255555555"),
    ("01555555555", "201555555555"),
    ("(010) 6386 4994", "201063864994"),
])
def test_valid_egyptian_mobiles(raw, expected):
    assert utils.whatsapp_mobile(raw) == expected


@pytest.mark.parametrize("raw", [
    None, "", "0100990002",          # 10 digits: typo
    "010200562886",                  # 12 digits: typo
    "0166622119",                    # unknown prefix 16
    "0226357935", "+20 2 26357935",  # Cairo landline
    "01363864994",                   # 013 is not a mobile operator
    "abc",
])
def test_rejects_landlines_and_typos(raw):
    assert utils.whatsapp_mobile(raw) == ""


@pytest.mark.parametrize("amount,expected", [
    (13500, "13,500"), (13500.0, "13,500"), (121900, "121,900"), (99.5, "99.50"),
    (1234567.891, "1,234,567.89"), (0, "0"), (None, "0"),
])
def test_format_egp_amount(amount, expected):
    assert utils.format_egp_amount(amount) == expected
