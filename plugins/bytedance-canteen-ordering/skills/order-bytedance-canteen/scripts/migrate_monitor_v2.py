#!/usr/bin/env python3
"""Upgrade one persisted canteen monitor from schema v1 to schema v2."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from resolve_monitor_schedule import parse_datetime, resolve_schedule


STATE_MIGRATIONS = {
    "approval_pending": "swap_approval_pending",
}
SUPPORTED_STATES = {
    "active",
    "checking",
    "swap_approval_pending",
    "swapping",
    "completed",
    "expired",
    "cancelled",
    "current_order_changed",
    "needs_recovery",
}


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--monitor", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--regular-order-cutoff-at")
    parser.add_argument("--pickup-start-at")
    parser.add_argument("--live-final-stop-at")
    parser.add_argument("--now")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source = args.monitor.expanduser().resolve()
    destination = (
        args.output.expanduser().resolve() if args.output else source
    )
    original = load(source)
    version = original.get("schema_version")
    if version not in {1, 2}:
        parser.error(f"unsupported monitor schema_version: {version}")
    recovered_legacy_submit = False
    if version == 2:
        result = copy.deepcopy(original)
        if (
            result.get("mode") == "fill_missing"
            and result.get("state") == "submit_approval_pending"
        ):
            recovered_legacy_submit = True
            recovered_at = args.now or datetime.now().astimezone().isoformat()
            result["state"] = "active"
            result["best_observation"] = None
            result["pending_swap"] = None
            schedule = result.setdefault("schedule", {})
            schedule["next_check_at"] = recovered_at
            reasons = schedule.setdefault("reason_codes", [])
            if "legacy_submit_confirmation_removed" not in reasons:
                reasons.append("legacy_submit_confirmation_removed")
            automation = result.setdefault("automation", {})
            automation["scheduled_for"] = recovered_at
            automation["status"] = "migration_requires_reschedule"
            result.setdefault("events", []).append(
                {
                    "at": recovered_at,
                    "type": "legacy_submit_confirmation_removed",
                    "note": (
                        "Discarded the stale candidate and resumed live "
                        "inventory checking under delegated missing-slot submit."
                    ),
                }
            )
    else:
        if not args.regular_order_cutoff_at or not args.pickup_start_at:
            parser.error(
                "schema v1 migration requires "
                "--regular-order-cutoff-at and --pickup-start-at "
                "from the live meal slot"
            )
        profile = load(args.profile.expanduser().resolve())
        if profile.get("schema_version") not in {4, 5, 6}:
            parser.error("migrate the profile to schema v4, v5, or v6 first")
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
        old_state = STATE_MIGRATIONS.get(
            original.get("state"),
            original.get("state"),
        )
        if old_state not in SUPPORTED_STATES:
            old_state = "needs_recovery"
        schedule = resolve_schedule(
            profile,
            now=now,
            regular_order_cutoff_at=regular_cutoff,
            pickup_start_at=pickup_start,
            live_final_stop_at=live_final_stop,
            current_score=original.get("current_order", {}).get("score"),
            state=("active" if old_state == "active" else old_state),
            mode="improve_existing",
        )
        skill_root = Path(__file__).resolve().parent.parent
        result = load(skill_root / "assets" / "monitor.template.json")
        result["monitor_id"] = original.get("monitor_id", "")
        result["state"] = (
            "expired"
            if old_state == "active" and schedule["state"] == "expired"
            else old_state
        )
        result["mode"] = "improve_existing"
        result["slot"] = copy.deepcopy(original.get("slot", {}))
        result["current_order"] = copy.deepcopy(
            original.get("current_order")
        )
        result["started_at"] = original.get("started_at") or now.isoformat()
        result["regular_order_cutoff_at"] = regular_cutoff.isoformat()
        result["pickup_start_at"] = pickup_start.isoformat()
        result["stop_at"] = schedule["stop_at"]
        result["window_phase"] = schedule["window_phase"]
        policy = profile["monitoring_policy"]
        result["policy_snapshot"] = {
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
            "recovery_sequence": copy.deepcopy(
                policy["recovery_sequence"]
            ),
        }
        result["schedule"] = {
            "mode": "adaptive",
            "last_checked_at": now.isoformat(),
            "next_check_at": schedule["next_check_at"],
            "last_interval_minutes": schedule["interval_minutes"],
            "consecutive_no_change": 0,
            "recent_inventory_change": False,
            "reason_codes": schedule["reason_codes"],
        }
        result["best_observation"] = copy.deepcopy(
            original.get("best_observation")
        )
        result["pending_swap"] = None
        old_automation = original.get("automation", {})
        result["automation"] = {
            "id": old_automation.get("id"),
            "scheduled_for": schedule["next_check_at"],
            "status": (
                "migration_requires_reschedule"
                if schedule["next_check_at"]
                else "not_scheduled"
            ),
        }
        result["events"] = copy.deepcopy(original.get("events", []))
        result["events"].append(
            {
                "at": now.isoformat(),
                "type": "monitor_migrated",
                "from_schema_version": 1,
                "note": (
                    "Old fixed recurrence is not reused; schedule the "
                    "next one-shot check from schedule.next_check_at."
                ),
            }
        )

    if args.dry_run:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    backup = None
    if destination == source and (version == 1 or recovered_legacy_submit):
        suffix = "v1" if version == 1 else "v2-predelegation"
        backup = source.with_name(f"{source.name}.{suffix}.bak")
        if not backup.exists():
            shutil.copy2(source, backup)
    write_atomic(destination, result)
    print(
        json.dumps(
            {
                "status": (
                    "recovered_legacy_submit_confirmation"
                    if recovered_legacy_submit
                    else ("already_current" if version == 2 else "migrated")
                ),
                "monitor_path": str(destination),
                "backup_path": str(backup) if backup else None,
                "schema_version": 2,
                "state": result.get("state"),
                "next_check_at": result.get("schedule", {}).get(
                    "next_check_at"
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
