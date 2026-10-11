# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Local gold / silver / USD price feed for Odoo (runs outside Odoo).

Polls the eDahab pricing API every POLL_SECONDS, keeps a SQLite history, and
serves the latest snapshot on a loopback-only HTTP endpoint, so Odoo reads one
small JSON document instead of scraping websites or driving headless Chrome:

    GET /prices          latest snapshot (+ age_seconds, stale); 503 until the first fetch
    GET /history?limit=N recent distinct snapshots
    GET /health          "ok" plus the last error, if any

Standalone: stdlib + requests (the Odoo venv's python is enough). Installed as
the systemd unit marjaan-price-feed by scripts/install-price-feed.sh.
"""
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = 'https://edahab.focal-tech.com/api'
HOST = os.environ.get('PRICE_FEED_HOST', '127.0.0.1')
PORT = int(os.environ.get('PRICE_FEED_PORT', '8075'))
POLL_SECONDS = int(os.environ.get('PRICE_FEED_POLL_SECONDS', '60'))
STALE_SECONDS = int(os.environ.get('PRICE_FEED_STALE_SECONDS', '900'))
DB_PATH = os.environ.get('PRICE_FEED_DB', '/var/lib/marjaan-price-feed/prices.db')
TIMEOUT = 15

log = logging.getLogger('price-feed')


class EDahabClient:
    """Guest-token client for the eDahab API (token renewed on 401)."""

    def __init__(self):
        self.session = requests.Session()
        retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504],
                      raise_on_status=False)
        self.session.mount('https://', HTTPAdapter(max_retries=retry))
        self.session.headers.update({
            'User-Agent': 'Dart/3.0 (dart:io)', 'Accept': 'application/json',
            'Content-Type': 'application/json',
        })

    def _authenticate(self):
        r = self.session.post(f'{BASE_URL}/v2/token/request', json={'device_id': str(uuid.uuid4())},
                              timeout=TIMEOUT)
        r.raise_for_status()
        self.session.headers['Authorization'] = 'Bearer ' + r.text.strip().strip('"').strip("'")

    def fetch(self):
        if 'Authorization' not in self.session.headers:
            self._authenticate()
        r = self.session.get(f'{BASE_URL}/prices', timeout=TIMEOUT)
        if r.status_code == 401:
            self._authenticate()
            r = self.session.get(f'{BASE_URL}/prices', timeout=TIMEOUT)
        r.raise_for_status()
        return to_snapshot(r.json().get('data') or {})


def _num(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def to_snapshot(raw):
    """eDahab payload -> our snapshot. 18K is derived from 24K (x 18/24)."""
    g24a, g24b = _num(raw.get('gold24Ask')), _num(raw.get('gold24Bid'))
    return {
        'record_id': raw.get('id'),
        'gold_24k': {'ask': g24a, 'bid': g24b},
        'gold_21k': {'ask': _num(raw.get('gold21Ask')), 'bid': _num(raw.get('gold21Bid'))},
        'gold_18k': {'ask': round(g24a * 18 / 24, 2) if g24a else None,
                     'bid': round(g24b * 18 / 24, 2) if g24b else None},
        'silver_999': {'ask': _num(raw.get('silver999Ask')), 'bid': _num(raw.get('silver999Bid'))},
        'silver_925': {'ask': _num(raw.get('silver925Ask')), 'bid': _num(raw.get('silver925Bid'))},
        'global_market': {
            'gold_ounce_usd': _num(raw.get('ounceUSD')),
            'silver_ounce_usd': _num(raw.get('silver_ounce')),
            'usd_egp': _num(raw.get('USDEGPask')),
            'usd_egp_bid': _num(raw.get('USDEGPbid')),
        },
        'market_updated_at': raw.get('updated_at'),
        'scraped_at': datetime.now(timezone.utc).isoformat(),
    }


class Store:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS snapshots ('
                       ' id INTEGER PRIMARY KEY AUTOINCREMENT, record_id INTEGER UNIQUE,'
                       ' scraped_at TEXT NOT NULL, payload TEXT NOT NULL)')

    def _db(self):
        return sqlite3.connect(self.path, timeout=10)

    def save(self, snap):
        with self._db() as db:
            db.execute('INSERT OR IGNORE INTO snapshots (record_id, scraped_at, payload) VALUES (?, ?, ?)',
                       (snap['record_id'], snap['scraped_at'], json.dumps(snap)))

    def latest(self):
        with self._db() as db:
            row = db.execute('SELECT payload FROM snapshots ORDER BY id DESC LIMIT 1').fetchone()
        return json.loads(row[0]) if row else None

    def history(self, limit):
        with self._db() as db:
            rows = db.execute('SELECT payload FROM snapshots ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        return [json.loads(r[0]) for r in rows]


class Feed:
    def __init__(self, store):
        self.store, self.client = store, EDahabClient()
        self.current = store.latest()          # survive restarts with the last good value
        self.last_ok = None                    # monotonic time of the last successful fetch
        self.last_error = None
        self.lock = threading.Lock()

    def poll_forever(self):
        while True:
            try:
                snap = self.client.fetch()
                if not snap['gold_21k']['ask']:
                    raise ValueError('eDahab returned no 21K price')
                self.store.save(snap)
                with self.lock:
                    self.current, self.last_ok, self.last_error = snap, time.time(), None
            except Exception as err:  # keep serving the last good snapshot
                self.last_error = f'{type(err).__name__}: {err}'
                log.warning('fetch failed: %s', self.last_error)
            time.sleep(POLL_SECONDS)

    def snapshot(self):
        with self.lock:
            snap = dict(self.current) if self.current else None
        if not snap:
            return None
        scraped = datetime.fromisoformat(snap['scraped_at'])
        age = (datetime.now(timezone.utc) - scraped).total_seconds()
        snap.update(age_seconds=round(age), stale=age > STALE_SECONDS, last_error=self.last_error)
        return snap


def make_handler(feed):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == '/prices':
                snap = feed.snapshot()
                return self._send(200, snap) if snap else self._send(503, {'error': 'no price yet'})
            if url.path == '/history':
                limit = min(int((parse_qs(url.query).get('limit') or ['20'])[0]), 1000)
                return self._send(200, feed.store.history(limit))
            if url.path == '/health':
                snap = feed.snapshot()
                return self._send(200 if snap and not snap['stale'] else 503,
                                  {'ok': bool(snap and not snap['stale']), 'last_error': feed.last_error})
            return self._send(404, {'error': 'not found'})

        def log_message(self, fmt, *args):  # quiet: Odoo polls this every few minutes
            return

    return Handler


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    feed = Feed(Store(DB_PATH))
    threading.Thread(target=feed.poll_forever, daemon=True).start()
    log.info('serving on http://%s:%s (poll %ss)', HOST, PORT, POLL_SECONDS)
    ThreadingHTTPServer((HOST, PORT), make_handler(feed)).serve_forever()


if __name__ == '__main__':
    main()
