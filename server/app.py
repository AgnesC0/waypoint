"""
app.py — Waypoint telemetry ingestion server.

Routes
    POST /event    Accept and store one anonymous Waypoint event.
    GET  /healthz  Liveness check.

Run locally
    pip install flask
    python app.py                   # listens on 127.0.0.1:8765
    flask --app app run             # Flask dev server with reloader

Does not log or store IP addresses or user agents.
"""

import re
import time
import uuid as _uuid_mod
from collections import defaultdict
from datetime import datetime

import db
from flask import Flask, jsonify, request

# ── Constants ─────────────────────────────────────────────────────────────────

_ALLOWED_FIELDS  = frozenset({"install_id", "event", "date", "platform", "schema"})
_VALID_EVENTS    = frozenset({"install", "heartbeat"})
_VALID_PLATFORMS = frozenset({"darwin", "win32", "linux"})
_DATE_RE         = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ── In-memory rate limiter ────────────────────────────────────────────────────
# IPs are kept only in this transient structure; they are never written to disk.
_RATE_WINDOW_S = 60
_RATE_LIMIT    = 20   # max requests per IP per window
_rate_counts: dict[str, list[float]] = defaultdict(list)


def _rate_ok(ip: str) -> bool:
    now = time.monotonic()
    recent = [t for t in _rate_counts[ip] if now - t < _RATE_WINDOW_S]
    _rate_counts[ip] = recent
    if len(recent) >= _RATE_LIMIT:
        return False
    _rate_counts[ip].append(now)
    return True


# ── Payload validation ────────────────────────────────────────────────────────

def _validate(body: object) -> str | None:
    """Return an error string if the payload is invalid, None if accepted."""
    if not isinstance(body, dict):
        return "payload must be a JSON object"

    extra = set(body) - _ALLOWED_FIELDS
    if extra:
        return f"unknown fields: {sorted(extra)}"

    missing = _ALLOWED_FIELDS - set(body)
    if missing:
        return f"missing fields: {sorted(missing)}"

    # install_id: must be a valid UUID4
    if not isinstance(body["install_id"], str):
        return "install_id must be a string"
    try:
        parsed = _uuid_mod.UUID(body["install_id"])
        if parsed.version != 4:
            return "install_id must be a UUID version 4"
    except (ValueError, AttributeError):
        return "install_id is not a valid UUID"

    # event
    if body["event"] not in _VALID_EVENTS:
        return f"event must be one of {sorted(_VALID_EVENTS)}"

    # date: YYYY-MM-DD and a real calendar date
    if not isinstance(body["date"], str) or not _DATE_RE.match(body["date"]):
        return "date must match YYYY-MM-DD"
    try:
        datetime.strptime(body["date"], "%Y-%m-%d")
    except ValueError:
        return "date is not a valid calendar date"

    # platform
    if body["platform"] not in _VALID_PLATFORMS:
        return f"platform must be one of {sorted(_VALID_PLATFORMS)}"

    # schema
    if body["schema"] != 1:
        return "schema must be 1"

    return None


# ── App factory ───────────────────────────────────────────────────────────────

def create_app(db_path: str | None = None) -> Flask:
    """
    Return a configured Flask application.
    Pass db_path to override the default database location (used in tests).
    """
    app = Flask(__name__)
    db.configure(db_path or db.DEFAULT_PATH)
    db.init()

    @app.route("/event", methods=["POST"])
    def ingest():
        ip = request.remote_addr or ""
        if not _rate_ok(ip):
            return jsonify({"error": "rate limit exceeded"}), 429

        if not request.is_json:
            return jsonify({"error": "Content-Type must be application/json"}), 415

        body = request.get_json(silent=True)
        if body is None:
            return jsonify({"error": "invalid JSON"}), 400

        err = _validate(body)
        if err:
            return jsonify({"error": err}), 422

        inserted = db.insert_event(
            install_id = body["install_id"],
            event      = body["event"],
            date       = body["date"],
            platform   = body["platform"],
        )
        return jsonify({"status": "ok", "new": inserted}), 200

    @app.route("/healthz", methods=["GET"])
    def health():
        return jsonify({"status": "ok"}), 200

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=8765, debug=False)
