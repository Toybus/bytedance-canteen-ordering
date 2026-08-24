#!/usr/bin/env python3
"""Create persisted adaptive monitoring for one canteen meal slot."""

from __future__ import annotations

import argparse
import copy
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from resolve_monitor_schedule import parse_datetime, resolve_schedule


ORDER_ARGUMENTS = (
    "dish",
    "pickup_point",
    "pickup_time",
    "status",
    "score",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=("improve_existing", "fill_missing"),
        default="improve_existing",
    )
    parser.add_argument("--date", required=True)
    parser.add_argument("--meal", choices=("lunch", "dinner"), required=True)
    parser.add_argument("--building", required=True)
    parser.add_argument("--dish")
    parser.add_argument("--pickup-point")
    parser.add_argument("--pickup-time")
    parser.add_argument("--status")
    parser.add_argument("--score", type=int)
    parser.add_argument("--regular-order-cutoff-at", required=True)
    parser.add_argument("--pickup-start-at", required=True)
    parser.add_argument("--live-final-stop-at")
    parser.add_argument("--now")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    date.fromisoformat(args.date)
    if not args.building.strip():
        parser.error("--building must not be empty")
    if args.mode == "improve_existing":
        missing = [
            f"--{name.replace('_', '-')}"
            for name in ORDER_ARGUMENTS
            if getattr(args, name) is None
        ]
        if missing:
            parser.error(
                "improve_existing requires " + ", ".join(missing)
            )
        if not 0 <= args.score <= 100:
            parser.error("--score must be between 0 and 100")
        if not all(
            value.strip()
            for value in (
                args.dish,
                args.pickup_point,
                args.pickup_time,
                args.status,
            )
        ):
            parser.error("current-order text fields must not be empty")

    profile_path = args.profile.expanduser().resolve()
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    timezone = ZoneInfo(profile["identity"]["timezone"])
    now = (
        parse_datetime(args.now, timezone)
        if args.now
        else datetime.now(timezone)
    )
    regular_cutoff = parse_datetime(
        args.regular_order_cutoff_at,
        timezone,
    )
    pickup_start = parse_datetime(args.pickup_start_at, timezone)
    live_final_stop = (
        parse_datetime(args.live_final_stop_at, timezone)
        if args.live_final_stop_at
        else None
    )
    schedule = resolve_schedule(
        profile,
        now=now,
        regular_order_cutoff_at=regular_cutoff,
        pickup_start_at=pickup_start,
        live_final_stop_at=live_final_stop,
        current_score=args.score,
        mode=args.mode,
    )
    if schedule["state"] == "expired":
        parser.error("monitor would already be expired")

    monitor_id = f"{args.date}-{args.meal}"
    output = (
        args.output.expanduser().resolve()
        if args.output
        else Path(profile["paths"]["monitor_dir"]).expanduser().resolve()
        / f"{monitor_id}.json"
    )
    if output.exists() and not args.force:
        print(
            json.dumps(
                {
                    "status": "existing",
                    "monitor_id": monitor_id,
                    "path": str(output),
                }
            )
        )
        return 0

    skill_root = Path(__file__).resolve().parent.parent
    monitor = json.loads(
        (skill_root / "assets" / "monitor.template.json").read_text(
            encoding="utf-8"
        )
    )
    monitor["monitor_id"] = monitor_id
    monitor["mode"] = args.mode
    monitor["slot"] = {
        "date": args.date,
        "meal": args.meal,
        "building": args.building.strip(),
    }
    if args.mode == "improve_existing":
        monitor["current_order"] = {
            "dish": args.dish.strip(),
            "pickup_point": args.pickup_point.strip(),
            "pickup_time": args.pickup_time.strip(),
            "status": args.status.strip(),
            "score": args.score,
            "quality": "provisional",
        }
    monitor["started_at"] = now.isoformat()
    monitor["regular_order_cutoff_at"] = regular_cutoff.isoformat()
    monitor["pickup_start_at"] = pickup_start.isoformat()
    monitor["stop_at"] = schedule["stop_at"]
    monitor["window_phase"] = schedule["window_phase"]
    policy = profile["monitoring_policy"]
    monitor["policy_snapshot"] = {
        "minimum_improvement_points": policy[
            "minimum_improvement_points"
        ],
        "stop_before_pickup_minutes": policy[
            "stop_before_pickup_minutes"
        ],
        "continue_after_regular_cutoff_for_releases": policy[
            "continue_after_regular_cutoff_for_releases"
        ],
        "effort_mode": policy["effort_mode"],
        "cadence": copy.deepcopy(policy["cadence"]),
        "replacement_mode": policy["replacement_mode"],
        "recovery_sequence": copy.deepcopy(policy["recovery_sequence"]),
    }
    monitor["schedule"] = {
        "mode": "adaptive",
        "last_checked_at": now.isoformat(),
        "next_check_at": schedule["next_check_at"],
        "last_interval_minutes": schedule["interval_minutes"],
        "consecutive_no_change": 0,
        "recent_inventory_change": False,
        "reason_codes": schedule["reason_codes"],
    }
    monitor["events"].append(
        {
            "at": now.isoformat(),
            "type": "monitor_created",
            "reason": (
                "provisional_order"
                if args.mode == "improve_existing"
                else "requested_coverage_missing_after_regular_cutoff"
            ),
        }
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(monitor, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "created",
                "monitor_id": monitor_id,
                "mode": args.mode,
                "window_phase": monitor["window_phase"],
                "next_check_at": monitor["schedule"]["next_check_at"],
                "path": str(output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
