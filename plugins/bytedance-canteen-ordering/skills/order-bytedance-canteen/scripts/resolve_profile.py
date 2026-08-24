#!/usr/bin/env python3
"""Resolve one user-wide canteen profile without creating project-local state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def already_merged(canonical: Path, legacy: Path) -> bool:
    try:
        canonical_value = json.loads(canonical.read_text(encoding="utf-8"))
        canonical_state = canonical_value.get("state_management", {})
        fingerprints = canonical_state.get("legacy_source_fingerprints", {})
        return fingerprints.get(str(legacy)) == digest(legacy)
    except (json.JSONDecodeError, OSError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--explicit", type=Path)
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument(
        "--canonical",
        type=Path,
        default=Path.home() / ".codex" / "order-bytedance-canteen" / "profile.json",
    )
    args = parser.parse_args()

    canonical = args.canonical.expanduser().resolve()
    local = (args.cwd.expanduser().resolve() / "canteen_profile.json")
    env_value = os.environ.get("BYTE_CANTEEN_PROFILE")

    if args.explicit:
        selected = args.explicit.expanduser().resolve()
        source = "explicit"
    elif env_value:
        selected = Path(env_value).expanduser().resolve()
        source = "environment"
    elif canonical.is_file():
        selected = canonical
        source = "canonical"
    elif local.is_file():
        selected = local
        source = "legacy_only"
    else:
        selected = canonical
        source = "bootstrap_required"

    legacy_candidates = []
    merge_recommended = False
    if canonical.is_file() and local.is_file() and canonical != local:
        if digest(canonical) != digest(local) and not already_merged(
            canonical, local
        ):
            legacy_candidates.append(str(local))
            merge_recommended = True

    print(
        json.dumps(
            {
                "selected_path": str(selected),
                "source": source,
                "exists": selected.is_file(),
                "canonical_path": str(canonical),
                "legacy_candidates": legacy_candidates,
                "merge_recommended": merge_recommended,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
