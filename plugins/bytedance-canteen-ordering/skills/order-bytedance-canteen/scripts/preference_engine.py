#!/usr/bin/env python3
"""Deterministic preference analysis, ranking, updates, and summaries."""

from __future__ import annotations

import argparse
import copy
import json
import re
import tempfile
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path


CONFIDENCE = {1: "low", 2: "medium"}
COMPLETED = {"completed", "complete", "已完成", "已取餐"}
RELEASED = {"released", "release", "已释放"}
DISCARDED = {"discarded", "cancelled", "canceled", "已取消", "已作废"}
MEALS = {"lunch", "dinner"}


def load_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
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


def normalized_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    value = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", value).strip().casefold()


def nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def canonical_status(value: object) -> str:
    status = normalized_text(value)
    if status in COMPLETED:
        return "completed"
    if status in RELEASED:
        return "released"
    if status in DISCARDED:
        return "discarded"
    return "other"


def confidence_for_count(count: int) -> str:
    return CONFIDENCE.get(count, "high")


def period(start: str | None, end: str | None, context: str) -> dict:
    return {"start": start, "end": end, "context": context}


def record_key(record: dict) -> tuple:
    order_id = record.get("order_id")
    if isinstance(order_id, str) and order_id.strip():
        return ("order_id", order_id.strip())
    return (
        record.get("date"),
        normalized_text(record.get("meal")),
        normalized_text(record.get("dish")),
        canonical_status(record.get("status")),
        normalized_text(record.get("building")),
        normalized_text(record.get("pickup_point")),
    )


def analyze_history(payload: dict) -> dict:
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("history.records must be a list")

    unique_records = []
    seen = set()
    warnings = []
    for index, raw in enumerate(records):
        if not isinstance(raw, dict):
            warnings.append(f"records[{index}] ignored: not an object")
            continue
        key = record_key(raw)
        if key in seen:
            continue
        seen.add(key)
        unique_records.append(copy.deepcopy(raw))

    dates = []
    status_counts = Counter()
    meal_counts = Counter()
    completed_meal_counts = Counter()
    monthly_counts = Counter()
    exact: dict[str, dict] = {}
    families: dict[str, dict] = {}
    logistics: dict[tuple, dict] = {}
    pickup_outcomes: dict[tuple, Counter] = defaultdict(Counter)

    for record in unique_records:
        raw_date = record.get("date")
        parsed_date = None
        if isinstance(raw_date, str):
            try:
                parsed_date = date.fromisoformat(raw_date)
                dates.append(raw_date)
                monthly_counts[raw_date[:7]] += 1
            except ValueError:
                warnings.append(f"ignored invalid date: {raw_date}")

        status = canonical_status(record.get("status"))
        status_counts[status] += 1
        meal = normalized_text(record.get("meal"))
        if meal in MEALS:
            meal_counts[meal] += 1

        pickup = record.get("pickup_point")
        if meal in MEALS and isinstance(pickup, str) and pickup.strip():
            pickup_outcomes[(meal, pickup.strip())][status] += 1

        if status != "completed":
            continue
        if meal in MEALS:
            completed_meal_counts[meal] += 1
        dish = record.get("dish")
        if not isinstance(dish, str) or not dish.strip():
            warnings.append("completed record ignored for taste: empty dish")
            continue
        dish = dish.strip()
        dish_key = normalized_text(dish)
        entry = exact.setdefault(dish_key, {"dish": dish, "completed_count": 0})
        entry["completed_count"] += 1

        family = record.get("dish_family")
        if isinstance(family, str) and family.strip():
            family_key = normalized_text(family)
            family_entry = families.setdefault(
                family_key,
                {
                    "dish_family": family.strip(),
                    "completed_count": 0,
                    "variants": {},
                },
            )
            family_entry["completed_count"] += 1
            family_entry["variants"][dish_key] = {
                "dish": dish,
                "completed_count": family_entry["variants"].get(
                    dish_key, {"completed_count": 0}
                )["completed_count"]
                + 1,
            }

        building = record.get("building")
        pickup_time = record.get("pickup_time")
        time_band = (
            pickup_time.strip()
            if isinstance(pickup_time, str) and pickup_time.strip()
            else None
        )
        if (
            parsed_date
            and meal in MEALS
            and isinstance(building, str)
            and building.strip()
            and isinstance(pickup, str)
            and pickup.strip()
        ):
            logistics_key = (
                normalized_text(building),
                parsed_date.isoweekday(),
                meal,
                normalized_text(pickup),
                normalized_text(time_band),
            )
            logistic = logistics.setdefault(
                logistics_key,
                {
                    "building": building.strip(),
                    "weekday": parsed_date.isoweekday(),
                    "meal": meal,
                    "pickup_point": pickup.strip(),
                    "time_band": time_band,
                    "completed_count": 0,
                },
            )
            logistic["completed_count"] += 1

    start = min(dates) if dates else None
    end = max(dates) if dates else None
    source = period(start, end, "completed_history")

    exact_affinity = []
    for entry in exact.values():
        item = copy.deepcopy(entry)
        item.update(
            {
                "confidence": confidence_for_count(item["completed_count"]),
                "specificity": "exact",
                "source_period": source,
            }
        )
        exact_affinity.append(item)
    exact_affinity.sort(key=lambda item: (-item["completed_count"], item["dish"]))

    family_affinity = []
    for entry in families.values():
        variants = sorted(
            entry["variants"].values(),
            key=lambda item: (-item["completed_count"], item["dish"]),
        )
        if len(variants) < 2:
            continue
        family_affinity.append(
            {
                "dish_family": entry["dish_family"],
                "completed_count": entry["completed_count"],
                "variants": variants,
                "confidence": confidence_for_count(entry["completed_count"]),
                "specificity": "tight_family",
                "source_period": source,
                "usable_for_ranking": True,
            }
        )
    family_affinity.sort(
        key=lambda item: (-item["completed_count"], item["dish_family"])
    )

    contextual = []
    for entry in logistics.values():
        item = copy.deepcopy(entry)
        item["confidence"] = confidence_for_count(item["completed_count"])
        item["source_period"] = period(start, end, "completed_logistics")
        contextual.append(item)
    contextual.sort(
        key=lambda item: (
            item["meal"],
            item["weekday"],
            -item["completed_count"],
            item["pickup_point"],
        )
    )

    pickup_summary = []
    for (meal, pickup_point), counts in sorted(pickup_outcomes.items()):
        pickup_summary.append(
            {
                "meal": meal,
                "pickup_point": pickup_point,
                "completed": counts["completed"],
                "released": counts["released"],
                "discarded": counts["discarded"],
                "other": counts["other"],
            }
        )

    collection = payload.get("collection", {})
    if not isinstance(collection, dict):
        collection = {}
    complete = all(
        collection.get(key) is True
        for key in ("all_statuses", "reached_end", "timezone_verified")
    )
    history_evidence = {
        "last_analyzed_at": datetime.now(timezone.utc).isoformat(),
        "analysis_period": period(
            start,
            end,
            nonempty_string(
                collection.get("context", "unknown"), "collection.context"
            ),
        ),
        "orders_sampled": len(unique_records),
        "workdays_sampled": len(
            {raw for raw in dates if date.fromisoformat(raw).isoweekday() <= 5}
        ),
        "status_counts": {
            "completed": status_counts["completed"],
            "released": status_counts["released"],
            "discarded": status_counts["discarded"],
            "other": status_counts["other"],
        },
        "meal_counts": {
            "lunch": meal_counts["lunch"],
            "dinner": meal_counts["dinner"],
        },
        "completed_meal_counts": {
            "lunch": completed_meal_counts["lunch"],
            "dinner": completed_meal_counts["dinner"],
        },
        "monthly_order_counts": dict(sorted(monthly_counts.items())),
        "collection": {
            "complete": complete,
            "all_statuses": collection.get("all_statuses") is True,
            "reached_end": collection.get("reached_end") is True,
            "timezone_verified": collection.get("timezone_verified") is True,
            "method": collection.get("method", "normalized_history_json"),
        },
        "pickup_outcomes": pickup_summary,
    }
    if not complete:
        warnings.append(
            "history is partial; continue ordering with conservative ranking and optional preference question"
        )

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "analysis": {
            "completed_dish_affinity": exact_affinity,
            "dish_family_affinity": family_affinity,
            "contextual_pickup_affinity": contextual,
            "history_evidence": history_evidence,
        },
        "warnings": warnings,
    }


def apply_analysis(profile: dict, result: dict, force_partial: bool) -> dict:
    if profile.get("schema_version") != 5:
        raise ValueError("profile schema_version must be 5")
    incoming = result["analysis"]["history_evidence"]
    current = profile.get("history_evidence", {})
    current_complete = current.get("collection", {}).get("complete") is True
    incoming_complete = incoming.get("collection", {}).get("complete") is True
    if current_complete and not incoming_complete and not force_partial:
        raise ValueError(
            "refusing to replace complete history evidence with partial evidence; use --force-partial to override"
        )
    updated = copy.deepcopy(profile)
    forgotten = {
        normalized_text(value)
        for value in updated["preference_learning"].get("forgotten_dishes", [])
    }
    updated["preferences"]["inferred"]["completed_dish_affinity"] = [
        copy.deepcopy(item)
        for item in result["analysis"]["completed_dish_affinity"]
        if normalized_text(item.get("dish")) not in forgotten
    ]
    filtered_families = []
    for raw in result["analysis"]["dish_family_affinity"]:
        item = copy.deepcopy(raw)
        item["variants"] = [
            variant
            for variant in item.get("variants", [])
            if normalized_text(variant.get("dish")) not in forgotten
        ]
        if len(item["variants"]) < 2:
            continue
        item["completed_count"] = sum(
            variant["completed_count"] for variant in item["variants"]
        )
        filtered_families.append(item)
    updated["preferences"]["inferred"]["dish_family_affinity"] = filtered_families
    updated["logistics_preferences"]["contextual_pickup_affinity"] = copy.deepcopy(
        result["analysis"]["contextual_pickup_affinity"]
    )
    updated["history_evidence"] = copy.deepcopy(incoming)
    return updated


def explicit_dishes(items: object) -> dict[str, dict]:
    result = {}
    if not isinstance(items, list):
        return result
    for raw in items:
        if isinstance(raw, str):
            dish = raw
            item = {"dish": raw, "specificity": "exact"}
        elif isinstance(raw, dict):
            dish = raw.get("dish")
            item = raw
        else:
            continue
        key = normalized_text(dish)
        if key:
            result[key] = item
    return result


def string_set(values: object) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {normalized_text(value) for value in values if normalized_text(value)}


def rank_candidates(profile: dict, payload: dict) -> dict:
    if profile.get("schema_version") != 5:
        raise ValueError("profile schema_version must be 5")
    candidates = payload.get("candidates")
    context = payload.get("context", {})
    if not isinstance(candidates, list) or not isinstance(context, dict):
        raise ValueError("ranking input requires candidates[] and context{}")

    expected_building = context.get(
        "building", profile.get("identity", {}).get("default_building")
    )
    expected_meal = normalized_text(context.get("meal"))
    expected_weekday = context.get("weekday")

    explicit = profile["preferences"]["explicit"]
    likes = explicit_dishes(explicit.get("likes"))
    dislikes = explicit_dishes(explicit.get("dislikes"))
    restrictions = explicit.get("restrictions", [])
    inferred = profile["preferences"]["inferred"]
    exact = {
        normalized_text(item.get("dish")): item
        for item in inferred.get("completed_dish_affinity", [])
        if isinstance(item, dict) and normalized_text(item.get("dish"))
    }
    families = {
        normalized_text(item.get("dish_family")): item
        for item in inferred.get("dish_family_affinity", [])
        if isinstance(item, dict)
        and item.get("usable_for_ranking") is True
        and len(item.get("variants", [])) >= 2
        and normalized_text(item.get("dish_family"))
    }
    broad = {
        key: string_set(inferred.get(key, []))
        for key in ("cuisines", "proteins", "flavors", "formats")
    }
    contextual = profile.get("logistics_preferences", {}).get(
        "contextual_pickup_affinity", []
    )

    ranked = []
    excluded = []
    for index, raw in enumerate(candidates):
        if not isinstance(raw, dict):
            excluded.append({"index": index, "reasons": ["invalid_candidate"]})
            continue
        candidate = copy.deepcopy(raw)
        dish = normalized_text(candidate.get("dish"))
        reasons = []
        if not dish:
            reasons.append("missing_dish")
        if candidate.get("available") is not True:
            reasons.append("not_available")
        if candidate.get("slot_open") is not True:
            reasons.append("slot_not_open")
        if candidate.get("existing_order") is True:
            reasons.append("slot_already_occupied")
        if normalized_text(candidate.get("building")) != normalized_text(
            expected_building
        ):
            reasons.append("wrong_building")
        if expected_meal and normalized_text(candidate.get("meal")) != expected_meal:
            reasons.append("wrong_meal")
        if restrictions and candidate.get("restriction_check") != "pass":
            reasons.append("restriction_not_verified")
        if dish in dislikes:
            reasons.append("explicit_exact_dislike")
        if reasons:
            candidate["excluded_reasons"] = reasons
            excluded.append(candidate)
            continue

        score = 0
        evidence = []
        evidence_level = "none"
        if dish in likes:
            score += 100
            evidence.append("explicit_exact_like")
            evidence_level = "explicit_exact"

        exact_item = exact.get(dish)
        if exact_item:
            count = exact_item.get("completed_count", 1)
            if type(count) is not int or count < 1:
                count = 1
            if count >= 2:
                score += 60 + min(count, 10) * 2
                evidence.append(f"repeated_exact_completed:{count}")
                if evidence_level == "none":
                    evidence_level = "repeated_exact"
            else:
                score += 35
                evidence.append("single_exact_completed")
                if evidence_level == "none":
                    evidence_level = "single_exact"

        family_key = normalized_text(candidate.get("dish_family"))
        family_item = families.get(family_key)
        if family_item and not exact_item:
            count = family_item.get("completed_count", 0)
            score += 25 + min(count if type(count) is int else 0, 10)
            evidence.append("tight_family_supported_by_multiple_variants")
            if evidence_level == "none":
                evidence_level = "tight_family"

        tags = candidate.get("tags", {})
        if not isinstance(tags, dict):
            tags = {}
        broad_points = {"cuisines": 3, "flavors": 3, "formats": 3, "proteins": 1}
        for key, points in broad_points.items():
            candidate_values = tags.get(key, [])
            if isinstance(candidate_values, str):
                candidate_values = [candidate_values]
            matches = string_set(candidate_values) & broad[key]
            if matches:
                score += points
                evidence.append(f"weak_{key}_tie_break")
        if evidence_level == "none" and evidence:
            evidence_level = "broad_only"

        pickup_point = normalized_text(candidate.get("pickup_point"))
        candidate_time = normalized_text(candidate.get("pickup_time"))
        for item in contextual:
            if not isinstance(item, dict):
                continue
            if normalized_text(item.get("building")) != normalized_text(
                expected_building
            ):
                continue
            if expected_meal and normalized_text(item.get("meal")) != expected_meal:
                continue
            if expected_weekday is not None and item.get("weekday") != expected_weekday:
                continue
            if normalized_text(item.get("pickup_point")) != pickup_point:
                continue
            learned_time = normalized_text(item.get("time_band"))
            if learned_time and learned_time != candidate_time:
                continue
            count = item.get("completed_count", 0)
            if type(count) is int and count > 0:
                score += min(12, count * 2)
                evidence.append("contextual_pickup_fit")

        within_week = candidate.get("within_week_count", 0)
        if type(within_week) is int and within_week > 0:
            score -= min(10, within_week * 5)
            evidence.append("weekly_repeat_penalty")

        novel = exact_item is None and family_item is None and dish not in likes
        if dish in likes or (exact_item and exact_item.get("completed_count", 0) >= 2):
            quality = "preferred"
        elif exact_item or family_item:
            quality = "acceptable"
        else:
            quality = "provisional"
        candidate.update(
            {
                "score": max(0, min(100, score)),
                "quality": quality,
                "novel": novel,
                "evidence_level": evidence_level,
                "reasons": evidence or ["neutral_baseline"],
                "requires_confirmation_as_novel": novel,
            }
        )
        ranked.append(candidate)

    ranked.sort(
        key=lambda item: (
            -item["score"],
            item["novel"],
            normalized_text(item.get("dish")),
        )
    )
    return {"ranked": ranked, "excluded": excluded}


def remove_matching_dish(items: list, dish: str) -> list:
    return [
        item
        for item in items
        if normalized_text(item if isinstance(item, str) else item.get("dish"))
        != normalized_text(dish)
    ]


def apply_delta(profile: dict, delta: dict) -> tuple[dict, dict]:
    if profile.get("schema_version") != 5:
        raise ValueError("profile schema_version must be 5")
    event_id = nonempty_string(delta.get("event_id"), "delta.event_id")
    if delta.get("confirmed_by_user") is not True:
        raise ValueError("delta.confirmed_by_user must be true")
    learning = profile["preference_learning"]
    if event_id in learning.get("applied_delta_ids", []):
        return copy.deepcopy(profile), {
            "status": "already_applied",
            "event_id": event_id,
            "changed": False,
        }

    updated = copy.deepcopy(profile)
    learning = updated["preference_learning"]
    explicit = updated["preferences"]["explicit"]
    inferred = updated["preferences"]["inferred"]
    logistics = updated["logistics_preferences"]
    kind = nonempty_string(delta.get("kind"), "delta.kind")
    recorded_at = delta.get("recorded_at") or datetime.now(timezone.utc).isoformat()
    reason = delta.get("reason") or "explicit user feedback"

    if kind in {"like", "dislike"}:
        dish = nonempty_string(delta.get("dish"), "delta.dish")
        learning["forgotten_dishes"] = [
            value
            for value in learning.get("forgotten_dishes", [])
            if normalized_text(value) != normalized_text(dish)
        ]
        target = "likes" if kind == "like" else "dislikes"
        opposite = "dislikes" if kind == "like" else "likes"
        explicit[opposite] = remove_matching_dish(explicit[opposite], dish)
        explicit[target] = remove_matching_dish(explicit[target], dish)
        explicit[target].append(
            {
                "dish": dish,
                "specificity": "exact",
                "reason": reason,
                "recorded_at": recorded_at,
            }
        )
        receipt = f"recorded explicit exact {kind}: {dish}"
    elif kind == "variant_allowance":
        family = nonempty_string(delta.get("dish_family"), "delta.dish_family")
        allowed = nonempty_string(delta.get("allowed"), "delta.allowed")
        entry = {"dish_family": family, "allowed": allowed, "recorded_at": recorded_at}
        explicit["variant_allowances"] = [
            item
            for item in explicit["variant_allowances"]
            if not (
                isinstance(item, dict)
                and normalized_text(item.get("dish_family")) == normalized_text(family)
                and normalized_text(item.get("allowed")) == normalized_text(allowed)
            )
        ]
        explicit["variant_allowances"].append(entry)
        receipt = f"recorded allowed variant for {family}: {allowed}"
    elif kind in {"restriction_add", "restriction_remove"}:
        restriction = nonempty_string(delta.get("restriction"), "delta.restriction")
        explicit["restrictions"] = [
            value
            for value in explicit["restrictions"]
            if normalized_text(value) != normalized_text(restriction)
        ]
        if kind == "restriction_add":
            explicit["restrictions"].append(restriction)
        receipt = f"{kind}: {restriction}"
    elif kind == "forget_dish":
        dish = nonempty_string(delta.get("dish"), "delta.dish")
        explicit["likes"] = remove_matching_dish(explicit["likes"], dish)
        explicit["dislikes"] = remove_matching_dish(explicit["dislikes"], dish)
        inferred["completed_dish_affinity"] = remove_matching_dish(
            inferred["completed_dish_affinity"], dish
        )
        retained_families = []
        for raw in inferred.get("dish_family_affinity", []):
            if not isinstance(raw, dict):
                continue
            family = copy.deepcopy(raw)
            family["variants"] = [
                variant
                for variant in family.get("variants", [])
                if normalized_text(variant.get("dish")) != normalized_text(dish)
            ]
            if len(family["variants"]) < 2:
                continue
            family["completed_count"] = sum(
                variant["completed_count"] for variant in family["variants"]
            )
            retained_families.append(family)
        inferred["dish_family_affinity"] = retained_families
        learning["forgotten_dishes"] = [
            value
            for value in learning.get("forgotten_dishes", [])
            if normalized_text(value) != normalized_text(dish)
        ]
        learning["forgotten_dishes"].append(dish)
        receipt = f"forgot dish: {dish}"
    elif kind == "logistics_preference":
        meal = nonempty_string(delta.get("meal"), "delta.meal").casefold()
        if meal not in MEALS:
            raise ValueError("delta.meal must be lunch or dinner")
        pickup = nonempty_string(delta.get("pickup_point"), "delta.pickup_point")
        entry = {
            "building": delta.get("building")
            or updated["identity"]["default_building"],
            "meal": meal,
            "weekday": delta.get("weekday"),
            "time_band": delta.get("time_band"),
            "pickup_point": pickup,
            "recorded_at": recorded_at,
        }
        logistics["explicit_contexts"] = [
            item
            for item in logistics["explicit_contexts"]
            if not (
                isinstance(item, dict)
                and normalized_text(item.get("building"))
                == normalized_text(entry["building"])
                and item.get("meal") == meal
                and item.get("weekday") == entry["weekday"]
                and normalized_text(item.get("pickup_point"))
                == normalized_text(pickup)
            )
        ]
        logistics["explicit_contexts"].append(entry)
        receipt = f"recorded contextual pickup preference: {meal} {pickup}"
    elif kind == "no_preference_change":
        receipt = "recorded calibration answer without changing preferences"
    elif kind == "reset_preferences":
        explicit.update(
            {"likes": [], "dislikes": [], "variant_allowances": [], "restrictions": []}
        )
        inferred.update(
            {
                "cuisines": [],
                "proteins": [],
                "flavors": [],
                "formats": [],
                "completed_dish_affinity": [],
                "dish_family_affinity": [],
            }
        )
        updated["preferences"]["deprioritized"] = []
        logistics["explicit_pickup_rankings"] = {"lunch": [], "dinner": []}
        logistics["explicit_contexts"] = []
        logistics["contextual_pickup_affinity"] = []
        learning["forgotten_dishes"] = []
        learning["applied_delta_ids"] = []
        receipt = "reset food and logistics preferences"
    else:
        raise ValueError(f"unsupported delta.kind: {kind}")

    learning["applied_delta_ids"].append(event_id)
    return updated, {
        "status": "applied",
        "event_id": event_id,
        "changed": kind != "no_preference_change",
        "receipt": receipt,
    }


def summarize(profile: dict) -> dict:
    if profile.get("schema_version") != 5:
        raise ValueError("profile schema_version must be 5")
    explicit = profile["preferences"]["explicit"]
    inferred = profile["preferences"]["inferred"]
    logistics = profile["logistics_preferences"]
    history = profile["history_evidence"]

    def dish_names(items: list) -> list[str]:
        result = []
        for item in items:
            dish = item if isinstance(item, str) else item.get("dish")
            if isinstance(dish, str) and dish.strip():
                result.append(dish.strip())
        return result

    known = [
        {
            "dish": item["dish"],
            "completed_count": item["completed_count"],
            "confidence": item["confidence"],
        }
        for item in inferred.get("completed_dish_affinity", [])[:10]
        if isinstance(item, dict)
    ]
    families = [
        {
            "dish_family": item["dish_family"],
            "completed_count": item["completed_count"],
            "variant_count": len(item.get("variants", [])),
        }
        for item in inferred.get("dish_family_affinity", [])
        if isinstance(item, dict) and item.get("usable_for_ranking") is True
    ]
    complete = history.get("collection", {}).get("complete") is True
    return {
        "preference_confidence": "established" if complete else "limited",
        "history_period": history.get("analysis_period"),
        "explicit_likes": dish_names(explicit.get("likes", [])),
        "explicit_dislikes": dish_names(explicit.get("dislikes", [])),
        "restrictions": explicit.get("restrictions", []),
        "known_good_dishes": known,
        "supported_dish_families": families,
        "explicit_logistics": logistics.get("explicit_contexts", []),
        "pickup_rankings": logistics.get("explicit_pickup_rankings", {}),
        "usage": [
            "按我的偏好订下一个可订周，提交前让我确认",
            "查看我的订餐偏好",
            "纠正偏好：我不喜欢某道菜",
            "忘记某道菜或重置全部偏好",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze-history")
    analyze.add_argument("--history", type=Path, required=True)
    analyze.add_argument("--output", type=Path)
    analyze.add_argument("--profile", type=Path)
    analyze.add_argument("--force-partial", action="store_true")

    rank = subparsers.add_parser("rank")
    rank.add_argument("--profile", type=Path, required=True)
    rank.add_argument("--candidates", type=Path, required=True)
    rank.add_argument("--output", type=Path)

    delta = subparsers.add_parser("apply-delta")
    delta.add_argument("--profile", type=Path, required=True)
    delta.add_argument("--delta", type=Path, required=True)
    delta.add_argument("--output", type=Path)

    summary = subparsers.add_parser("summarize")
    summary.add_argument("--profile", type=Path, required=True)
    summary.add_argument("--output", type=Path)

    args = parser.parse_args()
    if args.command == "analyze-history":
        result = analyze_history(load_object(args.history.expanduser().resolve()))
        if args.profile:
            profile_path = args.profile.expanduser().resolve()
            profile = apply_analysis(
                load_object(profile_path), result, args.force_partial
            )
            write_atomic(profile_path, profile)
            result["profile_updated"] = True
        if args.output:
            write_atomic(args.output.expanduser().resolve(), result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "rank":
        result = rank_candidates(
            load_object(args.profile.expanduser().resolve()),
            load_object(args.candidates.expanduser().resolve()),
        )
    elif args.command == "apply-delta":
        profile_path = args.profile.expanduser().resolve()
        updated, receipt = apply_delta(
            load_object(profile_path), load_object(args.delta.expanduser().resolve())
        )
        destination = args.output.expanduser().resolve() if args.output else profile_path
        write_atomic(destination, updated)
        result = receipt
    else:
        result = summarize(load_object(args.profile.expanduser().resolve()))

    if args.command in {"rank", "summarize"} and getattr(args, "output", None):
        write_atomic(args.output.expanduser().resolve(), result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
