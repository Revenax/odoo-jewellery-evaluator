# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import logging
import time

import requests
from odoo import api, fields, models

from ..utils import parse_gold_price_with_regex  # noqa: E402

_logger = logging.getLogger(__name__)


class GoldPriceService(models.Model):
    _name = 'gold.price.service'
    _description = 'Gold Price Service'

    def get_current_gold_price(self):
        """
        Get current 21K gold price per gram in base currency.

        Reads the cron-maintained cache (``jewellery_evaluator.fallback_price``)
        instead of hitting the external API. The price-update cron
        (:meth:`update_all_gold_product_prices`, every 10 min) is the *only* path
        that fetches live and refreshes that cache, so the ``@api.depends`` price
        computations on ``product.template`` (and POS min-price enforcement) stay
        instant and never block a record create/write on a network round-trip.

        A live fetch here used to cost ~0.4s per call and fired ~4x per product
        create (~1.6s); the price only changes every 10 min, so the cache is the
        correct source for compute paths. ``get_param`` is itself framework-cached
        (and invalidated when the cron writes the value), so repeated calls within
        one request share a single read.

        Note: the API/cache returns the 21K price, which must be converted for
        other purities.

        :return: float - 21K gold price per gram
        """
        return self._get_fallback_price()

    def _fetch_gold_price_from_api(self):
        """
        Fetch gold price from external API via GET request.
        On HTTP 200, treats the response body as HTML/text and extracts the 21K
        price using the configurable regex from settings (Gold 21K Regex Formula).

        :return: float - Gold price per gram (21K price)
        """
        api_endpoint = self.env['ir.config_parameter'].sudo().get_param(
            'jewellery_evaluator.gold_api_endpoint',
            ''
        )
        regex_formula = self.env['ir.config_parameter'].sudo().get_param(
            'jewellery_evaluator.gold_21k_regex_formula',
            ''
        )

        if not api_endpoint or not api_endpoint.strip():
            raise ValueError(
                'Gold API endpoint is not configured. '
                'Please set the "jewellery_evaluator.gold_api_endpoint" system parameter in '
                'Settings → Technical → Parameters → System Parameters'
            )

        if not regex_formula or not regex_formula.strip():
            raise ValueError(
                'Gold 21K regex formula is not configured. '
                'Please set the "jewellery_evaluator.gold_21k_regex_formula" system parameter in '
                'Settings → Technical → Parameters → System Parameters'
            )

        # Validate endpoint is a valid URL format
        has_http = api_endpoint.startswith('http://')
        has_https = api_endpoint.startswith('https://')
        if not (has_http or has_https):
            raise ValueError(
                'Gold API endpoint must be a valid HTTP/HTTPS URL. '
                f'Current value: {api_endpoint[:50]}...'
            )

        timeout = 10
        headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
        }

        try:
            response = requests.get(
                api_endpoint,
                headers=headers,
                timeout=timeout
            )
            response.raise_for_status()

            text = response.text
            price = parse_gold_price_with_regex(text, regex_formula)
            self.env['ir.config_parameter'].sudo().set_param(
                'jewellery_evaluator.fallback_price',
                str(price),
            )
            _logger.info(
                'Gold price fetched: %s; fallback price updated', price)
            return price

        except requests.exceptions.Timeout as e:
            _logger.error('API request timed out after %d seconds', timeout)
            raise ValueError(
                'Gold API request timed out. Please check network connectivity.') from e
        except requests.exceptions.ConnectionError as e:
            _logger.error('Failed to connect to gold API endpoint')
            raise ValueError(
                'Failed to connect to gold API. Please check endpoint configuration.') from e
        except requests.exceptions.HTTPError as e:
            _logger.error('API returned HTTP error: %d',
                          e.response.status_code)
            raise ValueError(
                f'Gold API returned error status {e.response.status_code}') from e
        except requests.exceptions.RequestException as e:
            _logger.error('API request failed: %s', type(e).__name__)
            raise ValueError(
                'Gold API request failed. Please check configuration and network.') from e
        except ValueError as e:
            _logger.error('Invalid API response or regex: %s', str(e))
            raise
        except (KeyError, AttributeError) as e:
            _logger.error(
                'Unexpected error parsing API response: %s', type(e).__name__)
            raise ValueError(
                'Unexpected error while parsing gold API response.') from e

    def _get_fallback_price(self):
        """
        Get fallback gold price from system parameters.
        Used when API is unavailable.

        :return: float - Fallback gold price per gram
        :raises ValueError: If fallback price is invalid
        """
        fallback_price_str = self.env['ir.config_parameter'].sudo().get_param(
            'jewellery_evaluator.fallback_price',
            '75.0'  # Default fallback price
        )
        try:
            fallback_price = float(fallback_price_str)
            if fallback_price <= 0:
                _logger.warning(
                    'Invalid fallback price configured: %s. Using default 75.0',
                    fallback_price_str
                )
                return 75.0
            return fallback_price
        except (ValueError, TypeError):
            _logger.warning(
                'Invalid fallback price format: %s. Using default 75.0',
                fallback_price_str
            )
            return 75.0

    def _cron_log(self, message, level='INFO'):
        """Write a UI-visible run entry to Settings > Technical > Logging so the
        gold cron's start/end is auditable without tailing the server log."""
        self.env['ir.logging'].sudo().create({
            'name': 'jewellery_evaluator.gold_price_cron',
            'type': 'server',
            'dbname': self.env.cr.dbname,
            'level': level,
            'message': message,
            'path': self._name,
            'func': 'update_all_gold_product_prices',
            'line': '0',
        })

    @api.model
    def update_all_gold_product_prices(self):
        """
        Update prices for all gold and diamond products. Called by cron.

        Only products whose sale price moved by at least the configured threshold
        (``product.template._price_update_threshold``) are written, so a flat or
        rounding-stable run is a cheap no-op. Every run is logged to the server
        log; an ir.logging entry (Settings > Technical > Logging) is written only
        when a price actually changed or on error — so 1-min no-op runs don't
        flood the table.

        :return: dict - Execution summary
        """
        start = time.perf_counter()
        started_at = fields.Datetime.to_string(fields.Datetime.now())
        _logger.info('[gold-cron] started at %s', started_at)

        try:
            # The cron is the only path that fetches the live price; it also
            # refreshes the jewellery_evaluator.fallback_price cache used by the
            # @api.depends compute methods.
            base_gold_price = self._fetch_gold_price_from_api()

            gold_products = self.env['product.template'].search([
                ('jewellery_type', 'in', [
                 'gold_local', 'gold_foreign', 'gold_bars']),
                ('gold_purity', '!=', False),
                ('jewellery_weight_g', '>', 0),
            ])
            # Diamonds share the same 21K base, so refresh them in the same run.
            diamond_products = self.env['product.template'].search([
                ('jewellery_type', '=', 'diamond_jewellery'),
                ('gold_purity', '!=', False),
                ('jewellery_weight_g', '>', 0),
            ])

            updated = 0
            skipped = 0
            batch_size = 100
            for i in range(0, len(gold_products), batch_size):
                u, s = gold_products[i:i + batch_size].update_gold_prices(
                    base_gold_price)
                updated += u
                skipped += s
            for i in range(0, len(diamond_products), batch_size):
                u, s = diamond_products[i:i + batch_size].update_diamond_jewellery_prices(
                    base_gold_price)
                updated += u
                skipped += s

            elapsed = time.perf_counter() - start
            summary = (
                f'Gold price cron finished in {elapsed:.2f}s '
                f'(started {started_at}) — base {base_gold_price}/g; '
                f'{updated} updated, {skipped} unchanged '
                f'(of {len(gold_products)} gold + {len(diamond_products)} diamond).'
            )
            _logger.info('[gold-cron] %s', summary)
            if updated:
                self._cron_log(summary)

            return {
                'success': True,
                'products_updated': updated,
                'products_skipped': skipped,
                'base_price': base_gold_price,
                'message': summary,
            }

        except Exception as e:
            elapsed = time.perf_counter() - start
            msg = (f'Gold price cron FAILED after {elapsed:.2f}s '
                   f'(started {started_at}): {e}')
            _logger.error('[gold-cron] %s', msg, exc_info=True)
            try:
                self._cron_log(msg, level='ERROR')
            except Exception:
                pass
            return {
                'success': False,
                'products_updated': 0,
                'base_price': None,
                'message': f'Update failed: {str(e)}',
                'error': str(e),
            }
