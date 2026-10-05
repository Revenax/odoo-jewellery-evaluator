# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
from . import controllers, models


def post_init_hook(env):
    """Build the category tree and publish the catalogue straight away."""
    env['product.template'].cron_sync_website_catalog()
