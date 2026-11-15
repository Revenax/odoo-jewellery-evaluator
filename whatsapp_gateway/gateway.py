# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Marjaan WhatsApp gateway: our own WhatsApp Cloud API integration (runs outside Odoo).

One small service that every Marjaan system (Odoo, the ops app, alerts) uses to talk
WhatsApp, kept separate from Odoo's own WhatsApp app on purpose:

    GET  /whatsapp/webhook   Meta's subscription check (hub.challenge)        PUBLIC via nginx
    POST /whatsapp/webhook   incoming messages + delivery statuses, signed    PUBLIC via nginx
    POST /send               send a template or a text (JSON)                 loopback only
    GET  /messages?limit=N   recent messages and their status                 loopback only
    GET  /health             config + last error                              loopback only

Every webhook POST must carry a valid X-Hub-Signature-256 (HMAC-SHA256 of the raw body
with the app secret); anything else is rejected. Events are stored in SQLite; a status
event updates the outbound message it belongs to (matched by its wamid).

Config comes from the environment (systemd EnvironmentFile /etc/marjaan-whatsapp.env):
WHATSAPP_TOKEN (system-user token), WHATSAPP_APP_SECRET, WHATSAPP_VERIFY_TOKEN,
WHATSAPP_PHONE_NUMBER_ID. Secrets are never logged, and Graph API errors are reduced to
their code/subcode/message with the token scrubbed (a malformed-token error echoes it).

Standard library only. Installed by scripts/install-whatsapp-gateway.sh.
"""
import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

GRAPH_VERSION = os.environ.get('WHATSAPP_GRAPH_VERSION', 'v25.0')
HOST = os.environ.get('WHATSAPP_HOST', '127.0.0.1')
PORT = int(os.environ.get('WHATSAPP_PORT', '8076'))
DB_PATH = os.environ.get('WHATSAPP_DB', '/var/lib/marjaan-whatsapp/whatsapp.db')
MAX_BODY = 1024 * 1024
TIMEOUT = 20

log = logging.getLogger('whatsapp-gateway')


# ---------------------------------------------------------------- pure helpers (tested)

def verify_signature(app_secret, body, header):
    """True when header is 'sha256=<hex>' and matches HMAC-SHA256(app_secret, body)."""
    if not app_secret or not header or not header.startswith('sha256='):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len('sha256='):].strip().lower())


def verification_response(params, verify_token):
    """Meta's GET subscription check: (status, body)."""
    mode = (params.get('hub.mode') or [''])[0]
    token = (params.get('hub.verify_token') or [''])[0]
    challenge = (params.get('hub.challenge') or [''])[0]
    if mode == 'subscribe' and verify_token and hmac.compare_digest(token, verify_token):
        return 200, challenge
    return 403, 'forbidden'


def normalize_phone(raw, default_country='20'):
    """Digits only, international form without '+': '01063864994' -> '201063864994'.

    Egyptian local numbers (leading 0) get the default country code; '+'/'00' prefixes
    are dropped. Returns '' for anything too short to be a phone number.
    """
    digits = re.sub(r'\D', '', raw or '')
    if digits.startswith('00'):
        digits = digits[2:]
    elif digits.startswith('0'):
        digits = default_country + digits[1:]
    return digits if len(digits) >= 10 else ''


def parse_webhook(payload):
    """Flatten a whatsapp_business_account webhook into simple events.

    Returns a list of dicts, each either
      {'kind': 'message', 'wamid', 'from', 'name', 'type', 'text', 'timestamp', 'raw'}
      {'kind': 'status', 'wamid', 'status', 'recipient', 'timestamp', 'errors', 'raw'}
    Unknown shapes are ignored, never raised on.
    """
    events = []
    if not isinstance(payload, dict) or payload.get('object') != 'whatsapp_business_account':
        return events
    for entry in payload.get('entry') or []:
        for change in entry.get('changes') or []:
            value = change.get('value') or {}
            names = {c.get('wa_id'): (c.get('profile') or {}).get('name')
                     for c in value.get('contacts') or []}
            for m in value.get('messages') or []:
                mtype = m.get('type')
                text = None
                if mtype == 'text':
                    text = (m.get('text') or {}).get('body')
                elif mtype == 'button':
                    text = (m.get('button') or {}).get('text')
                elif mtype == 'interactive':
                    inter = m.get('interactive') or {}
                    reply = inter.get('button_reply') or inter.get('list_reply') or {}
                    text = reply.get('title')
                elif mtype in ('image', 'document', 'video', 'audio', 'sticker'):
                    text = (m.get(mtype) or {}).get('caption')
                events.append({'kind': 'message', 'wamid': m.get('id'), 'from': m.get('from'),
                               'name': names.get(m.get('from')), 'type': mtype, 'text': text,
                               'timestamp': m.get('timestamp'), 'raw': m})
            for s in value.get('statuses') or []:
                events.append({'kind': 'status', 'wamid': s.get('id'), 'status': s.get('status'),
                               'recipient': s.get('recipient_id'), 'timestamp': s.get('timestamp'),
                               'errors': s.get('errors'), 'raw': s})
    return events


def build_message(to, template=None, language='en_US', params=None, text=None):
    """Cloud API /messages body for a template (with body params) or a plain text."""
    if bool(template) == bool(text):
        raise ValueError('give exactly one of template or text')
    body = {'messaging_product': 'whatsapp', 'to': to}
    if text:
        body.update(type='text', text={'body': text, 'preview_url': False})
        return body
    tpl = {'name': template, 'language': {'code': language}}
    if params:
        tpl['components'] = [{'type': 'body', 'parameters': [
            {'type': 'text', 'text': str(p)} for p in params]}]
    body.update(type='template', template=tpl)
    return body


def safe_graph_error(raw, token):
    """Reduce a Graph API error body to code/subcode/message, with the token scrubbed."""
    try:
        err = json.loads(raw).get('error') or {}
    except (ValueError, AttributeError):
        err = {'message': 'unreadable error body'}
    msg = str(err.get('message') or '')
    if token:
        msg = msg.replace(token, '[token]')
    msg = re.sub(r'EAA[A-Za-z0-9]{20,}', '[token]', msg)
    return {'code': err.get('code'), 'subcode': err.get('error_subcode'), 'message': msg[:300]}


# ---------------------------------------------------------------- storage

class Store:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with self._db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY,
                wamid TEXT,
                direction TEXT NOT NULL,      -- in / out
                peer TEXT,                    -- the customer's number
                name TEXT,
                type TEXT,
                text TEXT,
                status TEXT,                  -- out: accepted/sent/delivered/read/failed; in: received
                error TEXT,
                source TEXT,                  -- out: who asked (odoo, ops, alerts ...)
                payload TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS messages_wamid ON messages (wamid)')

    def _db(self):
        return sqlite3.connect(self.path, timeout=10)

    def add(self, **row):
        now = time.time()
        row.setdefault('created_at', now)
        row['updated_at'] = now
        cols = ', '.join(row)
        with self._db() as db:
            db.execute(f'INSERT INTO messages ({cols}) VALUES ({", ".join("?" * len(row))})',
                       list(row.values()))

    def set_status(self, wamid, status, error=None):
        with self._db() as db:
            cur = db.execute('UPDATE messages SET status = ?, error = COALESCE(?, error), updated_at = ? '
                             "WHERE wamid = ? AND direction = 'out'", (status, error, time.time(), wamid))
            return cur.rowcount

    def recent(self, limit):
        with self._db() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute('SELECT id, wamid, direction, peer, name, type, text, status, error, source, '
                              'created_at, updated_at FROM messages ORDER BY id DESC LIMIT ?',
                              (limit,)).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------- service

class Gateway:
    def __init__(self, store, env=os.environ):
        self.store = store
        self.token = env.get('WHATSAPP_TOKEN', '')
        self.app_secret = env.get('WHATSAPP_APP_SECRET', '')
        self.verify_token = env.get('WHATSAPP_VERIFY_TOKEN', '')
        self.phone_number_id = env.get('WHATSAPP_PHONE_NUMBER_ID', '')
        self.last_error = None
        self.lock = threading.Lock()

    def config_status(self):
        return {'token': bool(self.token), 'app_secret': bool(self.app_secret),
                'verify_token': bool(self.verify_token), 'phone_number_id': self.phone_number_id or None}

    def receive(self, body, signature):
        if not verify_signature(self.app_secret, body, signature):
            return 401, {'error': 'bad signature'}
        try:
            payload = json.loads(body)
        except ValueError:
            return 400, {'error': 'bad json'}
        for ev in parse_webhook(payload):
            if ev['kind'] == 'message':
                self.store.add(wamid=ev['wamid'], direction='in', peer=ev['from'], name=ev['name'],
                               type=ev['type'], text=ev['text'], status='received',
                               payload=json.dumps(ev['raw']))
                log.info('message in from %s (%s)', ev['from'], ev['type'])
            else:
                err = json.dumps(ev['errors']) if ev['errors'] else None
                if not self.store.set_status(ev['wamid'], ev['status'], err):
                    log.info('status %s for a message not sent through the gateway', ev['status'])
        return 200, {'ok': True}

    def send(self, req):
        to = normalize_phone(str(req.get('to') or ''))
        if not to:
            return 400, {'error': 'invalid "to" number'}
        if not (self.token and self.phone_number_id):
            return 503, {'error': 'gateway not configured (token / phone number id)'}
        try:
            body = build_message(to, template=req.get('template'), language=req.get('language') or 'en_US',
                                 params=req.get('params'), text=req.get('text'))
        except ValueError as err:
            return 400, {'error': str(err)}
        url = f'https://graph.facebook.com/{GRAPH_VERSION}/{self.phone_number_id}/messages'
        http_req = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST', headers={
            'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'})
        source = str(req.get('source') or '')[:40] or None
        summary = req.get('text') or f"template:{req.get('template')}"
        try:
            with urllib.request.urlopen(http_req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as err:
            safe = safe_graph_error(err.read().decode(errors='replace'), self.token)
            self.last_error = safe
            self.store.add(direction='out', peer=to, type=body['type'], text=summary, status='failed',
                           error=json.dumps(safe), source=source)
            log.warning('send to %s failed: %s', to, safe)
            return 502, {'error': safe}
        except (urllib.error.URLError, TimeoutError) as err:
            self.last_error = {'message': type(err).__name__}
            return 504, {'error': 'Graph API unreachable'}
        wamid = ((data.get('messages') or [{}])[0]).get('id')
        self.store.add(wamid=wamid, direction='out', peer=to, type=body['type'], text=summary,
                       status='accepted', source=source)
        return 200, {'ok': True, 'wamid': wamid, 'to': to}


def make_handler(gw):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, body, content_type='application/json'):
            data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self):
            length = int(self.headers.get('Content-Length') or 0)
            if length > MAX_BODY:
                return None
            return self.rfile.read(length)

        def _local_only(self):
            # nginx forwards the public path only, and always sets X-Forwarded-For.
            return self.headers.get('X-Forwarded-For') is None and self.client_address[0] in ('127.0.0.1', '::1')

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == '/whatsapp/webhook':
                status, body = verification_response(parse_qs(url.query), gw.verify_token)
                return self._send(status, body, 'text/plain')
            if not self._local_only():
                return self._send(404, {'error': 'not found'})
            if url.path == '/messages':
                limit = min(int((parse_qs(url.query).get('limit') or ['50'])[0]), 500)
                return self._send(200, gw.store.recent(limit))
            if url.path == '/health':
                return self._send(200, {'config': gw.config_status(), 'last_error': gw.last_error})
            return self._send(404, {'error': 'not found'})

        def do_POST(self):
            url = urlparse(self.path)
            body = self._body()
            if body is None:
                return self._send(413, {'error': 'too large'})
            if url.path == '/whatsapp/webhook':
                status, resp = gw.receive(body, self.headers.get('X-Hub-Signature-256'))
                return self._send(status, resp)
            if url.path == '/send' and self._local_only():
                try:
                    req = json.loads(body or b'{}')
                except ValueError:
                    return self._send(400, {'error': 'bad json'})
                status, resp = gw.send(req)
                return self._send(status, resp)
            return self._send(404, {'error': 'not found'})

        def log_message(self, fmt, *args):  # no access log: query strings carry the verify token
            return

    return Handler


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    gw = Gateway(Store(DB_PATH))
    log.info('serving on http://%s:%s; config %s', HOST, PORT, gw.config_status())
    ThreadingHTTPServer((HOST, PORT), make_handler(gw)).serve_forever()


if __name__ == '__main__':
    main()
