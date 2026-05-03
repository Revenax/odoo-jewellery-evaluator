# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import logging

from odoo import api, models

from ..utils import parse_silver_price_text  # noqa: E402

_logger = logging.getLogger(__name__)

_PAGE_LOAD_TIMEOUT = 30


def _create_driver():
    """Create a headless Chrome WebDriver (requires selenium + chromium)."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_experimental_option(
        "prefs",
        {
            "profile.managed_default_content_settings.images": 2,
            "profile.default_content_setting_values.images": 2,
        },
    )
    for a in (
        "--disable-extensions",
        "--disable-plugins",
        "--disable-sync",
        "--disable-translate",
        "--disable-background-networking",
        "--no-first-run",
        "--log-level=3",
    ):
        opts.add_argument(a)
    driver = webdriver.Chrome(options=opts)
    driver.implicitly_wait(10)
    return driver


def _scrape_silver_price(page_url: str, xpath_selector: str) -> float:
    """
    Launch headless Chrome, load *page_url*, wait for the element at
    *xpath_selector* to render a non-placeholder value, then return its first
    numeric token as a float.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    driver = _create_driver()
    try:
        driver.get(page_url)

        def _text_ready(drv):
            element = drv.find_element(By.XPATH, xpath_selector)
            text = element.text.strip() if element.text else ""
            return element if text and text != "--" else False

        element = WebDriverWait(driver, _PAGE_LOAD_TIMEOUT).until(_text_ready)
        return parse_silver_price_text(element.text)
    finally:
        driver.quit()


class SilverPriceService(models.Model):
    _name = 'silver.price.service'
    _description = 'Silver Price Service'

    def get_current_silver_price_999(self):
        """
        Get current silver 999 price per gram.

        Reads the cached fallback (the last successfully scraped value). The
        live headless-browser scrape runs only on the cron path
        (``update_all_silver_product_prices``) so opening a product form does
        not spawn Chrome. If you need a fresh value immediately, run the
        scheduled action "Update Silver Prices" manually.

        :return: float - Silver 999 price per gram (0.0 if not yet scraped)
        """
        return self._get_fallback_silver_price()

    def _fetch_silver_price_from_web(self):
        """
        Fetch silver 999 price by loading the configured page in a headless
        browser and reading the cell at the configured XPath selector.

        On success, the parsed price is written to the silver fallback parameter
        (mirrors the gold fetch flow).

        :return: float - Silver 999 price per gram
        """
        ICP = self.env['ir.config_parameter'].sudo()
        page_url = ICP.get_param('jewellery_evaluator.silver_page_url', '')
        xpath_selector = ICP.get_param(
            'jewellery_evaluator.silver_xpath_selector', ''
        )

        if not page_url or not page_url.strip():
            raise ValueError(
                'Silver page URL is not configured. '
                'Please set the "jewellery_evaluator.silver_page_url" system parameter in '
                'Settings → Technical → Parameters → System Parameters'
            )

        if not xpath_selector or not xpath_selector.strip():
            raise ValueError(
                'Silver 999 XPath selector is not configured. '
                'Please set the "jewellery_evaluator.silver_xpath_selector" system parameter in '
                'Settings → Technical → Parameters → System Parameters'
            )

        # Validate URL is HTTP/HTTPS (mirrors gold endpoint validation)
        has_http = page_url.startswith('http://')
        has_https = page_url.startswith('https://')
        if not (has_http or has_https):
            raise ValueError(
                'Silver page URL must be a valid HTTP/HTTPS URL. '
                f'Current value: {page_url[:50]}...'
            )

        try:
            price = _scrape_silver_price(page_url, xpath_selector)
        except ImportError as e:
            _logger.error(
                'Selenium is not installed — cannot auto-fetch silver price. '
                'Install with: pip install selenium'
            )
            raise ValueError(
                'Silver scrape requires selenium. Install it on the Odoo host.'
            ) from e
        except ValueError:
            # parse_silver_price_text already produced a useful message
            raise
        except Exception as e:
            _logger.error(
                'Selenium silver price scrape failed: %s', e, exc_info=True)
            raise ValueError(
                f'Silver scrape failed: {type(e).__name__}'
            ) from e

        ICP.set_param('jewellery_evaluator.silver_fallback_price', str(price))
        _logger.info('Silver price fetched: %s; fallback price updated', price)
        return price

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
    def update_all_silver_product_prices(self):
        """
        Update prices for all silver products.
        Called by cron job every 10 minutes.

        :return: dict - Execution summary
        """
        _logger.info('Starting silver price update for all products')

        try:
            try:
                base_silver_price = self._fetch_silver_price_from_web()
            except Exception as e:
                _logger.warning(
                    'Live silver scrape failed (%s); falling back to stored value.',
                    str(e),
                )
                base_silver_price = self._get_fallback_silver_price()

            if base_silver_price <= 0:
                _logger.warning(
                    'Silver price is 0 — neither live scrape nor stored fallback available.'
                )
                return {
                    'success': True,
                    'products_updated': 0,
                    'base_price': 0.0,
                    'message': 'Silver price not configured',
                }

            _logger.info('Fetched silver price: %s per gram', base_silver_price)

            silver_products = self.env['product.template'].search([
                ('jewellery_type', '=', 'silver'),
                ('silver_purity', '!=', False),
                ('jewellery_weight_g', '>', 0),
            ])

            if not silver_products:
                _logger.info('No silver products found to update')
                return {
                    'success': True,
                    'products_updated': 0,
                    'base_price': base_silver_price,
                    'message': 'No silver products found',
                }

            batch_size = 100
            total_updated = 0

            for i in range(0, len(silver_products), batch_size):
                batch = silver_products[i:i + batch_size]
                batch.update_silver_prices(base_silver_price)
                total_updated += len(batch)
                _logger.info('Updated batch: %d products (total: %d)',
                             len(batch), total_updated)

            _logger.info(
                'Silver price update completed: %d products updated with base price %s',
                total_updated,
                base_silver_price
            )

            return {
                'success': True,
                'products_updated': total_updated,
                'base_price': base_silver_price,
                'message': f'Successfully updated {total_updated} products',
            }

        except Exception as e:
            _logger.error('Silver price update failed: %s',
                          str(e), exc_info=True)
            return {
                'success': False,
                'products_updated': 0,
                'base_price': None,
                'message': f'Update failed: {str(e)}',
                'error': str(e),
            }
