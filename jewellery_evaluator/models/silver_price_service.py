# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import logging
import time

from odoo import api, fields, models

from ..utils import parse_silver_price_text  # noqa: E402

_logger = logging.getLogger(__name__)

_PAGE_LOAD_TIMEOUT = 30


_SYSTEM_CHROME_CANDIDATES = (
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)


def _find_system_chrome():
    import os
    for path in _SYSTEM_CHROME_CANDIDATES:
        if os.path.exists(path) and os.access(path, os.X_OK):
            return path
    return None


def _detect_chrome_version(browser_path: str) -> str | None:
    """Return the major version string of the Chrome at *browser_path*, e.g. '147'."""
    import re
    import subprocess
    try:
        out = subprocess.run(
            [browser_path, '--version'],
            capture_output=True, text=True, timeout=10, check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    m = re.search(r'(\d+)\.\d+\.\d+', out.stdout) or re.search(r'(\d+)\.\d+\.\d+', out.stderr)
    return m.group(1) if m else None


def _resolve_chromedriver(browser_path: str) -> str | None:
    """
    Resolve a chromedriver matching the system Chrome's *major* version.

    Strategy:
      1. Detect the system Chrome's major version (e.g. '147').
      2. Scan selenium's on-disk cache (~/.cache/selenium/chromedriver/<arch>/<ver>/)
         for a directory whose version starts with that major. This is the same
         cache selenium-manager populates, so any previously-downloaded matching
         chromedriver is reused without going through selenium-manager again.
      3. Fall back to selenium-manager with --browser-version to download a
         matching chromedriver if the cache has none.

    We avoid calling selenium-manager without --browser-version because its
    se-metadata.json cache can serve a stale "latest" entry (e.g. 148) and
    return a mismatched chromedriver that crashes with SIGTRAP at startup.
    """
    import glob
    import json
    import os
    import subprocess

    major = _detect_chrome_version(browser_path)

    # 1. Look in the on-disk cache for a chromedriver matching the system Chrome
    if major:
        home = os.path.expanduser('~')
        cache_root = os.path.join(home, '.cache', 'selenium', 'chromedriver')
        for arch_dir in glob.glob(os.path.join(cache_root, '*')):
            for ver_dir in glob.glob(os.path.join(arch_dir, f'{major}.*')):
                candidate = os.path.join(ver_dir, 'chromedriver')
                if os.path.exists(candidate) and os.access(candidate, os.X_OK):
                    return candidate

    # 2. Fall back to selenium-manager with explicit --browser-version
    import selenium
    sel_root = os.path.dirname(selenium.__file__)
    sm_candidates = [
        os.path.join(sel_root, 'webdriver', 'common', 'linux', 'selenium-manager'),
        os.path.join(sel_root, 'webdriver', 'common', 'macos', 'selenium-manager'),
    ]
    sm_bin = next((p for p in sm_candidates if os.path.exists(p) and os.access(p, os.X_OK)), None)
    if not sm_bin:
        return None
    args = [sm_bin, '--browser', 'chrome', '--browser-path', browser_path,
            '--output', 'JSON']
    if major:
        args.extend(['--browser-version', major])
    try:
        out = subprocess.run(
            args, capture_output=True, text=True, timeout=120, check=True,
        )
        return json.loads(out.stdout).get('result', {}).get('driver_path')
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return None


def _ensure_chrome_address_space():
    """
    Chrome needs a large virtual address space at startup (typically > 4 GB).
    The Odoo systemd service inherits the distro's default LimitAS (~2.5 GB),
    so Chrome and chromedriver crash immediately with SIGTRAP. Raise the soft
    limit on RLIMIT_AS up to the hard limit (which is unlimited) before
    spawning chromedriver. Hard-limit raises require privilege so we leave
    it alone — only the soft limit is bumped.
    """
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        if soft != resource.RLIM_INFINITY and (hard == resource.RLIM_INFINITY or hard > soft):
            resource.setrlimit(resource.RLIMIT_AS, (hard, hard))
    except (ImportError, ValueError, OSError) as e:
        _logger.warning('Could not raise RLIMIT_AS for Chrome: %s', e)


def _create_driver():
    """Create a headless Chrome WebDriver (requires selenium + chromium)."""
    import tempfile

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    _ensure_chrome_address_space()

    opts = Options()
    # Force the locally installed system Chrome — without this Selenium Manager
    # may download its own (incomplete) "Chrome for Testing" binary that often
    # crashes at startup with SIGTRAP because it lacks system libs the .deb
    # would have pulled in.
    chrome_bin = _find_system_chrome()
    if chrome_bin:
        opts.binary_location = chrome_bin
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    # Unique writable profile dir — avoids "DevToolsActivePort file doesn't exist"
    # when Chrome runs as root or when several drivers share /tmp.
    opts.add_argument(f"--user-data-dir={tempfile.mkdtemp(prefix='chrome-silver-')}")
    opts.add_argument("--remote-debugging-pipe")
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

    # Resolve chromedriver against the actual binary so versions match.
    service = None
    if chrome_bin:
        driver_path = _resolve_chromedriver(chrome_bin)
        if driver_path:
            service = Service(executable_path=driver_path)
    driver = webdriver.Chrome(options=opts, service=service) if service else webdriver.Chrome(options=opts)
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
        is a cheap no-op. Logs start/end to the server log and to ir.logging
        (Settings > Technical > Logging).

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
                    'Live silver scrape failed (%s); falling back to stored value.',
                    str(e),
                )
                base_silver_price = self._get_fallback_silver_price()

            if base_silver_price <= 0:
                msg = ('Silver price cron: no price (live scrape and stored '
                       'fallback both unavailable); nothing updated.')
                _logger.warning('[silver-cron] %s', msg)
                self._cron_log(msg, level='WARNING')
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
            return {
                'success': False,
                'products_updated': 0,
                'base_price': None,
                'message': f'Update failed: {str(e)}',
                'error': str(e),
            }
