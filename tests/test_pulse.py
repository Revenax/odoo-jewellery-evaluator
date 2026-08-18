# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Pure-function cover for the Pulse client.

The HTTP path needs a live service, so what is pinned here is the logic that
must be right regardless: idempotency keys stable across retries, payload
trimmed to the documented limits, and — most importantly — the promise that
``notify`` never raises into a sale or a cron run.
"""

import os
import sys
import types

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# The addon imports `requests`; stub it so these tests need no network stack.
if "requests" not in sys.modules:  # pragma: no cover - trivial shim
    stub = types.ModuleType("requests")

    class _RequestError(Exception):
        pass

    stub.RequestException = _RequestError

    def _post(*a, **kw):
        raise _RequestError("no network in tests")

    stub.post = _post
    sys.modules["requests"] = stub

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "pulse", os.path.join(_ROOT, "jewellery_evaluator", "pulse.py")
)
pulse = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pulse)


class TestIdempotencyKey:
    def test_is_stable_for_the_same_event(self):
        # The whole point: two attempts at the SAME event must reuse the key,
        # or the retry notifies everyone twice.
        a = pulse.make_idempotency_key("pos.order", 42, "paid")
        b = pulse.make_idempotency_key("pos.order", 42, "paid")
        assert a == b == "pos.order:42:paid"

    def test_differs_per_event_and_per_kind(self):
        assert pulse.make_idempotency_key("pos.order", 42, "paid") != \
            pulse.make_idempotency_key("pos.order", 43, "paid")
        assert pulse.make_idempotency_key("pos.order", 42, "paid") != \
            pulse.make_idempotency_key("pos.order", 42, "refunded")

    def test_skips_empty_parts(self):
        assert pulse.make_idempotency_key("a", None, "b", "") == "a:b"

    def test_long_keys_are_hashed_and_still_stable(self):
        parts = ("x" * 200, "y" * 200)
        key = pulse.make_idempotency_key(*parts)
        assert key.startswith("sha256:")
        assert len(key) < 128
        assert key == pulse.make_idempotency_key(*parts)


class TestPayloadCleaning:
    def test_topic_is_lowercased_and_capped(self):
        topic, _, _, _ = pulse._clean("ORDER-PAID", "t", "b", None)
        assert topic == "order-paid"
        assert len(pulse._clean("x" * 100, "t", "b", None)[0]) == 64

    def test_title_and_body_capped_to_the_documented_limits(self):
        _, title, body, _ = pulse._clean("t", "T" * 500, "B" * 5000, None)
        assert len(title) == 200
        assert len(body) == 2000

    def test_data_must_be_an_object(self):
        # The contract says an object — never a list or a string.
        assert pulse._clean("t", "a", "b", ["nope"])[3] == {}
        assert pulse._clean("t", "a", "b", "nope")[3] == {}
        assert pulse._clean("t", "a", "b", {"id": 1})[3] == {"id": 1}


class TestNeverRaises:
    """The contract that matters most: a notification cannot break its caller."""

    def test_missing_credentials_returns_quietly(self, monkeypatch):
        monkeypatch.delenv("REVENAX_PULSE_SERVICE_NAME", raising=False)
        monkeypatch.delenv("REVENAX_PULSE_API_KEY", raising=False)
        monkeypatch.setattr(pulse, "REVENAX_PULSE_SERVICE_NAME", "")
        monkeypatch.setattr(pulse, "REVENAX_PULSE_API_KEY", "")
        result = pulse.notify("order-paid", "t", "b")
        assert result == {"ok": False, "code": "not_configured"}

    def test_network_failure_is_swallowed(self, monkeypatch):
        monkeypatch.setattr(pulse, "BACKOFF_SECONDS", (0, 0))
        result = pulse.notify(
            "order-paid", "t", "b", credentials=("Marjaan", "pulse_x.y")
        )
        assert result["ok"] is False
        assert result["code"] == "network_error"

    def test_incomplete_payload_is_refused_not_raised(self):
        result = pulse.notify("", "", "", credentials=("Marjaan", "pulse_x.y"))
        assert result == {"ok": False, "code": "invalid_request"}

    def test_background_variant_never_raises(self, monkeypatch):
        monkeypatch.setattr(pulse, "REVENAX_PULSE_SERVICE_NAME", "")
        monkeypatch.setattr(pulse, "REVENAX_PULSE_API_KEY", "")
        monkeypatch.delenv("REVENAX_PULSE_SERVICE_NAME", raising=False)
        monkeypatch.delenv("REVENAX_PULSE_API_KEY", raising=False)
        assert pulse.notify_in_background("order-paid", "t", "b") is None


class TestCredentialResolution:
    def test_explicit_credentials_win(self):
        assert pulse._credentials(None, ("A", "B")) == ("A", "B")

    def test_environment_is_read(self, monkeypatch):
        monkeypatch.setenv("REVENAX_PULSE_SERVICE_NAME", "Marjaan")
        monkeypatch.setenv("REVENAX_PULSE_API_KEY", "pulse_a.b")
        assert pulse._credentials() == ("Marjaan", "pulse_a.b")

    def test_lowercase_spellings_accepted(self, monkeypatch):
        monkeypatch.delenv("REVENAX_PULSE_SERVICE_NAME", raising=False)
        monkeypatch.delenv("REVENAX_PULSE_API_KEY", raising=False)
        monkeypatch.setenv("revenax_pulse_service_name", "Marjaan")
        monkeypatch.setenv("revenax_pulse_api_key", "pulse_a.b")
        assert pulse._credentials() == ("Marjaan", "pulse_a.b")

    def test_a_broken_orm_does_not_propagate(self, monkeypatch):
        monkeypatch.delenv("REVENAX_PULSE_SERVICE_NAME", raising=False)
        monkeypatch.delenv("REVENAX_PULSE_API_KEY", raising=False)
        monkeypatch.setattr(pulse, "REVENAX_PULSE_SERVICE_NAME", "")
        monkeypatch.setattr(pulse, "REVENAX_PULSE_API_KEY", "")

        class _Boom:
            def __getitem__(self, key):
                raise RuntimeError("cursor closed")

        assert pulse._credentials(_Boom()) == ("", "")


class TestRetryPolicy:
    def _response(self, status, headers=None, payload=None):
        class _R:
            status_code = status

            def __init__(self):
                self.headers = headers or {}

            def json(self):
                if payload is None:
                    raise ValueError("no json")
                return payload

        return _R()

    def test_retry_after_is_honoured_and_capped(self):
        r = self._response(429, {"Retry-After": "3"})
        assert pulse._retry_after(r, 0.25) == 3.0
        # A hostile or silly value must not park a worker thread for an hour.
        assert pulse._retry_after(self._response(429, {"Retry-After": "9999"}), 0.25) \
            == pulse.MAX_RETRY_AFTER
        assert pulse._retry_after(self._response(429, {"Retry-After": "junk"}), 0.25) \
            == 0.25

    def test_error_code_comes_from_the_body_not_the_message(self):
        r = self._response(401, payload={"error": {"code": "unknown_sender"}})
        assert pulse._error_code(r) == "unknown_sender"

    def test_error_code_falls_back_to_the_status(self):
        assert pulse._error_code(self._response(503)) == "http_503"


class TestNonBlocking:
    """A notification must never hold up the thing that triggered it.

    `notify` is synchronous: up to MAX_ATTEMPTS x TIMEOUT_SECONDS plus backoff
    (~15.75s) if Pulse is unreachable. This box runs max_cron_threads=1, so one
    blocking call there stalls EVERY cron — including the gold price feed that
    the POS floor depends on. Model code therefore always uses the background
    variant.
    """

    def test_background_returns_immediately_even_when_the_network_hangs(
        self, monkeypatch
    ):
        import threading
        import time as _time

        started = threading.Event()
        release = threading.Event()

        def _hanging_post(*a, **kw):
            started.set()
            release.wait(5)          # simulate an unreachable Pulse
            raise pulse.requests.RequestException("hung")

        monkeypatch.setattr(pulse.requests, "post", _hanging_post)
        monkeypatch.setattr(pulse, "BACKOFF_SECONDS", (0, 0))

        began = _time.monotonic()
        pulse.notify_in_background(
            "order-paid", "t", "b", credentials=("Marjaan", "pulse_x.y")
        )
        elapsed = _time.monotonic() - began

        # The caller is free well before the request would have finished.
        assert elapsed < 0.5, f"notify_in_background blocked for {elapsed:.2f}s"
        assert started.wait(2), "the worker thread never ran"
        release.set()

    def test_the_worker_is_a_daemon_so_it_cannot_hold_the_process_open(
        self, monkeypatch
    ):
        seen = {}

        class _Thread(pulse.threading.Thread):
            def start(self):
                seen["daemon"] = self.daemon
                seen["name"] = self.name
                # Do not actually run; we only care how it was constructed.

        monkeypatch.setattr(pulse.threading, "Thread", _Thread)
        pulse.notify_in_background(
            "order-paid", "t", "b", credentials=("Marjaan", "pulse_x.y")
        )
        assert seen.get("daemon") is True
        assert seen.get("name") == "revenax-pulse"

    def test_credentials_are_resolved_before_the_thread_starts(self, monkeypatch):
        """The worker must never touch the ORM: a cursor is not thread-safe.

        Resolution happens on the calling thread, so the thread receives plain
        strings and `env` is never handed across.
        """
        captured = {}

        class _Thread(pulse.threading.Thread):
            def __init__(self, *a, **kw):
                captured.update(kw.get("kwargs") or {})
                super().__init__(*a, **kw)

            def start(self):
                pass

        monkeypatch.setattr(pulse.threading, "Thread", _Thread)
        pulse.notify_in_background(
            "order-paid", "t", "b", credentials=("Marjaan", "pulse_x.y")
        )
        assert captured.get("credentials") == ("Marjaan", "pulse_x.y")
        assert "env" not in captured
