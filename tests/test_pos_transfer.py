# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

"""POS Transfer helper: which way the pieces move, and the totals staff weigh against."""
import importlib.util
import os

import pytest

_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "jewellery_evaluator", "utils.py"))
_spec = importlib.util.spec_from_file_location("utils_transfer", _path)
utils = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(utils)


def test_send_goes_from_the_register():
    assert utils.transfer_route("send", 5, 40) == (5, 40)


def test_receive_comes_into_the_register():
    assert utils.transfer_route("receive", 5, 40) == (40, 5)


def test_unknown_direction_is_refused():
    with pytest.raises(ValueError):
        utils.transfer_route("swap", 5, 40)


def test_totals_count_each_unit():
    pieces = [
        {"qty": 1, "jewellery": 2.43, "net_gold": 2.4, "stones": 0.03, "reading": 2.49},
        {"qty": 3, "jewellery": 10, "net_gold": 10, "stones": 0, "reading": 10.06},
    ]
    totals = utils.transfer_totals(pieces)
    assert totals["pieces"] == 2
    assert totals["units"] == 4
    assert totals["jewellery"] == 32.43
    assert totals["net_gold"] == 32.4
    assert totals["stones"] == 0.03
    assert totals["reading"] == 32.67


def test_totals_of_nothing():
    assert utils.transfer_totals([]) == {
        "pieces": 0, "units": 0.0, "jewellery": 0.0, "net_gold": 0.0, "stones": 0.0, "reading": 0.0}


def test_missing_weights_count_as_zero():
    assert utils.transfer_totals([{"qty": 1}])["jewellery"] == 0.0
