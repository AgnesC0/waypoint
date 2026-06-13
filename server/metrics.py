#!/usr/bin/env python3
"""
metrics.py — Print Waypoint telemetry usage counts.

Usage:
    python metrics.py
    python metrics.py --db /path/to/telemetry.db
"""

import argparse
import os
import sys

import db


def main() -> None:
    parser = argparse.ArgumentParser(description="Waypoint telemetry metrics")
    parser.add_argument(
        "--db",
        default=db.DEFAULT_PATH,
        metavar="PATH",
        help=f"SQLite database path (default: {db.DEFAULT_PATH})",
    )
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"No database at {args.db} — no events received yet.", file=sys.stderr)
        sys.exit(1)

    db.configure(args.db)
    m = db.metrics()

    print(f"Total installs : {m['total_installs']}")
    print(f"DAU            : {m['dau']}")
    print(f"WAU            : {m['wau']}")
    print(f"MAU            : {m['mau']}")


if __name__ == "__main__":
    main()
