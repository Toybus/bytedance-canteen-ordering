# Profile Schema

## Purpose

Keep stable personal intent outside the Skill. The Skill is reusable logic; the profile is user-specific state.

## Resolution

Resolve in this order:

1. explicit path;
2. `BYTE_CANTEEN_PROFILE`;
3. `~/.codex/order-bytedance-canteen/profile.json`;
4. `./canteen_profile.json` only as a legacy source when canonical state does not exist;
5. initialize the canonical profile from `assets/profile.template.json`.

The profile is user state, not project state. Never create another active profile because the current working directory changed. When canonical and legacy files coexist, merge into canonical and record the source.

## Portable data layout

Default root:

```text
~/.codex/order-bytedance-canteen/
  profile.json
  site-guide.md
  runs/
  monitors/
  pending-intent.json   # only while work is resumable
```

## Top-level fields

### `schema_version`

Integer schema version. Current value: `6`.

### `identity`

- `timezone`: IANA timezone used to resolve “next week” and opening time.
- `default_building`: Aplus building name discovered from live page state.

### `ordering_window`

- `next_week_opens_weekday`: ISO weekday of expected opening; default `2` for Tuesday.
- `next_week_opens_time`: local `HH:MM`; default `10:00`.
- `target_week_offset_days`: days from target Monday back to expected opening; default `6`.

This rule predicts when to retry. The live page remains authoritative.

### `runtime_policy`

- `when_window_closed`: `schedule_resume`.
- `automation_preference`: `thread_heartbeat` or `none`.
- `open_check_grace_minutes`: delay after expected open before the first check.
- `retry_minutes`: interval while the page is unexpectedly closed.
- `max_open_delay_hours`: bounded retry horizon before `window_anomaly`.
- `confirmation_scope`: `post_submit_receipt` for ordinary new orders.

### `interaction_policy`

- `selection_mode`: `autonomous`; routine meal choice belongs to the agent.
- `review_mode`: `exceptions_only`.
- `normal_order_confirmation`: `post_submit_receipt`.
- `replacement_confirmation`: `single_exact_swap`.
- `user_response_token`: compact preferred acknowledgement such as `✅`.

This policy delegates policy-compliant new orders in empty slots. It does not authorize cancellation, release, or replacement of an existing order.

### `experience_policy` and `experience_state`

- `preference_visibility`: `relevant_by_default`; show only preferences that affected the current result.
- `show_preference_delta`: show explicit corrections as a small before/after receipt.
- `next_actions_limit`: maximum number of contextual next actions in a completion message.
- `onboarding_version_shown` and `onboarding_shown_at`: prevent repetitive first-use explanations while allowing a later material onboarding update.

### `transaction_policy`

- `normal_order_mode`: `submit_then_report`;
- `planning_scope`: `all_requested_unoccupied_slots`;
- `batch_order`: lunch, then dinner;
- `cross_batch_user_pause`: `forbidden`;
- `verify_each_batch`: true;
- `final_receipt_after_all_batches`: true;
- `occupied_slot_behavior`: `preserve`.

Lunch and dinner remain separate Aplus batches, but they are one uninterrupted user request. Plan both before cart work and do not send a user-facing message between them.

### `monitoring_policy`

- `activation`: `disabled`, `offer_for_provisional`, or `auto_for_provisional`.
- `missing_slot_release_monitoring`: whether to monitor requested but unfilled slots.
- `minimum_improvement_points`: required 0–100 score improvement before notification.
- `auto_monitor_below_score`: maximum score treated as a provisional auto-monitor candidate.
- `stop_before_pickup_minutes`: final safety margin before pickup begins.
- `continue_after_regular_cutoff_for_releases`: keep looking for inventory released after D-2.
- `max_active_monitors`: positive per-user limit.
- `effort_mode`: `economy`, `balanced`, or `aggressive`.
- `cadence`: adaptive time bands, interval bounds, unchanged-result backoff, and high-regret threshold.
- `replacement_mode`: `confirm_exact_swap`.
- `recovery_sequence`: ordered values from `original_order` and `confirmed_fallback`.

The cadence controls one-shot wakeups, not a fixed recurrence. The regular cutoff changes the monitor to `release_only`; it is not the stop boundary.

### `state_management`

- `scope`: `user`.
- `canonical_profile`: boolean; true for the active global profile.
- `legacy_sources`: paths previously merged into canonical.
- `legacy_source_fingerprints`: SHA-256 by source path, used to detect a later legacy edit.
- `last_merged_at`: ISO timestamp or null.
- `preference_conflicts`: unresolved explicit like/dislike or restriction conflicts.

### `coverage`

- `weekdays`: ISO weekday integers.
- `lunch` and `dinner`: `all_open_workdays`, `only_requested`, or `disabled`.

### `supported_scope`

- `buildings`: buildings verified for transactional use. This release contains only `Lincoln Square North`.
- `unsupported_behavior`: `stop_before_transaction`.

An unsupported building is a normal, safe result. Do not best-effort a transaction using unverified page structure.

### `logistics_preferences`

Keep logistics separate from food preference:

- `explicit_pickup_rankings`: user-stated lunch and dinner pickup order;
- `explicit_contexts`: user-stated building, weekday, meal, time-band, and pickup combinations;
- `contextual_pickup_affinity`: completed-history counts for an exact building, weekday, meal, and pickup point.

Logistics can break a food tie. It cannot override an explicit dislike, restriction, or materially better known dish.

### `preferences`

Separate:

- `explicit`: exact likes, exact dislikes, variant allowances, and restrictions;
- `inferred.completed_dish_affinity`: exact dishes with positive `completed_count`, `confidence`, `specificity: exact`, and structured `source_period`;
- `inferred.dish_family_affinity`: a tight family, total count, structured variants, and source period. Set `usable_for_ranking: true` only when at least two distinct completed variants support the family;
- `inferred.cuisines`, `flavors`, and `formats`: weak tie-break evidence;
- `inferred.proteins`: the weakest tie-break evidence;
- `deprioritized`: weak negative evidence.

Do not promote inferred evidence to explicit without user confirmation.

Do not create cuisine, flavor, format, or protein preferences automatically from repeated exact-dish history. In particular, exact fish dishes do not establish a general fish preference.

### `preference_learning`

- `cold_start`: one compact, optional question; skipping never blocks ordering;
- `calibration`: at most one question after a preference-relevant change, with no update when unanswered;
- `forgotten_dishes`: exact dishes that history re-analysis must not reintroduce;
- `applied_delta_ids`: idempotency keys for explicit updates.

A replacement, cancellation, release, or stock substitution is only a calibration signal. Persist a change only after an explicit answer.

### `decision_policy`

- `avoid_exact_repeat_within_week`;
- `prefer_dish_over_small_pickup_difference`;
- `prefer_known_good_dishes_over_novel_candidates` must be true;
- `do_not_generalize_specific_dish_history_to_broad_protein` must be true;
- `known_bad_pickup_slots`;
- `require_exception_confirmation`: false; omit an unsafe slot and report it afterward instead of pausing the rest of the ordinary order.

### `confirmation_policy`

Use `delegated` for ordinary submit and `required` for cancel and release. Replacement also follows `interaction_policy.replacement_confirmation: single_exact_swap`.

### `paths`

- `site_guide_path`;
- `run_log_dir`.
- `monitor_dir`.

Use absolute paths in the resolved personal profile.

### `history_evidence`

Record:

- analysis date and structured period;
- sampled orders and workdays;
- counts by status, month, and meal;
- completed meal counts;
- whether all statuses were read, infinite scroll reached the end, and timezone was verified;
- pickup outcomes.

Prefer 60–90 days of history and read monthly chunks when the page is unstable. A partial history is valid and must not block ordering, but it produces limited confidence and must not replace a previously complete baseline unless the user explicitly resets it. Evidence explains ranking but never overrides explicit corrections.

## Pending intent

Create `pending-intent.json` only while work waits for setup, authentication, menu opening, or page recovery. It must contain:

- schema version and saved time;
- original request summary;
- target week and coverage;
- profile path;
- current lifecycle state and reason;
- next check time when known;
- occupied-slot snapshot;
- delegated normal-order authorization and post-submit receipt status.

Pending normal-order intent remains delegated when resumed. It never authorizes cancel, release, or replacement. Do not store credentials or browser session data.

## Preference update rules

- “I dislike spicy noodle soup but the mild version is okay” becomes a dislike plus a variant allowance.
- A stock-driven one-off choice stays in the run record.
- Repeated completed orders may raise inferred affinity.
- Released orders update pickup reliability before dish affinity.

Validate after every structural edit.

## Migration

For an existing schema-v3, v4, or v5 profile, migrate one version at a time:

```bash
python3 scripts/migrate_profile_v4.py --profile <canonical-profile>
python3 scripts/migrate_profile_v5.py --profile <canonical-profile>
python3 scripts/migrate_profile_v6.py --profile <canonical-profile>
python3 scripts/validate_config.py --profile <canonical-profile>
```

Run only the migrator matching the current `schema_version`. In-place migration creates a versioned backup once and preserves explicit preferences. Unstructured legacy families remain visible but are marked unusable for ranking until history analysis reconstructs at least two exact variants.

## Deterministic preference operations

Use `scripts/preference_engine.py` for history analysis, candidate ranking, explicit deltas, and user-facing summaries. Normalized history input contains `records[]` and `collection`; normalized candidate input contains `context` and `candidates[]`.

Only an `apply-delta` event with a unique `event_id` and `confirmed_by_user: true` may mutate explicit preferences. Support exact like/dislike, variant allowance, restriction add/remove, forget dish, contextual logistics, no-preference-change calibration, and reset.

Schema-v1 monitors need live slot times and migrate separately:

```bash
python3 scripts/migrate_monitor_v2.py \
  --monitor <monitor.json> \
  --profile <canonical-profile> \
  --regular-order-cutoff-at <ISO-datetime> \
  --pickup-start-at <ISO-datetime>
```
