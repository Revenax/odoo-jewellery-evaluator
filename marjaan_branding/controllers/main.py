# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
from odoo.addons.web.controllers.webmanifest import WebManifest

NAVY = '#0f1138'


class MarjaanWebManifest(WebManifest):
    """Installed app (PWA): Marjaan name, navy colours and the Marjaan icon."""

    def _get_webmanifest(self):
        manifest = super()._get_webmanifest()
        manifest.update({'background_color': NAVY, 'theme_color': NAVY})
        manifest['icons'] = [{
            'src': f'/marjaan_branding/static/img/icon-{size}.png',
            'sizes': size,
            'type': 'image/png',
            'purpose': 'any maskable',
        } for size in ('192x192', '512x512')]
        return manifest
