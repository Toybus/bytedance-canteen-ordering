#!/usr/bin/env python3
"""Generate an opt-in diagnostic report without orders, preferences, or auth data."""

from __future__ import annotations

import argparse
import json
import platform
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ALLOWED_STATES = {"available", "missing", "unknown", "ok", "error", "logged_out"}


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


def safe_state(value: str, field: str) -> str:
    if value not in ALLOWED_STATES:
        raise ValueError(f"{field} must be one of {sorted(ALLOWED_STATES)}")
    return value


def profile_shape(path: Path) -> dict:
    if not path.is_file():
        return {"exists": False, "schema_version": None, "parseable": False}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"exists": True, "schema_version": None, "parseable": False}
    return {
        "exists": True,
        "schema_version": value.get("schema_version") if isinstance(value, dict) else None,
        "parseable": isinstance(value, dict),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--browser-state", default="unknown")
    parser.add_argument("--login-state", default="unknown")
    parser.add_argument("--page-state", default="unknown")
    parser.add_argument("--stage", default="unknown")
    parser.add_argument("--error-code")
    parser.add_argument("--plugin-version", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    browser_state = safe_state(args.browser_state, "browser-state")
    login_state = safe_state(args.login_state, "login-state")
    page_state = safe_state(args.page_state, "page-state")
    profile_path = (
        args.profile.expanduser().resolve()
        if args.profile
        else Path.home() / ".codex" / "order-bytedance-canteen" / "profile.json"
    )
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "plugin": {
            "name": "bytedance-canteen-ordering",
            "version": args.plugin_version,
        },
        "environment": {
            "python_version": platform.python_version(),
            "profile": profile_shape(profile_path),
            "browser_control": browser_state,
            "aplus_login": login_state,
            "aplus_page": page_state,
        },
        "execution": {
            "stage": args.stage,
            "error_code": args.error_code,
        },
        "privacy": {
            "contains_orders": False,
            "contains_preferences": False,
            "contains_credentials": False,
            "contains_cookie_or_browser_storage": False,
            "contains_local_paths": False,
        },
    }
    output = args.output
    if output is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = (
            Path.home()
            / ".codex"
            / "order-bytedance-canteen"
            / "diagnostics"
            / f"diagnostic-{stamp}.json"
        )
    output = output.expanduser().resolve()
    write_atomic(output, report)
    print(
        json.dumps(
            {"status": "created", "diagnostic_path": str(output)},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
