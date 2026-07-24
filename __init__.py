# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

# Only when loaded as a package by Odoo (addons path = parent of this repo).
# When the repo dir has hyphens (e.g. odoo-jewellery-evaluator), pytest/mypy
# may load this file without a parent package; then "from . import ..." would fail.
if __package__:
    from . import jewellery_evaluator  # noqa: F401
    from .jewellery_evaluator.hooks import post_init_hook  # noqa: F401
