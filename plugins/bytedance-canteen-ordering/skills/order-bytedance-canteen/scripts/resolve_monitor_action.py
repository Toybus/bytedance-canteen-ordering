#!/usr/bin/env python3
"""Resolve one released-stock observation to a business action."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=("improve_existing", "fill_missing"),
        default="improve_existing",
    )
    parser.add_argument(
        "--window-phase",
        choices=("regular_window", "release_only"),
        default="regular_window",
    )
    parser.add_argument("--current-score", type=int)
    parser.add_argument("--candidate-score", type=int, required=True)
    parser.add_argument(
        "--candidate-state",
        choices=("available", "unavailable", "unknown"),
        required=True,
    )
    parser.add_argument(
        "--current-order-state",
        choices=("verified", "changed", "missing", "unknown"),
    )
    parser.add_argument(
        "--actionability-state",
        choices=("open", "final_closed", "unknown"),
    )
    parser.add_argument(
        "--cutoff-state",
        choices=("open", "closed", "unknown"),
        help="Legacy alias; closed means final_closed.",
    )
    args = parser.parse_args()

    if args.actionability_state and args.cutoff_state:
        parser.error("use only one of --actionability-state or --cutoff-state")
    actionability = args.actionability_state
    if actionability is None and args.cutoff_state is not None:
        actionability = {
            "open": "open",
            "closed": "final_closed",
            "unknown": "unknown",
        }[args.cutoff_state]
    if actionability is None:
        parser.error("--actionability-state is required")
    if not 0 <= args.candidate_score <= 100:
        parser.error("--candidate-score must be between 0 and 100")

    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    threshold = profile["monitoring_policy"]["minimum_improvement_points"]
    current_score = args.current_score
    improvement = (
        args.candidate_score - current_score
        if current_score is not None
        else None
    )

    if actionability == "final_closed":
        state, action = "expired", "stop_monitoring"
    elif actionability == "unknown" or args.candidate_state == "unknown":
        state, action = "needs_recovery", "preserve_monitor_and_recover_page"
    elif args.mode == "fill_missing":
        if args.candidate_state == "unavailable":
            state, action = "active", "continue_monitoring"
        else:
            state, action = (
                "submitting",
                "submit_released_candidate_then_report",
            )
    else:
        if current_score is None:
            parser.error("--current-score is required for improve_existing")
        if not 0 <= current_score <= 100:
            parser.error("--current-score must be between 0 and 100")
        if args.current_order_state is None:
            parser.error(
                "--current-order-state is required for improve_existing"
            )
        if args.current_order_state in {"changed", "missing"}:
            state, action = (
                "current_order_changed",
                "rebaseline_before_monitoring",
            )
        elif args.current_order_state == "unknown":
            state, action = (
                "needs_recovery",
                "preserve_monitor_and_recover_page",
            )
        elif args.candidate_state == "unavailable":
            state, action = "active", "continue_monitoring"
        elif improvement < threshold:
            state, action = "active", "continue_monitoring"
        else:
            state, action = (
                "swap_approval_pending",
                "emit_exact_swap_manifest",
            )

    confirmation_scope = {
        "swap_approval_pending": "single_exact_swap",
    }.get(state)
    receipt_scope = "post_submit_receipt" if (
        args.mode == "fill_missing" and state == "submitting"
    ) else None
    print(
        json.dumps(
            {
                "state": state,
                "action": action,
                "mode": args.mode,
                "window_phase": args.window_phase,
                "current_score": current_score,
                "candidate_score": args.candidate_score,
                "improvement_points": improvement,
                "minimum_improvement_points": threshold,
                "confirmation_required": confirmation_scope is not None,
                "confirmation_scope": confirmation_scope,
                "receipt_scope": receipt_scope,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
