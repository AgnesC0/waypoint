"""
test_session_log_privacy.py — Confirms session_log.jsonl only ever contains
the anonymous, privacy-reduced fields established in the telemetry review.

Run with:
    python test_session_log_privacy.py
    python -m pytest test_session_log_privacy.py
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import logger as logger_mod
from logger import WorkspaceLogger, _SESSION_LOG_PATH
from detector import Workspace

# Fields permitted in session_log.jsonl — no identity, path, or process info.
_SAFE_FIELDS = frozenset({
    "schema_version",
    "hour",
    "day",
    "duration_seconds",
    "end_reason",
    "task_load",
    "session_depth",
    "workspace_count_today",
    "hint_type",
    "recommendation_accepted",
    "feedback_label",
})

# Fields that must never appear in session_log.jsonl.
_UNSAFE_FIELDS = frozenset({
    "cwd", "path", "tty", "pid", "window_id", "username",
    "workspace", "project", "name",
    "start_time", "end_time",
    "context",
})


def _ws(name: str) -> Workspace:
    """Workspace with all sensitive fields populated — they must never reach the log."""
    return Workspace(
        name=name,
        path=f"/home/alice/projects/{name.lower()}",
        window_id="99001",
        tab_index=2,
        tty="/dev/ttys003",
        cwd=f"/home/alice/projects/{name.lower()}/src",
        pid="8888",
    )


class TestSessionLogPrivacy(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._session_log   = os.path.join(self._tmp, "session_log.jsonl")
        self._activity_log  = os.path.join(self._tmp, "activity_log.jsonl")
        self._completed_log = os.path.join(self._tmp, "completed_sessions.jsonl")
        # Redirect module-level log paths to temp dir so tests are side-effect-free.
        self._patches = [
            patch.object(logger_mod, "_SESSION_LOG_PATH",  self._session_log),
            patch.object(logger_mod, "_COMPLETED_PATH",    self._completed_log),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _records(self) -> list[dict]:
        if not os.path.exists(self._session_log):
            return []
        with open(self._session_log) as fh:
            return [json.loads(line) for line in fh if line.strip()]

    # ── Core schema tests ─────────────────────────────────────────────────────

    def test_only_safe_fields_after_session_end(self):
        """Records written on shutdown must contain only permitted fields."""
        log = WorkspaceLogger(log_path=self._activity_log)
        log.update([_ws("Alpha")])
        log.shutdown()

        records = self._records()
        self.assertTrue(records, "session_log.jsonl must have at least one record after shutdown")
        for rec in records:
            leaked = set(rec) - _SAFE_FIELDS
            self.assertFalse(leaked,
                f"Unsafe fields leaked into session_log.jsonl: {leaked}\nRecord: {rec}")

    def test_only_safe_fields_after_workspace_switch(self):
        """Records written on a workspace switch must contain only permitted fields."""
        log = WorkspaceLogger(log_path=self._activity_log)
        log.update([_ws("Alpha")])
        log.update([_ws("Beta")])   # triggers switch: Alpha record written
        log.shutdown()              # Beta record written

        records = self._records()
        self.assertTrue(records, "session_log.jsonl must have records after a switch + shutdown")
        for rec in records:
            leaked = set(rec) - _SAFE_FIELDS
            self.assertFalse(leaked,
                f"Unsafe fields after workspace switch: {leaked}\nRecord: {rec}")

    def test_unsafe_fields_absent(self):
        """Each explicitly unsafe field must never appear in any record."""
        log = WorkspaceLogger(log_path=self._activity_log)
        log.update([_ws("Secret")])
        log.shutdown()

        for rec in self._records():
            for field in _UNSAFE_FIELDS:
                self.assertNotIn(field, rec,
                    f"Field {field!r} must never appear in session_log.jsonl\nRecord: {rec}")

    def test_required_safe_fields_present(self):
        """Every record must include all structural safe fields."""
        required = {
            "schema_version", "hour", "day", "duration_seconds",
            "end_reason", "task_load", "session_depth",
            "workspace_count_today", "recommendation_accepted",
        }
        log = WorkspaceLogger(log_path=self._activity_log)
        log.update([_ws("Gamma")])
        log.shutdown()

        for rec in self._records():
            missing = required - set(rec)
            self.assertFalse(missing,
                f"Required safe fields missing from record: {missing}\nRecord: {rec}")

    def test_hint_type_is_enum_or_none(self):
        """hint_type must be one of the allowed enum labels or null — never free text."""
        allowed = {"manual", "semantic_diff", "commit", "foreground_cmd", None}
        log = WorkspaceLogger(log_path=self._activity_log)
        log.update([_ws("Delta")])
        log.shutdown()

        for rec in self._records():
            self.assertIn(rec.get("hint_type"), allowed,
                f"hint_type {rec.get('hint_type')!r} is not a permitted label\nRecord: {rec}")

    # ── Real-file validation ──────────────────────────────────────────────────

    def test_existing_real_session_log(self):
        """If ~/.waypoint/session_log.jsonl already exists, every line must pass."""
        if not os.path.exists(_SESSION_LOG_PATH):
            self.skipTest("No existing session_log.jsonl — skipping real-file check")
        with open(_SESSION_LOG_PATH) as fh:
            lines = [line.strip() for line in fh if line.strip()]
        for i, line in enumerate(lines, 1):
            rec = json.loads(line)
            leaked = set(rec) - _SAFE_FIELDS
            self.assertFalse(leaked,
                f"Line {i} of existing session_log.jsonl contains unsafe fields: {leaked}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
