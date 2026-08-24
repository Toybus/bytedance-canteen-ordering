# Released-Stock Monitoring

## Purpose

Monitoring handles two distinct business needs:

- `improve_existing`: keep an existing fallback order while looking for a meaningfully better released meal;
- `fill_missing`: look for released inventory when a requested meal slot has no order.

The normal D-2 cutoff closes ordinary advance ordering. It does not prove that the meal can never be ordered again: inventory released by another user may become available later. After the regular cutoff, use `release_only` until the live page reports final closure or the pickup safety boundary is reached.

## Activation

For `improve_existing`, read `monitoring_policy.activation`:

- `disabled`: do not create a monitor;
- `offer_for_provisional`: offer monitoring for a `provisional` order;
- `auto_for_provisional`: create it automatically.

For `fill_missing`, read `missing_slot_release_monitoring`:

- `disabled`;
- `offer_for_requested_coverage`;
- `auto_for_requested_coverage`.

Create at most one active monitor per `(date, meal)` and respect `max_active_monitors`. Creating a monitor never authorizes a future transaction.

## Stop boundary

Calculate:

```text
stop_at = min(
  pickup_start_at - stop_before_pickup_minutes,
  live_final_stop_at when the page exposes one
)
```

Do not stop merely because the regular ordering cutoff passed. Stop at `stop_at`, when the page explicitly reports final closure, when the user cancels monitoring, or after a verified success.

## Adaptive one-shot cadence

Schedule one future heartbeat at a time. After every wake, recompute the next check with `scripts/resolve_monitor_schedule.py`; do not create a permanent fixed 15-minute recurrence.

Default balanced bands:

| Time to stop boundary | Base interval |
| --- | ---: |
| 72 hours or more | 8 hours |
| 24–72 hours | 4 hours |
| 6–24 hours | 1 hour |
| 2–6 hours | 30 minutes |
| under 2 hours | 15 minutes |

Check one step faster after recent inventory changes or when the held fallback has high regret. After three unchanged checks and more than 24 hours remaining, back off by the configured multiplier, bounded by `min_interval_minutes` and `max_interval_minutes`.

An unchanged check is a normal result. Persist it, schedule the next one-shot check, and do not notify the user.

## Persisted state and migration

Store schema-v2 monitors under:

```text
<canonical-profile-dir>/monitors/<date>-<meal>.json
```

Create with `scripts/create_monitor.py`. A `fill_missing` monitor has `current_order: null`; an `improve_existing` monitor stores the exact current-order fingerprint.

Migrate schema-v1 monitors with `scripts/migrate_monitor_v2.py`. Obtain the live regular cutoff and pickup start for the slot before migration. Do not reuse the old recurring automation; schedule the v2 `schedule.next_check_at` as a new one-shot wakeup.

Never store credentials, cookies, or browser state.

## Each wake

1. Re-read My Orders.
2. For `improve_existing`, require the stored order to still match exactly; otherwise enter `current_order_changed`.
3. Read the live menu across allowed floors and pickup times.
4. Distinguish `regular_window`, `release_only`, and live `final_closed`.
5. Apply the normal hard filters and preference ranking.
6. Resolve the observation with `scripts/resolve_monitor_action.py`.
7. If no actionable candidate exists, persist the observation and compute one next check.

For `improve_existing`, notify only when the candidate clears `minimum_improvement_points`. For `fill_missing`, any policy-compliant available candidate may produce an exact submission manifest.

## Missing-slot submission

When `fill_missing` finds a candidate:

1. Show one exact execution manifest containing date, meal, dish, building, pickup point, time, and anomalies.
2. Keep monitoring while confirmation is pending.
3. After confirmation, revalidate that exact candidate.
4. Submit it once and verify it in My Orders.
5. If it disappeared, submit nothing, return to `active`, and continue until the stop boundary.

## Existing-order swap

Keep the original order while confirmation is pending. The exact manifest must show:

- full old-order fingerprint;
- full candidate fingerprint;
- reason and improvement;
- the unavoidable non-atomic gap;
- the authorized recovery sequence.

One confirmation authorizes only that disclosed old order, candidate, and recovery sequence.

Immediately after confirmation, refresh both My Orders and the candidate menu, then run the equivalent of:

```bash
python3 scripts/resolve_swap_preflight.py \
  --manifest <confirmed-manifest.json> \
  --live-order <live-old-order.json> \
  --live-candidate <live-candidate.json> \
  --candidate-state available \
  --page-state stable \
  --cancel-control-scope matching_order_card \
  --matching-order-count 1
```

The preflight must prove:

- the confirmed candidate is still available;
- exactly one live old order matches every fingerprint field;
- the cancel control belongs to that matching order card;
- the page is stable and actionable.

If any fact changed, abort and keep the original order. Do not ask for a second confirmation when all facts still match.

After an allowed preflight:

1. Click the single scoped cancel/release control.
2. Immediately select and submit the confirmed candidate.
3. Verify the new order in My Orders.
4. If submission fails after cancellation, use only the disclosed recovery sequence: original order first, then a listed confirmed fallback.
5. If no authorized recovery succeeds, enter `needs_recovery` and report the empty slot immediately.

The system cannot guarantee atomic replacement. Its guarantee is narrower: no cancellation before an exact user confirmation and an immediate live preflight; one scoped cancellation at most; no silent candidate substitution.

## Terminal states

- `completed`: submitted or replaced order verified;
- `expired`: pickup safety boundary or live final closure reached;
- `cancelled`: user stopped monitoring;
- `current_order_changed`: another actor changed the held order;
- `needs_recovery`: authentication, page state, or post-cancel recovery cannot reach a verified result.

Use [presentation.md](presentation.md) to report ownership, relevant preferences, and the next action.
