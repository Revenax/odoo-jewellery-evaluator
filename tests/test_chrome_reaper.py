# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Finding the Chrome processes a scrape left behind.

`driver.quit()` is the only thing that kills headless Chrome, and it is not
reliable: when the page fails (this scraper hits repeated SSL errors on
dahabmasr) quit() can raise or hang, and the browser survives. That once left
22 orphaned processes holding 1.7 GB — 45% of the box — from two runs.

Every process is matched by the scrape's OWN --user-data-dir, which is a unique
mkdtemp path. That is deliberately narrow: a broad "pkill chrome" would kill
someone else's browser, and on this host Chrome is also used by other tooling.
"""

import os
import sys

try:
    from jewellery_evaluator_silver import pids_for_profile
except ImportError:
    import importlib.util

    _path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..",
                     "jewellery_evaluator", "models", "silver_price_service.py")
    )
    sys.path.insert(0, os.path.dirname(_path))
    spec = importlib.util.spec_from_file_location("silver_mod", _path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:                      # needs odoo; fall back to source exec
        mod = None
    if mod is None or not hasattr(mod, "pids_for_profile"):
        import re
        src = open(_path, encoding="utf-8").read()
        ns = {}
        m = re.search(r"def pids_for_profile\(.*?(?=\ndef |\nclass )", src, re.S)
        assert m, "pids_for_profile not found"
        exec("import glob, os\n" + m.group(0), ns)
        mod = type("m", (), ns)
    pids_for_profile = mod.pids_for_profile


def _fake_proc(tmp_path, procs):
    """procs: {pid: cmdline_string}. Writes a /proc-shaped tree."""
    for pid, cmd in procs.items():
        d = tmp_path / str(pid)
        d.mkdir()
        (d / "cmdline").write_bytes(cmd.replace(" ", "\0").encode())
    (tmp_path / "self").mkdir()            # non-numeric entry, must be skipped
    return str(tmp_path)


class TestPidsForProfile:
    def test_finds_only_processes_holding_that_profile(self, tmp_path):
        root = _fake_proc(tmp_path, {
            101: "/opt/google/chrome/chrome --user-data-dir=/tmp/chrome-silver-AAA",
            102: "/opt/google/chrome/chrome --type=renderer --user-data-dir=/tmp/chrome-silver-AAA",
            103: "/opt/google/chrome/chrome --user-data-dir=/tmp/chrome-silver-BBB",
            104: "/usr/bin/google-chrome --user-data-dir=/home/someone/.config",
            105: "postgres: 16/main: odoo marjaan [local] idle",
        })
        assert sorted(pids_for_profile("/tmp/chrome-silver-AAA", root)) == [101, 102]

    def test_another_scrape_is_never_touched(self, tmp_path):
        # Two runs can overlap; killing the wrong one breaks a live scrape.
        root = _fake_proc(tmp_path, {
            201: "chrome --user-data-dir=/tmp/chrome-silver-AAA",
            202: "chrome --user-data-dir=/tmp/chrome-silver-BBB",
        })
        assert pids_for_profile("/tmp/chrome-silver-BBB", root) == [202]

    def test_a_users_own_chrome_is_never_touched(self, tmp_path):
        root = _fake_proc(tmp_path, {
            301: "/usr/bin/google-chrome",
            302: "/usr/bin/google-chrome --user-data-dir=/home/abdallah/.config/google-chrome",
        })
        assert pids_for_profile("/tmp/chrome-silver-AAA", root) == []

    def test_empty_or_missing_profile_matches_nothing(self, tmp_path):
        # A blank profile path must never degenerate into "match everything".
        root = _fake_proc(tmp_path, {401: "chrome --user-data-dir=/tmp/chrome-silver-AAA"})
        assert pids_for_profile("", root) == []
        assert pids_for_profile(None, root) == []

    def test_unreadable_entries_are_skipped_not_fatal(self, tmp_path):
        root = _fake_proc(tmp_path, {501: "chrome --user-data-dir=/tmp/chrome-silver-AAA"})
        (tmp_path / "999").mkdir()          # numeric dir with no cmdline
        assert pids_for_profile("/tmp/chrome-silver-AAA", root) == [501]

    def test_no_proc_tree_returns_empty(self):
        assert pids_for_profile("/tmp/chrome-silver-AAA", "/nonexistent") == []
