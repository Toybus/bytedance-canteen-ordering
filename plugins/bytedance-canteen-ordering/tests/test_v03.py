from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "order-bytedance-canteen"
SCRIPTS = SKILL / "scripts"
ASSETS = SKILL / "assets"


def run_script(name: str, *args: str, expect_success: bool = True) -> dict:
    result = subprocess.run(
        ["python3", str(SCRIPTS / name), *map(str, args)],
        text=True,
        capture_output=True,
        check=False,
    )
    if expect_success and result.returncode != 0:
        raise AssertionError(
            f"{name} failed with {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    if not expect_success:
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    return json.loads(result.stdout)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def profile_paths(root: Path) -> dict:
    return {
        "site_guide_path": str(root / "site-guide.md"),
        "run_log_dir": str(root / "runs"),
        "monitor_dir": str(root / "monitors"),
    }


def make_v3_profile(root: Path) -> Path:
    profile = json.loads(
        (ASSETS / "profile.template.json").read_text(encoding="utf-8")
    )
    profile["schema_version"] = 3
    profile.pop("experience_policy", None)
    profile.pop("experience_state", None)
    profile["identity"]["default_building"] = "Test Building"
    profile["paths"] = profile_paths(root)
    profile["preferences"]["explicit"]["dislikes"] = [
        {
            "dish": "Pepper Dumpling",
            "reason": "explicit correction",
        }
    ]
    profile["monitoring_policy"] = {
        "activation": "auto_for_provisional",
        "poll_minutes": 15,
        "minimum_improvement_points": 15,
        "auto_monitor_below_score": 60,
        "stop_before_cutoff_minutes": 15,
        "max_active_monitors": 5,
        "replacement_mode": "confirm_exact_swap",
        "recovery_sequence": ["original_order", "confirmed_fallback"],
    }
    path = root / "profile-v3.json"
    write_json(path, profile)
    return path


def make_v4_profile(root: Path) -> Path:
    profile = json.loads(
        (ASSETS / "profile.template.json").read_text(encoding="utf-8")
    )
    profile["identity"]["default_building"] = "Test Building"
    profile["paths"] = profile_paths(root)
    path = root / "profile-v4.json"
    write_json(path, profile)
    return path


class ProfileMigrationTests(unittest.TestCase):
    def test_v3_to_v4_preserves_preferences_and_adds_adaptive_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = make_v3_profile(root)
            output = root / "profile-v4.json"

            result = run_script(
                "migrate_profile_v4.py",
                "--profile",
                source,
                "--output",
                output,
            )
            migrated = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(result["schema_version"], 4)
            self.assertEqual(migrated["schema_version"], 4)
            self.assertEqual(
                migrated["preferences"]["explicit"]["dislikes"][0]["dish"],
                "Pepper Dumpling",
            )
            policy = migrated["monitoring_policy"]
            self.assertNotIn("poll_minutes", policy)
            self.assertNotIn("stop_before_cutoff_minutes", policy)
            self.assertEqual(policy["stop_before_pickup_minutes"], 15)
            self.assertTrue(policy["continue_after_regular_cutoff_for_releases"])
            self.assertEqual(
                policy["missing_slot_release_monitoring"],
                "auto_for_requested_coverage",
            )
            self.assertEqual(policy["cadence"]["mode"], "adaptive")
            self.assertEqual(
                migrated["experience_state"]["onboarding_version_shown"],
                0,
            )

    def test_v4_migration_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = make_v3_profile(root)
            output = root / "profile-v4.json"
            run_script(
                "migrate_profile_v4.py",
                "--profile",
                source,
                "--output",
                output,
            )
            first = output.read_text(encoding="utf-8")
            result = run_script(
                "migrate_profile_v4.py",
                "--profile",
                output,
            )

            self.assertEqual(result["status"], "already_current")
            self.assertEqual(output.read_text(encoding="utf-8"), first)


class MonitorScheduleTests(unittest.TestCase):
    def test_far_monitor_uses_four_hours(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = make_v4_profile(Path(directory))
            result = run_script(
                "resolve_monitor_schedule.py",
                "--profile",
                profile,
                "--now",
                "2026-08-03T16:00:00-07:00",
                "--regular-order-cutoff-at",
                "2026-08-04T10:00:00-07:00",
                "--pickup-start-at",
                "2026-08-06T12:00:00-07:00",
                "--current-score",
                "60",
            )

            self.assertEqual(result["state"], "active")
            self.assertEqual(result["window_phase"], "regular_window")
            self.assertEqual(result["interval_minutes"], 240)
            self.assertEqual(
                result["next_check_at"],
                "2026-08-03T20:00:00-07:00",
            )

    def test_same_day_release_only_monitor_uses_fifteen_minutes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = make_v4_profile(Path(directory))
            result = run_script(
                "resolve_monitor_schedule.py",
                "--profile",
                profile,
                "--now",
                "2026-08-06T16:00:00-07:00",
                "--regular-order-cutoff-at",
                "2026-08-04T10:00:00-07:00",
                "--pickup-start-at",
                "2026-08-06T18:00:00-07:00",
                "--current-score",
                "60",
            )

            self.assertEqual(result["state"], "active")
            self.assertEqual(result["window_phase"], "release_only")
            self.assertEqual(result["interval_minutes"], 15)
            self.assertEqual(
                result["next_check_at"],
                "2026-08-06T16:15:00-07:00",
            )

    def test_no_change_backoff_caps_at_twelve_hours(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = make_v4_profile(Path(directory))
            result = run_script(
                "resolve_monitor_schedule.py",
                "--profile",
                profile,
                "--now",
                "2026-08-03T08:00:00-07:00",
                "--regular-order-cutoff-at",
                "2026-08-04T10:00:00-07:00",
                "--pickup-start-at",
                "2026-08-07T17:00:00-07:00",
                "--current-score",
                "60",
                "--consecutive-no-change",
                "3",
            )

            self.assertEqual(result["interval_minutes"], 720)
            self.assertIn("no_change_backoff", result["reason_codes"])

    def test_high_regret_checks_one_band_faster(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = make_v4_profile(Path(directory))
            result = run_script(
                "resolve_monitor_schedule.py",
                "--profile",
                profile,
                "--now",
                "2026-08-03T16:00:00-07:00",
                "--regular-order-cutoff-at",
                "2026-08-04T10:00:00-07:00",
                "--pickup-start-at",
                "2026-08-06T12:00:00-07:00",
                "--current-score",
                "35",
            )

            self.assertEqual(result["interval_minutes"], 60)
            self.assertIn("high_regret", result["reason_codes"])

    def test_recent_inventory_change_checks_one_band_faster(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = make_v4_profile(Path(directory))
            result = run_script(
                "resolve_monitor_schedule.py",
                "--profile",
                profile,
                "--now",
                "2026-08-03T16:00:00-07:00",
                "--regular-order-cutoff-at",
                "2026-08-04T10:00:00-07:00",
                "--pickup-start-at",
                "2026-08-06T12:00:00-07:00",
                "--current-score",
                "60",
                "--recent-inventory-change",
            )

            self.assertEqual(result["interval_minutes"], 60)
            self.assertIn(
                "recent_inventory_change",
                result["reason_codes"],
            )

    def test_near_pickup_tightens_even_after_previous_no_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = make_v4_profile(Path(directory))
            result = run_script(
                "resolve_monitor_schedule.py",
                "--profile",
                profile,
                "--now",
                "2026-08-06T12:00:00-07:00",
                "--regular-order-cutoff-at",
                "2026-08-04T10:00:00-07:00",
                "--pickup-start-at",
                "2026-08-06T18:00:00-07:00",
                "--current-score",
                "60",
                "--consecutive-no-change",
                "8",
            )

            self.assertEqual(result["interval_minutes"], 30)
            self.assertNotIn("no_change_backoff", result["reason_codes"])

    def test_pending_confirmation_has_no_ordinary_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = make_v4_profile(Path(directory))
            result = run_script(
                "resolve_monitor_schedule.py",
                "--profile",
                profile,
                "--now",
                "2026-08-03T16:00:00-07:00",
                "--regular-order-cutoff-at",
                "2026-08-04T10:00:00-07:00",
                "--pickup-start-at",
                "2026-08-06T12:00:00-07:00",
                "--state",
                "swap_approval_pending",
            )

            self.assertEqual(result["action"], "no_schedule")
            self.assertIsNone(result["next_check_at"])

    def test_next_check_crossing_stop_expires(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = make_v4_profile(Path(directory))
            result = run_script(
                "resolve_monitor_schedule.py",
                "--profile",
                profile,
                "--now",
                "2026-08-06T17:40:00-07:00",
                "--regular-order-cutoff-at",
                "2026-08-04T10:00:00-07:00",
                "--pickup-start-at",
                "2026-08-06T18:00:00-07:00",
                "--current-score",
                "60",
            )

            self.assertEqual(result["state"], "expired")
            self.assertIn(
                "next_check_crosses_stop",
                result["reason_codes"],
            )


class LifecycleAndActionTests(unittest.TestCase):
    def test_regular_cutoff_closed_enters_release_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = make_v4_profile(Path(directory))
            result = run_script(
                "resolve_lifecycle.py",
                "--profile",
                profile,
                "--target-week",
                "2026-08-03",
                "--menu-state",
                "closed",
                "--cutoff-state",
                "closed",
                "--release-state",
                "none",
                "--occupied-slots",
                "1",
                "--expected-slots",
                "2",
                "--now",
                "2026-08-04T16:00:00-07:00",
            )

            self.assertEqual(result["state"], "release_only")
            self.assertEqual(
                result["action"],
                "monitor_released_inventory_for_missing_slots",
            )

    def test_released_inventory_can_fill_a_missing_slot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = make_v4_profile(Path(directory))
            result = run_script(
                "resolve_monitor_action.py",
                "--profile",
                profile,
                "--mode",
                "fill_missing",
                "--window-phase",
                "release_only",
                "--candidate-score",
                "50",
                "--candidate-state",
                "available",
                "--actionability-state",
                "open",
            )

            self.assertEqual(result["state"], "submitting")
            self.assertEqual(
                result["action"],
                "submit_released_candidate_then_report",
            )
            self.assertFalse(result["confirmation_required"])
            self.assertIsNone(result["confirmation_scope"])
            self.assertEqual(result["receipt_scope"], "post_submit_receipt")

    def test_released_inventory_can_improve_an_existing_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = make_v4_profile(Path(directory))
            result = run_script(
                "resolve_monitor_action.py",
                "--profile",
                profile,
                "--mode",
                "improve_existing",
                "--window-phase",
                "release_only",
                "--current-score",
                "50",
                "--candidate-score",
                "75",
                "--candidate-state",
                "available",
                "--current-order-state",
                "verified",
                "--actionability-state",
                "open",
            )

            self.assertEqual(result["state"], "swap_approval_pending")
            self.assertEqual(result["action"], "emit_exact_swap_manifest")
            self.assertEqual(result["confirmation_scope"], "single_exact_swap")


class MonitorCreationAndValidationTests(unittest.TestCase):
    def test_fill_missing_monitor_has_no_current_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = make_v4_profile(root)
            output = root / "monitor.json"
            result = run_script(
                "create_monitor.py",
                "--profile",
                profile,
                "--mode",
                "fill_missing",
                "--date",
                "2026-08-06",
                "--meal",
                "dinner",
                "--building",
                "Test Building",
                "--regular-order-cutoff-at",
                "2026-08-04T10:00:00-07:00",
                "--pickup-start-at",
                "2026-08-06T18:00:00-07:00",
                "--now",
                "2026-08-06T16:00:00-07:00",
                "--output",
                output,
            )
            monitor = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(result["status"], "created")
            self.assertEqual(monitor["schema_version"], 2)
            self.assertEqual(monitor["mode"], "fill_missing")
            self.assertIsNone(monitor["current_order"])
            self.assertEqual(monitor["window_phase"], "release_only")
            self.assertEqual(
                monitor["schedule"]["last_interval_minutes"],
                15,
            )
            validation = subprocess.run(
                [
                    "python3",
                    str(SCRIPTS / "validate_config.py"),
                    "--profile",
                    str(profile),
                    "--monitor",
                    str(output),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(validation.returncode, 0, validation.stderr)

    def test_v1_monitor_migrates_to_adaptive_v2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = make_v4_profile(root)
            source = root / "monitor-v1.json"
            output = root / "monitor-v2.json"
            write_json(
                source,
                {
                    "schema_version": 1,
                    "monitor_id": "2026-08-06-dinner",
                    "state": "active",
                    "slot": {
                        "date": "2026-08-06",
                        "meal": "dinner",
                        "building": "Test Building",
                    },
                    "current_order": {
                        "dish": "Old Dish",
                        "pickup_point": "Test Pickup A",
                        "pickup_time": "18:00 - 19:30",
                        "status": "ordered",
                        "score": 50,
                        "quality": "provisional",
                    },
                    "started_at": "2026-08-03T12:00:00-07:00",
                    "stop_at": "2026-08-04T09:45:00-07:00",
                    "policy": {
                        "poll_minutes": 15,
                        "minimum_improvement_points": 15,
                        "stop_before_cutoff_minutes": 15,
                        "replacement_mode": "confirm_exact_swap",
                        "recovery_sequence": [
                            "original_order",
                            "confirmed_fallback",
                        ],
                    },
                    "best_observation": None,
                    "automation": {
                        "id": "old-recurring-id",
                        "status": "active",
                    },
                    "events": [],
                },
            )

            result = run_script(
                "migrate_monitor_v2.py",
                "--monitor",
                source,
                "--profile",
                profile,
                "--regular-order-cutoff-at",
                "2026-08-04T10:00:00-07:00",
                "--pickup-start-at",
                "2026-08-06T18:00:00-07:00",
                "--now",
                "2026-08-06T16:00:00-07:00",
                "--output",
                output,
            )
            monitor = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(result["schema_version"], 2)
            self.assertEqual(monitor["window_phase"], "release_only")
            self.assertEqual(
                monitor["schedule"]["last_interval_minutes"],
                15,
            )
            self.assertEqual(
                monitor["automation"]["status"],
                "migration_requires_reschedule",
            )
            validation = subprocess.run(
                [
                    "python3",
                    str(SCRIPTS / "validate_config.py"),
                    "--profile",
                    str(profile),
                    "--monitor",
                    str(output),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(validation.returncode, 0, validation.stderr)


class SwapPreflightTests(unittest.TestCase):
    def make_files(self, root: Path) -> tuple[Path, Path, Path]:
        old_order = {
            "date": "2026-08-06",
            "meal": "dinner",
            "dish": "Old Dish",
            "building": "Test Building",
            "pickup_point": "Test Pickup A",
            "pickup_time": "18:00 - 19:30",
        }
        new_order = {
            "date": "2026-08-06",
            "meal": "dinner",
            "dish": "New Dish",
            "building": "Test Building",
            "pickup_point": "Test Pickup B",
            "pickup_time": "18:00 - 19:30",
        }
        manifest = root / "manifest.json"
        live_order = root / "live-order.json"
        live_candidate = root / "live-candidate.json"
        write_json(
            manifest,
            {
                "old_order": old_order,
                "new_order": new_order,
                "recovery_sequence": ["original_order", "confirmed_fallback"],
                "confirmed": True,
            },
        )
        write_json(live_order, old_order)
        write_json(live_candidate, new_order)
        return manifest, live_order, live_candidate

    def test_exact_match_allows_one_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, live_order, live_candidate = self.make_files(
                Path(directory)
            )
            result = run_script(
                "resolve_swap_preflight.py",
                "--manifest",
                manifest,
                "--live-order",
                live_order,
                "--live-candidate",
                live_candidate,
                "--candidate-state",
                "available",
                "--page-state",
                "stable",
                "--cancel-control-scope",
                "matching_order_card",
                "--matching-order-count",
                "1",
            )

            self.assertEqual(result["decision"], "allow_single_cancel")
            self.assertTrue(result["confirmation_valid"])

    def test_order_mismatch_aborts_and_keeps_original(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, live_order, live_candidate = self.make_files(root)
            changed = json.loads(live_order.read_text(encoding="utf-8"))
            changed["meal"] = "lunch"
            write_json(live_order, changed)
            result = run_script(
                "resolve_swap_preflight.py",
                "--manifest",
                manifest,
                "--live-order",
                live_order,
                "--live-candidate",
                live_candidate,
                "--candidate-state",
                "available",
                "--page-state",
                "stable",
                "--cancel-control-scope",
                "matching_order_card",
                "--matching-order-count",
                "1",
            )

            self.assertEqual(result["decision"], "abort_keep_original")
            self.assertIn("old_order_mismatch", result["reasons"])

    def test_wrong_cancel_scope_aborts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, live_order, live_candidate = self.make_files(
                Path(directory)
            )
            result = run_script(
                "resolve_swap_preflight.py",
                "--manifest",
                manifest,
                "--live-order",
                live_order,
                "--live-candidate",
                live_candidate,
                "--candidate-state",
                "available",
                "--page-state",
                "stable",
                "--cancel-control-scope",
                "other",
                "--matching-order-count",
                "1",
            )

            self.assertEqual(result["decision"], "abort_keep_original")
            self.assertIn("cancel_control_not_scoped", result["reasons"])

    def test_candidate_disappearing_aborts_without_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, live_order, live_candidate = self.make_files(
                Path(directory)
            )
            result = run_script(
                "resolve_swap_preflight.py",
                "--manifest",
                manifest,
                "--live-order",
                live_order,
                "--live-candidate",
                live_candidate,
                "--candidate-state",
                "unavailable",
                "--page-state",
                "stable",
                "--cancel-control-scope",
                "matching_order_card",
                "--matching-order-count",
                "1",
            )

            self.assertEqual(result["decision"], "abort_keep_original")
            self.assertIn("candidate_not_available", result["reasons"])


if __name__ == "__main__":
    unittest.main()
