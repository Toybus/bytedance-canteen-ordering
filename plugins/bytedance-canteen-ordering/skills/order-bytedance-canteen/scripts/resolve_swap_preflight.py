#!/usr/bin/env python3
"""Verify that one confirmed swap still targets the exact live order."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


FINGERPRINT_FIELDS = (
    "date",
    "meal",
    "dish",
    "building",
    "pickup_point",
    "pickup_time",
)


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def fingerprint(value: dict) -> tuple[str, ...]:
    result = []
    for field in FINGERPRINT_FIELDS:
        item = value.get(field)
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field} must be a non-empty string")
        result.append(item.strip())
    return tuple(result)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--live-order", type=Path, required=True)
    parser.add_argument("--live-candidate", type=Path, required=True)
    parser.add_argument(
        "--candidate-state",
        choices=("available", "unavailable", "unknown"),
        required=True,
    )
    parser.add_argument(
        "--page-state",
        choices=("stable", "unstable", "blocked", "unknown"),
        required=True,
    )
    parser.add_argument(
        "--cancel-control-scope",
        choices=("matching_order_card", "other", "unknown"),
        required=True,
    )
    parser.add_argument("--matching-order-count", type=int, required=True)
    args = parser.parse_args()

    manifest = load(args.manifest.expanduser().resolve())
    live_order = load(args.live_order.expanduser().resolve())
    live_candidate = load(args.live_candidate.expanduser().resolve())
    reasons = []

    if manifest.get("confirmed") is not True:
        reasons.append("manifest_not_confirmed")
    old_order = manifest.get("old_order")
    new_order = manifest.get("new_order")
    if not isinstance(old_order, dict) or not isinstance(new_order, dict):
        raise ValueError("manifest must contain old_order and new_order objects")
    if fingerprint(old_order) != fingerprint(live_order):
        reasons.append("old_order_mismatch")
    if fingerprint(new_order) != fingerprint(live_candidate):
        reasons.append("candidate_mismatch")
    if args.matching_order_count != 1:
        reasons.append("matching_order_count_not_one")
    if args.candidate_state != "available":
        reasons.append("candidate_not_available")
    if args.page_state != "stable":
        reasons.append("page_not_stable")
    if args.cancel_control_scope != "matching_order_card":
        reasons.append("cancel_control_not_scoped")

    allowed = not reasons
    print(
        json.dumps(
            {
                "decision": (
                    "allow_single_cancel"
                    if allowed
                    else "abort_keep_original"
                ),
                "confirmation_valid": allowed,
                "reasons": reasons,
                "authorized_scope": (
                    {
                        "old_order": old_order,
                        "new_order": new_order,
                        "recovery_sequence": manifest.get(
                            "recovery_sequence",
                            [],
                        ),
                    }
                    if allowed
                    else None
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
