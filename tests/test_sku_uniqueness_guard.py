# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""The Python and Postgres spellings of a unique-piece SKU must agree.

`ProductTemplate.init` builds a partial UNIQUE index whose predicate uses
SERIAL_SKU_SQL_REGEX. If that ever drifts from `_SERIAL_SKU_RE` the index would
silently cover the wrong rows -- either missing real duplicates or refusing
legitimate sell-by-weight codes. These tests pin them together.

Background: 11 SKUs existed twice in Odoo because the ops sync does
`search` then `create` -- a check-then-act race between the registration sync
and the reconcile sweep. Three of them showed 2 on hand for a ONE-OF-A-KIND
piece. Only a database constraint can close that window.
"""

import importlib.util
import os
import re
import sys

_utils_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "jewellery_evaluator", "utils.py")
)
sys.path.insert(0, os.path.dirname(_utils_path))
_spec = importlib.util.spec_from_file_location("utils", _utils_path)
utils = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(utils)

SERIAL_SKU_SQL_REGEX = utils.SERIAL_SKU_SQL_REGEX
is_serial_sku = utils.is_serial_sku

# Postgres `~` is POSIX; for this pattern Python's re is equivalent.
_SQL_AS_PY = re.compile(SERIAL_SKU_SQL_REGEX)


def _sql_matches(code: str) -> bool:
    return bool(_SQL_AS_PY.search(code))


class TestSerialSkuRegexParity:
    UNIQUE_PIECES = [
        "GRF8-0140", "DRL8-0070A", "DRL8-0070B", "GBF8-0303",
        "GCF8-0039", "DNL8-0034", "DEL8-0009", "GC-BTC-0001",
    ]
    NOT_UNIQUE = [
        "GOLD-SCRAP", "SILVER-BULK", "GB-1000G", "", "BARS-21K",
    ]

    def test_unique_piece_skus_match_both_engines(self):
        for code in self.UNIQUE_PIECES:
            assert is_serial_sku(code), code
            assert _sql_matches(code), f"SQL predicate would miss {code}"

    def test_non_unique_codes_match_neither(self):
        for code in self.NOT_UNIQUE:
            assert not is_serial_sku(code), code
            assert not _sql_matches(code), f"SQL predicate would wrongly cover {code}"

    def test_four_digit_gram_weight_is_not_a_serial(self):
        # -1000G must not be mistaken for a serial, or the index would make two
        # legitimate 1000g bars collide.
        assert not is_serial_sku("GB-1000G")
        assert not _sql_matches("GB-1000G")

    def test_twin_suffix_is_only_a_or_b(self):
        for good in ("DRL8-0082A", "DRL8-0082B"):
            assert is_serial_sku(good) and _sql_matches(good)
        for bad in ("DRL8-0082C", "DRL8-0082Z"):
            assert not is_serial_sku(bad) and not _sql_matches(bad)

    def test_the_two_patterns_agree_on_a_wide_sample(self):
        samples = [
            "X-0001", "X-0001A", "X-0001B", "X-001", "X-00001",
            "ABC-1234", "ABC-1234A", "abc-1234", "-0000", "0000",
            "GRF8-0140 ", " GRF8-0140", "GRF8-0140-EXTRA",
        ]
        for code in samples:
            assert is_serial_sku(code) == _sql_matches(code), code
