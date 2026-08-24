#!/usr/bin/env python3
"""Persist or clear a resumable canteen ordering request."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--clear", action="store_true")
    parser.add_argument("--request")
    parser.add_argument("--target-week")
    parser.add_argument("--weekdays", default="")
    parser.add_argument("--lunch", action="store_true")
    parser.add_argument("--dinner", action="store_true")
    parser.add_argument(
        "--state",
        choices=(
            "waiting_for_window",
            "waiting_for_page",
            "window_anomaly",
            "needs_recovery",
            "target_closed",
        ),
    )
    parser.add_argument("--reason", default="")
    parser.add_argument("--next-check-at")
    parser.add_argument(
        "--occupied-slot",
        action="append",
        default=[],
        help="Repeat as YYYY-MM-DD:lunch or YYYY-MM-DD:dinner",
    )
    args = parser.parse_args()

    profile_path = args.profile.expanduser().resolve()
    output_path = (
        args.output.expanduser().resolve()
        if args.output
        else profile_path.parent / "pending-intent.json"
    )
    if args.clear:
        output_path.unlink(missing_ok=True)
        print(json.dumps({"status": "cleared", "path": str(output_path)}))
        return 0

    missing = [
        flag
        for flag, value in (
            ("--request", args.request),
            ("--target-week", args.target_week),
            ("--state", args.state),
        )
        if not value
    ]
    if missing:
        parser.error(f"required unless --clear: {', '.join(missing)}")

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    timezone = ZoneInfo(profile["identity"]["timezone"])
    weekdays = [int(value) for value in args.weekdays.split(",") if value]
    if any(value < 1 or value > 7 for value in weekdays):
        parser.error("--weekdays must contain comma-separated ISO weekdays 1-7")

    value = {
        "schema_version": 1,
        "saved_at": datetime.now(timezone).isoformat(),
        "original_request": args.request,
        "target_week": args.target_week,
        "coverage": {
            "weekdays": weekdays,
            "lunch": args.lunch,
            "dinner": args.dinner,
        },
        "profile_path": str(profile_path),
        "lifecycle": {
            "state": args.state,
            "reason": args.reason,
            "next_check_at": args.next_check_at,
        },
        "occupied_slots": args.occupied_slot,
        "confirmation": {
            "obtained": False,
            "scope": "execution_manifest",
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "saved", "path": str(output_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
