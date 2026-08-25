#!/usr/bin/env python3
"""Resolve a canteen request to a normal, resumable business state."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


def load_profile(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_now(value: str | None, timezone: ZoneInfo) -> datetime:
    if value is None:
        return datetime.now(timezone)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def output(
    state: str,
    action: str,
    expected_open: datetime,
    remaining_slots: int,
    next_check_at: datetime | None = None,
    reason: str | None = None,
) -> int:
    result = {
        "state": state,
        "action": action,
        "expected_open": expected_open.isoformat(),
        "next_check_at": next_check_at.isoformat() if next_check_at else None,
        "remaining_slots": remaining_slots,
        "normal_order": {
            "authorization": "delegated",
            "receipt": "after_submit",
        },
    }
    if reason:
        result["reason"] = reason
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--target-week", required=True, help="Monday in YYYY-MM-DD")
    parser.add_argument(
        "--menu-state",
        choices=("open", "closed", "error", "unknown"),
        required=True,
    )
    parser.add_argument(
        "--cutoff-state",
        choices=("open", "closed", "unknown"),
        default="unknown",
    )
    parser.add_argument(
        "--release-state",
        choices=("available", "none", "final_closed", "unknown"),
        default="unknown",
        help="Live released-stock state after the regular ordering cutoff.",
    )
    parser.add_argument("--occupied-slots", type=int, required=True)
    parser.add_argument("--expected-slots", type=int, required=True)
    parser.add_argument("--now", help="ISO datetime; defaults to now in profile timezone")
    args = parser.parse_args()

    profile = load_profile(args.profile)
    timezone = ZoneInfo(profile["identity"]["timezone"])
    target_monday = date.fromisoformat(args.target_week)
    if target_monday.isoweekday() != 1:
        raise ValueError("--target-week must be a Monday")
    if args.expected_slots < 0 or args.occupied_slots < 0:
        raise ValueError("slot counts must be non-negative")
    if args.occupied_slots > args.expected_slots:
        raise ValueError("occupied slots cannot exceed expected slots")

    window = profile["ordering_window"]
    runtime = profile["runtime_policy"]
    open_time = time.fromisoformat(window["next_week_opens_time"])
    expected_open_date = target_monday - timedelta(
        days=window["target_week_offset_days"]
    )
    if expected_open_date.isoweekday() != window["next_week_opens_weekday"]:
        raise ValueError(
            "ordering_window weekday and target_week_offset_days are inconsistent"
        )
    expected_open = datetime.combine(expected_open_date, open_time, tzinfo=timezone)
    now = parse_now(args.now, timezone)
    remaining = args.expected_slots - args.occupied_slots

    if args.expected_slots > 0 and remaining == 0:
        return output(
            "already_complete",
            "verify_existing_orders_and_finish",
            expected_open,
            remaining,
        )

    if args.menu_state in {"error", "unknown"}:
        return output(
            "needs_recovery",
            "persist_intent_and_recover_browser_auth_or_page",
            expected_open,
            remaining,
            reason=f"menu_state_{args.menu_state}",
        )

    if args.cutoff_state == "closed":
        if args.release_state == "final_closed":
            return output(
                "target_closed",
                "preserve_existing_orders_and_offer_next_eligible_week",
                expected_open,
                remaining,
            )
        if args.release_state == "available":
            state = "partial_fill" if args.occupied_slots else "ready_to_plan"
            return output(
                state,
                "inspect_released_inventory_for_missing_slots",
                expected_open,
                remaining,
            )
        return output(
            "release_only",
            "monitor_released_inventory_for_missing_slots",
            expected_open,
            remaining,
            reason="regular_ordering_closed_but_releases_can_reopen_stock",
        )

    if args.menu_state == "open":
        state = "partial_fill" if args.occupied_slots else "ready_to_plan"
        return output(
            state,
            "inspect_live_menus_for_missing_slots",
            expected_open,
            remaining,
        )

    grace = timedelta(minutes=runtime["open_check_grace_minutes"])
    retry = timedelta(minutes=runtime["retry_minutes"])
    horizon = expected_open + timedelta(hours=runtime["max_open_delay_hours"])
    if now < expected_open:
        return output(
            "waiting_for_window",
            "persist_intent_and_schedule_resume",
            expected_open,
            remaining,
            expected_open + grace,
        )
    if now <= horizon:
        return output(
            "waiting_for_page",
            "persist_intent_and_schedule_bounded_retry",
            expected_open,
            remaining,
            min(now + retry, horizon),
        )
    return output(
        "window_anomaly",
        "preserve_intent_and_report_live_page_delay",
        expected_open,
        remaining,
        reason="menu_still_closed_beyond_retry_horizon",
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"state": "needs_recovery", "reason": str(exc)}))
        sys.exit(1)
