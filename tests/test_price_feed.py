# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""price_from_feed: reading one price from the local price-feed snapshot."""
import importlib.util
import os

import pytest

_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "jewellery_evaluator", "utils.py"))
_spec = importlib.util.spec_from_file_location("utils_feed", _path)
utils = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(utils)

SNAP = {
    "gold_21k": {"ask": 6150.0, "bid": 6130.0},
    "silver_999": {"ask": 102.0, "bid": 98.0},
    "global_market": {"usd_egp": 52.6, "usd_egp_bid": 0.001},
    "age_seconds": 40,
}


def test_reads_ask_by_default():
    assert utils.price_from_feed(SNAP, "gold_21k") == 6150.0


def test_reads_bid_when_asked():
    assert utils.price_from_feed(SNAP, "silver_999", side="bid") == 98.0


def test_usd_comes_from_global_market():
    assert utils.price_from_feed(SNAP, "usd_egp") == 52.6


def test_stale_feed_is_refused():
    with pytest.raises(ValueError, match="stale"):
        utils.price_from_feed({**SNAP, "age_seconds": 4000}, "gold_21k")


def test_missing_age_is_refused():
    snap = {k: v for k, v in SNAP.items() if k != "age_seconds"}
    with pytest.raises(ValueError, match="stale"):
        utils.price_from_feed(snap, "gold_21k")


@pytest.mark.parametrize("value", [None, 0, -5, "abc"])
def test_bad_values_are_refused(value):
    with pytest.raises(ValueError):
        utils.price_from_feed({**SNAP, "gold_21k": {"ask": value}}, "gold_21k")


def test_unknown_side_is_refused():
    with pytest.raises(ValueError, match="side"):
        utils.price_from_feed(SNAP, "gold_21k", side="mid")


def test_not_a_dict_is_refused():
    with pytest.raises(ValueError):
        utils.price_from_feed(None, "gold_21k")
