# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Online-catalogue rules (jewellery_website/website_utils.py), without Odoo."""

import importlib.util
import os

_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "jewellery_website", "website_utils.py")
)
_spec = importlib.util.spec_from_file_location("website_utils", _path)
wu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wu)


class TestWebsiteTitle:
    def test_gold_piece(self):
        assert wu.website_title("Gold / Ring", "gold_foreign", "18K", 4.45, 0) == "18K Gold Ring · 4.45 g"

    def test_whole_gram_weight_has_no_decimals(self):
        assert wu.website_title("Gold / Bar", "gold_bars", "24K", 10.0, 0) == "24K Gold Bar · 10 g"

    def test_diamond_piece_quotes_carat_not_weight(self):
        assert (
            wu.website_title("Diamond / Ring", "diamond_jewellery", "18K", 5.31, 0.52)
            == "Diamond Ring · 18K Gold · 0.52 ct"
        )

    def test_twin_ring_names_its_half(self):
        assert wu.website_title(
            "Diamond / Twin Ring", "diamond_jewellery", "18K", 4.6, 0.31, "DRL8-0082A"
        ) == "Diamond Twin Ring · 18K Gold · 0.31 ct · Ring A"

    def test_center_stone_is_a_loose_diamond(self):
        assert wu.website_title("Diamond / Center Stone", "center_stone", False, 0, 0.75) == "Loose Diamond · 0.75 ct"

    def test_small_carat_keeps_its_precision(self):
        assert wu.website_title("Diamond / Earrings", "diamond_jewellery", None, 0, 0.045) == "Diamond Earrings · 0.045 ct"

    def test_missing_purity_and_weight_still_reads(self):
        assert wu.website_title("Gold / Chain", "gold_local", None, 0, 0) == "Gold Chain"

    def test_unknown_or_flat_category_gives_none(self):
        assert wu.website_title("Services", None, None, 0, 0) is None
        assert wu.website_title("", None, None, 0, 0) is None
        assert wu.website_title(None, None, None, 0, 0) is None


class TestPublicCategories:
    def test_gold_ring_goes_to_leaf_and_gold_collection(self):
        assert wu.public_category_keys("Gold / Ring") == ["gold_rings", "gold_collection"]

    def test_new_piece_also_in_new_arrivals(self):
        assert wu.public_category_keys("Diamond / Ring", is_new=True) == [
            "diamond_rings", "diamond_collection", "new_arrivals"]

    def test_bars_coins_and_loose_stones_are_not_collections(self):
        assert wu.public_category_keys("Gold / Bar") == ["gold_bars"]
        assert wu.public_category_keys("Gold / Coin") == ["gold_coins"]
        assert wu.public_category_keys("Diamond / Center Stone") == ["loose_diamonds"]

    def test_unmapped_category_is_never_sold_online(self):
        assert wu.public_category_keys("Services") == []
        assert wu.public_category_keys(None) == []

    def test_every_leaf_exists_in_the_tree(self):
        keys = {k for k, *_ in wu.PUBLIC_TREE}
        assert set(wu.CATEGORY_LEAF.values()) <= keys
        assert {"gold_collection", "diamond_collection", "new_arrivals"} <= keys

    def test_tree_parents_are_declared_before_children(self):
        seen = set()
        for key, _name, parent, _seq in wu.PUBLIC_TREE:
            assert parent is None or parent in seen, key
            seen.add(key)


class TestShouldPublish:
    def test_in_stock_with_photo_and_price(self):
        assert wu.should_publish(True, True, True, 28650, 1, True)

    def test_sold_one_of_a_kind_comes_off(self):
        assert not wu.should_publish(True, True, True, 28650, 0, True)

    def test_negative_stock_never_publishes(self):
        # bars were never received into stock, so they read negative
        assert not wu.should_publish(True, True, True, 7270, -36, True)

    def test_no_photo_no_listing(self):
        assert not wu.should_publish(True, True, False, 28650, 1, True)

    def test_zero_price_never_shown(self):
        assert not wu.should_publish(True, True, True, 0, 1, True)

    def test_archived_or_not_for_sale(self):
        assert not wu.should_publish(False, True, True, 1, 1, True)
        assert not wu.should_publish(True, False, True, 1, 1, True)

    def test_unmapped_category(self):
        assert not wu.should_publish(True, True, True, 1, 1, False)


class TestWebOrderSummary:
    def test_pickup_order(self):
        assert wu.web_order_summary(
            "S00012", 514400, "EGP", "Pick up in store", "Sway Mall", "Pay on Site", ["DRL8-0149"], "Sara",
        ) == "S00012 — 514,400 EGP · Pick up in store: Sway Mall · Pay on Site · DRL8-0149 · Sara"

    def test_delivery_without_store_or_payment(self):
        assert wu.web_order_summary(
            "S00013", 16000.4, "EGP", "Standard delivery", "", "", ["GNL8-0001", "GNL8-0002"], "",
        ) == "S00013 — 16,000 EGP · Standard delivery · GNL8-0001, GNL8-0002"

    def test_long_orders_list_five_pieces(self):
        skus = [f"SKU-{i}" for i in range(7)]
        line = wu.web_order_summary("S1", 1, "EGP", "", "", "", skus, "")
        assert line.endswith("SKU-0, SKU-1, SKU-2, SKU-3, SKU-4 +2 more")


class TestWebsitePriceDisplay:
    def test_whole_egp_drops_decimals_and_says_egp(self):
        assert wu.website_price_display(37500.0, 2, "EGP", "LE") == (0, "EGP")

    def test_piastres_keep_the_decimals(self):
        assert wu.website_price_display(37500.25, 2, "EGP", "LE") == (2, "EGP")

    def test_float_noise_still_counts_as_whole(self):
        assert wu.website_price_display(0.1 + 0.2 + 37499.7, 2, "EGP", "LE") == (0, "EGP")

    def test_other_currencies_keep_their_symbol(self):
        assert wu.website_price_display(1200.0, 2, "USD", "$") == (0, "$")
