# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Never merge identical products into one POS line.

Marjaan invoices hide the quantity on purpose, so every piece must be its own
line. Odoo merges a re-added product into the existing line whenever the
product's unit of measure has "Group Products in POS" (`is_pos_groupable`) on,
and point_of_sale's own data switches it on for Units, which all 1,602
products use. That is how MJ-1442 (3 x GB-BTC-1G) and MJ-1447/1448
(3 x GB-BTC-5G) became single qty-3 lines.

This is a one-time setting, not code: the Units record is `noupdate`, so a data
file in this module would be skipped on every `-u`, and point_of_sale will not
re-enable it on upgrade for the same reason. hooks.post_init_hook does the same
on a fresh install.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    units = env.ref('uom.product_uom_unit', raise_if_not_found=False)
    if units and units.is_pos_groupable:
        units.is_pos_groupable = False
        _logger.info("POS line grouping turned off for UoM %s", units.name)
