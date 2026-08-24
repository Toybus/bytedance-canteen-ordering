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


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


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


def complete_collection(context: str = "pre_agent_baseline") -> dict:
    return {
        "all_statuses": True,
        "reached_end": True,
        "timezone_verified": True,
        "method": "monthly_scroll",
        "context": context,
    }


class MigrationAndValidationTests(unittest.TestCase):
    def test_v4_migrates_without_promoting_unstructured_family(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = json.loads(
                (ASSETS / "profile.template.json").read_text(encoding="utf-8")
            )
            profile["schema_version"] = 4
            profile["identity"]["default_building"] = "Lincoln Square North"
            profile["paths"] = {
                "site_guide_path": str(root / "guide.md"),
                "run_log_dir": str(root / "runs"),
                "monitor_dir": str(root / "monitors"),
            }
            profile.pop("supported_scope")
            profile.pop("preference_learning")
            profile["pickup_rankings"] = {"lunch": ["F20"], "dinner": []}
            profile.pop("logistics_preferences")
            profile["preferences"]["explicit"]["likes"] = [
                {"dish": "Roast Chicken", "reason": "said so"}
            ]
            profile["preferences"]["inferred"]["completed_dish_affinity"] = [
                {
                    "dish": "Roast Chicken",
                    "completed_count": 3,
                    "confidence": "high",
                    "source_period": "2026-05-01/2026-07-31",
                }
            ]
            profile["preferences"]["inferred"]["dish_family_affinity"] = [
                {
                    "dish_family": "Chicken dishes",
                    "completed_count": 3,
                    "confidence": "high",
                    "evidence": "legacy prose",
                }
            ]
            source = root / "v4.json"
            output = root / "v5.json"
            write_json(source, profile)

            result = run_script(
                "migrate_profile_v5.py", "--profile", source, "--output", output
            )
            migrated = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(result["schema_version"], 5)
            self.assertEqual(migrated["schema_version"], 5)
            self.assertEqual(
                migrated["preferences"]["explicit"]["likes"][0]["specificity"],
                "exact",
            )
            self.assertEqual(
                migrated["preferences"]["inferred"]["completed_dish_affinity"][0][
                    "source_period"
                ]["start"],
                "2026-05-01",
            )
            family = migrated["preferences"]["inferred"]["dish_family_affinity"][0]
            self.assertFalse(family["usable_for_ranking"])
            self.assertEqual(family["variants"], [])
            self.assertEqual(
                migrated["logistics_preferences"]["explicit_pickup_rankings"][
                    "lunch"
                ],
                ["F20"],
            )
            validation = subprocess.run(
                [
                    "python3",
                    str(SCRIPTS / "validate_config.py"),
                    "--profile",
                    str(output),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(validation.returncode, 0, validation.stderr)

            first = output.read_text(encoding="utf-8")
            again = run_script("migrate_profile_v5.py", "--profile", output)
            self.assertEqual(again["status"], "already_current")
            self.assertEqual(output.read_text(encoding="utf-8"), first)

    def test_validator_rejects_one_variant_as_rankable_family(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile_path = make_profile(Path(directory))
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["preferences"]["inferred"]["dish_family_affinity"] = [
                {
                    "dish_family": "Noodle soup",
                    "completed_count": 4,
                    "variants": [{"dish": "Beef Noodle", "completed_count": 4}],
                    "confidence": "high",
                    "specificity": "tight_family",
                    "source_period": {
                        "start": "2026-05-01",
                        "end": "2026-07-31",
                        "context": "completed_history",
                    },
                    "usable_for_ranking": True,
                }
            ]
            write_json(profile_path, profile)
            result = subprocess.run(
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
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("at least two variants", result.stderr)


class HistoryAnalysisTests(unittest.TestCase):
    def test_exact_history_does_not_create_broad_protein_preference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = root / "history.json"
            records = [
                {
                    "order_id": f"unagi-{index}",
                    "date": f"2026-07-{index + 1:02d}",
                    "meal": "lunch",
                    "dish": "Known Exact Fish Bowl",
                    "status": "completed",
                    "building": "Lincoln Square North",
                    "pickup_point": "F20 12:00 Pickup",
                    "tags": {"proteins": ["fish"]},
                }
                for index in range(6)
            ]
            records.extend(
                [
                    {
                        "order_id": "released-example",
                        "date": "2026-07-10",
                        "meal": "lunch",
                        "dish": "Novel Fish Stew",
                        "status": "released",
                        "building": "Lincoln Square North",
                        "pickup_point": "F20 12:00 Pickup",
                    },
                    {
                        "order_id": "discarded-example",
                        "date": "2026-07-11",
                        "meal": "lunch",
                        "dish": "Alternate Fish Soup",
                        "status": "discarded",
                        "building": "Lincoln Square North",
                        "pickup_point": "F20 12:00 Pickup",
                    },
                ]
            )
            write_json(history, {"records": records, "collection": complete_collection()})
            result = run_script(
                "preference_engine.py", "analyze-history", "--history", history
            )
            analysis = result["analysis"]

            self.assertEqual(len(analysis["completed_dish_affinity"]), 1)
            self.assertEqual(
                analysis["completed_dish_affinity"][0]["dish"], "Known Exact Fish Bowl"
            )
            self.assertEqual(
                analysis["completed_dish_affinity"][0]["completed_count"], 6
            )
            self.assertEqual(analysis["dish_family_affinity"], [])
            self.assertNotIn("proteins", analysis)
            self.assertEqual(
                analysis["history_evidence"]["status_counts"],
                {"completed": 6, "released": 1, "discarded": 1, "other": 0},
            )

    def test_family_requires_two_completed_variants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = root / "history.json"
            records = [
                {
                    "order_id": "a1",
                    "date": "2026-07-01",
                    "meal": "lunch",
                    "dish": "Northern Beef Noodle",
                    "dish_family": "Beef noodle soup",
                    "status": "completed",
                    "building": "Lincoln Square North",
                    "pickup_point": "F20",
                },
                {
                    "order_id": "a2",
                    "date": "2026-07-02",
                    "meal": "lunch",
                    "dish": "Sichuan Beef Noodle",
                    "dish_family": "Beef noodle soup",
                    "status": "completed",
                    "building": "Lincoln Square North",
                    "pickup_point": "F20",
                },
                {
                    "order_id": "a3",
                    "date": "2026-07-03",
                    "meal": "lunch",
                    "dish": "Northern Beef Noodle",
                    "dish_family": "Beef noodle soup",
                    "status": "released",
                    "building": "Lincoln Square North",
                    "pickup_point": "F20",
                },
            ]
            write_json(history, {"records": records, "collection": complete_collection()})
            result = run_script(
                "preference_engine.py", "analyze-history", "--history", history
            )
            family = result["analysis"]["dish_family_affinity"][0]
            self.assertEqual(family["completed_count"], 2)
            self.assertEqual(len(family["variants"]), 2)
            self.assertTrue(family["usable_for_ranking"])

    def test_partial_history_is_valid_and_does_not_block_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = root / "history.json"
            write_json(
                history,
                {
                    "records": [],
                    "collection": {
                        "all_statuses": False,
                        "reached_end": False,
                        "timezone_verified": True,
                        "context": "unknown",
                    },
                },
            )
            result = run_script(
                "preference_engine.py", "analyze-history", "--history", history
            )
            self.assertFalse(
                result["analysis"]["history_evidence"]["collection"]["complete"]
            )
            self.assertTrue(result["warnings"])

    def test_partial_history_cannot_overwrite_complete_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = make_profile(root)
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["history_evidence"]["collection"] = {
                "complete": True,
                "all_statuses": True,
                "reached_end": True,
                "timezone_verified": True,
                "method": "monthly_scroll",
            }
            profile["history_evidence"]["orders_sampled"] = 50
            write_json(profile_path, profile)
            original = profile_path.read_text(encoding="utf-8")
            history = root / "partial.json"
            write_json(
                history,
                {
                    "records": [],
                    "collection": {
                        "all_statuses": False,
                        "reached_end": False,
                        "timezone_verified": True,
                        "context": "unknown",
                    },
                },
            )
            result = run_script(
                "preference_engine.py",
                "analyze-history",
                "--history",
                history,
                "--profile",
                profile_path,
                success=False,
            )
            self.assertNotEqual(result["returncode"], 0)
            self.assertIn("refusing to replace complete history", result["stderr"])
            self.assertEqual(profile_path.read_text(encoding="utf-8"), original)


class RankingAndDeltaTests(unittest.TestCase):
    def test_known_exact_dish_outranks_novel_fish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = make_profile(root)
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["preferences"]["inferred"]["proteins"] = ["fish"]
            profile["preferences"]["inferred"]["completed_dish_affinity"] = [
                {
                    "dish": "Known Exact Fish Bowl",
                    "completed_count": 6,
                    "confidence": "high",
                    "specificity": "exact",
                    "source_period": {
                        "start": "2026-05-01",
                        "end": "2026-07-31",
                        "context": "completed_history",
                    },
                }
            ]
            write_json(profile_path, profile)
            candidates = root / "candidates.json"
            base = {
                "building": "Lincoln Square North",
                "meal": "lunch",
                "pickup_point": "F20",
                "available": True,
                "slot_open": True,
                "existing_order": False,
            }
            write_json(
                candidates,
                {
                    "context": {
                        "building": "Lincoln Square North",
                        "meal": "lunch",
                        "weekday": 2,
                    },
                    "candidates": [
                        {**base, "dish": "Novel Fish Stew", "tags": {"proteins": ["fish"]}},
                        {**base, "dish": "Known Exact Fish Bowl", "tags": {"proteins": ["fish"]}},
                    ],
                },
            )
            result = run_script(
                "preference_engine.py",
                "rank",
                "--profile",
                profile_path,
                "--candidates",
                candidates,
            )
            self.assertEqual(result["ranked"][0]["dish"], "Known Exact Fish Bowl")
            self.assertEqual(result["ranked"][0]["evidence_level"], "repeated_exact")
            novel = result["ranked"][1]
            self.assertTrue(novel["novel"])
            self.assertEqual(novel["quality"], "provisional")
            self.assertEqual(novel["score"], 1)

    def test_explicit_dislike_is_hard_filter_even_with_logistics_fit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = make_profile(root)
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["preferences"]["explicit"]["dislikes"] = [
                {"dish": "Pepper Chicken", "specificity": "exact"}
            ]
            profile["logistics_preferences"]["contextual_pickup_affinity"] = [
                {
                    "building": "Lincoln Square North",
                    "weekday": 2,
                    "meal": "lunch",
                    "pickup_point": "F20",
                    "completed_count": 10,
                    "confidence": "high",
                    "source_period": {
                        "start": "2026-05-01",
                        "end": "2026-07-31",
                        "context": "completed_logistics",
                    },
                }
            ]
            write_json(profile_path, profile)
            candidates = root / "candidates.json"
            write_json(
                candidates,
                {
                    "context": {
                        "building": "Lincoln Square North",
                        "meal": "lunch",
                        "weekday": 2,
                    },
                    "candidates": [
                        {
                            "dish": "Pepper Chicken",
                            "building": "Lincoln Square North",
                            "meal": "lunch",
                            "pickup_point": "F20",
                            "available": True,
                            "slot_open": True,
                            "existing_order": False,
                        }
                    ],
                },
            )
            result = run_script(
                "preference_engine.py",
                "rank",
                "--profile",
                profile_path,
                "--candidates",
                candidates,
            )
            self.assertEqual(result["ranked"], [])
            self.assertIn("explicit_exact_dislike", result["excluded"][0]["excluded_reasons"])

    def test_contextual_pickup_affinity_matches_weekday_meal_and_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = make_profile(root)
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["logistics_preferences"]["contextual_pickup_affinity"] = [
                {
                    "building": "Lincoln Square North",
                    "weekday": 2,
                    "meal": "lunch",
                    "pickup_point": "F20",
                    "time_band": "12:30 - 13:00",
                    "completed_count": 5,
                    "confidence": "high",
                    "source_period": {
                        "start": "2026-05-01",
                        "end": "2026-07-31",
                        "context": "completed_logistics",
                    },
                }
            ]
            write_json(profile_path, profile)
            base = {
                "dish": "Seasonal Bowl",
                "building": "Lincoln Square North",
                "meal": "lunch",
                "pickup_point": "F20",
                "available": True,
                "slot_open": True,
                "existing_order": False,
            }
            candidates = root / "candidates.json"
            write_json(
                candidates,
                {
                    "context": {
                        "building": "Lincoln Square North",
                        "meal": "lunch",
                        "weekday": 2,
                    },
                    "candidates": [
                        {**base, "id": "early", "pickup_time": "11:30 - 12:00"},
                        {**base, "id": "matching", "pickup_time": "12:30 - 13:00"},
                    ],
                },
            )
            result = run_script(
                "preference_engine.py",
                "rank",
                "--profile",
                profile_path,
                "--candidates",
                candidates,
            )
            self.assertEqual(result["ranked"][0]["id"], "matching")
            self.assertIn("contextual_pickup_fit", result["ranked"][0]["reasons"])

    def test_unconfirmed_change_cannot_mutate_profile_and_confirmed_delta_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = make_profile(root)
            original = profile_path.read_text(encoding="utf-8")
            delta = root / "delta.json"
            write_json(
                delta,
                {
                    "event_id": "swap-1",
                    "kind": "dislike",
                    "dish": "Pepper Chicken",
                    "confirmed_by_user": False,
                },
            )
            result = run_script(
                "preference_engine.py",
                "apply-delta",
                "--profile",
                profile_path,
                "--delta",
                delta,
                success=False,
            )
            self.assertNotEqual(result["returncode"], 0)
            self.assertEqual(profile_path.read_text(encoding="utf-8"), original)

            value = json.loads(delta.read_text(encoding="utf-8"))
            value["confirmed_by_user"] = True
            write_json(delta, value)
            first = run_script(
                "preference_engine.py",
                "apply-delta",
                "--profile",
                profile_path,
                "--delta",
                delta,
            )
            second = run_script(
                "preference_engine.py",
                "apply-delta",
                "--profile",
                profile_path,
                "--delta",
                delta,
            )
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            self.assertTrue(first["changed"])
            self.assertEqual(second["status"], "already_applied")
            self.assertEqual(len(profile["preferences"]["explicit"]["dislikes"]), 1)

    def test_summary_exposes_preferences_and_usage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile_path = make_profile(Path(directory))
            result = run_script(
                "preference_engine.py", "summarize", "--profile", profile_path
            )
            self.assertEqual(result["preference_confidence"], "limited")
            self.assertIn("查看我的订餐偏好", result["usage"])

    def test_forgotten_dish_is_not_reintroduced_by_history_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = make_profile(root)
            delta = root / "forget.json"
            write_json(
                delta,
                {
                    "event_id": "forget-1",
                    "kind": "forget_dish",
                    "dish": "Roast Chicken",
                    "confirmed_by_user": True,
                },
            )
            run_script(
                "preference_engine.py",
                "apply-delta",
                "--profile",
                profile_path,
                "--delta",
                delta,
            )
            history = root / "history.json"
            write_json(
                history,
                {
                    "records": [
                        {
                            "order_id": "old-1",
                            "date": "2026-07-01",
                            "meal": "lunch",
                            "dish": "Roast Chicken",
                            "status": "completed",
                            "building": "Lincoln Square North",
                            "pickup_point": "F20",
                        }
                    ],
                    "collection": complete_collection(),
                },
            )
            run_script(
                "preference_engine.py",
                "analyze-history",
                "--history",
                history,
                "--profile",
                profile_path,
            )
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            self.assertEqual(
                profile["preferences"]["inferred"]["completed_dish_affinity"],
                [],
            )
            self.assertEqual(
                profile["preference_learning"]["forgotten_dishes"],
                ["Roast Chicken"],
            )


class PortabilityTests(unittest.TestCase):
    def test_unsupported_building_stops_before_creating_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = run_script(
                "bootstrap_profile.py",
                "--building",
                "Unsupported Test Building",
                "--timezone",
                "America/Los_Angeles",
                "--data-dir",
                root,
                success=False,
            )
            self.assertEqual(result["returncode"], 2)
            payload = json.loads(result["stdout"])
            self.assertEqual(payload["status"], "unsupported_building")
            self.assertFalse(payload["transaction_attempted"])
            self.assertFalse((root / "profile.json").exists())

    def test_diagnostic_contains_no_profile_path_or_personal_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = make_profile(root)
            output = root / "diagnostic.json"
            run_script(
                "generate_diagnostic.py",
                "--profile",
                profile_path,
                "--browser-state",
                "available",
                "--login-state",
                "logged_out",
                "--page-state",
                "unknown",
                "--stage",
                "readiness",
                "--error-code",
                "LOGIN_REQUIRED",
                "--plugin-version",
                "test",
                "--output",
                output,
            )
            report_text = output.read_text(encoding="utf-8")
            report = json.loads(report_text)
            self.assertNotIn(str(root), report_text)
            self.assertFalse(report["privacy"]["contains_orders"])
            self.assertFalse(report["privacy"]["contains_preferences"])
            self.assertEqual(report["environment"]["profile"]["schema_version"], 5)


class FreshUserFlowTests(unittest.TestCase):
    def test_blank_user_can_bootstrap_answer_one_question_and_rank(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            created = run_script(
                "bootstrap_profile.py",
                "--building",
                "Lincoln Square North",
                "--timezone",
                "America/Los_Angeles",
                "--data-dir",
                root,
            )
            profile_path = Path(created["profile_path"])
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

            history = root / "partial-history.json"
            write_json(
                history,
                {
                    "records": [],
                    "collection": {
                        "all_statuses": False,
                        "reached_end": False,
                        "timezone_verified": True,
                        "context": "new_user",
                    },
                },
            )
            analysis = run_script(
                "preference_engine.py",
                "analyze-history",
                "--history",
                history,
                "--profile",
                profile_path,
            )
            self.assertTrue(analysis["profile_updated"])
            self.assertTrue(analysis["warnings"])

            delta = root / "cold-start-answer.json"
            write_json(
                delta,
                {
                    "event_id": "cold-start-1",
                    "kind": "like",
                    "dish": "Roast Chicken",
                    "confirmed_by_user": True,
                },
            )
            run_script(
                "preference_engine.py",
                "apply-delta",
                "--profile",
                profile_path,
                "--delta",
                delta,
            )
            candidates = root / "candidates.json"
            base = {
                "building": "Lincoln Square North",
                "meal": "lunch",
                "pickup_point": "F20",
                "available": True,
                "slot_open": True,
                "existing_order": False,
            }
            write_json(
                candidates,
                {
                    "context": {
                        "building": "Lincoln Square North",
                        "meal": "lunch",
                        "weekday": 2,
                    },
                    "candidates": [
                        {**base, "dish": "New Seasonal Bowl"},
                        {**base, "dish": "Roast Chicken"},
                    ],
                },
            )
            ranking = run_script(
                "preference_engine.py",
                "rank",
                "--profile",
                profile_path,
                "--candidates",
                candidates,
            )
            self.assertEqual(ranking["ranked"][0]["dish"], "Roast Chicken")
            self.assertEqual(ranking["ranked"][0]["quality"], "preferred")
            self.assertTrue(ranking["ranked"][1]["requires_confirmation_as_novel"])


if __name__ == "__main__":
    unittest.main()
