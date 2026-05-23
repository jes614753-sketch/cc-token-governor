"""Tests for diagnosis sniffers — edge cases and boundary conditions."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cc_token_governor.diagnosis.sniffers import (
    classify_toxic,
    find_bloated_output,
    find_death_loops,
    find_large_edits,
    find_repeated_reads,
    find_toxic_files,
)
from cc_token_governor.models import ToolCall


def _make_call(**kwargs) -> ToolCall:
    defaults = {
        "session_id": "s1",
        "tool_use_id": "u1",
        "tool_name": "Read",
        "tool_result_size_bytes": 0,
        "tool_input_size_bytes": 0,
    }
    defaults.update(kwargs)
    return ToolCall(**defaults)


class RepeatedReadsTests(unittest.TestCase):
    def test_single_read_no_finding(self):
        calls = [_make_call(tool_name="Read", file_path="a.py")]
        self.assertEqual(find_repeated_reads(calls), [])

    def test_two_reads_finds(self):
        calls = [
            _make_call(tool_name="Read", file_path="a.py", tool_use_id="u1", tool_result_size_bytes=100),
            _make_call(tool_name="Read", file_path="a.py", tool_use_id="u2", tool_result_size_bytes=100),
        ]
        findings = find_repeated_reads(calls)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].category, "repeated_read")

    def test_different_files_no_finding(self):
        calls = [
            _make_call(tool_name="Read", file_path="a.py", tool_use_id="u1"),
            _make_call(tool_name="Read", file_path="b.py", tool_use_id="u2"),
        ]
        self.assertEqual(find_repeated_reads(calls), [])

    def test_non_read_ignored(self):
        calls = [
            _make_call(tool_name="Bash", file_path="a.py", tool_use_id="u1"),
            _make_call(tool_name="Bash", file_path="a.py", tool_use_id="u2"),
        ]
        self.assertEqual(find_repeated_reads(calls), [])


class ToxicFilesTests(unittest.TestCase):
    def test_node_modules(self):
        self.assertEqual(classify_toxic("node_modules/lodash/index.js"), "dependency")

    def test_lockfile(self):
        self.assertEqual(classify_toxic("package-lock.json"), "lockfile")

    def test_binary(self):
        self.assertEqual(classify_toxic("image.png"), "binary_or_media")

    def test_normal_file(self):
        self.assertIsNone(classify_toxic("src/app.py"))

    def test_build_output(self):
        self.assertEqual(classify_toxic("dist/bundle.js"), "build_output")

    def test_git_dir(self):
        self.assertEqual(classify_toxic(".git/config"), "vcs")

    def test_backslash_normalization(self):
        self.assertEqual(classify_toxic("node_modules\\lodash\\index.js"), "dependency")


class BloatedOutputTests(unittest.TestCase):
    def test_small_output_no_finding(self):
        calls = [_make_call(tool_name="Bash", tool_result_size_bytes=1000)]
        self.assertEqual(find_bloated_output(calls), [])

    def test_large_output_finds(self):
        calls = [_make_call(tool_name="Bash", tool_result_size_bytes=25000, bash_command_text="cat big.log")]
        findings = find_bloated_output(calls)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "high")

    def test_critical_output(self):
        calls = [_make_call(tool_name="Bash", tool_result_size_bytes=150000)]
        findings = find_bloated_output(calls)
        self.assertEqual(findings[0].severity, "critical")

    def test_non_bash_ignored(self):
        calls = [_make_call(tool_name="Read", tool_result_size_bytes=50000)]
        self.assertEqual(find_bloated_output(calls), [])


class DeathLoopTests(unittest.TestCase):
    def test_three_consecutive_failures(self):
        calls = [
            _make_call(tool_name="Bash", bash_command_hash="abc", tool_status="failed", session_id="s1", tool_use_id="u1", tool_result_size_bytes=100),
            _make_call(tool_name="Bash", bash_command_hash="abc", tool_status="failed", session_id="s1", tool_use_id="u2", tool_result_size_bytes=100),
            _make_call(tool_name="Bash", bash_command_hash="abc", tool_status="failed", session_id="s1", tool_use_id="u3", tool_result_size_bytes=100),
        ]
        findings = find_death_loops(calls)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].category, "death_loop")

    def test_two_failures_no_finding(self):
        calls = [
            _make_call(tool_name="Bash", bash_command_hash="abc", tool_status="failed", session_id="s1", tool_use_id="u1"),
            _make_call(tool_name="Bash", bash_command_hash="abc", tool_status="failed", session_id="s1", tool_use_id="u2"),
        ]
        self.assertEqual(find_death_loops(calls), [])

    def test_mixed_commands_no_loop(self):
        calls = [
            _make_call(tool_name="Bash", bash_command_hash="abc", tool_status="failed", session_id="s1", tool_use_id="u1"),
            _make_call(tool_name="Bash", bash_command_hash="def", tool_status="failed", session_id="s1", tool_use_id="u2"),
            _make_call(tool_name="Bash", bash_command_hash="abc", tool_status="failed", session_id="s1", tool_use_id="u3"),
        ]
        self.assertEqual(find_death_loops(calls), [])


class LargeEditsTests(unittest.TestCase):
    def test_small_edit_no_finding(self):
        calls = [_make_call(tool_name="Edit", tool_input_size_bytes=100)]
        self.assertEqual(find_large_edits(calls), [])

    def test_large_edit_finds(self):
        calls = [_make_call(tool_name="Edit", tool_input_size_bytes=25000, file_path="a.py")]
        findings = find_large_edits(calls)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].category, "large_edit")

    def test_write_included(self):
        calls = [_make_call(tool_name="Write", tool_input_size_bytes=25000)]
        findings = find_large_edits(calls)
        self.assertEqual(len(findings), 1)


if __name__ == "__main__":
    unittest.main()
