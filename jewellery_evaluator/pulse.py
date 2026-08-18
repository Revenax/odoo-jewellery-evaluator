# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Revenax Pulse — push a notification to the Revenax team.

Deliberately dependency-free beyond ``requests``, which this addon already
uses for the gold price feed.

**This module must never break the thing that called it.** Every entry point
swallows its own errors and returns a result the caller is free to ignore; a
failed notification must never fail a sale, a cron run, or a stock move.

Credentials, in priority order:

1. ``REVENAX_PULSE_SERVICE_NAME`` / ``REVENAX_PULSE_API_KEY`` in the process
   environment (lowercase spellings accepted too).
2. ``jewellery_evaluator.revenax_pulse_service_name`` /
   ``…_api_key`` in ``ir.config_parameter``.
3. The constants below.

Step 2 exists because it is how this deployment actually works: Odoo runs from
a systemd unit with no env file, and every other tunable in this addon already
lives in ``ir.config_parameter``. It lets the owner set the key from Settings
without editing the unit and restarting the server. The API key is read
server-side only and is never shipped to the POS or any browser bundle.
"""

import hashlib
import json
import logging
import os
import threading
import time

import requests

_logger = logging.getLogger(__name__)

# === FILL THESE IN (only if you are not using env vars or ir.config_parameter) ===
REVENAX_PULSE_SERVICE_NAME = ''   # e.g. "Marjaan" — ask Revenax
REVENAX_PULSE_API_KEY = ''        # shaped pulse_<prefix>.<secret> — ask Revenax
# ================================================================================

PULSE_ENDPOINT = 'https://pulse.revenax.com/notify'
TIMEOUT_SECONDS = 5
MAX_ATTEMPTS = 3                  # the first try plus two retries
BACKOFF_SECONDS = (0.25, 0.5)
MAX_RETRY_AFTER = 30              # never sleep longer than this on a 429

PARAM_SERVICE_NAME = 'jewellery_evaluator.revenax_pulse_service_name'
PARAM_API_KEY = 'jewellery_evaluator.revenax_pulse_api_key'

# Warn once per missing-credential process, not once per event — the crons fire
# every minute and would otherwise bury the log.
_warned_missing = False
_warn_lock = threading.Lock()


def _from_env(*names):
    for name in names:
        value = (os.environ.get(name) or '').strip()
        if value:
            return value
    return ''


def _credentials(env=None, credentials=None):
    """(service_name, api_key). Empty strings when unset — never raises.

    ``credentials`` short-circuits the lookup; the background worker uses it so
    it never touches the ORM from another thread.
    """
    if credentials and credentials[0] and credentials[1]:
        return credentials[0], credentials[1]
    service = _from_env('REVENAX_PULSE_SERVICE_NAME', 'revenax_pulse_service_name')
    key = _from_env('REVENAX_PULSE_API_KEY', 'revenax_pulse_api_key')

    if (not service or not key) and env is not None:
        try:
            icp = env['ir.config_parameter'].sudo()
            service = service or (icp.get_param(PARAM_SERVICE_NAME) or '').strip()
            key = key or (icp.get_param(PARAM_API_KEY) or '').strip()
        except Exception:
            # A missing/!closed cursor must not turn into a caller-visible error.
            pass

    return service or REVENAX_PULSE_SERVICE_NAME, key or REVENAX_PULSE_API_KEY


def _warn_missing_once(service, key):
    global _warned_missing
    with _warn_lock:
        if _warned_missing:
            return
        _warned_missing = True
    missing = []
    if not service:
        missing.append('REVENAX_PULSE_SERVICE_NAME')
    if not key:
        missing.append('REVENAX_PULSE_API_KEY')
    _logger.warning(
        '[pulse] %s not set; notifications disabled', ' and '.join(missing)
    )


def make_idempotency_key(*parts):
    """Stable key from the event's own identity, so a retry reuses it.

    Never random: a fresh value per attempt would let the same event through
    twice. Long keys are hashed to keep the header small.
    """
    raw = ':'.join(str(p) for p in parts if p not in (None, ''))
    if len(raw) <= 128:
        return raw
    return 'sha256:' + hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _clean(topic, title, body, data):
    """Trim to the documented limits so we never earn a 400 for length."""
    topic = (topic or '').strip().lower()[:64]
    title = (title or '').strip()[:200]
    body = (body or '').strip()[:2000]
    if not isinstance(data, dict):
        data = {}
    return topic, title, body, data


def notify(topic, title, body, data=None, idempotency_key=None, env=None,
           credentials=None):
    """Send one notification. Never raises.

    Returns ``{'ok': True, ...}`` or ``{'ok': False, 'code': ..., 'error': ...}``.
    Callers may ignore the result entirely.
    """
    try:
        service, key = _credentials(env, credentials)
        if not service or not key:
            _warn_missing_once(service, key)
            return {'ok': False, 'code': 'not_configured'}

        topic, title, body, data = _clean(topic, title, body, data)
        if not topic or not title or not body:
            _logger.warning(
                '[pulse] refusing to send an incomplete notification (topic=%r)', topic
            )
            return {'ok': False, 'code': 'invalid_request'}

        headers = {
            'X-Service-Name': service,
            'X-API-Key': key,
            'Content-Type': 'application/json',
        }
        if idempotency_key:
            headers['Idempotency-Key'] = str(idempotency_key)[:200]

        payload = {'topic': topic, 'title': title, 'body': body}
        if data:
            payload['data'] = data

        for attempt in range(MAX_ATTEMPTS):
            try:
                response = requests.post(
                    PULSE_ENDPOINT,
                    headers=headers,
                    data=json.dumps(payload),
                    timeout=TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                # Network error / timeout: retryable.
                if attempt < MAX_ATTEMPTS - 1:
                    time.sleep(BACKOFF_SECONDS[attempt])
                    continue
                _logger.warning('[pulse] could not notify "%s": %s', topic, exc)
                return {'ok': False, 'code': 'network_error', 'error': str(exc)}

            status = response.status_code

            if status in (200, 201):
                info: dict = {}
                try:
                    info = response.json() or {}
                except ValueError:
                    pass
                delivery = info.get('delivery') or {}
                recipients = delivery.get('recipients')
                if recipients == 0:
                    # Success. Nobody has subscribed to this topic yet.
                    _logger.info(
                        '[pulse] "%s" sent, 0 recipients (nobody subscribed yet)', topic
                    )
                return {
                    'ok': True,
                    'status': status,
                    'idempotent': bool(info.get('idempotent')),
                    'recipients': recipients,
                }

            code = _error_code(response)

            if status == 429 and attempt < MAX_ATTEMPTS - 1:
                time.sleep(_retry_after(response, BACKOFF_SECONDS[attempt]))
                continue
            if status >= 500 and attempt < MAX_ATTEMPTS - 1:
                time.sleep(BACKOFF_SECONDS[attempt])
                continue

            # 4xx other than 429 fails identically on a second attempt.
            _logger.warning('[pulse] could not notify "%s": %s', topic, code)
            return {'ok': False, 'code': code, 'status': status}

        return {'ok': False, 'code': 'exhausted'}
    except Exception as exc:
        # Belt and braces: this function is called from sale and cron paths and
        # must not be able to raise, whatever happens above.
        _logger.warning('[pulse] unexpected failure notifying "%s": %s', topic, exc)
        return {'ok': False, 'code': 'unexpected', 'error': str(exc)}


def _error_code(response):
    try:
        return ((response.json() or {}).get('error') or {}).get('code') or (
            f'http_{response.status_code}'
        )
    except ValueError:
        return f'http_{response.status_code}'


def _retry_after(response, default):
    try:
        value = float(response.headers.get('Retry-After', '') or default)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(value, MAX_RETRY_AFTER))


def notify_in_background(topic, title, body, data=None, idempotency_key=None,
                         env=None, credentials=None):
    """Fire-and-forget ``notify`` on a daemon thread. Never raises.

    Credentials are resolved HERE, on the calling thread, and handed to the
    worker as a plain tuple. ``env`` carries a database cursor that is not safe
    to touch from another thread, so the worker only ever does HTTP. Use this
    from anything a user is waiting on — a sale, a POS sync, a web request.
    """
    try:
        credentials = _credentials(env, credentials)
        if not credentials[0] or not credentials[1]:
            _warn_missing_once(*credentials)
            return
        threading.Thread(
            target=notify,
            args=(topic, title, body, data, idempotency_key),
            kwargs={'credentials': credentials},
            daemon=True,
            name='revenax-pulse',
        ).start()
    except Exception as exc:
        _logger.warning('[pulse] could not queue notification "%s": %s', topic, exc)
