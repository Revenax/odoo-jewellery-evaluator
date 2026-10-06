# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
{
    'name': 'Payment Provider: Kashier',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Payment Providers',
    'summary': 'Kashier (Egypt) hosted checkout for the website shop: cards and wallets.',
    'description': """
Kashier payment sessions: the customer pays on Kashier's hosted checkout and
returns to the shop. Payments are confirmed only from Kashier's signed
redirect and signed server webhook, both checked with the Payment API Key.
Separate test and live key pairs; the provider's state (Test / Enabled)
picks which pair and which Kashier host is used.
""",
    'author': 'Revenax Digital Services',
    'website': 'https://www.revenax.com',
    'license': 'LGPL-3',
    'depends': ['payment'],
    'data': [
        'views/payment_kashier_templates.xml',
        'views/payment_provider_views.xml',
        'data/payment_provider_data.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
}
