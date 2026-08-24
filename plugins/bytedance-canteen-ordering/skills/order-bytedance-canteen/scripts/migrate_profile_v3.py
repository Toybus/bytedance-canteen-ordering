#!/usr/bin/env python3
"""Upgrade and conservatively merge canteen profiles into schema v3."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


CONFIDENCE = {"low": 1, "medium": 2, "high": 3}


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"profile must be an object: {path}")
    return value


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def prepare_state_dirs(
    profile: dict,
    skill_root: Path,
    legacy_guide: Path | None,
) -> None:
    paths = profile["paths"]
    Path(paths["run_log_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
    Path(paths["monitor_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
    guide = Path(paths["site_guide_path"]).expanduser()
    guide.parent.mkdir(parents=True, exist_ok=True)
    if guide.exists():
        return
    if legacy_guide and legacy_guide.is_file():
        shutil.copyfile(legacy_guide, guide)
    else:
        shutil.copyfile(skill_root / "assets" / "site-guide.template.md", guide)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unique(values: list) -> list:
    result = []
    seen = set()
    for value in values:
        key = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            result.append(copy.deepcopy(value))
    return result


def preference_label(value: object) -> str:
    if isinstance(value, str):
        return value.strip().casefold()
    if isinstance(value, dict):
        for key in ("dish", "dish_family", "name", "value"):
            label = value.get(key)
            if isinstance(label, str) and label.strip():
                return label.strip().casefold()
    return json.dumps(value, ensure_ascii=False, sort_keys=True).casefold()


def affinity_key(value: object) -> str:
    label = preference_label(value)
    label = re.sub(r"【[^】]*】|\[[^\]]*\]", "", label)
    return re.sub(r"\s+", " ", label).strip()


def normalize_affinity(value: object) -> dict:
    if isinstance(value, str):
        return {"dish": value, "confidence": "high"}
    if isinstance(value, dict) and isinstance(value.get("dish"), str):
        result = copy.deepcopy(value)
        result.setdefault("confidence", "medium")
        return result
    return {"dish": str(value), "confidence": "low"}


def merge_affinities(primary: list, incoming: list) -> list:
    merged: dict[str, dict] = {}
    order: list[str] = []
    for raw in [*primary, *incoming]:
        item = normalize_affinity(raw)
        key = affinity_key(item)
        if key not in merged:
            merged[key] = item
            order.append(key)
            continue
        old = merged[key]
        if CONFIDENCE.get(item.get("confidence"), 0) > CONFIDENCE.get(
            old.get("confidence"), 0
        ):
            merged[key] = item
    return [merged[key] for key in order]


def apply_v3_defaults(profile: dict, template: dict, canonical: Path) -> dict:
    version = profile.get("schema_version")
    if version not in {2, 3}:
        raise ValueError(f"unsupported schema_version: {version}")
    result = copy.deepcopy(profile)
    for key in (
        "interaction_policy",
        "monitoring_policy",
        "state_management",
    ):
        result.setdefault(key, copy.deepcopy(template[key]))
    result["schema_version"] = 3
    result["runtime_policy"]["confirmation_scope"] = "execution_manifest"
    result.setdefault("paths", {})
    result["paths"].setdefault(
        "site_guide_path",
        str(canonical.parent / "site-guide.md"),
    )
    result["paths"].setdefault("run_log_dir", str(canonical.parent / "runs"))
    result["paths"].setdefault(
        "monitor_dir",
        str(canonical.parent / "monitors"),
    )
    result["state_management"]["scope"] = "user"
    result["state_management"]["canonical_profile"] = True
    result["state_management"].setdefault("legacy_sources", [])
    result["state_management"].setdefault("legacy_source_fingerprints", {})
    result["state_management"].setdefault("last_merged_at", None)
    result["state_management"].setdefault("preference_conflicts", [])
    return result


def merge_profile(primary: dict, incoming: dict) -> dict:
    result = copy.deepcopy(primary)
    result_explicit = result["preferences"]["explicit"]
    incoming_explicit = incoming["preferences"]["explicit"]
    for key in ("likes", "dislikes", "variant_allowances", "restrictions"):
        result_explicit[key] = unique(
            [*result_explicit.get(key, []), *incoming_explicit.get(key, [])]
        )

    result_inferred = result["preferences"]["inferred"]
    incoming_inferred = incoming["preferences"]["inferred"]
    for key in ("cuisines", "proteins", "flavors", "formats"):
        result_inferred[key] = unique(
            [*result_inferred.get(key, []), *incoming_inferred.get(key, [])]
        )
    result_inferred["completed_dish_affinity"] = merge_affinities(
        result_inferred.get("completed_dish_affinity", []),
        incoming_inferred.get("completed_dish_affinity", []),
    )
    result["preferences"]["deprioritized"] = unique(
        [
            *result["preferences"].get("deprioritized", []),
            *incoming["preferences"].get("deprioritized", []),
        ]
    )

    for meal in ("lunch", "dinner"):
        result["pickup_rankings"][meal] = unique(
            [
                *result["pickup_rankings"].get(meal, []),
                *incoming["pickup_rankings"].get(meal, []),
            ]
        )
    result["decision_policy"]["known_bad_pickup_slots"] = unique(
        [
            *result["decision_policy"].get("known_bad_pickup_slots", []),
            *incoming["decision_policy"].get("known_bad_pickup_slots", []),
        ]
    )

    if incoming["history_evidence"].get("orders_sampled", 0) > result[
        "history_evidence"
    ].get("orders_sampled", 0):
        result["history_evidence"] = copy.deepcopy(incoming["history_evidence"])

    likes = {preference_label(item) for item in result_explicit["likes"]}
    dislikes = {preference_label(item) for item in result_explicit["dislikes"]}
    conflicts = [
        {"type": "like_dislike", "value": value}
        for value in sorted(likes & dislikes)
    ]
    result["state_management"]["preference_conflicts"] = unique(
        [
            *result["state_management"].get("preference_conflicts", []),
            *conflicts,
        ]
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--merge-from", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    profile_path = args.profile.expanduser().resolve()
    merge_paths = [path.expanduser().resolve() for path in args.merge_from]
    skill_root = Path(__file__).resolve().parent.parent
    template = load(skill_root / "assets" / "profile.template.json")

    primary_legacy_source = None
    legacy_guide = None
    if profile_path.is_file():
        primary = load(profile_path)
    elif merge_paths:
        primary_legacy_source = merge_paths.pop(0)
        primary = load(primary_legacy_source)
        guide_value = primary.get("paths", {}).get("site_guide_path")
        if isinstance(guide_value, str) and guide_value.strip():
            legacy_guide = Path(guide_value).expanduser()
    else:
        raise ValueError("profile is missing and no --merge-from source was provided")

    result = apply_v3_defaults(primary, template, profile_path)
    merged_sources = (
        [str(primary_legacy_source)] if primary_legacy_source else []
    )
    if primary_legacy_source:
        result["paths"] = {
            "site_guide_path": str(profile_path.parent / "site-guide.md"),
            "run_log_dir": str(profile_path.parent / "runs"),
            "monitor_dir": str(profile_path.parent / "monitors"),
        }
    for path in merge_paths:
        incoming = apply_v3_defaults(load(path), template, profile_path)
        result = merge_profile(result, incoming)
        merged_sources.append(str(path))

    if merged_sources:
        state = result["state_management"]
        state["legacy_sources"] = unique(
            [*state.get("legacy_sources", []), *merged_sources]
        )
        timezone = ZoneInfo(result["identity"]["timezone"])
        state["last_merged_at"] = datetime.now(timezone).isoformat()
        state["legacy_source_fingerprints"] = {
            **state.get("legacy_source_fingerprints", {}),
            **{
                str(path): digest(path)
                for path in (
                    [primary_legacy_source] if primary_legacy_source else []
                )
                + merge_paths
            },
        }

    destination = (
        args.output.expanduser().resolve() if args.output else profile_path
    )
    if args.dry_run:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if args.output is None:
            prepare_state_dirs(result, skill_root, legacy_guide)
        write(destination, result)
        print(
            json.dumps(
                {
                    "status": "migrated",
                    "profile_path": str(destination),
                    "merged_sources": merged_sources,
                    "schema_version": 3,
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
