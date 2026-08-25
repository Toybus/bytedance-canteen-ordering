#!/usr/bin/env python3
"""Upgrade a ByteDance canteen profile from schema v5 to schema v6."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import tempfile
from pathlib import Path


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


def migrate(profile: dict, template: dict) -> dict:
    version = profile.get("schema_version")
    if version not in {5, 6}:
        raise ValueError(f"unsupported schema_version: {version}")

    result = merge_defaults(profile, template)
    result["schema_version"] = 6
    result["runtime_policy"]["confirmation_scope"] = "post_submit_receipt"
    result["interaction_policy"]["normal_order_confirmation"] = (
        "post_submit_receipt"
    )
    result["confirmation_policy"]["submit"] = "delegated"
    result["decision_policy"]["require_exception_confirmation"] = False
    result["transaction_policy"] = copy.deepcopy(template["transaction_policy"])
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
    if destination == source and original.get("schema_version") == 5:
        backup = source.with_name(f"{source.name}.v5.bak")
        if not backup.exists():
            shutil.copy2(source, backup)
    write_atomic(destination, result)
    print(
        json.dumps(
            {
                "status": (
                    "already_current"
                    if original.get("schema_version") == 6
                    else "migrated"
                ),
                "profile_path": str(destination),
                "backup_path": str(backup) if backup else None,
                "schema_version": 6,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
