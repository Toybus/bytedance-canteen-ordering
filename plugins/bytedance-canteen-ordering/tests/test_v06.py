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


def run_script(name: str, *args: object, success: bool = True) -> dict:
    result = subprocess.run(
        ["python3", str(SCRIPTS / name), *map(str, args)],
        text=True,
        capture_output=True,
        check=False,
    )
    if success and result.returncode != 0:
        raise AssertionError(
            f"{name} failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    if not success:
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    return json.loads(result.stdout)


def write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def make_profile(root: Path) -> Path:
    profile = json.loads(
        (ASSETS / "profile.template.json").read_text(encoding="utf-8")
    )
    profile["identity"]["default_building"] = "Lincoln Square North"
    profile["paths"] = {
        "site_guide_path": str(root / "site-guide.md"),
        "run_log_dir": str(root / "runs"),
        "monitor_dir": str(root / "monitors"),
    }
    path = root / "profile.json"
    write_json(path, profile)
    return path


class ProfileV6Tests(unittest.TestCase):
    def test_v5_migration_preserves_preferences_and_delegates_only_submit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = make_profile(root)
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["schema_version"] = 5
            profile["runtime_policy"]["confirmation_scope"] = "execution_manifest"
            profile["interaction_policy"]["normal_order_confirmation"] = (
                "single_execution_manifest"
            )
            profile["confirmation_policy"]["submit"] = "required"
            profile["decision_policy"]["require_exception_confirmation"] = True
            profile.pop("transaction_policy")
            profile["preferences"]["explicit"]["dislikes"] = [
                {
                    "dish": "Spicy Pork Xiao Long Bao",
                    "specificity": "exact",
                }
            ]
            profile["history_evidence"]["orders_sampled"] = 42
            write_json(profile_path, profile)

            result = run_script("migrate_profile_v6.py", "--profile", profile_path)
            migrated = json.loads(profile_path.read_text(encoding="utf-8"))

            self.assertEqual(result["schema_version"], 6)
            self.assertTrue(Path(result["backup_path"]).exists())
            self.assertEqual(
                migrated["preferences"]["explicit"]["dislikes"][0]["dish"],
                "Spicy Pork Xiao Long Bao",
            )
            self.assertEqual(migrated["history_evidence"]["orders_sampled"], 42)
            self.assertEqual(migrated["confirmation_policy"]["submit"], "delegated")
            self.assertEqual(migrated["confirmation_policy"]["cancel"], "required")
            self.assertEqual(migrated["confirmation_policy"]["release"], "required")
            self.assertEqual(
                migrated["transaction_policy"]["normal_order_mode"],
                "submit_then_report",
            )
            self.assertEqual(
                migrated["transaction_policy"]["cross_batch_user_pause"],
                "forbidden",
            )
            self.assertFalse(
                migrated["decision_policy"]["require_exception_confirmation"]
            )

            validation = subprocess.run(
                [
                    "python3",
                    str(SCRIPTS / "validate_config.py"),
                    "--profile",
                    str(profile_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(validation.returncode, 0, validation.stderr)

    def test_validator_rejects_pre_submit_normal_order_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile_path = make_profile(Path(directory))
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["interaction_policy"]["normal_order_confirmation"] = (
                "single_execution_manifest"
            )
            write_json(profile_path, profile)
            result = run_script(
                "validate_config.py",
                "--profile",
                profile_path,
                success=False,
            )
            self.assertNotEqual(result["returncode"], 0)
            self.assertIn("post_submit_receipt", result["stderr"])

    def test_validator_keeps_destructive_actions_guarded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile_path = make_profile(Path(directory))
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["confirmation_policy"]["cancel"] = "delegated"
            write_json(profile_path, profile)
            result = run_script(
                "validate_config.py",
                "--profile",
                profile_path,
                success=False,
            )
            self.assertNotEqual(result["returncode"], 0)
            self.assertIn("cancel must be required", result["stderr"])


class BatchExecutionTests(unittest.TestCase):
    def resolve(self, *args: object) -> dict:
        return run_script(
            "resolve_batch_execution.py", "--plan-state", "complete", *args
        )

    def test_incomplete_plan_cannot_stage_lunch(self) -> None:
        result = run_script(
            "resolve_batch_execution.py",
            "--plan-state",
            "incomplete",
            "--lunch-rows",
            5,
            "--lunch-state",
            "planned",
        )
        self.assertEqual(result["state"], "planning")
        self.assertEqual(
            result["action"],
            "complete_full_requested_lunch_and_dinner_plan",
        )
        self.assertFalse(result["conversation_boundary"])

    def test_complete_plan_starts_lunch_without_confirmation(self) -> None:
        result = self.resolve(
            "--lunch-rows", 5, "--lunch-state", "planned",
            "--dinner-rows", 4, "--dinner-state", "planned",
        )
        self.assertEqual(result["action"], "stage_lunch_batch")
        self.assertFalse(result["conversation_boundary"])
        self.assertFalse(result["user_confirmation_required"])

    def test_verified_lunch_continues_directly_to_dinner(self) -> None:
        result = self.resolve(
            "--lunch-rows", 5, "--lunch-state", "verified",
            "--dinner-rows", 4, "--dinner-state", "planned",
        )
        self.assertEqual(result["action"], "stage_dinner_batch")
        self.assertFalse(result["conversation_boundary"])

    def test_receipt_is_emitted_only_after_both_batches_verified(self) -> None:
        result = self.resolve(
            "--lunch-rows", 5, "--lunch-state", "verified",
            "--dinner-rows", 4, "--dinner-state", "verified",
        )
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["action"], "emit_post_submit_receipt")
        self.assertTrue(result["conversation_boundary"])

    def test_all_slots_occupied_never_touches_a_cart(self) -> None:
        result = self.resolve()
        self.assertEqual(result["state"], "already_complete")
        self.assertEqual(
            result["action"], "verify_existing_orders_and_emit_receipt"
        )

    def test_isolated_lunch_failure_still_attempts_dinner(self) -> None:
        result = self.resolve(
            "--lunch-rows", 5, "--lunch-state", "failed",
            "--dinner-rows", 4, "--dinner-state", "planned",
            "--failure-scope", "isolated_batch",
        )
        self.assertEqual(result["action"], "stage_dinner_batch")
        self.assertEqual(result["failed_batches"], ["lunch"])
        self.assertFalse(result["conversation_boundary"])

    def test_unstable_page_stops_before_more_transactions(self) -> None:
        result = self.resolve(
            "--lunch-rows", 5, "--lunch-state", "failed",
            "--dinner-rows", 4, "--dinner-state", "planned",
            "--failure-scope", "page_unstable",
        )
        self.assertEqual(result["state"], "needs_recovery")
        self.assertEqual(
            result["action"], "stop_and_recover_page_before_more_transactions"
        )


class LifecyclePolicyTests(unittest.TestCase):
    def test_lifecycle_exposes_delegated_normal_order_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile_path = make_profile(Path(directory))
            result = run_script(
                "resolve_lifecycle.py",
                "--profile",
                profile_path,
                "--target-week",
                "2026-08-31",
                "--menu-state",
                "open",
                "--occupied-slots",
                0,
                "--expected-slots",
                9,
                "--now",
                "2026-08-25T10:05:00-07:00",
            )
            self.assertEqual(result["state"], "ready_to_plan")
            self.assertEqual(result["normal_order"]["authorization"], "delegated")
            self.assertEqual(result["normal_order"]["receipt"], "after_submit")


class LegacyMonitorRecoveryTests(unittest.TestCase):
    def test_old_missing_slot_confirmation_resumes_live_monitoring(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = make_profile(root)
            monitor_path = root / "monitor.json"
            run_script(
                "create_monitor.py",
                "--profile",
                profile_path,
                "--mode",
                "fill_missing",
                "--date",
                "2026-09-03",
                "--meal",
                "dinner",
                "--building",
                "Lincoln Square North",
                "--regular-order-cutoff-at",
                "2026-09-01T10:00:00-07:00",
                "--pickup-start-at",
                "2026-09-03T18:00:00-07:00",
                "--now",
                "2026-09-03T16:00:00-07:00",
                "--output",
                monitor_path,
            )
            monitor = json.loads(monitor_path.read_text(encoding="utf-8"))
            monitor["state"] = "submit_approval_pending"
            monitor["best_observation"] = {"dish": "Stale Candidate"}
            write_json(monitor_path, monitor)

            result = run_script(
                "migrate_monitor_v2.py",
                "--monitor",
                monitor_path,
                "--profile",
                profile_path,
                "--now",
                "2026-09-03T16:01:00-07:00",
            )
            recovered = json.loads(monitor_path.read_text(encoding="utf-8"))

            self.assertEqual(
                result["status"], "recovered_legacy_submit_confirmation"
            )
            self.assertTrue(Path(result["backup_path"]).exists())
            self.assertEqual(recovered["state"], "active")
            self.assertIsNone(recovered["best_observation"])
            self.assertEqual(
                recovered["schedule"]["next_check_at"],
                "2026-09-03T16:01:00-07:00",
            )
            self.assertIn(
                "legacy_submit_confirmation_removed",
                recovered["schedule"]["reason_codes"],
            )
            validation = subprocess.run(
                [
                    "python3",
                    str(SCRIPTS / "validate_config.py"),
                    "--profile",
                    str(profile_path),
                    "--monitor",
                    str(monitor_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(validation.returncode, 0, validation.stderr)


if __name__ == "__main__":
    unittest.main()
