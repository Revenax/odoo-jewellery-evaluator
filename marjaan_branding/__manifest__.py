# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
{
    'name': 'Marjaan Branding',
    'version': '19.0.1.0.0',
    'summary': 'Marjaan look across the backend, POS, app icon and emails',
    'description': """
Replaces Odoo's own branding wherever staff or customers see it:

* browser tab titles read "<page> · Marjaan" and use the Marjaan icon (backend and POS)
* the home menu in Marjaan navy with gold light
* installable app (PWA) named Marjaan, in navy, with the Marjaan icon
* no Odoo "Help" / "My Odoo.com account" entries in the user menu
* "Powered by Revenax" on the login page and in email footers instead of Odoo
""",
    'author': 'Revenax Digital Services',
    'website': 'https://www.revenax.com',
    'category': 'Hidden',
    'license': 'LGPL-3',
    'depends': ['web', 'web_enterprise', 'mail', 'point_of_sale'],
    'data': [
        'views/templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'marjaan_branding/static/src/title_service.js',
            'marjaan_branding/static/src/user_menu.js',
            'marjaan_branding/static/src/home_menu.scss',
        ],
    },
    'installable': True,
    'application': False,
}
