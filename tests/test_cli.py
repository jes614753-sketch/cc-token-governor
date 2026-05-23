"""CLI integration tests."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "waste_session.jsonl"
CLI = [sys.executable, "-m", "cc_token_governor.cli"]


class CliAuditTests(unittest.TestCase):
    def test_audit_json_output(self):
        result = subprocess.run(
            CLI + ["audit", "--path", str(FIXTURE), "--json"],
            capture_output=True, text=True, cwd=str(ROOT / "src"),
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertIn("findings", data)
        self.assertIn("tool_calls", data)

    def test_audit_to_file(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            out = f.name
        result = subprocess.run(
            CLI + ["audit", "--path", str(FIXTURE), "--output", out],
            capture_output=True, text=True, cwd=str(ROOT / "src"),
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads(Path(out).read_text(encoding="utf-8"))
        self.assertIn("findings", data)

    def test_compile_policy(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            audit_out = f.name
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            policy_out = f.name

        subprocess.run(
            CLI + ["audit", "--path", str(FIXTURE), "--output", audit_out],
            capture_output=True, text=True, cwd=str(ROOT / "src"),
        )
        result = subprocess.run(
            CLI + ["compile-policy", "--input", audit_out, "--output", policy_out],
            capture_output=True, text=True, cwd=str(ROOT / "src"),
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads(Path(policy_out).read_text(encoding="utf-8"))
        self.assertIn("policies", data)
        self.assertTrue(len(data["policies"]) > 0)


class CliLearnTests(unittest.TestCase):
    def test_learn_and_suggest(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "rules.sqlite")
            result = subprocess.run(
                CLI + ["learn", "test correction", "--db", db, "--project", "."],
                capture_output=True, text=True, cwd=str(ROOT / "src"),
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("Learned rule", result.stdout)

            result = subprocess.run(
                CLI + ["suggest", "--prompt", "test", "--db", db, "--project", "."],
                capture_output=True, text=True, cwd=str(ROOT / "src"),
            )
            self.assertEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertIn("rules", data)


if __name__ == "__main__":
    unittest.main()
