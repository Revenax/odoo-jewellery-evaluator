# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Day names for NOTIFICATIONS, which must never contain Arabic.

The POS day book is deliberately Arabic — it mirrors the paper ledger. But a
notification lands on a lock screen, in an inbox and in a browser toast, none
of which are guaranteed to render or order RTL text correctly, so everything
Pulse sends stays ASCII.
"""

import datetime
import os
import sys

try:
    from jewellery_evaluator_utils import english_day_name
except ImportError:
    import importlib.util

    _utils_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "jewellery_evaluator", "utils.py")
    )
    sys.path.insert(0, os.path.dirname(_utils_path))
    spec = importlib.util.spec_from_file_location("utils", _utils_path)
    utils = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(utils)
    english_day_name = utils.english_day_name


class TestEnglishDayName:
    def test_every_weekday(self):
        # 2026-08-10 is a Monday.
        monday = datetime.date(2026, 8, 10)
        expected = ["Monday", "Tuesday", "Wednesday", "Thursday",
                    "Friday", "Saturday", "Sunday"]
        for offset, name in enumerate(expected):
            assert english_day_name(monday + datetime.timedelta(days=offset)) == name

    def test_matches_the_arabic_book_day(self):
        # The ledger showed السبت for 2026-08-08; the notification must say Saturday.
        assert english_day_name(datetime.date(2026, 8, 8)) == "Saturday"

    def test_accepts_an_iso_string(self):
        assert english_day_name("2026-08-08") == "Saturday"

    def test_output_is_always_ascii(self):
        # The guarantee that matters: nothing here can ever reach a lock screen
        # as Arabic.
        start = datetime.date(2026, 1, 1)
        for offset in range(371):
            name = english_day_name(start + datetime.timedelta(days=offset))
            assert name.isascii(), name
            assert name.isalpha()

    def test_bad_input_is_empty_not_an_exception(self):
        # This feeds a notification; it must never be the reason one fails.
        assert english_day_name(None) == ""
        assert english_day_name("not-a-date") == ""
        assert english_day_name(12345) == ""
