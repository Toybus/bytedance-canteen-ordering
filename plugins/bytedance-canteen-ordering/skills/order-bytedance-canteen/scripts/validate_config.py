#!/usr/bin/env python3
"""Validate a ByteDance canteen profile and optional ordering run."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


POLICIES = {"all_open_workdays", "only_requested", "disabled"}
CONFIRMATION_VALUES = {"required"}
MONITOR_ACTIVATIONS = {
    "disabled",
    "offer_for_provisional",
    "auto_for_provisional",
}
MONITOR_STATES = {
    "active",
    "checking",
    "submit_approval_pending",
    "swap_approval_pending",
    "submitting",
    "swapping",
    "completed",
    "expired",
    "cancelled",
    "current_order_changed",
    "needs_recovery",
}
MONITOR_MODES = {"improve_existing", "fill_missing"}
WINDOW_PHASES = {"regular_window", "release_only"}
MISSING_SLOT_MONITORING = {
    "disabled",
    "offer_for_requested_coverage",
    "auto_for_requested_coverage",
}
EFFORT_MODES = {"economy", "balanced", "aggressive"}
ORDER_QUALITIES = {"preferred", "acceptable", "provisional"}
TIME_RANGE = re.compile(r"^\d{2}:\d{2}\s*-\s*\d{2}:\d{2}$")
LOCAL_TIME = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
YEAR_MONTH = re.compile(r"^\d{4}-\d{2}$")
CONFIDENCE_VALUES = {"low", "medium", "high"}


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"missing file: {path}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from None
    if not isinstance(value, dict):
        raise ValueError(f"top-level JSON value must be an object: {path}")
    return value


def require(obj: dict, key: str, expected_type: type, where: str):
    if key not in obj:
        raise ValueError(f"{where}.{key} is required")
    value = obj[key]
    if not isinstance(value, expected_type):
        raise ValueError(
            f"{where}.{key} must be {expected_type.__name__}, got {type(value).__name__}"
        )
    return value


def require_unique_strings(values: list, where: str, allow_empty: bool = False) -> None:
    if not values and not allow_empty:
        raise ValueError(f"{where} must not be empty")
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"{where} must contain non-empty strings")
    if len(values) != len(set(values)):
        raise ValueError(f"{where} must not contain duplicates")


def require_iso_datetime(
    obj: dict,
    key: str,
    where: str,
    *,
    allow_null: bool = False,
) -> str | None:
    if key not in obj:
        raise ValueError(f"{where}.{key} is required")
    value = obj[key]
    if value is None and allow_null:
        return None
    if not isinstance(value, str) or not value.strip():
        qualifier = "null or " if allow_null else ""
        raise ValueError(
            f"{where}.{key} must be {qualifier}a non-empty ISO datetime"
        )
    try:
        datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(
            f"{where}.{key} must be an ISO datetime"
        ) from None
    return value


def require_period(value: object, where: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be an object")
    for key in ("start", "end"):
        item = value.get(key)
        if item is not None and (
            not isinstance(item, str) or not ISO_DATE.match(item)
        ):
            raise ValueError(f"{where}.{key} must be null or YYYY-MM-DD")
    context = value.get("context")
    if not isinstance(context, str) or not context.strip():
        raise ValueError(f"{where}.context must be a non-empty string")


def validate_exact_preference(item: object, where: str) -> None:
    if not isinstance(item, dict):
        raise ValueError(f"{where} must be an object")
    dish = require(item, "dish", str, where)
    if not dish.strip():
        raise ValueError(f"{where}.dish must not be empty")
    if require(item, "specificity", str, where) != "exact":
        raise ValueError(f"{where}.specificity must be exact")


def validate_completed_affinity(item: object, where: str) -> None:
    validate_exact_preference(item, where)
    count = require(item, "completed_count", int, where)
    if count <= 0:
        raise ValueError(f"{where}.completed_count must be positive")
    if require(item, "confidence", str, where) not in CONFIDENCE_VALUES:
        raise ValueError(
            f"{where}.confidence must be one of {sorted(CONFIDENCE_VALUES)}"
        )
    require_period(require(item, "source_period", dict, where), f"{where}.source_period")


def validate_profile(profile: dict) -> None:
    if profile.get("schema_version") != 5:
        raise ValueError("schema_version must be 5")

    identity = require(profile, "identity", dict, "profile")
    timezone = require(identity, "timezone", str, "profile.identity")
    building = require(identity, "default_building", str, "profile.identity")
    if not building.strip():
        raise ValueError("profile.identity.default_building must not be empty")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        raise ValueError(f"unknown timezone: {timezone}") from None

    ordering_window = require(profile, "ordering_window", dict, "profile")
    opens_weekday = require(
        ordering_window,
        "next_week_opens_weekday",
        int,
        "profile.ordering_window",
    )
    if opens_weekday < 1 or opens_weekday > 7:
        raise ValueError(
            "profile.ordering_window.next_week_opens_weekday must be 1-7"
        )
    opens_time = require(
        ordering_window,
        "next_week_opens_time",
        str,
        "profile.ordering_window",
    )
    if not LOCAL_TIME.match(opens_time):
        raise ValueError(
            "profile.ordering_window.next_week_opens_time must look like HH:MM"
        )
    offset_days = require(
        ordering_window,
        "target_week_offset_days",
        int,
        "profile.ordering_window",
    )
    if offset_days < 0:
        raise ValueError(
            "profile.ordering_window.target_week_offset_days must be non-negative"
        )

    runtime = require(profile, "runtime_policy", dict, "profile")
    if (
        require(runtime, "when_window_closed", str, "profile.runtime_policy")
        != "schedule_resume"
    ):
        raise ValueError(
            "profile.runtime_policy.when_window_closed must be schedule_resume"
        )
    automation = require(
        runtime,
        "automation_preference",
        str,
        "profile.runtime_policy",
    )
    if automation not in {"thread_heartbeat", "none"}:
        raise ValueError(
            "profile.runtime_policy.automation_preference must be "
            "thread_heartbeat or none"
        )
    for key, allow_zero in (
        ("open_check_grace_minutes", True),
        ("retry_minutes", False),
        ("max_open_delay_hours", False),
    ):
        value = require(runtime, key, int, "profile.runtime_policy")
        if value < 0 or (not allow_zero and value == 0):
            qualifier = "non-negative" if allow_zero else "positive"
            raise ValueError(f"profile.runtime_policy.{key} must be {qualifier}")
    if (
        require(runtime, "confirmation_scope", str, "profile.runtime_policy")
        != "execution_manifest"
    ):
        raise ValueError(
            "profile.runtime_policy.confirmation_scope must be execution_manifest"
        )

    interaction = require(profile, "interaction_policy", dict, "profile")
    expected_interaction = {
        "selection_mode": "autonomous",
        "review_mode": "exceptions_only",
        "normal_order_confirmation": "single_execution_manifest",
        "replacement_confirmation": "single_exact_swap",
    }
    for key, expected in expected_interaction.items():
        value = require(interaction, key, str, "profile.interaction_policy")
        if value != expected:
            raise ValueError(
                f"profile.interaction_policy.{key} must be {expected}"
            )
    if not require(
        interaction,
        "user_response_token",
        str,
        "profile.interaction_policy",
    ).strip():
        raise ValueError(
            "profile.interaction_policy.user_response_token must not be empty"
        )

    experience = require(profile, "experience_policy", dict, "profile")
    if (
        require(
            experience,
            "preference_visibility",
            str,
            "profile.experience_policy",
        )
        != "relevant_by_default"
    ):
        raise ValueError(
            "profile.experience_policy.preference_visibility must be "
            "relevant_by_default"
        )
    require(
        experience,
        "show_preference_delta",
        bool,
        "profile.experience_policy",
    )
    next_actions_limit = require(
        experience,
        "next_actions_limit",
        int,
        "profile.experience_policy",
    )
    if next_actions_limit < 1 or next_actions_limit > 3:
        raise ValueError(
            "profile.experience_policy.next_actions_limit must be 1-3"
        )
    experience_state = require(profile, "experience_state", dict, "profile")
    onboarding_version = require(
        experience_state,
        "onboarding_version_shown",
        int,
        "profile.experience_state",
    )
    if onboarding_version < 0:
        raise ValueError(
            "profile.experience_state.onboarding_version_shown "
            "must be non-negative"
        )
    onboarding_shown_at = experience_state.get("onboarding_shown_at")
    if onboarding_shown_at is not None and (
        not isinstance(onboarding_shown_at, str)
        or not onboarding_shown_at.strip()
    ):
        raise ValueError(
            "profile.experience_state.onboarding_shown_at must be null "
            "or a non-empty string"
        )

    monitoring = require(profile, "monitoring_policy", dict, "profile")
    activation = require(
        monitoring,
        "activation",
        str,
        "profile.monitoring_policy",
    )
    if activation not in MONITOR_ACTIVATIONS:
        raise ValueError(
            "profile.monitoring_policy.activation must be one of "
            f"{sorted(MONITOR_ACTIVATIONS)}"
        )
    missing_monitoring = require(
        monitoring,
        "missing_slot_release_monitoring",
        str,
        "profile.monitoring_policy",
    )
    if missing_monitoring not in MISSING_SLOT_MONITORING:
        raise ValueError(
            "profile.monitoring_policy.missing_slot_release_monitoring "
            f"must be one of {sorted(MISSING_SLOT_MONITORING)}"
        )
    max_active = require(
        monitoring,
        "max_active_monitors",
        int,
        "profile.monitoring_policy",
    )
    if max_active <= 0:
        raise ValueError(
            "profile.monitoring_policy.max_active_monitors must be positive"
        )
    for key in (
        "minimum_improvement_points",
        "auto_monitor_below_score",
    ):
        value = require(monitoring, key, int, "profile.monitoring_policy")
        if value < 0 or value > 100:
            raise ValueError(
                f"profile.monitoring_policy.{key} must be between 0 and 100"
            )
    stop_margin = require(
        monitoring,
        "stop_before_pickup_minutes",
        int,
        "profile.monitoring_policy",
    )
    if stop_margin < 0:
        raise ValueError(
            "profile.monitoring_policy.stop_before_pickup_minutes "
            "must be non-negative"
        )
    require(
        monitoring,
        "continue_after_regular_cutoff_for_releases",
        bool,
        "profile.monitoring_policy",
    )
    effort = require(
        monitoring,
        "effort_mode",
        str,
        "profile.monitoring_policy",
    )
    if effort not in EFFORT_MODES:
        raise ValueError(
            "profile.monitoring_policy.effort_mode must be one of "
            f"{sorted(EFFORT_MODES)}"
        )
    cadence = require(
        monitoring,
        "cadence",
        dict,
        "profile.monitoring_policy",
    )
    if require(cadence, "mode", str, "profile.monitoring_policy.cadence") != "adaptive":
        raise ValueError(
            "profile.monitoring_policy.cadence.mode must be adaptive"
        )
    bands = require(
        cadence,
        "bands",
        list,
        "profile.monitoring_policy.cadence",
    )
    if not bands:
        raise ValueError(
            "profile.monitoring_policy.cadence.bands must not be empty"
        )
    thresholds = []
    intervals = []
    for index, band in enumerate(bands):
        if not isinstance(band, dict):
            raise ValueError(
                f"profile.monitoring_policy.cadence.bands[{index}] "
                "must be an object"
            )
        threshold = band.get("remaining_hours_gte")
        interval = band.get("interval_minutes")
        if not isinstance(threshold, (int, float)) or threshold < 0:
            raise ValueError(
                f"profile.monitoring_policy.cadence.bands[{index}] "
                ".remaining_hours_gte must be non-negative"
            )
        if not isinstance(interval, int) or interval <= 0:
            raise ValueError(
                f"profile.monitoring_policy.cadence.bands[{index}] "
                ".interval_minutes must be positive"
            )
        thresholds.append(threshold)
        intervals.append(interval)
    if thresholds != sorted(thresholds, reverse=True):
        raise ValueError(
            "profile.monitoring_policy.cadence.bands must be ordered "
            "by descending remaining_hours_gte"
        )
    if len(thresholds) != len(set(thresholds)) or thresholds[-1] != 0:
        raise ValueError(
            "profile.monitoring_policy.cadence.bands thresholds must be "
            "unique and end at 0"
        )
    minimum_interval = require(
        cadence,
        "min_interval_minutes",
        int,
        "profile.monitoring_policy.cadence",
    )
    maximum_interval = require(
        cadence,
        "max_interval_minutes",
        int,
        "profile.monitoring_policy.cadence",
    )
    if minimum_interval <= 0 or maximum_interval < minimum_interval:
        raise ValueError(
            "profile.monitoring_policy.cadence interval bounds are invalid"
        )
    if any(
        interval < minimum_interval or interval > maximum_interval
        for interval in intervals
    ):
        raise ValueError(
            "profile.monitoring_policy.cadence band interval is out of bounds"
        )
    backoff_after = require(
        cadence,
        "no_change_backoff_after",
        int,
        "profile.monitoring_policy.cadence",
    )
    if backoff_after <= 0:
        raise ValueError(
            "profile.monitoring_policy.cadence.no_change_backoff_after "
            "must be positive"
        )
    backoff_multiplier = cadence.get("no_change_backoff_multiplier")
    if (
        not isinstance(backoff_multiplier, (int, float))
        or backoff_multiplier <= 1
    ):
        raise ValueError(
            "profile.monitoring_policy.cadence.no_change_backoff_multiplier "
            "must be greater than 1"
        )
    high_regret = require(
        cadence,
        "high_regret_score_below",
        int,
        "profile.monitoring_policy.cadence",
    )
    if high_regret < 0 or high_regret > 100:
        raise ValueError(
            "profile.monitoring_policy.cadence.high_regret_score_below "
            "must be between 0 and 100"
        )
    if (
        require(
            monitoring,
            "replacement_mode",
            str,
            "profile.monitoring_policy",
        )
        != "confirm_exact_swap"
    ):
        raise ValueError(
            "profile.monitoring_policy.replacement_mode must be "
            "confirm_exact_swap"
        )
    recovery = require(
        monitoring,
        "recovery_sequence",
        list,
        "profile.monitoring_policy",
    )
    require_unique_strings(
        recovery,
        "profile.monitoring_policy.recovery_sequence",
    )
    if any(
        item not in {"original_order", "confirmed_fallback"}
        for item in recovery
    ):
        raise ValueError(
            "profile.monitoring_policy.recovery_sequence contains "
            "an unsupported action"
        )

    state = require(profile, "state_management", dict, "profile")
    if require(state, "scope", str, "profile.state_management") != "user":
        raise ValueError("profile.state_management.scope must be user")
    require(
        state,
        "canonical_profile",
        bool,
        "profile.state_management",
    )
    require_unique_strings(
        require(
            state,
            "legacy_sources",
            list,
            "profile.state_management",
        ),
        "profile.state_management.legacy_sources",
        allow_empty=True,
    )
    fingerprints = require(
        state,
        "legacy_source_fingerprints",
        dict,
        "profile.state_management",
    )
    if any(
        not isinstance(path, str)
        or not path.strip()
        or not isinstance(value, str)
        or len(value) != 64
        for path, value in fingerprints.items()
    ):
        raise ValueError(
            "profile.state_management.legacy_source_fingerprints must map "
            "paths to SHA-256 strings"
        )
    last_merged = state.get("last_merged_at")
    if last_merged is not None and (
        not isinstance(last_merged, str) or not last_merged.strip()
    ):
        raise ValueError(
            "profile.state_management.last_merged_at must be null "
            "or a non-empty string"
        )
    require(
        state,
        "preference_conflicts",
        list,
        "profile.state_management",
    )

    coverage = require(profile, "coverage", dict, "profile")
    weekdays = require(coverage, "weekdays", list, "profile.coverage")
    if not weekdays or any(type(day) is not int or day < 1 or day > 7 for day in weekdays):
        raise ValueError("profile.coverage.weekdays must contain ISO weekday integers 1-7")
    if len(weekdays) != len(set(weekdays)):
        raise ValueError("profile.coverage.weekdays must not contain duplicates")
    for meal in ("lunch", "dinner"):
        policy = require(coverage, meal, str, "profile.coverage")
        if policy not in POLICIES:
            raise ValueError(f"profile.coverage.{meal} must be one of {sorted(POLICIES)}")

    supported = require(profile, "supported_scope", dict, "profile")
    require_unique_strings(
        require(supported, "buildings", list, "profile.supported_scope"),
        "profile.supported_scope.buildings",
    )
    if (
        require(
            supported,
            "unsupported_behavior",
            str,
            "profile.supported_scope",
        )
        != "stop_before_transaction"
    ):
        raise ValueError(
            "profile.supported_scope.unsupported_behavior must be stop_before_transaction"
        )

    logistics = require(profile, "logistics_preferences", dict, "profile")
    rankings = require(
        logistics,
        "explicit_pickup_rankings",
        dict,
        "profile.logistics_preferences",
    )
    for meal in ("lunch", "dinner"):
        require_unique_strings(
            require(
                rankings,
                meal,
                list,
                "profile.logistics_preferences.explicit_pickup_rankings",
            ),
            f"profile.logistics_preferences.explicit_pickup_rankings.{meal}",
            allow_empty=True,
        )
    explicit_contexts = require(
        logistics,
        "explicit_contexts",
        list,
        "profile.logistics_preferences",
    )
    for index, item in enumerate(explicit_contexts):
        where = f"profile.logistics_preferences.explicit_contexts[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{where} must be an object")
        for key in ("building", "meal", "pickup_point"):
            if not require(item, key, str, where).strip():
                raise ValueError(f"{where}.{key} must not be empty")
        if item["meal"] not in {"lunch", "dinner"}:
            raise ValueError(f"{where}.meal must be lunch or dinner")
        weekday = item.get("weekday")
        if weekday is not None and (
            type(weekday) is not int or weekday < 1 or weekday > 7
        ):
            raise ValueError(f"{where}.weekday must be null or 1-7")
    contextual = require(
        logistics,
        "contextual_pickup_affinity",
        list,
        "profile.logistics_preferences",
    )
    for index, item in enumerate(contextual):
        where = f"profile.logistics_preferences.contextual_pickup_affinity[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{where} must be an object")
        for key in ("building", "meal", "pickup_point"):
            if not require(item, key, str, where).strip():
                raise ValueError(f"{where}.{key} must not be empty")
        if item["meal"] not in {"lunch", "dinner"}:
            raise ValueError(f"{where}.meal must be lunch or dinner")
        weekday = require(item, "weekday", int, where)
        if weekday < 1 or weekday > 7:
            raise ValueError(f"{where}.weekday must be 1-7")
        time_band = item.get("time_band")
        if time_band is not None and (
            not isinstance(time_band, str) or not time_band.strip()
        ):
            raise ValueError(f"{where}.time_band must be null or a non-empty string")
        count = require(item, "completed_count", int, where)
        if count <= 0:
            raise ValueError(f"{where}.completed_count must be positive")
        if require(item, "confidence", str, where) not in CONFIDENCE_VALUES:
            raise ValueError(f"{where}.confidence is invalid")
        require_period(
            require(item, "source_period", dict, where),
            f"{where}.source_period",
        )

    preferences = require(profile, "preferences", dict, "profile")
    explicit = require(preferences, "explicit", dict, "profile.preferences")
    inferred = require(preferences, "inferred", dict, "profile.preferences")
    for key in ("likes", "dislikes"):
        values = require(explicit, key, list, "profile.preferences.explicit")
        seen_dishes = set()
        for index, item in enumerate(values):
            where = f"profile.preferences.explicit.{key}[{index}]"
            validate_exact_preference(item, where)
            normalized = item["dish"].strip().casefold()
            if normalized in seen_dishes:
                raise ValueError(f"profile.preferences.explicit.{key} has duplicate dishes")
            seen_dishes.add(normalized)
    allowances = require(
        explicit,
        "variant_allowances",
        list,
        "profile.preferences.explicit",
    )
    for index, item in enumerate(allowances):
        where = f"profile.preferences.explicit.variant_allowances[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{where} must be an object")
        for key in ("dish_family", "allowed"):
            if not require(item, key, str, where).strip():
                raise ValueError(f"{where}.{key} must not be empty")
    require_unique_strings(
        require(
            explicit,
            "restrictions",
            list,
            "profile.preferences.explicit",
        ),
        "profile.preferences.explicit.restrictions",
        allow_empty=True,
    )
    for key in ("cuisines", "proteins", "flavors", "formats"):
        require_unique_strings(
            require(inferred, key, list, "profile.preferences.inferred"),
            f"profile.preferences.inferred.{key}",
            allow_empty=True,
        )
    completed = require(
        inferred,
        "completed_dish_affinity",
        list,
        "profile.preferences.inferred",
    )
    for index, item in enumerate(completed):
        validate_completed_affinity(
            item,
            f"profile.preferences.inferred.completed_dish_affinity[{index}]",
        )
    families = require(
        inferred,
        "dish_family_affinity",
        list,
        "profile.preferences.inferred",
    )
    for index, item in enumerate(families):
        where = f"profile.preferences.inferred.dish_family_affinity[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{where} must be an object")
        if not require(item, "dish_family", str, where).strip():
            raise ValueError(f"{where}.dish_family must not be empty")
        if require(item, "specificity", str, where) != "tight_family":
            raise ValueError(f"{where}.specificity must be tight_family")
        count = require(item, "completed_count", int, where)
        if count <= 0:
            raise ValueError(f"{where}.completed_count must be positive")
        if require(item, "confidence", str, where) not in CONFIDENCE_VALUES:
            raise ValueError(f"{where}.confidence is invalid")
        variants = require(item, "variants", list, where)
        variant_names = set()
        for variant_index, variant in enumerate(variants):
            variant_where = f"{where}.variants[{variant_index}]"
            if not isinstance(variant, dict):
                raise ValueError(f"{variant_where} must be an object")
            dish = require(variant, "dish", str, variant_where)
            variant_count = require(
                variant, "completed_count", int, variant_where
            )
            if not dish.strip() or variant_count <= 0:
                raise ValueError(f"{variant_where} must contain dish and positive count")
            normalized = dish.strip().casefold()
            if normalized in variant_names:
                raise ValueError(f"{where}.variants must not duplicate dishes")
            variant_names.add(normalized)
        usable = require(item, "usable_for_ranking", bool, where)
        if usable and len(variants) < 2:
            raise ValueError(f"{where} needs at least two variants for ranking")
        require_period(
            require(item, "source_period", dict, where),
            f"{where}.source_period",
        )
    require(preferences, "deprioritized", list, "profile.preferences")

    learning = require(profile, "preference_learning", dict, "profile")
    cold_start = require(
        learning, "cold_start", dict, "profile.preference_learning"
    )
    if require(cold_start, "mode", str, "profile.preference_learning.cold_start") != "one_compact_optional":
        raise ValueError(
            "profile.preference_learning.cold_start.mode must be one_compact_optional"
        )
    require(cold_start, "allow_skip", bool, "profile.preference_learning.cold_start")
    require(
        cold_start,
        "continue_when_history_incomplete",
        bool,
        "profile.preference_learning.cold_start",
    )
    calibration = require(
        learning, "calibration", dict, "profile.preference_learning"
    )
    if require(calibration, "trigger", str, "profile.preference_learning.calibration") != "preference_relevant_change":
        raise ValueError(
            "profile.preference_learning.calibration.trigger must be preference_relevant_change"
        )
    if require(calibration, "question_limit_per_event", int, "profile.preference_learning.calibration") != 1:
        raise ValueError(
            "profile.preference_learning.calibration.question_limit_per_event must be 1"
        )
    if require(calibration, "unanswered_behavior", str, "profile.preference_learning.calibration") != "no_update":
        raise ValueError(
            "profile.preference_learning.calibration.unanswered_behavior must be no_update"
        )
    require(calibration, "post_first_order", bool, "profile.preference_learning.calibration")
    require_unique_strings(
        require(learning, "forgotten_dishes", list, "profile.preference_learning"),
        "profile.preference_learning.forgotten_dishes",
        allow_empty=True,
    )
    require_unique_strings(
        require(learning, "applied_delta_ids", list, "profile.preference_learning"),
        "profile.preference_learning.applied_delta_ids",
        allow_empty=True,
    )

    decision = require(profile, "decision_policy", dict, "profile")
    for key in (
        "avoid_exact_repeat_within_week",
        "prefer_dish_over_small_pickup_difference",
        "prefer_known_good_dishes_over_novel_candidates",
        "do_not_generalize_specific_dish_history_to_broad_protein",
        "require_exception_confirmation",
    ):
        require(decision, key, bool, "profile.decision_policy")
    if not decision["prefer_known_good_dishes_over_novel_candidates"]:
        raise ValueError(
            "profile.decision_policy.prefer_known_good_dishes_over_novel_candidates must be true"
        )
    if not decision["do_not_generalize_specific_dish_history_to_broad_protein"]:
        raise ValueError(
            "profile.decision_policy.do_not_generalize_specific_dish_history_to_broad_protein must be true"
        )
    require_unique_strings(
        require(decision, "known_bad_pickup_slots", list, "profile.decision_policy"),
        "profile.decision_policy.known_bad_pickup_slots",
        allow_empty=True,
    )

    confirmation = require(profile, "confirmation_policy", dict, "profile")
    for action in ("submit", "cancel", "release"):
        value = require(confirmation, action, str, "profile.confirmation_policy")
        if value not in CONFIRMATION_VALUES:
            raise ValueError(
                f"profile.confirmation_policy.{action} must be one of "
                f"{sorted(CONFIRMATION_VALUES)}"
            )

    paths = require(profile, "paths", dict, "profile")
    for key in ("site_guide_path", "run_log_dir", "monitor_dir"):
        value = require(paths, key, str, "profile.paths")
        if not value.strip():
            raise ValueError(f"profile.paths.{key} must not be empty")

    history = require(profile, "history_evidence", dict, "profile")
    last_analyzed = history.get("last_analyzed_at")
    if last_analyzed is not None and (
        not isinstance(last_analyzed, str) or not last_analyzed.strip()
    ):
        raise ValueError(
            "profile.history_evidence.last_analyzed_at must be null or an ISO datetime"
        )
    if last_analyzed is not None:
        try:
            datetime.fromisoformat(last_analyzed)
        except ValueError:
            raise ValueError(
                "profile.history_evidence.last_analyzed_at must be null or an ISO datetime"
            ) from None
    require_period(
        require(history, "analysis_period", dict, "profile.history_evidence"),
        "profile.history_evidence.analysis_period",
    )
    for key in ("orders_sampled", "workdays_sampled"):
        value = require(history, key, int, "profile.history_evidence")
        if value < 0:
            raise ValueError(f"profile.history_evidence.{key} must be non-negative")
    meal_counts = require(history, "meal_counts", dict, "profile.history_evidence")
    for meal in ("lunch", "dinner"):
        value = require(meal_counts, meal, int, "profile.history_evidence.meal_counts")
        if value < 0:
            raise ValueError(
                f"profile.history_evidence.meal_counts.{meal} must be non-negative"
            )
    completed_meal_counts = require(
        history,
        "completed_meal_counts",
        dict,
        "profile.history_evidence",
    )
    for meal in ("lunch", "dinner"):
        value = require(
            completed_meal_counts,
            meal,
            int,
            "profile.history_evidence.completed_meal_counts",
        )
        if value < 0:
            raise ValueError(
                f"profile.history_evidence.completed_meal_counts.{meal} must be non-negative"
            )
    status_counts = require(
        history, "status_counts", dict, "profile.history_evidence"
    )
    for status in ("completed", "released", "discarded", "other"):
        value = require(
            status_counts,
            status,
            int,
            "profile.history_evidence.status_counts",
        )
        if value < 0:
            raise ValueError(
                f"profile.history_evidence.status_counts.{status} must be non-negative"
            )
    monthly = require(
        history, "monthly_order_counts", dict, "profile.history_evidence"
    )
    if any(
        not isinstance(key, str)
        or not YEAR_MONTH.match(key)
        or type(value) is not int
        or value < 0
        for key, value in monthly.items()
    ):
        raise ValueError(
            "profile.history_evidence.monthly_order_counts must map YYYY-MM to non-negative integers"
        )
    collection = require(
        history, "collection", dict, "profile.history_evidence"
    )
    for key in ("complete", "all_statuses", "reached_end", "timezone_verified"):
        require(collection, key, bool, "profile.history_evidence.collection")
    if not require(
        collection, "method", str, "profile.history_evidence.collection"
    ).strip():
        raise ValueError(
            "profile.history_evidence.collection.method must not be empty"
        )
    require(history, "pickup_outcomes", list, "profile.history_evidence")


def validate_run(run: dict) -> None:
    if run.get("schema_version") != 1:
        raise ValueError("run.schema_version must be 1")
    week = require(run, "target_week", dict, "run")
    require(week, "start", str, "run.target_week")
    require(week, "end", str, "run.target_week")
    orders = require(run, "orders", list, "run")
    seen = set()
    for index, order in enumerate(orders):
        if not isinstance(order, dict):
            raise ValueError(f"run.orders[{index}] must be an object")
        where = f"run.orders[{index}]"
        date = require(order, "date", str, where)
        meal = require(order, "meal", str, where)
        if meal not in {"lunch", "dinner"}:
            raise ValueError(f"{where}.meal must be lunch or dinner")
        key = (date, meal)
        if key in seen:
            raise ValueError(f"duplicate order slot: {date} {meal}")
        seen.add(key)
        for key_name in ("dish", "building", "pickup_point", "status"):
            if not require(order, key_name, str, where).strip():
                raise ValueError(f"{where}.{key_name} must not be empty")
        pickup_time = require(order, "pickup_time", str, where)
        if not TIME_RANGE.match(pickup_time):
            raise ValueError(f"{where}.pickup_time must look like HH:MM - HH:MM")
    require(run, "exceptions", list, "run")
    require(run, "substitutions", list, "run")


def validate_monitor(monitor: dict) -> None:
    if monitor.get("schema_version") != 2:
        raise ValueError("monitor.schema_version must be 2")
    monitor_id = require(monitor, "monitor_id", str, "monitor")
    if not monitor_id.strip():
        raise ValueError("monitor.monitor_id must not be empty")
    state = require(monitor, "state", str, "monitor")
    if state not in MONITOR_STATES:
        raise ValueError(
            f"monitor.state must be one of {sorted(MONITOR_STATES)}"
        )
    mode = require(monitor, "mode", str, "monitor")
    if mode not in MONITOR_MODES:
        raise ValueError(
            f"monitor.mode must be one of {sorted(MONITOR_MODES)}"
        )
    slot = require(monitor, "slot", dict, "monitor")
    for key in ("date", "building"):
        if not require(slot, key, str, "monitor.slot").strip():
            raise ValueError(f"monitor.slot.{key} must not be empty")
    meal = require(slot, "meal", str, "monitor.slot")
    if meal not in {"lunch", "dinner"}:
        raise ValueError("monitor.slot.meal must be lunch or dinner")

    current = monitor.get("current_order")
    if mode == "fill_missing":
        if current is not None:
            raise ValueError(
                "monitor.current_order must be null in fill_missing mode"
            )
    else:
        if not isinstance(current, dict):
            raise ValueError(
                "monitor.current_order must be an object in "
                "improve_existing mode"
            )
        for key in ("dish", "pickup_point", "pickup_time", "status"):
            if not require(
                current,
                key,
                str,
                "monitor.current_order",
            ).strip():
                raise ValueError(
                    f"monitor.current_order.{key} must not be empty"
                )
        score = require(current, "score", int, "monitor.current_order")
        if score < 0 or score > 100:
            raise ValueError(
                "monitor.current_order.score must be between 0 and 100"
            )
        quality = require(
            current,
            "quality",
            str,
            "monitor.current_order",
        )
        if quality not in ORDER_QUALITIES:
            raise ValueError(
                "monitor.current_order.quality must be preferred, "
                "acceptable, or provisional"
            )

    require_iso_datetime(monitor, "started_at", "monitor")
    regular_cutoff = require_iso_datetime(
        monitor,
        "regular_order_cutoff_at",
        "monitor",
    )
    pickup_start = require_iso_datetime(
        monitor,
        "pickup_start_at",
        "monitor",
    )
    stop_at = require_iso_datetime(monitor, "stop_at", "monitor")
    if datetime.fromisoformat(regular_cutoff) >= datetime.fromisoformat(
        pickup_start
    ):
        raise ValueError(
            "monitor.regular_order_cutoff_at must be before pickup_start_at"
        )
    if datetime.fromisoformat(stop_at) > datetime.fromisoformat(pickup_start):
        raise ValueError(
            "monitor.stop_at must not be after pickup_start_at"
        )
    phase = require(monitor, "window_phase", str, "monitor")
    if phase not in WINDOW_PHASES:
        raise ValueError(
            f"monitor.window_phase must be one of {sorted(WINDOW_PHASES)}"
        )

    policy = require(monitor, "policy_snapshot", dict, "monitor")
    for key in (
        "minimum_improvement_points",
        "stop_before_pickup_minutes",
    ):
        value = require(policy, key, int, "monitor.policy_snapshot")
        if value < 0:
            raise ValueError(
                f"monitor.policy_snapshot.{key} must be non-negative"
            )
    require(
        policy,
        "continue_after_regular_cutoff_for_releases",
        bool,
        "monitor.policy_snapshot",
    )
    effort = require(
        policy,
        "effort_mode",
        str,
        "monitor.policy_snapshot",
    )
    if effort not in EFFORT_MODES:
        raise ValueError(
            "monitor.policy_snapshot.effort_mode must be one of "
            f"{sorted(EFFORT_MODES)}"
        )
    cadence = require(policy, "cadence", dict, "monitor.policy_snapshot")
    if (
        require(cadence, "mode", str, "monitor.policy_snapshot.cadence")
        != "adaptive"
    ):
        raise ValueError(
            "monitor.policy_snapshot.cadence.mode must be adaptive"
        )
    if (
        require(
            policy,
            "replacement_mode",
            str,
            "monitor.policy_snapshot",
        )
        != "confirm_exact_swap"
    ):
        raise ValueError(
            "monitor.policy_snapshot.replacement_mode must be "
            "confirm_exact_swap"
        )
    require_unique_strings(
        require(
            policy,
            "recovery_sequence",
            list,
            "monitor.policy_snapshot",
        ),
        "monitor.policy_snapshot.recovery_sequence",
    )

    schedule = require(monitor, "schedule", dict, "monitor")
    if require(schedule, "mode", str, "monitor.schedule") != "adaptive":
        raise ValueError("monitor.schedule.mode must be adaptive")
    require_iso_datetime(
        schedule,
        "last_checked_at",
        "monitor.schedule",
        allow_null=True,
    )
    require_iso_datetime(
        schedule,
        "next_check_at",
        "monitor.schedule",
        allow_null=True,
    )
    last_interval = schedule.get("last_interval_minutes")
    if last_interval is not None and (
        not isinstance(last_interval, int) or last_interval <= 0
    ):
        raise ValueError(
            "monitor.schedule.last_interval_minutes must be null "
            "or positive"
        )
    no_change = require(
        schedule,
        "consecutive_no_change",
        int,
        "monitor.schedule",
    )
    if no_change < 0:
        raise ValueError(
            "monitor.schedule.consecutive_no_change must be non-negative"
        )
    require(
        schedule,
        "recent_inventory_change",
        bool,
        "monitor.schedule",
    )
    require_unique_strings(
        require(schedule, "reason_codes", list, "monitor.schedule"),
        "monitor.schedule.reason_codes",
        allow_empty=True,
    )

    pending_swap = monitor.get("pending_swap")
    if pending_swap is not None and not isinstance(pending_swap, dict):
        raise ValueError("monitor.pending_swap must be null or an object")
    automation = require(monitor, "automation", dict, "monitor")
    automation_id = automation.get("id")
    if automation_id is not None and (
        not isinstance(automation_id, str) or not automation_id.strip()
    ):
        raise ValueError(
            "monitor.automation.id must be null or a non-empty string"
        )
    require_iso_datetime(
        automation,
        "scheduled_for",
        "monitor.automation",
        allow_null=True,
    )
    if not require(
        automation,
        "status",
        str,
        "monitor.automation",
    ).strip():
        raise ValueError("monitor.automation.status must not be empty")
    require(monitor, "events", list, "monitor")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--monitor", type=Path)
    args = parser.parse_args()

    try:
        profile = load_json(args.profile)
        validate_profile(profile)
        if args.run:
            validate_run(load_json(args.run))
        if args.monitor:
            validate_monitor(load_json(args.monitor))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    message = f"OK profile: {args.profile}"
    if args.run:
        message += f"; run: {args.run}"
    if args.monitor:
        message += f"; monitor: {args.monitor}"
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
