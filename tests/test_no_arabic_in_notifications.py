# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Guard: HARDCODED notification text must be English.

The wording we write — titles, bodies, labels — stays English so a lock screen
never mixes an RTL sentence into LTR English. Runtime VALUES are a different
matter and are deliberately left alone: most customers here have Arabic names,
and a notification saying who bought something is more useful with the real
name than with a sanitised placeholder.

The POS day book and its views also stay Arabic — they mirror the paper ledger.

This walks the AST for every ``pulse.notify`` / ``pulse.notify_in_background``
call and fails if any string LITERAL inside one contains an Arabic character,
so the rule survives future edits instead of relying on someone remembering it.
"""

import ast
import os
import pathlib
import re

_ROOT = pathlib.Path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
_ARABIC = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
_NOTIFY = {"notify", "notify_in_background"}


def _pulse_calls(tree):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _NOTIFY:
            base = func.value
            if isinstance(base, ast.Name) and base.id == "pulse":
                yield node


def _literals(node):
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            yield child.value


class TestNoArabicInNotifications:
    def test_hardcoded_python_notification_text_is_english(self):
        offenders = []
        for path in (_ROOT / "jewellery_evaluator").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for call in _pulse_calls(tree):
                for text in _literals(call):
                    if _ARABIC.search(text):
                        offenders.append(f"{path.name}:{call.lineno} {text!r}")
        assert not offenders, "Arabic in notification text:\n" + "\n".join(offenders)

    def test_hardcoded_shell_notification_text_is_english(self):
        offenders = []
        for path in (_ROOT / "scripts").glob("*.sh"):
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if re.search(r"^\s*pulse [a-z0-9._-]+ ", line) and _ARABIC.search(line):
                    offenders.append(f"{path.name}:{lineno}")
        assert not offenders, "Arabic in shell notifications: " + ", ".join(offenders)

    def test_the_guard_actually_detects_arabic(self):
        # A guard that cannot fail is worthless — prove it catches the real thing.
        tree = ast.parse("pulse.notify('t', 'Day totals', 'مبيعات اليوم')")
        found = [
            text
            for call in _pulse_calls(tree)
            for text in _literals(call)
            if _ARABIC.search(text)
        ]
        assert found == ["مبيعات اليوم"]

    def test_the_ledger_still_keeps_its_arabic_book(self):
        # The book is SUPPOSED to be Arabic; make sure this guard never tempts
        # anyone into stripping it.
        ledger = (_ROOT / "jewellery_evaluator/models/jewellery_ledger.py").read_text(
            encoding="utf-8"
        )
        assert _ARABIC.search(ledger), "the day book lost its Arabic column names"
