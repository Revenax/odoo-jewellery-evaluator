# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
import re

from jewellery_evaluator_utils import badge_key

URL = 'https://www.revenax.com/contact/mohamed-a-abdallah'


def test_plain_badges_are_kept():
    assert badge_key('041123456789') == '041123456789'
    assert badge_key(' ABC123 ') == 'ABC123'


def test_link_badge_is_a_valid_odoo_badge():
    key = badge_key(URL)
    assert re.fullmatch(r'[A-Za-z0-9]{1,18}', key)
    assert len(key) == 18 and key.startswith('U')


def test_scanner_variations_give_one_key():
    key = badge_key(URL)
    for variant in ('http://www.revenax.com/contact/mohamed-a-abdallah',
                    'https://revenax.com/contact/mohamed-a-abdallah/',
                    '  HTTPS://WWW.REVENAX.COM/contact/mohamed-a-abdallah\n'):
        assert badge_key(variant) == key


def test_other_links_differ_and_empty_is_empty():
    assert badge_key('https://www.revenax.com/contact/someone-else') != badge_key(URL)
    assert badge_key('') == ''
    assert badge_key(None) == ''
    assert badge_key('https://') == ''
