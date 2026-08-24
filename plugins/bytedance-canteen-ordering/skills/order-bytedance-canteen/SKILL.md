---
name: order-bytedance-canteen
description: Manage delegated end-to-end ByteDance Aplus canteen ordering across friendly first-use setup, user-wide preference state, dependency and login recovery, menu-window resumption, autonomous meal selection, one exact execution confirmation, verification, adaptive released-stock monitoring, guarded meal swaps, and preference learning. Use when Codex needs to initialize a user, order weekly lunches or dinners, inspect history, resume an unopened week, fill a missing slot after the regular cutoff, improve a fallback meal, replace or cancel a meal, or verify results.
---

# Order ByteDance Canteen

Operate Aplus as a persistent personal ordering agent for Lincoln Square North. Own meal selection from the saved policy instead of returning routine decisions to the user. Every invocation must end in a normal business result: fulfilled, already complete, partially filled, ready for one execution-manifest confirmation, actively monitoring an existing or missing meal, waiting with a resumable intent, finally closed, unsupported building, or setup required with one precise recovery action.

## Start with readiness

Read [references/readiness.md](references/readiness.md) on first use, after environment changes, or when the page cannot be reached.

Hard requirements:

- this Skill or its containing plugin is installed;
- Browser or Chrome control is available;
- the selected browser can reach Aplus and has a valid corporate login;
- a writable data directory exists.

Do not require Lark CLI, a Lark connector, an external MCP, cookies, or local-storage access. Python 3 is only a helper dependency; if unavailable, perform the small JSON operations directly.

Capture the user's original ordering intent before asking them to install or sign in. Resume that intent after readiness succeeds instead of asking them to restate it.

## Resolve persistent state portably

Resolve the profile in this order:

1. An explicit profile path from the user.
2. `BYTE_CANTEEN_PROFILE`.
3. `~/.codex/order-bytedance-canteen/profile.json`.
4. `./canteen_profile.json` only as a legacy migration source when the canonical profile is missing.
5. Bootstrap the canonical profile after discovering the user's building and timezone.

Never create a second active profile merely because the working directory changed. If canonical and legacy profiles both exist, keep canonical paths, conservatively merge explicit preferences and the more complete history, record migration sources, migrate in order, and validate schema v5.

When Python is available:

```bash
python3 scripts/resolve_profile.py
# Run v2 -> v3 or merge a legacy profile only when needed.
python3 scripts/migrate_profile_v3.py \
  --profile ~/.codex/order-bytedance-canteen/profile.json \
  --merge-from ./canteen_profile.json
# Run v3 -> v4 only when the resolved profile is schema v3.
python3 scripts/migrate_profile_v4.py \
  --profile ~/.codex/order-bytedance-canteen/profile.json
# Run v4 -> v5 when the resolved profile is schema v4.
python3 scripts/migrate_profile_v5.py \
  --profile ~/.codex/order-bytedance-canteen/profile.json
python3 scripts/bootstrap_profile.py \
  --building "<live Aplus building>" \
  --timezone "<IANA timezone>"
python3 scripts/validate_config.py --profile <profile-path>
```

Inspect `schema_version` first and run only the needed migrations. Do not run an older migrator against an already newer profile.

Read the profile before recommending or touching menu controls. Read its `site_guide_path` when present.

## Load only the needed references

- For initialization, preference changes, or profile repair, read [references/profile-schema.md](references/profile-schema.md).
- For lifecycle decisions, planning, cart work, submission, cancellation, or verification, read [references/workflow.md](references/workflow.md).
- For provisional-order monitoring or a released-stock replacement, read [references/monitoring.md](references/monitoring.md).
- For first-use, preference changes, waiting states, confirmation manifests, or completion messages, read [references/presentation.md](references/presentation.md).
- Before operating the page, read [references/site-knowledge.md](references/site-knowledge.md) and use Browser or Chrome control. Do not replace the authenticated page with web search.

## Resolve the business state before menu work

After reading My Orders, classify the target using live page evidence plus the configured ordering-window rule. The live page is authoritative; the rule only predicts when to retry.

When Python is available:

```bash
python3 scripts/resolve_lifecycle.py \
  --profile <profile-path> \
  --target-week YYYY-MM-DD \
  --menu-state open \
  --occupied-slots 0 \
  --expected-slots 9
```

Handle the result as follows:

- `already_complete`: verify existing rows and finish without touching carts.
- `partial_fill`: plan only missing slots.
- `ready_to_plan`: inspect menus and build the plan.
- `waiting_for_window`: save pending intent and create a one-shot thread heartbeat for open time plus grace when automation is available.
- `waiting_for_page`: retry at the returned time, bounded by `max_open_delay_hours`.
- `window_anomaly`: preserve intent and report that the live page stayed closed past the bounded retry window.
- `release_only`: inspect released inventory now and monitor requested missing slots until the pickup safety boundary.
- `target_closed`: the live page says ordering is finally closed; preserve existing orders and offer the next eligible week.
- `needs_recovery`: preserve intent and give one exact setup or page-recovery action.

Do not treat “next week is not open yet” as task failure. Long-lived delegation authorizes autonomous planning and monitoring, not an unknown future transaction. Resume, build the concrete execution manifest, and request one action-time confirmation.

Persist waiting or recovery work with `scripts/persist_intent.py`; clear it only after the original request reaches a verified terminal result.

## Protect these invariants

1. Treat the canonical profile's explicit preferences as authoritative; keep inferred history separate.
2. Check My Orders before selecting meals to prevent duplicates.
3. Verify date, meal, building, pickup point, stock, cutoff, and live menu state.
4. Make routine selections autonomously; ask the user only for exceptions and one exact execution-manifest confirmation before `提交`.
5. Require one exact-swap confirmation before canceling or releasing an existing order for replacement.
6. Batch lunch and dinner separately when the page will not mix meal types.
7. Disclose stock loss, gray controls, time mismatches, closed slots, and substitutions.
8. Verify success in My Orders; a success toast is insufficient.
9. Never infer that a released order means the user disliked the dish.
10. Treat a user change as a calibration signal, not a preference update. Ask at most one optional question and update only after an explicit answer.
11. Never overwrite or duplicate occupied `(date, meal)` slots without explicit instruction.
12. Persist enough state that a setup interruption or future opening can resume the original request.
13. Maintain one user-wide canonical profile across projects and tasks.
14. Never cancel an existing meal merely because a better candidate was observed; after exact authorization, revalidate the old order, candidate, page stability, and the single cancel control immediately before cancellation.
15. Treat the D-2 cutoff as the end of regular ordering, not proof that released stock can no longer appear.
16. Never generalize repeated exact-dish history into a broad protein preference. Broad cuisine, flavor, format, and protein evidence can only break ties.
17. Prefer an explicit or completed known-good dish over a novel candidate. Show a broad-match new dish only as a low-confidence alternative unless no known-good candidate is available; mark it provisional and include it in the execution manifest.
18. Keep food preference separate from contextual logistics preference. A weekday/meal pickup pattern cannot override an exact dislike or restriction.
19. Stop before any transaction outside `supported_scope.buildings`; this release supports Lincoln Square North only.

## Choose the workflow

### Initialize or re-initialize

1. Run the readiness gate and discover building/timezone from live context.
2. Bootstrap portable local state.
3. Explore the ordering page without submitting.
4. Record structure, cart behavior, disabled states, scrolling, ordering-window behavior, and failures in the site guide.
5. Read 60–90 days of history when available. Query monthly chunks, include every status, scroll My Orders until it states there are no more rows, and verify dates in the profile timezone. Prefer a pre-agent baseline; label mixed or partial history honestly.
6. Normalize the rows and run `preference_engine.py analyze-history`. Count only completed orders as food evidence. Use released and discarded orders only for logistics outcomes. Create a dish family only when at least two independently completed exact variants share a high-confidence family label.
7. If history is empty or incomplete, continue the ordering request. Ask one compact, optional cold-start question covering explicit avoidances/restrictions, exact favorites, and usual pickup context; do not block when the user skips it.
8. Separate explicit preferences, exact completed-dish evidence, supported tight families, contextual pickup behavior, and uncertainty; merge legacy evidence into the canonical profile.
9. Write and validate the profile. Never replace a complete history baseline with a partial read unless the user explicitly requests that reset.
10. Show the first-use receipt from [references/presentation.md](references/presentation.md): confidence, relevant preferences, confirmation boundary, correction controls, and direct-use examples.
11. Continue the original ordering intent when one exists; initialization alone never submits.

### Plan or order a week

1. Resolve the target week in the profile timezone.
2. Read My Orders and mark occupied slots.
3. Resolve lifecycle state before menu sampling.
4. If waiting, persist intent and arrange a resume; if complete, verify and finish.
5. Inspect every requested open, unoccupied slot and collect live evidence.
6. Normalize candidates and run `preference_engine.py rank` using the profile and [references/workflow.md](references/workflow.md); label each selected meal `preferred`, `acceptable`, or `provisional`.
7. Prefer variety; avoid exact repeats when equally suitable alternatives exist.
8. Add one candidate per open unoccupied slot to the correct meal-type cart.
9. Verify every cart row.
10. Present one compact execution manifest. Include every batch and exception, but do not ask the user to choose among routine candidates.
11. Submit each confirmed meal-type batch.
12. Verify My Orders and save a run record.
13. For any `provisional` order or requested missing slot, follow the profile monitoring policy and [references/monitoring.md](references/monitoring.md).
14. Clear pending intent only after the requested terminal state is verified or transferred to an active monitor.

### Replace a meal

Treat the requested transaction as a delta and preserve the rest of the plan. Do not infer that the old dish was disliked. Re-read alternatives including other floors/times, replace only the target row, and re-verify the batch. After the ordering result is safe, ask at most one optional calibration question when the change could represent a durable preference. Apply a preference delta only when the user explicitly answers; otherwise leave the profile unchanged.

### Monitor released inventory

1. Use `improve_existing` when a provisional order exists; use `fill_missing` when requested coverage has no order.
2. Persist one schema-v2 monitor per `(date, meal)`.
3. Schedule one adaptive heartbeat at a time until pickup safety boundary or live final closure; the regular cutoff changes the phase to `release_only` but does not stop monitoring.
4. Ignore candidates that fail hard filters. For an existing order, also require the configured minimum improvement.
5. For a missing slot, send one exact submission manifest. For an existing order, send one exact swap manifest with old/new meal, logistics, improvement, unavoidable non-atomic gap, and recovery path.
6. After approval, run the live preflight. If any fingerprint or button scope changed, keep the original order and abort.
7. If the preflight passes, execute the disclosed transaction without a second confirmation, then verify My Orders.

### Cancel or release

Inspect and explain the exact target first. Require separate action-time confirmation, then verify the resulting state in My Orders.

## Learn without overfitting

Use this evidence order:

1. Explicit exact dislikes, restrictions, and variant rules.
2. Explicit exact likes.
3. Repeated completed exact dishes.
4. Tight dish families supported by at least two completed variants.
5. Single completed exact dishes.
6. Broad cuisine, flavor, and format evidence only as weak tie-breakers.
7. Broad protein evidence only as the weakest tie-breaker.
8. Released and discarded orders only as logistics evidence.

Record a preference delta only when it should change future ranking. A stock-driven substitution belongs in the run record, not stable preferences. Never derive a broad protein preference from an exact dish, even after many completions.

Use the deterministic helper when Python is available:

```bash
python3 scripts/preference_engine.py analyze-history \
  --history <normalized-history.json> --profile <profile-path>
python3 scripts/preference_engine.py rank \
  --profile <profile-path> --candidates <normalized-candidates.json>
python3 scripts/preference_engine.py apply-delta \
  --profile <profile-path> --delta <confirmed-delta.json>
python3 scripts/preference_engine.py summarize --profile <profile-path>
```

Support explicit requests to view, correct, forget one dish, or reset preferences. Use `apply-delta` for mutations so repeated events remain idempotent. A confirmed delta must carry a unique `event_id` and `confirmed_by_user: true`.

## Generate opt-in diagnostics

When a user reports a setup or page failure, offer one local diagnostic report. Pass only dependency states, execution stage, and a stable error code to `scripts/generate_diagnostic.py`. Never include orders, dish preferences, credentials, cookies, browser storage, or local paths in the report. Do not upload it automatically.

## Finish with an auditable result

Lead with the verified business result. Report occupied or missing slots, substitutions, unavailable slots, unresolved exceptions, final times, relevant preferences, and who owns the next action. Show state paths only when the user asks or recovery requires them. Never claim completion beyond the point verified in My Orders.
