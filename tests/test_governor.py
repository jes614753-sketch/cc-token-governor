import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cc_token_governor.audit.jsonl_reader import read_tool_calls
from cc_token_governor.diagnosis.sniffers import audit_tool_calls
from cc_token_governor.learning.store import LearningStore
from cc_token_governor.policy.compiler import compile_policies
from cc_token_governor.runtime.hook_runner import run_post_tool_use, run_pre_tool_use


ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "fixtures" / "waste_session.jsonl"


class GovernorTests(unittest.TestCase):
    def test_audit_finds_core_waste_patterns(self):
        calls = read_tool_calls(FIXTURE)
        findings = audit_tool_calls(calls)
        categories = {finding.category for finding in findings}

        self.assertIn("repeated_read", categories)
        self.assertIn("death_loop", categories)
        self.assertIn("bloated_output", categories)
        self.assertIn("large_edit", categories)

    def test_policy_compiler_includes_mvp_policies(self):
        findings = audit_tool_calls(read_tool_calls(FIXTURE))
        policies = compile_policies(findings)
        ids = {policy.id for policy in policies}

        self.assertIn("avoid-repeated-read", ids)
        self.assertIn("stop-death-loop", ids)
        self.assertIn("avoid-large-edit", ids)
        self.assertIn("cap-bash-output", ids)

    def test_pre_tool_use_warns_on_repeated_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = str(Path(tmp) / "state.json")
            payload = {
                "session_id": "s1",
                "tool_name": "Read",
                "tool_input": {"file_path": "src/app.py"},
            }

            first = run_pre_tool_use(payload, state_path=state)
            second = run_pre_tool_use(payload, state_path=state)

        self.assertEqual(first["decision"], "approve")
        self.assertIn("additionalContext", second)
        self.assertIn("already read", second["additionalContext"])

    def test_pre_tool_use_blocks_third_failed_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = str(Path(tmp) / "state.json")
            result_payload = {
                "session_id": "s1",
                "tool_name": "Bash",
                "tool_input": {"command": "npm run build"},
                "tool_result": "Exit code 1\nboom",
            }
            run_post_tool_use(result_payload, state_path=state)
            run_post_tool_use(result_payload, state_path=state)

            decision = run_pre_tool_use({
                "session_id": "s1",
                "tool_name": "Bash",
                "tool_input": {"command": "npm run build"},
            }, state_path=state)

        self.assertEqual(decision["decision"], "block")

    def test_learning_store_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "rules.sqlite")
            store = LearningStore(db)
            store.learn("不要全量重写文件，优先使用局部 patch", project_root=".")
            rules = store.suggest("修复测试时怎么编辑文件", project_root=".", limit=3)

        self.assertTrue(rules)
        self.assertIn("局部 patch", rules[0]["correction"])


if __name__ == "__main__":
    unittest.main()
