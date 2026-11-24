# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
import importlib.util
import os

_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "jewellery_evaluator", "utils.py"))
_spec = importlib.util.spec_from_file_location("utils_session", _path)
utils = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(utils)
next_session_number = utils.next_session_number


def test_first_session_of_branch():
    assert next_session_number([], 'Ismail Ramzy') == 'Ismail Ramzy/00001'


def test_counts_only_own_branch():
    names = ['Sway Mall/00136', 'Ismail Ramzy/00007', 'Ismail Ramzy/x', '/', 'Marjaan Jewellery/00013']
    assert next_session_number(names, 'Ismail Ramzy') == 'Ismail Ramzy/00008'
    assert next_session_number(names, 'Sway Mall') == 'Sway Mall/00137'
