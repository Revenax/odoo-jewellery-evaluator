# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

"""local_eg_phone: every way staff type an Egyptian number ends up as 010..."""
import importlib.util
import os

import pytest

_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "jewellery_evaluator", "utils.py"))
_spec = importlib.util.spec_from_file_location("utils_phone", _path)
utils = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(utils)


@pytest.mark.parametrize("raw", [
    "01063864994", "+201063864994", "+20 106 386 4994", "00201063864994",
    "201063864994", "1063864994", "010-6386-4994", "٠١٠٦٣٨٦٤٩٩٤",
])
def test_mobile_forms(raw):
    assert utils.local_eg_phone(raw) == "01063864994"


def test_landline_with_country_code():
    assert utils.local_eg_phone("+20 2 26357935") == "0226357935"


@pytest.mark.parametrize("raw", ["+966 55 103 8650", "0100990002", "011114111300", "010", ""])
def test_not_egyptian_or_invalid_unchanged(raw):
    assert utils.local_eg_phone(raw) == raw
