"""Tests for policy evaluator."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cc_token_governor.models import Policy
from cc_token_governor.policy.evaluator import PolicyEvaluator, _match_trigger


class MatchTriggerTests(unittest.TestCase):
    def test_tool_name_string_match(self):
        trigger = {"tool_name": "Read"}
        self.assertTrue(_match_trigger(trigger, "Read", {}, {}))
        self.assertFalse(_match_trigger(trigger, "Bash", {}, {}))

    def test_tool_name_list_match(self):
        trigger = {"tool_name": ["Bash", "PowerShell"]}
        self.assertTrue(_match_trigger(trigger, "Bash", {}, {}))
        self.assertTrue(_match_trigger(trigger, "PowerShell", {}, {}))
        self.assertFalse(_match_trigger(trigger, "Read", {}, {}))

    def test_gte_threshold(self):
        trigger = {"tool_name": "Read", "same_file_read_count_gte": 2}
        self.assertFalse(_match_trigger(trigger, "Read", {}, {"same_file_read_count": 1}))
        self.assertTrue(_match_trigger(trigger, "Read", {}, {"same_file_read_count": 2}))
        self.assertTrue(_match_trigger(trigger, "Read", {}, {"same_file_read_count": 5}))

    def test_boolean_flag(self):
        trigger = {"tool_name": ["Bash"], "risky_output_command": True}
        self.assertTrue(_match_trigger(trigger, "Bash", {}, {"risky_output_command": True}))
        self.assertFalse(_match_trigger(trigger, "Bash", {}, {"risky_output_command": False}))
        self.assertFalse(_match_trigger(trigger, "Bash", {}, {}))

    def test_multiple_conditions(self):
        trigger = {"tool_name": ["Edit", "Write"], "tool_input_size_bytes_gte": 20000}
        self.assertTrue(_match_trigger(trigger, "Edit", {}, {"tool_input_size_bytes": 25000}))
        self.assertFalse(_match_trigger(trigger, "Edit", {}, {"tool_input_size_bytes": 1000}))


class PolicyEvaluatorTests(unittest.TestCase):
    def test_empty_policies_approve(self):
        evaluator = PolicyEvaluator([])
        result = evaluator.evaluate("Read", {"file_path": "x.py"}, {})
        self.assertEqual(result["decision"], "approve")

    def test_matching_policy_returns_decision(self):
        policy = Policy(
            id="test-rule",
            trigger={"tool_name": "Read", "same_file_read_count_gte": 2},
            action="warn",
            message="Already read.",
        )
        evaluator = PolicyEvaluator([policy])
        result = evaluator.evaluate("Read", {"file_path": "x.py"}, {"same_file_read_count": 3})
        self.assertEqual(result["decision"], "warn")
        self.assertEqual(result["policy_id"], "test-rule")

    def test_no_match_returns_approve(self):
        policy = Policy(
            id="test-rule",
            trigger={"tool_name": "Read", "same_file_read_count_gte": 2},
            action="warn",
            message="Already read.",
        )
        evaluator = PolicyEvaluator([policy])
        result = evaluator.evaluate("Bash", {"command": "ls"}, {})
        self.assertEqual(result["decision"], "approve")

    def test_first_matching_policy_wins(self):
        p1 = Policy(id="rule-1", trigger={"tool_name": "Read"}, action="warn", message="first")
        p2 = Policy(id="rule-2", trigger={"tool_name": "Read"}, action="block", message="second")
        evaluator = PolicyEvaluator([p1, p2])
        result = evaluator.evaluate("Read", {}, {})
        self.assertEqual(result["policy_id"], "rule-1")

    def test_from_file_round_trip(self):
        policies = [
            Policy(id="p1", trigger={"tool_name": "Read"}, action="warn", message="m1"),
            Policy(id="p2", trigger={"tool_name": "Bash"}, action="block", message="m2"),
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"schema_version": 1, "policies": [p.to_dict() for p in policies]}, f)
            path = f.name

        evaluator = PolicyEvaluator.from_file(path)
        self.assertEqual(len(evaluator.policies), 2)
        self.assertEqual(evaluator.policies[0].id, "p1")

    def test_from_file_missing_returns_empty(self):
        evaluator = PolicyEvaluator.from_file("/nonexistent/path.json")
        self.assertEqual(len(evaluator.policies), 0)

    def test_from_defaults_loads_builtin(self):
        evaluator = PolicyEvaluator.from_defaults()
        ids = {p.id for p in evaluator.policies}
        self.assertIn("avoid-repeated-read", ids)
        self.assertIn("stop-death-loop", ids)


if __name__ == "__main__":
    unittest.main()
