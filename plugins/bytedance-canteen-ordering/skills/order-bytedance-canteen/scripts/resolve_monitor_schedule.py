#!/usr/bin/env python3
"""Compute the next adaptive released-stock monitor check."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


def parse_datetime(value: str, timezone: ZoneInfo) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def one_step_faster(
    interval: int,
    available_intervals: list[int],
) -> int:
    values = sorted(set(available_intervals))
    smaller = [value for value in values if value < interval]
    return smaller[-1] if smaller else values[0]


def one_step_slower(
    interval: int,
    available_intervals: list[int],
) -> int:
    values = sorted(set(available_intervals))
    larger = [value for value in values if value > interval]
    return larger[0] if larger else values[-1]


def resolve_schedule(
    profile: dict,
    *,
    now: datetime,
    regular_order_cutoff_at: datetime,
    pickup_start_at: datetime,
    live_final_stop_at: datetime | None = None,
    current_score: int | None = None,
    consecutive_no_change: int = 0,
    recent_inventory_change: bool = False,
    state: str = "active",
    mode: str = "improve_existing",
) -> dict:
    policy = profile["monitoring_policy"]
    cadence = policy["cadence"]
    pickup_stop = pickup_start_at - timedelta(
        minutes=policy["stop_before_pickup_minutes"]
    )
    stop_at = min(
        value
        for value in (pickup_stop, live_final_stop_at)
        if value is not None
    )
    phase = (
        "release_only"
        if now >= regular_order_cutoff_at
        else "regular_window"
    )
    if state != "active":
        return {
            "state": state,
            "action": "no_schedule",
            "mode": mode,
            "window_phase": phase,
            "stop_at": stop_at.isoformat(),
            "next_check_at": None,
            "interval_minutes": None,
            "reason_codes": ["state_not_active"],
        }
    if now >= stop_at:
        return {
            "state": "expired",
            "action": "stop_monitoring",
            "mode": mode,
            "window_phase": phase,
            "stop_at": stop_at.isoformat(),
            "next_check_at": None,
            "interval_minutes": None,
            "reason_codes": ["pickup_safety_boundary_reached"],
        }

    remaining_hours = (stop_at - now).total_seconds() / 3600
    bands = sorted(
        cadence["bands"],
        key=lambda band: band["remaining_hours_gte"],
        reverse=True,
    )
    selected = next(
        band
        for band in bands
        if remaining_hours >= band["remaining_hours_gte"]
    )
    interval = selected["interval_minutes"]
    options = [
        cadence["min_interval_minutes"],
        cadence["max_interval_minutes"],
        *(band["interval_minutes"] for band in bands),
    ]
    reasons = [
        f"remaining_hours_gte_{selected['remaining_hours_gte']}",
        phase,
    ]

    if (
        current_score is not None
        and current_score < cadence["high_regret_score_below"]
    ):
        interval = one_step_faster(interval, options)
        reasons.append("high_regret")
    if recent_inventory_change:
        interval = one_step_faster(interval, options)
        reasons.append("recent_inventory_change")
    if (
        consecutive_no_change >= cadence["no_change_backoff_after"]
        and remaining_hours > 24
    ):
        interval = round(
            interval * cadence["no_change_backoff_multiplier"]
        )
        reasons.append("no_change_backoff")

    effort = policy["effort_mode"]
    if effort == "aggressive":
        interval = one_step_faster(interval, options)
        reasons.append("aggressive_effort")
    elif effort == "economy" and remaining_hours > 6:
        interval = one_step_slower(interval, options)
        reasons.append("economy_effort")

    interval = max(
        cadence["min_interval_minutes"],
        min(interval, cadence["max_interval_minutes"]),
    )
    next_check_at = now + timedelta(minutes=interval)
    if next_check_at >= stop_at:
        return {
            "state": "expired",
            "action": "stop_monitoring",
            "mode": mode,
            "window_phase": phase,
            "stop_at": stop_at.isoformat(),
            "next_check_at": None,
            "interval_minutes": None,
            "reason_codes": [*reasons, "next_check_crosses_stop"],
        }
    return {
        "state": "active",
        "action": "schedule_one_shot_heartbeat",
        "mode": mode,
        "window_phase": phase,
        "stop_at": stop_at.isoformat(),
        "next_check_at": next_check_at.isoformat(),
        "interval_minutes": interval,
        "reason_codes": reasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--now")
    parser.add_argument("--regular-order-cutoff-at", required=True)
    parser.add_argument("--pickup-start-at", required=True)
    parser.add_argument("--live-final-stop-at")
    parser.add_argument("--current-score", type=int)
    parser.add_argument("--consecutive-no-change", type=int, default=0)
    parser.add_argument("--recent-inventory-change", action="store_true")
    parser.add_argument("--state", default="active")
    parser.add_argument(
        "--mode",
        choices=("improve_existing", "fill_missing"),
        default="improve_existing",
    )
    args = parser.parse_args()

    profile = json.loads(
        args.profile.expanduser().resolve().read_text(encoding="utf-8")
    )
    timezone = ZoneInfo(profile["identity"]["timezone"])
    now = (
        parse_datetime(args.now, timezone)
        if args.now
        else datetime.now(timezone)
    )
    if args.consecutive_no_change < 0:
        parser.error("--consecutive-no-change must be non-negative")
    if args.current_score is not None and not 0 <= args.current_score <= 100:
        parser.error("--current-score must be between 0 and 100")

    result = resolve_schedule(
        profile,
        now=now,
        regular_order_cutoff_at=parse_datetime(
            args.regular_order_cutoff_at,
            timezone,
        ),
        pickup_start_at=parse_datetime(args.pickup_start_at, timezone),
        live_final_stop_at=(
            parse_datetime(args.live_final_stop_at, timezone)
            if args.live_final_stop_at
            else None
        ),
        current_score=args.current_score,
        consecutive_no_change=args.consecutive_no_change,
        recent_inventory_change=args.recent_inventory_change,
        state=args.state,
        mode=args.mode,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
