#!/usr/bin/env python3
"""Resolve the next safe step for uninterrupted normal-order batches."""

from __future__ import annotations

import argparse
import json


STATES = ("none", "planned", "staged", "submitted", "verified", "failed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--plan-state",
        choices=("incomplete", "complete"),
        required=True,
    )
    for meal in ("lunch", "dinner"):
        parser.add_argument(f"--{meal}-rows", type=int, default=0)
        parser.add_argument(
            f"--{meal}-state",
            choices=STATES,
            default="none",
        )
    parser.add_argument(
        "--failure-scope",
        choices=("isolated_batch", "page_unstable"),
        default="isolated_batch",
    )
    args = parser.parse_args()

    batches = {
        meal: {
            "rows": getattr(args, f"{meal}_rows"),
            "state": getattr(args, f"{meal}_state"),
        }
        for meal in ("lunch", "dinner")
    }
    if args.plan_state == "incomplete":
        print(
            json.dumps(
                {
                    "state": "planning",
                    "action": "complete_full_requested_lunch_and_dinner_plan",
                    "meal": None,
                    "conversation_boundary": False,
                    "user_confirmation_required": False,
                    "failed_batches": [],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    for meal, batch in batches.items():
        if batch["rows"] < 0:
            parser.error(f"--{meal}-rows must be non-negative")
        if batch["rows"] == 0 and batch["state"] != "none":
            parser.error(f"--{meal}-state must be none when row count is zero")
        if batch["rows"] > 0 and batch["state"] == "none":
            parser.error(f"--{meal}-state must not be none when rows exist")

    failed_batches = []
    for meal in ("lunch", "dinner"):
        batch = batches[meal]
        if batch["rows"] == 0:
            continue
        if batch["state"] == "failed":
            failed_batches.append(meal)
            if args.failure_scope == "page_unstable":
                result = {
                    "state": "needs_recovery",
                    "action": "stop_and_recover_page_before_more_transactions",
                    "meal": meal,
                    "conversation_boundary": True,
                    "user_confirmation_required": False,
                    "failed_batches": failed_batches,
                }
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0
            continue
        action = {
            "planned": f"stage_{meal}_batch",
            "staged": f"submit_{meal}_batch",
            "submitted": f"verify_{meal}_batch_in_my_orders",
        }.get(batch["state"])
        if action:
            result = {
                "state": "executing",
                "action": action,
                "meal": meal,
                "conversation_boundary": False,
                "user_confirmation_required": False,
                "failed_batches": failed_batches,
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

    rows = sum(batch["rows"] for batch in batches.values())
    if rows == 0:
        state = "already_complete"
        action = "verify_existing_orders_and_emit_receipt"
    else:
        state = "partial_failure" if failed_batches else "completed"
        action = "emit_post_submit_receipt"
    result = {
        "state": state,
        "action": action,
        "meal": None,
        "conversation_boundary": True,
        "user_confirmation_required": False,
        "failed_batches": failed_batches,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
