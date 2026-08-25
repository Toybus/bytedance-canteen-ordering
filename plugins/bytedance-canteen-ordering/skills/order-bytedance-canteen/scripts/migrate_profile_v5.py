#!/usr/bin/env python3
"""Upgrade a ByteDance canteen profile from schema v4 to schema v5."""

from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import tempfile
from pathlib import Path


PERIOD = re.compile(r"^(\d{4}-\d{2}-\d{2})/(\d{4}-\d{2}-\d{2})$")
CONFIDENCE = {"low", "medium", "high"}


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("profile must be a JSON object")
    return value


def merge_defaults(value: dict, defaults: dict) -> dict:
    result = copy.deepcopy(defaults)
    for key, item in value.items():
        if isinstance(item, dict) and isinstance(result.get(key), dict):
            result[key] = merge_defaults(item, result[key])
        else:
            result[key] = copy.deepcopy(item)
    return result


def source_period(value: object, history: dict) -> dict:
    if isinstance(value, dict):
        return {
            "start": value.get("start"),
            "end": value.get("end"),
            "context": value.get("context", "completed_history"),
        }
    if isinstance(value, str):
        match = PERIOD.match(value.strip())
        if match:
            return {
                "start": match.group(1),
                "end": match.group(2),
                "context": "completed_history",
            }
    analysis = history.get("analysis_period", {})
    if isinstance(analysis, dict):
        return {
            "start": analysis.get("start"),
            "end": analysis.get("end"),
            "context": analysis.get("context", "unknown"),
        }
    return {"start": None, "end": None, "context": "unknown"}


def dedupe(items: list, key) -> list:
    result = []
    seen = set()
    for item in items:
        identity = key(item)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(item)
    return result


def normalize_explicit(items: object) -> list:
    result = []
    if not isinstance(items, list):
        return result
    for raw in items:
        if isinstance(raw, str) and raw.strip():
            item = {"dish": raw.strip()}
        elif isinstance(raw, dict) and isinstance(raw.get("dish"), str):
            item = copy.deepcopy(raw)
            item["dish"] = item["dish"].strip()
        else:
            continue
        if not item["dish"]:
            continue
        item["specificity"] = "exact"
        result.append(item)
    return dedupe(result, lambda item: item["dish"].casefold())


def normalize_affinities(items: object, history: dict) -> list:
    result = []
    if not isinstance(items, list):
        return result
    for raw in items:
        if isinstance(raw, str) and raw.strip():
            item = {"dish": raw.strip()}
        elif isinstance(raw, dict) and isinstance(raw.get("dish"), str):
            item = copy.deepcopy(raw)
            item["dish"] = item["dish"].strip()
        else:
            continue
        if not item["dish"]:
            continue
        count = item.get("completed_count", 1)
        item["completed_count"] = count if type(count) is int and count > 0 else 1
        confidence = item.get("confidence", "medium")
        item["confidence"] = confidence if confidence in CONFIDENCE else "medium"
        item["specificity"] = "exact"
        item["source_period"] = source_period(item.get("source_period"), history)
        result.append(item)
    return dedupe(result, lambda item: item["dish"].casefold())


def normalize_family_affinities(items: object, history: dict) -> list:
    result = []
    if not isinstance(items, list):
        return result
    for raw in items:
        if not isinstance(raw, dict):
            continue
        family = raw.get("dish_family")
        if not isinstance(family, str) or not family.strip():
            continue
        item = copy.deepcopy(raw)
        item["dish_family"] = family.strip()
        variants = []
        for variant in item.get("variants", []):
            if not isinstance(variant, dict):
                continue
            dish = variant.get("dish")
            count = variant.get("completed_count")
            if (
                isinstance(dish, str)
                and dish.strip()
                and type(count) is int
                and count > 0
            ):
                variants.append(
                    {"dish": dish.strip(), "completed_count": count}
                )
        variants = dedupe(variants, lambda value: value["dish"].casefold())
        item["variants"] = variants
        count = item.get("completed_count", 0)
        if type(count) is not int or count <= 0:
            count = sum(variant["completed_count"] for variant in variants)
        item["completed_count"] = count
        confidence = item.get("confidence", "medium")
        item["confidence"] = confidence if confidence in CONFIDENCE else "medium"
        item["specificity"] = "tight_family"
        item["source_period"] = source_period(item.get("source_period"), history)
        item["usable_for_ranking"] = len(variants) >= 2
        result.append(item)
    return dedupe(result, lambda item: item["dish_family"].casefold())


def migrate(profile: dict, template: dict) -> dict:
    version = profile.get("schema_version")
    if version not in {4, 5}:
        raise ValueError(f"unsupported schema_version: {version}")

    result = merge_defaults(profile, template)
    history = result["history_evidence"]
    analysis = history.get("analysis_period")
    if not isinstance(analysis, dict):
        history["analysis_period"] = {
            "start": None,
            "end": None,
            "context": "unknown",
        }

    old_rankings = result.pop("pickup_rankings", None)
    if isinstance(old_rankings, dict):
        explicit_rankings = result["logistics_preferences"][
            "explicit_pickup_rankings"
        ]
        for meal in ("lunch", "dinner"):
            values = old_rankings.get(meal, [])
            if isinstance(values, list):
                explicit_rankings[meal] = dedupe(
                    [value for value in values if isinstance(value, str) and value.strip()],
                    lambda value: value.casefold(),
                )

    explicit = result["preferences"]["explicit"]
    explicit["likes"] = normalize_explicit(explicit.get("likes"))
    explicit["dislikes"] = normalize_explicit(explicit.get("dislikes"))

    inferred = result["preferences"]["inferred"]
    inferred["completed_dish_affinity"] = normalize_affinities(
        inferred.get("completed_dish_affinity"), history
    )
    inferred["dish_family_affinity"] = normalize_family_affinities(
        inferred.get("dish_family_affinity"), history
    )

    decision = result["decision_policy"]
    decision["prefer_known_good_dishes_over_novel_candidates"] = True
    decision["do_not_generalize_specific_dish_history_to_broad_protein"] = True
    result["runtime_policy"]["confirmation_scope"] = "execution_manifest"
    result["interaction_policy"]["normal_order_confirmation"] = (
        "single_execution_manifest"
    )
    result["confirmation_policy"]["submit"] = "required"
    result.pop("transaction_policy", None)
    result["schema_version"] = 5
    return result


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
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source = args.profile.expanduser().resolve()
    destination = args.output.expanduser().resolve() if args.output else source
    skill_root = Path(__file__).resolve().parent.parent
    template = load(skill_root / "assets" / "profile.template.json")
    original = load(source)
    result = migrate(original, template)

    if args.dry_run:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    backup = None
    if destination == source and original.get("schema_version") == 4:
        backup = source.with_name(f"{source.name}.v4.bak")
        if not backup.exists():
            shutil.copy2(source, backup)
    write_atomic(destination, result)
    print(
        json.dumps(
            {
                "status": (
                    "already_current"
                    if original.get("schema_version") == 5
                    else "migrated"
                ),
                "profile_path": str(destination),
                "backup_path": str(backup) if backup else None,
                "schema_version": 5,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
