# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
{
    'name': 'Jewellery Website',
    'version': '19.0.1.2.0',
    'summary': 'Wires the Marjaan eCommerce shop to the live jewellery catalogue',
    'description': """
Keeps the website shop in step with the boutique's stock, so nobody curates it by hand:

* customer-facing titles (products are named by SKU for the till)
* eCommerce categories mirroring the Shopify collections, assigned from each
  product's internal category
* a piece is published while it is in stock with a photo and a price, and taken
  off the moment it sells (unique pieces are one of a kind)
* a jewellery details block (SKU, karat, weight, stones) on the product page
* the homepage featured grid fed from live, published pieces
* analytics: Google Analytics items named by title/SKU, and a consent-gated
  Meta pixel (Website settings) fed by the shop's own ecommerce events
""",
    'author': 'Revenax Digital Services',
    'website': 'https://www.revenax.com',
    'category': 'Website/eCommerce',
    'license': 'LGPL-3',
    'depends': ['jewellery_evaluator', 'website_sale_stock'],
    'data': [
        'data/ir_cron.xml',
        'views/templates.xml',
        'views/snippets.xml',
        'views/tracking.xml',
        'views/res_config_settings_views.xml',
        'views/product_template_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'jewellery_website/static/src/js/meta_pixel_events.js',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
