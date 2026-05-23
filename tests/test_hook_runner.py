"""End-to-end tests for hook_runner — Claude Code hook format output."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cc_token_governor.runtime.hook_runner import (
    run_post_tool_use,
    run_pre_tool_use,
    run_user_prompt_submit,
)


class PreToolUsePolicyDrivenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state = str(Path(self.tmp) / "state.sqlite")

    def test_first_read_allows(self):
        result = run_pre_tool_use(
            {"session_id": "s1", "tool_name": "Read", "tool_input": {"file_path": "a.py"}},
            state_path=self.state,
        )
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "allow")
        self.assertNotIn("additionalContext", result["hookSpecificOutput"])

    def test_second_read_warns_via_additional_context(self):
        payload = {"session_id": "s1", "tool_name": "Read", "tool_input": {"file_path": "a.py"}}
        run_pre_tool_use(payload, state_path=self.state)
        result = run_pre_tool_use(payload, state_path=self.state)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "allow")
        self.assertIn("additionalContext", result["hookSpecificOutput"])
        self.assertIn("already read", result["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(result["policy_id"], "avoid-repeated-read")

    def test_different_files_both_allow(self):
        run_pre_tool_use(
            {"session_id": "s1", "tool_name": "Read", "tool_input": {"file_path": "a.py"}},
            state_path=self.state,
        )
        result = run_pre_tool_use(
            {"session_id": "s1", "tool_name": "Read", "tool_input": {"file_path": "b.py"}},
            state_path=self.state,
        )
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "allow")

    def test_death_loop_denies_on_third_attempt(self):
        payload = {"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "npm run build"}}
        result_payload = {**payload, "tool_result": "Exit code 1\nfail"}

        run_post_tool_use(result_payload, state_path=self.state)
        run_post_tool_use(result_payload, state_path=self.state)

        result = run_pre_tool_use(payload, state_path=self.state)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("permissionDecisionReason", result["hookSpecificOutput"])
        self.assertEqual(result["policy_id"], "stop-death-loop")

    def test_risky_output_warns_via_additional_context(self):
        result = run_pre_tool_use(
            {"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "cat giant.log"}},
            state_path=self.state,
        )
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "allow")
        self.assertIn("additionalContext", result["hookSpecificOutput"])
        self.assertEqual(result["policy_id"], "cap-bash-output")

    def test_guarded_command_no_risky_warn(self):
        result = run_pre_tool_use(
            {"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "cat giant.log | head -20"}},
            state_path=self.state,
        )
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "allow")
        self.assertNotIn("additionalContext", result["hookSpecificOutput"])

    def test_large_edit_warns_via_additional_context(self):
        big_input = {"file_path": "a.py", "old_string": "x", "new_string": "y" * 25000}
        result = run_pre_tool_use(
            {"session_id": "s1", "tool_name": "Edit", "tool_input": big_input},
            state_path=self.state,
        )
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "allow")
        self.assertIn("additionalContext", result["hookSpecificOutput"])
        self.assertEqual(result["policy_id"], "avoid-large-edit")

    def test_small_edit_allows(self):
        result = run_pre_tool_use(
            {"session_id": "s1", "tool_name": "Edit", "tool_input": {"old_string": "x", "new_string": "y"}},
            state_path=self.state,
        )
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "allow")

    def test_custom_policy_overrides_defaults(self):
        custom_policy = {
            "schema_version": 1,
            "policies": [{
                "id": "block-all-reads",
                "trigger": {"tool_name": "Read"},
                "action": "block",
                "message": "No reads allowed.",
                "confidence": "high",
            }],
        }
        policy_path = Path(self.tmp) / "custom-policy.json"
        policy_path.write_text(json.dumps(custom_policy), encoding="utf-8")

        result = run_pre_tool_use(
            {"session_id": "s1", "tool_name": "Read", "tool_input": {"file_path": "a.py"}},
            policy_path=str(policy_path),
            state_path=self.state,
        )
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(result["policy_id"], "block-all-reads")

    def test_hook_event_name_is_pre_tool_use(self):
        result = run_pre_tool_use(
            {"session_id": "s1", "tool_name": "Read", "tool_input": {"file_path": "a.py"}},
            state_path=self.state,
        )
        self.assertEqual(result["hookSpecificOutput"]["hookEventName"], "PreToolUse")


class PostToolUseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state = str(Path(self.tmp) / "state.sqlite")

    def test_records_failed_command_returns_empty(self):
        payload = {
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "npm run build"},
            "tool_result": "Exit code 1\nfail",
        }
        result = run_post_tool_use(payload, state_path=self.state)
        self.assertEqual(result, {})

    def test_records_success_clears_failure(self):
        fail_payload = {
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "npm run build"},
            "tool_result": "Exit code 1\nfail",
        }
        success_payload = {
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "npm run build"},
            "tool_result": "ok",
        }
        run_post_tool_use(fail_payload, state_path=self.state)
        run_post_tool_use(success_payload, state_path=self.state)
        # After success, the failure counter should be cleared
        result = run_pre_tool_use(
            {"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "npm run build"}},
            state_path=self.state,
        )
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "allow")


class UserPromptSubmitTests(unittest.TestCase):
    def test_no_rules_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "rules.sqlite")
            result = run_user_prompt_submit({"prompt": "hello"}, db_path=db)
            self.assertEqual(result, {})

    def test_injects_learned_rules_in_hook_specific_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "rules.sqlite")
            from cc_token_governor.learning.store import LearningStore
            store = LearningStore(db)
            store.learn("use targeted patches", project_root=".")

            result = run_user_prompt_submit({"prompt": "fix the patch"}, db_path=db)
            self.assertIn("hookSpecificOutput", result)
            self.assertEqual(result["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
            self.assertIn("additionalContext", result["hookSpecificOutput"])
            self.assertIn("targeted patches", result["hookSpecificOutput"]["additionalContext"])


if __name__ == "__main__":
    unittest.main()
