"""
test_telemetry.py — Validates opt-in install/active-user telemetry behaviour.

Run with:
    python test_telemetry.py
    python -m pytest test_telemetry.py
"""

import datetime
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, call, patch

import telemetry as telemetry_mod

_ENDPOINT = "https://example.test/event"
_ALLOWED_FIELDS = frozenset({"install_id", "event", "date", "platform", "schema"})
_UNSAFE_FIELDS  = frozenset({
    "cwd", "path", "tty", "pid", "window_id", "username",
    "workspace", "project", "name",
    "start_time", "end_time", "timestamp",
    "context", "hint", "command",
    "duration_seconds", "session_depth", "task_load",
    "workspace_count_today", "feedback_label", "recommendation_accepted",
    "hour", "day",
})


def _cfg(enabled: bool = True, endpoint: str = _ENDPOINT) -> dict:
    return {"telemetry": {"enabled": enabled, "endpoint": endpoint}}


def _payloads(mock_urlopen: MagicMock) -> list[dict]:
    """Extract JSON payloads from every urlopen call."""
    result = []
    for c in mock_urlopen.call_args_list:
        req = c[0][0]
        result.append(json.loads(req.data))
    return result


class TestTelemetryDisabled(unittest.TestCase):
    """When telemetry is disabled, no files are created and no network calls are made."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._install_id = os.path.join(self._tmp, "install_id")
        self._heartbeat  = os.path.join(self._tmp, "last_heartbeat_date")
        self._patches = [
            patch.object(telemetry_mod, "_DATA_DIR",        self._tmp),
            patch.object(telemetry_mod, "_INSTALL_ID_PATH", self._install_id),
            patch.object(telemetry_mod, "_HEARTBEAT_PATH",  self._heartbeat),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)

    @patch("urllib.request.urlopen")
    def test_disabled_flag_no_files_no_network(self, mock_urlopen):
        telemetry_mod.maybe_emit({"telemetry": {"enabled": False, "endpoint": _ENDPOINT}})
        mock_urlopen.assert_not_called()
        self.assertFalse(os.path.exists(self._install_id))
        self.assertFalse(os.path.exists(self._heartbeat))

    @patch("urllib.request.urlopen")
    def test_missing_telemetry_key_no_files_no_network(self, mock_urlopen):
        telemetry_mod.maybe_emit({})
        mock_urlopen.assert_not_called()
        self.assertFalse(os.path.exists(self._install_id))
        self.assertFalse(os.path.exists(self._heartbeat))

    @patch("urllib.request.urlopen")
    def test_empty_telemetry_dict_no_files_no_network(self, mock_urlopen):
        telemetry_mod.maybe_emit({"telemetry": {}})
        mock_urlopen.assert_not_called()
        self.assertFalse(os.path.exists(self._install_id))
        self.assertFalse(os.path.exists(self._heartbeat))

    @patch("urllib.request.urlopen")
    def test_enabled_but_no_endpoint_no_network(self, mock_urlopen):
        """Enabled flag without an endpoint must not make any network call."""
        telemetry_mod.maybe_emit({"telemetry": {"enabled": True}})
        mock_urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_enabled_but_blank_endpoint_no_network(self, mock_urlopen):
        telemetry_mod.maybe_emit({"telemetry": {"enabled": True, "endpoint": "   "}})
        mock_urlopen.assert_not_called()


class TestTelemetryEnabled(unittest.TestCase):
    """When opted in, install_id is created and events are sent correctly."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._install_id = os.path.join(self._tmp, "install_id")
        self._heartbeat  = os.path.join(self._tmp, "last_heartbeat_date")
        self._patches = [
            patch.object(telemetry_mod, "_DATA_DIR",        self._tmp),
            patch.object(telemetry_mod, "_INSTALL_ID_PATH", self._install_id),
            patch.object(telemetry_mod, "_HEARTBEAT_PATH",  self._heartbeat),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ── install_id file ───────────────────────────────────────────────────────

    @patch("urllib.request.urlopen")
    def test_first_run_creates_install_id_file(self, _mock):
        telemetry_mod.maybe_emit(_cfg())
        self.assertTrue(os.path.exists(self._install_id))

    @patch("urllib.request.urlopen")
    def test_install_id_is_uuid4_format(self, _mock):
        telemetry_mod.maybe_emit(_cfg())
        with open(self._install_id) as fh:
            id_ = fh.read().strip()
        import re
        self.assertRegex(id_, r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')

    @patch("urllib.request.urlopen")
    def test_install_id_stable_across_runs(self, mock_urlopen):
        """The same install_id must be reused across all subsequent calls."""
        telemetry_mod.maybe_emit(_cfg())
        with open(self._install_id) as fh:
            id1 = fh.read().strip()

        # advance date so heartbeat fires
        with patch("telemetry.datetime") as mock_dt:
            mock_dt.date.today.return_value = datetime.date(2099, 6, 1)
            telemetry_mod.maybe_emit(_cfg())

        for p in _payloads(mock_urlopen):
            self.assertEqual(p["install_id"], id1)

    # ── install event ─────────────────────────────────────────────────────────

    @patch("urllib.request.urlopen")
    def test_first_run_sends_install_event(self, mock_urlopen):
        telemetry_mod.maybe_emit(_cfg())
        ps = _payloads(mock_urlopen)
        self.assertEqual(len(ps), 1)
        self.assertEqual(ps[0]["event"], "install")

    @patch("urllib.request.urlopen")
    def test_install_event_sent_only_once(self, mock_urlopen):
        """Second call on the same day must NOT send another install."""
        telemetry_mod.maybe_emit(_cfg())
        mock_urlopen.reset_mock()
        telemetry_mod.maybe_emit(_cfg())
        mock_urlopen.assert_not_called()

    # ── heartbeat ─────────────────────────────────────────────────────────────

    @patch("urllib.request.urlopen")
    def test_no_heartbeat_same_day(self, mock_urlopen):
        """Multiple calls on the same calendar day send at most one network event."""
        telemetry_mod.maybe_emit(_cfg())   # install
        mock_urlopen.reset_mock()
        telemetry_mod.maybe_emit(_cfg())   # same day — no heartbeat
        telemetry_mod.maybe_emit(_cfg())   # same day — no heartbeat
        mock_urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_heartbeat_sent_on_new_day(self, mock_urlopen):
        with patch("telemetry.datetime") as mock_dt:
            mock_dt.date.today.return_value = datetime.date(2026, 1, 1)
            telemetry_mod.maybe_emit(_cfg())   # install on day 1

        mock_urlopen.reset_mock()

        with patch("telemetry.datetime") as mock_dt:
            mock_dt.date.today.return_value = datetime.date(2026, 1, 2)
            telemetry_mod.maybe_emit(_cfg())   # heartbeat on day 2

        ps = _payloads(mock_urlopen)
        self.assertEqual(len(ps), 1)
        self.assertEqual(ps[0]["event"], "heartbeat")
        self.assertEqual(ps[0]["date"],  "2026-01-02")

    @patch("urllib.request.urlopen")
    def test_heartbeat_at_most_once_per_new_day(self, mock_urlopen):
        """Three calls on day 2 must produce exactly one heartbeat."""
        with patch("telemetry.datetime") as mock_dt:
            mock_dt.date.today.return_value = datetime.date(2026, 1, 1)
            telemetry_mod.maybe_emit(_cfg())

        mock_urlopen.reset_mock()

        with patch("telemetry.datetime") as mock_dt:
            mock_dt.date.today.return_value = datetime.date(2026, 1, 2)
            telemetry_mod.maybe_emit(_cfg())
            telemetry_mod.maybe_emit(_cfg())
            telemetry_mod.maybe_emit(_cfg())

        self.assertEqual(mock_urlopen.call_count, 1)

    # ── payload shape ─────────────────────────────────────────────────────────

    @patch("urllib.request.urlopen")
    def test_payload_contains_only_allowed_fields(self, mock_urlopen):
        telemetry_mod.maybe_emit(_cfg())
        for p in _payloads(mock_urlopen):
            extra = set(p) - _ALLOWED_FIELDS
            self.assertFalse(extra, f"Non-allowed fields in payload: {extra}\n{p}")

    @patch("urllib.request.urlopen")
    def test_payload_contains_no_unsafe_fields(self, mock_urlopen):
        telemetry_mod.maybe_emit(_cfg())
        for p in _payloads(mock_urlopen):
            for field in _UNSAFE_FIELDS:
                self.assertNotIn(field, p,
                    f"Unsafe field {field!r} must never appear in telemetry payload\n{p}")

    @patch("urllib.request.urlopen")
    def test_payload_field_types_and_values(self, mock_urlopen):
        """Every permitted field must have the expected type and value shape."""
        telemetry_mod.maybe_emit(_cfg())
        ps = _payloads(mock_urlopen)
        self.assertTrue(ps)
        p = ps[0]

        self.assertIsInstance(p["install_id"], str)
        self.assertRegex(p["install_id"], r'^[0-9a-f-]{36}$')
        self.assertIn(p["event"],    {"install", "heartbeat"})
        self.assertRegex(p["date"],  r'^\d{4}-\d{2}-\d{2}$')
        self.assertIsInstance(p["platform"], str)
        self.assertGreater(len(p["platform"]), 0)
        self.assertEqual(p["schema"], 1)

    @patch("urllib.request.urlopen")
    def test_heartbeat_payload_allowed_fields_only(self, mock_urlopen):
        """Heartbeat payload must also obey the field allowlist."""
        with patch("telemetry.datetime") as mock_dt:
            mock_dt.date.today.return_value = datetime.date(2026, 1, 1)
            telemetry_mod.maybe_emit(_cfg())

        mock_urlopen.reset_mock()

        with patch("telemetry.datetime") as mock_dt:
            mock_dt.date.today.return_value = datetime.date(2026, 1, 2)
            telemetry_mod.maybe_emit(_cfg())

        for p in _payloads(mock_urlopen):
            extra = set(p) - _ALLOWED_FIELDS
            self.assertFalse(extra, f"Non-allowed fields in heartbeat payload: {extra}\n{p}")

    # ── resilience ────────────────────────────────────────────────────────────

    @patch("urllib.request.urlopen", side_effect=OSError("connection refused"))
    def test_network_failure_does_not_raise(self, _mock):
        """Network errors must be swallowed; the app must not crash."""
        try:
            telemetry_mod.maybe_emit(_cfg())
        except Exception as exc:
            self.fail(f"maybe_emit raised {exc!r} on network failure")

    @patch("urllib.request.urlopen", side_effect=Exception("timeout"))
    def test_any_exception_in_send_does_not_raise(self, _mock):
        try:
            telemetry_mod.maybe_emit(_cfg())
        except Exception as exc:
            self.fail(f"maybe_emit raised {exc!r}: {exc}")

    # ── import isolation ──────────────────────────────────────────────────────

    def test_telemetry_does_not_import_workspace_modules(self):
        """telemetry.py must not import logger, detector, or hud."""
        import sys
        forbidden = {"logger", "detector", "detector_macos", "detector_windows", "hud"}
        # Check the module's own __dict__ for any imported names from forbidden modules
        for name in forbidden:
            self.assertNotIn(name, telemetry_mod.__dict__,
                f"telemetry.py must not import {name!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
