# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

"""fold_sold_state: whether a unique piece is sold, for the ops-app sold sync."""
import importlib.util
import os

_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "jewellery_evaluator", "utils.py"))
_spec = importlib.util.spec_from_file_location("utils_sold", _path)
utils = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(utils)


def test_never_sold():
    assert utils.fold_sold_state([]) == {'sold': False, 'sold_at': None, 'sold_ref': None}


def test_sold_once():
    state = utils.fold_sold_state([(1, '2026-10-01', 'Shop/0001')])
    assert state == {'sold': True, 'sold_at': '2026-10-01', 'sold_ref': 'Shop/0001'}


def test_sold_then_refunded_is_back_in_stock():
    state = utils.fold_sold_state([(1, '2026-10-01', 'Shop/0001'), (-1, '2026-10-03', 'Shop/0002')])
    assert state['sold'] is False


def test_resold_after_refund_reports_latest_sale():
    state = utils.fold_sold_state([
        (1, '2026-10-01', 'Shop/0001'),
        (-1, '2026-10-03', 'Shop/0002'),
        (1, '2026-10-05', 'INV/2026/0009'),
    ])
    assert state == {'sold': True, 'sold_at': '2026-10-05', 'sold_ref': 'INV/2026/0009'}


def test_none_quantities_are_ignored():
    assert utils.fold_sold_state([(None, None, None)])['sold'] is False
