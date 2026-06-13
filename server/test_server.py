"""
test_server.py — Tests for the Waypoint telemetry ingestion server.

Run with:
    python test_server.py
    python -m pytest test_server.py -v
"""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest
import uuid
from datetime import date, timedelta

import app as app_mod
import db
from app import _validate, create_app

# ── Helpers ───────────────────────────────────────────────────────────────────

def _uid() -> str:
    return str(uuid.uuid4())

def _valid(**overrides) -> dict:
    base = {
        "install_id": _uid(),
        "event":      "install",
        "date":       date.today().isoformat(),
        "platform":   "darwin",
        "schema":     1,
    }
    base.update(overrides)
    return base


class ServerTestCase(unittest.TestCase):
    """Base class: creates a temp DB and fresh Flask test client per test."""

    def setUp(self):
        self._tmp    = tempfile.mkdtemp()
        self._db     = os.path.join(self._tmp, "test.db")
        self._orig   = db._db_path
        self._client = create_app(db_path=self._db).test_client()
        app_mod._rate_counts.clear()

    def tearDown(self):
        db.configure(self._orig)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def post(self, payload: dict, content_type: str = "application/json") -> object:
        return self._client.post(
            "/event",
            data         = json.dumps(payload),
            content_type = content_type,
        )

    def json(self, resp) -> dict:
        return json.loads(resp.data)


# ── Valid payloads ────────────────────────────────────────────────────────────

class TestValidPayloads(ServerTestCase):

    def test_valid_install_returns_200_new_true(self):
        r = self.post(_valid(event="install"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.json(r), {"status": "ok", "new": True})

    def test_valid_heartbeat_returns_200_new_true(self):
        r = self.post(_valid(event="heartbeat"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.json(r), {"status": "ok", "new": True})

    def test_all_supported_platforms_accepted(self):
        for platform in ("darwin", "win32", "linux"):
            with self.subTest(platform=platform):
                r = self.post(_valid(install_id=_uid(), platform=platform))
                self.assertEqual(r.status_code, 200)

    def test_healthz(self):
        r = self._client.get("/healthz")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.json(r)["status"], "ok")

    def test_wrong_http_method_on_event(self):
        r = self._client.get("/event")
        self.assertEqual(r.status_code, 405)


# ── Invalid payloads ─────────────────────────────────────────────────────────

class TestInvalidPayloads(ServerTestCase):

    def _expect_422(self, payload: dict):
        r = self.post(payload)
        self.assertEqual(r.status_code, 422, msg=f"Expected 422 for {payload!r}")

    def test_unknown_field_rejected(self):
        self._expect_422(_valid(workspace="secret"))

    def test_multiple_unknown_fields_rejected(self):
        p = _valid()
        p["cwd"]   = "/home/user/project"
        p["token"] = "abc"
        self._expect_422(p)

    def test_missing_install_id_rejected(self):
        p = _valid()
        del p["install_id"]
        self._expect_422(p)

    def test_missing_event_rejected(self):
        p = _valid()
        del p["event"]
        self._expect_422(p)

    def test_missing_date_rejected(self):
        p = _valid()
        del p["date"]
        self._expect_422(p)

    def test_missing_platform_rejected(self):
        p = _valid()
        del p["platform"]
        self._expect_422(p)

    def test_missing_schema_rejected(self):
        p = _valid()
        del p["schema"]
        self._expect_422(p)

    def test_invalid_uuid_format_rejected(self):
        self._expect_422(_valid(install_id="not-a-uuid"))

    def test_uuid_wrong_version_rejected(self):
        # UUID1 is not UUID4
        self._expect_422(_valid(install_id=str(uuid.uuid1())))

    def test_install_id_not_string_rejected(self):
        self._expect_422(_valid(install_id=12345))

    def test_invalid_event_value_rejected(self):
        self._expect_422(_valid(event="session"))
        self._expect_422(_valid(event=""))
        self._expect_422(_valid(event=None))

    def test_invalid_date_format_rejected(self):
        self._expect_422(_valid(date="13/06/2026"))
        self._expect_422(_valid(date="2026-6-1"))
        self._expect_422(_valid(date="20260613"))

    def test_invalid_calendar_date_rejected(self):
        self._expect_422(_valid(date="2026-02-30"))  # Feb 30 does not exist
        self._expect_422(_valid(date="2026-13-01"))  # month 13 does not exist

    def test_unsupported_platform_rejected(self):
        self._expect_422(_valid(platform="haiku"))
        self._expect_422(_valid(platform=""))

    def test_wrong_schema_version_rejected(self):
        self._expect_422(_valid(schema=0))
        self._expect_422(_valid(schema=2))
        self._expect_422(_valid(schema="1"))

    def test_non_json_content_type_rejected(self):
        r = self._client.post(
            "/event",
            data         = json.dumps(_valid()),
            content_type = "text/plain",
        )
        self.assertEqual(r.status_code, 415)

    def test_malformed_json_rejected(self):
        r = self._client.post(
            "/event",
            data         = b"{not valid json}",
            content_type = "application/json",
        )
        self.assertEqual(r.status_code, 400)

    def test_json_array_instead_of_object_rejected(self):
        r = self._client.post(
            "/event",
            data         = json.dumps([_valid()]),
            content_type = "application/json",
        )
        self.assertEqual(r.status_code, 422)


# ── Deduplication ─────────────────────────────────────────────────────────────

class TestDeduplication(ServerTestCase):

    def test_duplicate_install_returns_new_false(self):
        payload = _valid(event="install")
        r1 = self.post(payload)
        r2 = self.post(payload)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(self.json(r1)["new"])
        self.assertFalse(self.json(r2)["new"])

    def test_duplicate_heartbeat_same_date_returns_new_false(self):
        payload = _valid(event="heartbeat", date="2026-06-13")
        r1 = self.post(payload)
        r2 = self.post(payload)
        self.assertTrue(self.json(r1)["new"])
        self.assertFalse(self.json(r2)["new"])

    def test_heartbeat_different_dates_both_accepted(self):
        uid = _uid()
        r1 = self.post(_valid(install_id=uid, event="heartbeat", date="2026-06-13"))
        r2 = self.post(_valid(install_id=uid, event="heartbeat", date="2026-06-14"))
        self.assertTrue(self.json(r1)["new"])
        self.assertTrue(self.json(r2)["new"])

    def test_install_and_heartbeat_same_install_id_both_accepted(self):
        uid = _uid()
        r1 = self.post(_valid(install_id=uid, event="install",   date="2026-06-13"))
        r2 = self.post(_valid(install_id=uid, event="heartbeat", date="2026-06-13"))
        self.assertTrue(self.json(r1)["new"])
        self.assertTrue(self.json(r2)["new"])

    def test_different_install_ids_both_accepted(self):
        r1 = self.post(_valid(install_id=_uid(), event="install"))
        r2 = self.post(_valid(install_id=_uid(), event="install"))
        self.assertTrue(self.json(r1)["new"])
        self.assertTrue(self.json(r2)["new"])


# ── Metrics ───────────────────────────────────────────────────────────────────

class TestMetrics(ServerTestCase):

    def _seed(self, install_id: str, event: str, event_date: str,
              platform: str = "darwin") -> None:
        """Insert directly via db to control dates precisely."""
        db.insert_event(install_id, event, event_date, platform)

    def test_empty_db_returns_zeros(self):
        m = db.metrics()
        self.assertEqual(m, {"total_installs": 0, "dau": 0, "wau": 0, "mau": 0})

    def test_total_installs_counts_distinct_install_ids(self):
        ids = [_uid() for _ in range(3)]
        for uid in ids:
            self._seed(uid, "install", "2025-01-01")
        # Duplicate install for ids[0] should not inflate count
        self._seed(ids[0], "install", "2025-01-01")  # → ignored by uq_install
        self.assertEqual(db.metrics()["total_installs"], 3)

    def test_dau_wau_mau_with_known_dates(self):
        today  = date.today()
        ago3   = (today - timedelta(days=3)).isoformat()
        ago8   = (today - timedelta(days=8)).isoformat()
        ago35  = (today - timedelta(days=35)).isoformat()
        today  = today.isoformat()

        # User A: active today → DAU + WAU + MAU
        uid_a = _uid()
        self._seed(uid_a, "install",   today, "darwin")
        self._seed(uid_a, "heartbeat", today, "darwin")

        # User B: active 3 days ago → WAU + MAU (not DAU)
        uid_b = _uid()
        self._seed(uid_b, "install",   ago35, "win32")   # install outside MAU window
        self._seed(uid_b, "heartbeat", ago3,  "win32")   # heartbeat inside WAU window

        # User C: active 8 days ago → MAU only (not DAU, not WAU)
        uid_c = _uid()
        self._seed(uid_c, "install",   ago8, "linux")
        self._seed(uid_c, "heartbeat", ago8, "linux")

        # User D: active 35 days ago → none of DAU/WAU/MAU
        uid_d = _uid()
        self._seed(uid_d, "install",   ago35, "darwin")
        self._seed(uid_d, "heartbeat", ago35, "darwin")

        m = db.metrics()
        self.assertEqual(m["total_installs"], 4)  # all 4 sent install events
        self.assertEqual(m["dau"],            1)  # user A only
        self.assertEqual(m["wau"],            2)  # users A + B
        self.assertEqual(m["mau"],            3)  # users A + B + C

    def test_dau_via_endpoint(self):
        """Confirm HTTP path lands in DB and shows up in metrics."""
        self.post(_valid(event="install", date=date.today().isoformat()))
        self.assertEqual(db.metrics()["dau"], 1)


# ── Privacy: no IP or user agent stored ──────────────────────────────────────

class TestPrivacy(ServerTestCase):

    def test_db_has_no_ip_or_user_agent_column(self):
        conn = sqlite3.connect(self._db)
        cur  = conn.execute("PRAGMA table_info(events)")
        cols = {row[1] for row in cur.fetchall()}
        conn.close()
        for forbidden in ("ip", "ip_address", "user_agent", "remote_addr", "host"):
            self.assertNotIn(forbidden, cols,
                f"Column {forbidden!r} must not exist in the events table")

    def test_inserted_row_contains_no_client_network_info(self):
        self.post(_valid(event="install"))
        conn = sqlite3.connect(self._db)
        cur  = conn.execute("SELECT * FROM events LIMIT 1")
        row  = cur.fetchone()
        cols = [d[0] for d in cur.description]
        conn.close()
        row_dict = dict(zip(cols, row))
        for key in ("ip", "ip_address", "user_agent", "remote_addr"):
            self.assertNotIn(key, row_dict)


# ── Rate limiting ─────────────────────────────────────────────────────────────

class TestRateLimiting(ServerTestCase):

    def test_rate_limit_triggers_429(self):
        # Send one more than the limit from the same IP
        responses = []
        for _ in range(app_mod._RATE_LIMIT + 1):
            r = self._client.post(
                "/event",
                data         = json.dumps(_valid()),
                content_type = "application/json",
                environ_base = {"REMOTE_ADDR": "10.0.0.1"},
            )
            responses.append(r.status_code)
        self.assertIn(429, responses)

    def test_different_ips_not_cross_limited(self):
        """Each IP has its own counter; one IP hitting the limit does not block others."""
        # Fill ip A to the limit
        for _ in range(app_mod._RATE_LIMIT):
            self._client.post(
                "/event",
                data         = json.dumps(_valid()),
                content_type = "application/json",
                environ_base = {"REMOTE_ADDR": "10.0.0.2"},
            )
        # ip B should still be accepted
        r = self._client.post(
            "/event",
            data         = json.dumps(_valid()),
            content_type = "application/json",
            environ_base = {"REMOTE_ADDR": "10.0.0.3"},
        )
        self.assertEqual(r.status_code, 200)


# ── Validate function unit tests ──────────────────────────────────────────────

class TestValidateUnit(unittest.TestCase):
    """Direct tests of _validate() without HTTP overhead."""

    def test_valid_payload_returns_none(self):
        self.assertIsNone(_validate(_valid()))

    def test_extra_field_detected(self):
        self.assertIn("unknown", _validate(_valid(extra_key="x")))

    def test_session_fields_rejected(self):
        for field in ("cwd", "path", "tty", "pid", "window_id",
                      "workspace", "duration_seconds", "hint"):
            p = _valid()
            p[field] = "value"
            err = _validate(p)
            self.assertIsNotNone(err, f"Expected error for field {field!r}")
            self.assertIn("unknown", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
