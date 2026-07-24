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

            # Plausibility guard: a source-site layout change can make the regex
            # match a WRONG-but-positive number, which would silently reprice the
            # whole catalog (including the POS floor). Reject a fetched price that
            # jumps more than the configured fraction off the last known-good
            # value; keep the old price and fail the run loudly. The first-ever
            # fetch (no prior value) bootstraps without a bound.
            last_good = self._last_good_gold_price()
            max_jump = self._gold_max_jump_pct()
            if last_good > 0 and max_jump > 0:
                jump = abs(price - last_good) / last_good
                if jump > max_jump:
                    raise ValueError(
                        f'Rejected implausible gold price {price:.2f}: '
                        f'{jump * 100:.0f}% jump from last good {last_good:.2f} '
                        f'(max {max_jump * 100:.0f}%). Kept previous price.'
                    )

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
        Get the cached gold price from system parameters.

        Returns 0.0 (NOT a hardcoded guess) when the cache was never set or is
        invalid, so a misconfigured branch prices gold at 0 — obviously broken —
        instead of the old 75 EGP/g default (~1.5% of the real 21K price), which
        looked plausible and silently sold gold near-free. compute_gold_product_price
        rejects base <= 0, so the model computes 0 prices and logs, never crashes.

        :return: float - Cached gold price per gram, or 0.0 if unavailable.
        """
        fallback_price_str = self.env['ir.config_parameter'].sudo().get_param(
            'jewellery_evaluator.fallback_price',
            '0'
        )
        try:
            fallback_price = float(fallback_price_str)
            if fallback_price <= 0:
                _logger.error(
                    'Gold price cache not configured (%s); gold pricing is '
                    'disabled until the cron fetches a live price.',
                    fallback_price_str
                )
                return 0.0
            return fallback_price
        except (ValueError, TypeError):
            _logger.error(
                'Invalid gold price cache format: %s; gold pricing disabled.',
                fallback_price_str
            )
            return 0.0

    def _last_good_gold_price(self):
        """Last known-good cached price (0.0 if never set), read WITHOUT the
        error logging of _get_fallback_price — used by the plausibility guard."""
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'jewellery_evaluator.fallback_price', '0')
        try:
            value = float(raw)
        except (ValueError, TypeError):
            return 0.0
        return value if value > 0 else 0.0

    def _gold_max_jump_pct(self):
        """Max allowed fractional jump between consecutive fetched gold prices
        (system parameter jewellery_evaluator.gold_price_max_jump_pct, default
        0.35 = 35%). 0 disables the guard."""
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'jewellery_evaluator.gold_price_max_jump_pct', '0.35')
        try:
            value = float(raw)
        except (ValueError, TypeError):
            return 0.35
        return value if value > 0 else 0.0

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
            icp = self.env['ir.config_parameter'].sudo()

            def _num(key, fallback=0.0):
                raw = icp.get_param(key)
                try:
                    return float(raw) if raw not in (None, False, '') else float(fallback)
                except (TypeError, ValueError):
                    return float(fallback)

            # Capture the PAST inputs before anything changes, for the audit log.
            # Gold's past is the cached fallback_price (the fetch below overwrites
            # it). USD rate and the gold making fees (local/foreign per-gram
            # markup) are manual settings the cron never changes, so we stash each
            # run's value in our own params and read them back next run to show the
            # before -> after when they move.
            new_usd = _num('jewellery_evaluator.diamond_exchange_rate_usd')
            new_fee_local = _num('jewellery_evaluator.markup_jewellery_local')
            new_fee_foreign = _num('jewellery_evaluator.markup_jewellery_foreign')
            past_gold = _num('jewellery_evaluator.fallback_price')
            past_usd = _num('jewellery_evaluator.gold_cron_prev_usd', new_usd)
            past_fee_local = _num(
                'jewellery_evaluator.gold_cron_prev_fee_local', new_fee_local)
            past_fee_foreign = _num(
                'jewellery_evaluator.gold_cron_prev_fee_foreign', new_fee_foreign)

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
            # Center Stones (no gold) are included too so exchange-rate/Rap drift
            # keeps their list_price synced.
            diamond_products = self.env['product.template'].search([
                '|',
                '&', '&',
                ('jewellery_type', '=', 'diamond_jewellery'),
                ('gold_purity', '!=', False),
                ('jewellery_weight_g', '>', 0),
                ('jewellery_type', '=', 'center_stone'),
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

            # Remember this run's USD / making fees so the next run can show the move.
            icp.set_param('jewellery_evaluator.gold_cron_prev_usd', new_usd)
            icp.set_param('jewellery_evaluator.gold_cron_prev_fee_local', new_fee_local)
            icp.set_param('jewellery_evaluator.gold_cron_prev_fee_foreign', new_fee_foreign)

            elapsed = time.perf_counter() - start
            summary = (
                f'Gold price cron finished in {elapsed:.2f}s (started {started_at}); '
                f'{updated} updated, {skipped} unchanged '
                f'(of {len(gold_products)} gold + {len(diamond_products)} diamond). '
                f'Gold price {past_gold:g} -> {base_gold_price:g} EGP/g; '
                f'USD {past_usd:g} -> {new_usd:g}; '
                f'making fee (local/foreign) '
                f'{past_fee_local:g}/{past_fee_foreign:g} -> '
                f'{new_fee_local:g}/{new_fee_foreign:g} EGP/g.'
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
