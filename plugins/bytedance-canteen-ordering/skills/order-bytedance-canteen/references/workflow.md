# Ordering Workflow

## State model

Treat one ordering request as a resumable state machine:

```text
intent_captured
  -> dependencies_ready
  -> authenticated
  -> canonical_profile_ready
  -> existing_orders_checked
  -> lifecycle_resolved
     -> already_complete -> my_orders_verified -> run_recorded
     -> waiting_for_window/page -> intent_persisted -> resume_scheduled
     -> release_only -> released_stock_monitor_created
     -> target_closed/window_anomaly/needs_recovery -> intent_persisted
     -> ready_to_plan/partial_fill
        -> menus_sampled
        -> plan_built
        -> lunch_staged -> lunch_submitted -> lunch_verified
        -> dinner_staged -> dinner_submitted -> dinner_verified
        -> all_attempted_rows_verified
        -> post_submit_receipt_emitted
        -> run_recorded
        -> provisional_orders_detected
           -> monitors_created
```

Do not skip a state because a click or tool call succeeded. Advance only when its observable condition is true.

## 1. Capture intent and establish scope

Persist the request before any setup or waiting step. Resolve:

- building;
- timezone and target week;
- requested meal coverage;
- current occupied slots;
- restrictions and explicit corrections;
- preference confidence and whether one optional cold-start question is useful;
- normal-order delegation and destructive-action confirmation scope.

Default to open workdays only. A closed Friday dinner or another unavailable slot is an omission, not an execution error.

## 2. Pass readiness

Use [readiness.md](readiness.md). Resolve the user-wide canonical profile before reading preferences. If setup is missing, preserve the request and return one precise recovery action. After the user installs a browser controller or signs in, resume from the saved request.

Verify the live building against `supported_scope.buildings`. Stop before cart or cancellation work when it is unsupported.

## 3. Read existing orders

Open My Orders before building a plan. For every target `(date, meal)`, record:

- status;
- dish;
- building;
- pickup point;
- pickup time.

Never add a second order for an occupied slot. Do not cancel to make room unless explicitly requested.

## 4. Resolve lifecycle

Calculate the expected opening only after identifying the target week and profile timezone:

```text
expected_open = target_week_monday - target_week_offset_days
                at next_week_opens_time
```

For the default rule, next-week ordering opens on the previous Tuesday at 10:00.

Use live evidence as authoritative:

- all expected slots occupied -> `already_complete`;
- regular cutoff closed, but released inventory may still appear -> `release_only`;
- live page says the target is finally closed -> `target_closed`;
- before expected open and page closed -> `waiting_for_window`;
- after expected open and within retry horizon -> `waiting_for_page`;
- page still closed beyond retry horizon -> `window_anomaly`;
- page or authentication cannot be evaluated -> `needs_recovery`;
- some occupied and some missing with menu open -> `partial_fill`;
- none occupied and menu open -> `ready_to_plan`.

For waiting states:

1. Write `pending-intent.json` with the original request and current evidence, preferably through `scripts/persist_intent.py`.
2. If native automation is available, create a one-shot heartbeat on the current task:
   - `waiting_for_window`: expected open plus grace;
   - `waiting_for_page`: returned bounded retry time.
3. On wake, re-check My Orders and the live menu before planning.
4. If automation is unavailable, give the exact resume time and one-line prompt; keep the intent file.

Never interpret a schedule prediction as proof that menus are open.

The D-2 rule is the regular advance-ordering cutoff, not an absolute stock-death rule. If a requested slot is still empty after it, inspect any currently released inventory and create a `fill_missing` release monitor when policy allows. Continue until the pickup safety boundary or a live final-closed signal.

## 5. Sample menus

For each unoccupied slot:

1. Select the date and verify selected styling.
2. Select lunch or dinner.
3. Wait for menu stabilization.
4. Verify cutoff and absence of a not-open message.
5. Read preferred pickup sites first, then fallbacks.
6. Record available dishes, sold-out state, dietary tags, and spice level.

Normalize each candidate with exact dish name, high-confidence dish family when known, building, meal, pickup point/time, availability, slot state, restriction-check state, and broad tags. Do not invent a family from one similar name.

Keep live evidence separate from preference scores. Availability is a hard condition.

## 6. Rank candidates

Apply hard filters:

- correct building and meal;
- slot open;
- no existing order;
- dish available;
- before cutoff;
- restrictions satisfied.

Then rank by:

1. explicit exact dislike/restriction/variant rules as hard filters;
2. explicit exact likes;
3. repeated completed exact dishes;
4. a tight family supported by at least two completed exact variants;
5. a single completed exact dish;
6. contextual building/weekday/meal/pickup behavior;
7. cuisine, flavor, and format only as weak tie-breakers;
8. protein only as the weakest tie-breaker;
9. weekly variety and weak negative evidence.

Prefer a clearly better dish over a small logistics difference. Prefer the better pickup time when dishes are similar. Penalize known unreliable pickup slots, but do not treat a released order as dish dislike. Never infer a broad protein preference from exact dish history.

Use `scripts/preference_engine.py rank` when Python is available. A novel candidate with only broad evidence is `provisional`; it may be shown as a low-confidence alternative but cannot displace a known-good candidate. If no known-good option is available, it may be selected as a provisional fallback and must be disclosed in the post-submit receipt.

Record a relative 0–100 suitability score and assign:

- `preferred`: strong explicit or repeated-history fit;
- `acceptable`: suitable without material compromise;
- `provisional`: a fallback caused by weak menu, stock, pickup, or timing options.

The score is for relative choice and monitoring thresholds, not nutrition or medical safety. Do not show routine score calculations unless they explain an exception.

## 7. Build carts

Freeze one complete plan for every requested open, unoccupied lunch and dinner slot before adding any selection. This prevents a user-facing pause after the lunch cart has already been staged.

Add reversible selections only after verifying the active target site.

Observed behavior may require:

- clicking the pickup tab;
- waiting more than two seconds for smooth scrolling;
- clicking a real radio/control rather than the title;
- confirming a pickup-point change dialog.

The page can accumulate dates in one meal-type cart. A non-empty lunch cart may silently block dinner selection, so the batches cannot reliably coexist. Stage, verify, submit, and verify lunch first; then immediately do the same for dinner. This is one uninterrupted normal-order transaction from the user's perspective: send no plan update, candidate question, or confirmation request between batches.

## 8. Verify cart details

For each row compare:

- date;
- meal;
- dish;
- building;
- pickup point;
- displayed time.

If pickup label and cart time conflict, treat it as a live anomaly. Continue only when the final pickup time can be determined safely from the page; otherwise omit that row and disclose it after all safe batches have been attempted.

## 9. Submit without a conversation pause

The profile delegates routine selection and ordinary submission to the agent. The user's request to order the target coverage is the authorization for policy-compliant new orders in empty slots. Do not ask the user to choose among ordinary candidates, approve rows, or confirm a pre-submit manifest.

Before the first cart action, hold the complete lunch-and-dinner plan internally. Execute meal-type batches in `transaction_policy.batch_order`. Verify each batch at the point of effect, then continue directly to the next batch without a user-facing message.

If stock changes during execution, rerank that empty slot from the already sampled, policy-compliant candidates. Never overwrite an occupied slot. Omit a slot rather than violate an explicit dislike, restriction, building scope, or safety boundary, and explain the omission in the final receipt.

Immediately before submit, re-read:

- cart count;
- every row;
- submit visual enabled state;
- modal or overlay state.

Submit one meal-type batch at a time and record the result count. An isolated batch failure does not justify abandoning a still-safe other meal type; continue it and report the partial result. Authentication loss, ambiguous active date/meal, or unstable page state stops further transactions until recovered.

Use `scripts/resolve_batch_execution.py` when a deterministic next-step check is useful. Any `executing` result has `conversation_boundary: false`; only the final receipt or a safety recovery may cross that boundary.

## 10. Verify point of effect

Open My Orders and expose every target date. Require one row per expected occupied slot with:

- expected dish;
- expected pickup point;
- expected final pickup time;
- `已下单` or the appropriate success state.

If a cart-time anomaly resolves correctly in My Orders, record a rendering exception. If My Orders differs, report the exact discrepancy and do not claim completion.

## 11. Persist the result

Write one JSON run record per target week under `run_log_dir`. Include:

- profile schema version;
- target week;
- lifecycle result;
- normal-order delegation evidence and any separate destructive-action confirmation;
- existing and newly submitted orders;
- selection score and `preferred`/`acceptable`/`provisional` quality for new orders;
- substitutions and exceptions;
- active monitor IDs for provisional orders;
- verification timestamp.

For provisional orders, continue with [monitoring.md](monitoring.md). Clear pending intent only when the original request has reached a verified terminal result or responsibility has transferred to a persisted active monitor. Never store credentials, cookies, browser state, or session data.

Use [presentation.md](presentation.md) for first-use receipts, contextual preference disclosure, waiting ownership, preference deltas, and completion messages.

## 12. Calibrate after a meaningful change

Do not interrupt the transaction to complete preference research. Finish or safely stop the requested ordering action first. When the user's final choice differs from the recommendation and taste could explain it, ask one optional question that distinguishes durable preference from stock, logistics, variety, or a one-off mood.

- Explicit durable preference: apply one idempotent delta and show the small receipt.
- Logistics reason: update only contextual logistics when the user explicitly requests it.
- One-off or unanswered: record no stable preference change.

Never turn the mere existence of a swap, cancellation, or release into a dislike.
