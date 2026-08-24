#!/usr/bin/env python3
"""Create portable first-use state for the ByteDance canteen ordering Skill."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--building", required=True)
    parser.add_argument("--timezone", required=True)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path.home() / ".codex" / "order-bytedance-canteen",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    try:
        ZoneInfo(args.timezone)
    except ZoneInfoNotFoundError:
        print(json.dumps({"status": "error", "reason": "unknown_timezone"}))
        return 1
    if not args.building.strip():
        print(json.dumps({"status": "error", "reason": "empty_building"}))
        return 1

    skill_root = Path(__file__).resolve().parent.parent
    profile_template = skill_root / "assets" / "profile.template.json"
    guide_template = skill_root / "assets" / "site-guide.template.md"
    profile = json.loads(profile_template.read_text(encoding="utf-8"))
    supported_buildings = profile["supported_scope"]["buildings"]
    building_by_key = {
        value.strip().casefold(): value for value in supported_buildings
    }
    building_key = args.building.strip().casefold()
    if building_key not in building_by_key:
        print(
            json.dumps(
                {
                    "status": "unsupported_building",
                    "supported_buildings": supported_buildings,
                    "transaction_attempted": False,
                },
                ensure_ascii=False,
            )
        )
        return 2
    data_dir = args.data_dir.expanduser().resolve()
    profile_path = data_dir / "profile.json"
    guide_path = data_dir / "site-guide.md"
    runs_path = data_dir / "runs"
    monitors_path = data_dir / "monitors"

    data_dir.mkdir(parents=True, exist_ok=True)
    runs_path.mkdir(parents=True, exist_ok=True)
    monitors_path.mkdir(parents=True, exist_ok=True)

    if profile_path.exists() and not args.force:
        print(
            json.dumps(
                {
                    "status": "existing",
                    "profile_path": str(profile_path),
                    "site_guide_path": str(guide_path),
                    "run_log_dir": str(runs_path),
                    "monitor_dir": str(monitors_path),
                },
                ensure_ascii=False,
            )
        )
        return 0

    profile["identity"]["timezone"] = args.timezone
    profile["identity"]["default_building"] = building_by_key[building_key]
    profile["paths"]["site_guide_path"] = str(guide_path)
    profile["paths"]["run_log_dir"] = str(runs_path)
    profile["paths"]["monitor_dir"] = str(monitors_path)
    profile_path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if args.force or not guide_path.exists():
        shutil.copyfile(guide_template, guide_path)

    print(
        json.dumps(
            {
                "status": "created",
                "profile_path": str(profile_path),
                "site_guide_path": str(guide_path),
                "run_log_dir": str(runs_path),
                "monitor_dir": str(monitors_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
