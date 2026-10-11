# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import logging
import time

from odoo import api, fields, models

from .. import pulse
from ..utils import price_from_feed  # noqa: E402

_logger = logging.getLogger(__name__)


class SilverPriceService(models.Model):
    _name = 'silver.price.service'
    _description = 'Silver Price Service'

    def get_current_silver_price_999(self):
        """
        Get current silver 999 price per gram.

        Reads the stored value (the last good price from the local feed). The
        feed is read only on the cron path (``update_all_silver_product_prices``);
        run the scheduled action "Update Silver Prices" for a fresh value.

        :return: float - Silver 999 price per gram (0.0 if not yet scraped)
        """
        return self._get_fallback_silver_price()

    def _fetch_silver_price_from_web(self):
        """
        Silver 999 price from the local price feed. On success it becomes the
        stored fallback price (mirrors the gold fetch flow).

        :return: float - Silver 999 price per gram
        """
        ICP = self.env['ir.config_parameter'].sudo()
        # The only live source: the local price feed (price_feed/edahab_feed.py).
        # The old headless-Chrome scrape was removed on 2026-10-11.
        gold_service = self.env['gold.price.service']
        feed_url = gold_service._price_feed_url()
        if feed_url:
            side = ICP.get_param('jewellery_evaluator.price_feed_side', 'ask')
            price = price_from_feed(gold_service._read_price_feed(feed_url), 'silver_999', side=side)
            ICP.set_param('jewellery_evaluator.silver_fallback_price', str(price))
            _logger.info('Silver price from local feed: %s; fallback price updated', price)
            return price

        raise ValueError(
            'Local price feed is switched off (jewellery_evaluator.price_feed_url); '
            'silver is priced from the stored value.'
        )

    def _get_fallback_silver_price(self):
        """
        Get fallback silver 999 price from system parameters.
        Used when the live scrape is unavailable.

        :return: float - Fallback silver 999 price per gram (0.0 if not configured)
        """
        fallback_price_str = self.env['ir.config_parameter'].sudo().get_param(
            'jewellery_evaluator.silver_fallback_price',
            '0.0'
        )
        try:
            fallback_price = float(
                str(fallback_price_str).replace(',', '').strip()
            )
            if fallback_price < 0:
                _logger.warning(
                    'Invalid fallback silver price configured: %s. Using 0.0',
                    fallback_price_str
                )
                return 0.0
            return fallback_price
        except (ValueError, TypeError):
            _logger.warning(
                'Invalid fallback silver price format: %s. Using 0.0',
                fallback_price_str
            )
            return 0.0

    @api.model
    def set_silver_price_999(self, price_per_gram):
        """Store silver 999 price. Available for external scripts via RPC."""
        if price_per_gram is None or price_per_gram <= 0:
            return
        self.env['ir.config_parameter'].sudo().set_param(
            'jewellery_evaluator.silver_fallback_price', str(price_per_gram)
        )
        _logger.info('Silver 999 price updated: %s per gram', price_per_gram)

    @api.model
    def _cron_log(self, message, level='INFO'):
        """Write a UI-visible run entry to Settings > Technical > Logging so the
        silver cron's start/end is auditable without tailing the server log."""
        self.env['ir.logging'].sudo().create({
            'name': 'jewellery_evaluator.silver_price_cron',
            'type': 'server',
            'dbname': self.env.cr.dbname,
            'level': level,
            'message': message,
            'path': self._name,
            'func': 'update_all_silver_product_prices',
            'line': '0',
        })

    def update_all_silver_product_prices(self):
        """
        Update prices for all silver products. Called by cron.

        Only products whose sale price moved by at least the configured threshold
        (``product.template._price_update_threshold``) are written, so a flat run
        is a cheap no-op. Every run is logged to the server log; an ir.logging
        entry (Settings > Technical > Logging) is written only when a price
        actually changed or on error.

        :return: dict - Execution summary
        """
        start = time.perf_counter()
        started_at = fields.Datetime.to_string(fields.Datetime.now())
        _logger.info('[silver-cron] started at %s', started_at)

        try:
            try:
                base_silver_price = self._fetch_silver_price_from_web()
            except Exception as e:
                _logger.warning(
                    'Silver price feed failed (%s); falling back to stored value.',
                    str(e),
                )
                # Not fatal — we still price from the cache. Hourly idempotency:
                # the cron is frequent.
                pulse.notify_in_background(
                    'vendor-down',
                    'Silver price feed failed',
                    f'The local price feed gave no silver price: {e}. Silver is '
                    f'being priced from the last stored value.',
                    {'vendor': 'price-feed-silver', 'error': str(e)[:500]},
                    pulse.make_idempotency_key(
                        'silver-vendor-down', started_at[:13]),
                    env=self.env,
                )
                base_silver_price = self._get_fallback_silver_price()

            if base_silver_price <= 0:
                msg = ('Silver price cron: no price (live scrape and stored '
                       'fallback both unavailable); nothing updated.')
                _logger.warning('[silver-cron] %s', msg)
                self._cron_log(msg, level='WARNING')
                pulse.notify_in_background(
                    'job-failed',
                    'Silver price unavailable',
                    'Both the live silver scrape and the stored fallback are '
                    'unavailable, so no silver product was repriced.',
                    {'job': 'update_all_silver_product_prices'},
                    pulse.make_idempotency_key(
                        'silver-noprice', started_at[:13]),
                    env=self.env,
                )
                return {
                    'success': True,
                    'products_updated': 0,
                    'base_price': 0.0,
                    'message': msg,
                }

            silver_products = self.env['product.template'].search([
                ('jewellery_type', '=', 'silver'),
                ('silver_purity', '!=', False),
                ('jewellery_weight_g', '>', 0),
            ])

            updated = 0
            skipped = 0
            batch_size = 100
            for i in range(0, len(silver_products), batch_size):
                u, s = silver_products[i:i + batch_size].update_silver_prices(
                    base_silver_price)
                updated += u
                skipped += s

            elapsed = time.perf_counter() - start
            summary = (
                f'Silver price cron finished in {elapsed:.2f}s '
                f'(started {started_at}) — base {base_silver_price}/g; '
                f'{updated} updated, {skipped} unchanged '
                f'(of {len(silver_products)}).'
            )
            _logger.info('[silver-cron] %s', summary)
            if updated:
                self._cron_log(summary)

            return {
                'success': True,
                'products_updated': updated,
                'products_skipped': skipped,
                'base_price': base_silver_price,
                'message': summary,
            }

        except Exception as e:
            elapsed = time.perf_counter() - start
            msg = (f'Silver price cron FAILED after {elapsed:.2f}s '
                   f'(started {started_at}): {e}')
            _logger.error('[silver-cron] %s', msg, exc_info=True)
            try:
                self._cron_log(msg, level='ERROR')
            except Exception:
                pass
            pulse.notify_in_background(
                'job-failed',
                'Silver price update failed',
                f'The silver cron failed after {elapsed:.1f}s. Silver prices '
                f'are frozen at the last good value. {e}',
                {'job': 'update_all_silver_product_prices', 'error': str(e)[:500]},
                pulse.make_idempotency_key(
                    'silver-cron-failed', started_at[:13], str(e)[:60]),
                env=self.env,
            )
            return {
                'success': False,
                'products_updated': 0,
                'base_price': None,
                'message': f'Update failed: {str(e)}',
                'error': str(e),
            }
