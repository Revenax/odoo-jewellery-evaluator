# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
from odoo.addons.payment import reset_payment_provider, setup_provider

from . import controllers, models


def post_init_hook(env):
    setup_provider(env, 'kashier')


def uninstall_hook(env):
    reset_payment_provider(env, 'kashier')
