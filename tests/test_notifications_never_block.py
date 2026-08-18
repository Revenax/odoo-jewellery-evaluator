# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Guard: model code must not call the BLOCKING notify().

``pulse.notify`` is synchronous — worst case MAX_ATTEMPTS x TIMEOUT_SECONDS
plus backoff (~15.75s) when Pulse is unreachable. Two places that hurts:

* a sale, where the cashier is waiting on the response;
* a cron, because this deployment runs ``max_cron_threads = 1``, so ONE
  blocking call stalls every cron — including the gold price feed the POS
  floor depends on.

So models always use ``notify_in_background``. ``pulse.py`` itself is exempt:
that is where the blocking implementation lives, and the background variant
calls it from its worker thread.
"""

import ast
import os
import pathlib

_ROOT = pathlib.Path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
_CLIENT = _ROOT / "jewellery_evaluator" / "pulse.py"


def _blocking_calls(tree):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "notify"
            and isinstance(func.value, ast.Name)
            and func.value.id == "pulse"
        ):
            yield node


class TestNotificationsNeverBlock:
    def test_no_model_calls_the_blocking_notify(self):
        offenders = []
        for path in (_ROOT / "jewellery_evaluator").rglob("*.py"):
            if path.resolve() == _CLIENT.resolve():
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for call in _blocking_calls(tree):
                offenders.append(f"{path.name}:{call.lineno}")
        assert not offenders, (
            "pulse.notify() blocks its caller; use notify_in_background():\n  "
            + "\n  ".join(offenders)
        )

    def test_every_model_notification_uses_the_background_variant(self):
        found = 0
        for path in (_ROOT / "jewellery_evaluator").rglob("*.py"):
            if path.resolve() == _CLIENT.resolve():
                continue
            found += path.read_text(encoding="utf-8").count(
                "pulse.notify_in_background("
            )
        # If this ever drops to zero the guard above passes vacuously.
        assert found >= 10, f"only {found} background notifications found"

    def test_the_guard_actually_detects_a_blocking_call(self):
        tree = ast.parse("pulse.notify('t', 'a', 'b')")
        assert len(list(_blocking_calls(tree))) == 1
        tree = ast.parse("pulse.notify_in_background('t', 'a', 'b')")
        assert list(_blocking_calls(tree)) == []
