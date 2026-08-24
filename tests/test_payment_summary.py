# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""How a sale's payment methods read in a notification.

Marjaan takes Cash, InstaPay, Card and Customer Account, and a single sale can
be split across them. On a lock screen the method matters as much as the
amount — "paid in cash" and "paid by InstaPay" have very different
implications for the drawer — so it goes in the body, not just the data.
"""

import os
import sys

try:
    from jewellery_evaluator_utils import format_payment_summary
except ImportError:
    import importlib.util

    _utils_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "jewellery_evaluator", "utils.py")
    )
    sys.path.insert(0, os.path.dirname(_utils_path))
    spec = importlib.util.spec_from_file_location("utils", _utils_path)
    utils = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(utils)
    format_payment_summary = utils.format_payment_summary


class TestFormatPaymentSummary:
    def test_a_single_method_is_just_its_name(self):
        # The overwhelmingly common case; an amount here would only repeat the
        # order total already in the message.
        assert format_payment_summary([("InstaPay", 26800.0)]) == "InstaPay"
        assert format_payment_summary([("Cash", 5000.0)]) == "Cash"

    def test_a_split_payment_shows_each_amount(self):
        # Here the split IS the information — which part hit the drawer.
        # Ordered by size, not by how the cashier happened to tender them.
        assert (
            format_payment_summary([("Cash", 5000.0), ("InstaPay", 20000.0)])
            == "InstaPay 20,000 + Cash 5,000"
        )

    def test_same_method_twice_is_merged(self):
        # Two cash tenders are one cash payment as far as a reader cares.
        assert format_payment_summary([("Cash", 1000.0), ("Cash", 500.0)]) == "Cash"

    def test_merged_split_keeps_the_combined_amount(self):
        assert (
            format_payment_summary(
                [("Cash", 1000.0), ("InstaPay", 2000.0), ("Cash", 500.0)]
            )
            == "InstaPay 2,000 + Cash 1,500"
        )

    def test_order_follows_the_largest_amount_first(self):
        assert (
            format_payment_summary([("Cash", 100.0), ("InstaPay", 900.0)])
            == "InstaPay 900 + Cash 100"
        )

    def test_no_payments_is_empty_not_a_crash(self):
        # An unpaid or draft order must not break the notification.
        assert format_payment_summary([]) == ""
        assert format_payment_summary(None) == ""

    def test_refund_amounts_are_shown_absolute(self):
        # A return carries negative payments; "-5,000" reads as a typo next to
        # a refund total that is already stated positively.
        assert format_payment_summary([("Cash", -5000.0)]) == "Cash"
        assert (
            format_payment_summary([("Cash", -1000.0), ("InstaPay", -2000.0)])
            == "InstaPay 2,000 + Cash 1,000"
        )

    def test_junk_entries_are_skipped(self):
        assert format_payment_summary([(None, 100.0), ("Cash", 50.0)]) == "Cash"
        assert format_payment_summary([("", 100.0)]) == ""
