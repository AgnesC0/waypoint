"""
telemetry.py — Optional anonymous install and active-user counting.

Disabled by default. To opt in, add to config.yaml:

    telemetry:
      enabled: true
      endpoint: https://your-collection-endpoint

When enabled, sends at most two kinds of event:
  "install"   — once, on the first launch after opt-in
  "heartbeat" — at most once per calendar day on subsequent launches

Complete payload (no other fields are ever included):
    {
      "install_id": "<uuid4>",
      "event":      "install" | "heartbeat",
      "date":       "YYYY-MM-DD",
      "platform":   "<sys.platform>",
      "schema":     1
    }

This module never imports Workspace, logger, detector, or hud.
It never reads or transmits workspace names, paths, cwds, tty, pid,
window_id, commands, git data, hint text, session durations, or task data.
"""

import datetime
import json
import os
import sys
import urllib.request
import uuid

_DATA_DIR        = os.path.expanduser("~/.waypoint")
_INSTALL_ID_PATH = os.path.join(_DATA_DIR, "install_id")
_HEARTBEAT_PATH  = os.path.join(_DATA_DIR, "last_heartbeat_date")

_SCHEMA    = 1
_TIMEOUT_S = 5


def maybe_emit(config: dict) -> None:
    """
    No-op unless config contains telemetry.enabled = true and a non-empty endpoint.
    When opted in: sends "install" on the first run, then "heartbeat" at most once
    per calendar day.  Creates no files and makes no network calls when disabled.
    """
    tel = config.get("telemetry") or {}
    if not tel.get("enabled"):
        return
    endpoint = (tel.get("endpoint") or "").strip()
    if not endpoint:
        return

    today      = datetime.date.today().isoformat()
    install_id, is_new = _get_or_create_install_id()

    if is_new:
        _send(endpoint, _payload(install_id, "install", today))
        _write_heartbeat_date(today)
    elif _heartbeat_due(today):
        _send(endpoint, _payload(install_id, "heartbeat", today))
        _write_heartbeat_date(today)


# ── Internals ─────────────────────────────────────────────────────────────────

def _get_or_create_install_id() -> tuple[str, bool]:
    """Return (install_id, is_new).  Writes to disk only after opt-in is confirmed."""
    os.makedirs(_DATA_DIR, exist_ok=True, mode=0o700)
    try:
        with open(_INSTALL_ID_PATH) as fh:
            stored = fh.read().strip()
        if stored:
            return stored, False
    except FileNotFoundError:
        pass
    new_id = str(uuid.uuid4())
    with open(_INSTALL_ID_PATH, "w") as fh:
        fh.write(new_id + "\n")
    return new_id, True


def _heartbeat_due(today: str) -> bool:
    try:
        with open(_HEARTBEAT_PATH) as fh:
            return fh.read().strip() != today
    except FileNotFoundError:
        return True


def _write_heartbeat_date(today: str) -> None:
    try:
        with open(_HEARTBEAT_PATH, "w") as fh:
            fh.write(today + "\n")
    except OSError:
        pass


def _payload(install_id: str, event: str, date: str) -> dict:
    return {
        "install_id": install_id,
        "event":      event,
        "date":       date,
        "platform":   sys.platform,
        "schema":     _SCHEMA,
    }


def _send(endpoint: str, payload: dict) -> None:
    try:
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(
            endpoint,
            data    = data,
            headers = {"Content-Type": "application/json"},
            method  = "POST",
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S):
            pass
    except Exception:
        pass
