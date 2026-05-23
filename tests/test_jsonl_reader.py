"""Tests for JSONL reader — including edge cases and version detection."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cc_token_governor.audit.jsonl_reader import (
    content_size,
    content_to_text,
    estimate_duration_ms,
    infer_status,
    read_session_tool_calls,
    read_tool_calls,
)


class JsonlReaderEdgeCases(unittest.TestCase):
    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("")
            path = Path(f.name)
        calls = read_session_tool_calls(path)
        self.assertEqual(calls, [])

    def test_corrupted_json_lines(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("not valid json\n")
            f.write("{}\n")
            f.write("also bad\n")
            path = Path(f.name)
        calls = read_session_tool_calls(path)
        self.assertEqual(calls, [])

    def test_mixed_valid_and_invalid(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({
                "type": "assistant",
                "timestamp": "2026-05-23T10:00:00Z",
                "message": {"id": "m1", "content": [
                    {"type": "tool_use", "id": "r1", "name": "Read", "input": {"file_path": "a.py"}}
                ]}
            }) + "\n")
            f.write("GARBAGE\n")
            f.write(json.dumps({
                "type": "user",
                "timestamp": "2026-05-23T10:00:01Z",
                "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "r1", "content": [{"type": "text", "text": "ok"}]}
                ]}
            }) + "\n")
            path = Path(f.name)
        calls = read_session_tool_calls(path)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].tool_name, "Read")

    def test_nonexistent_path(self):
        calls = read_tool_calls("/nonexistent/path/that/doesnt/exist")
        self.assertEqual(calls, [])

    def test_sidechain_entries_skipped(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({
                "type": "assistant",
                "isSidechain": True,
                "timestamp": "2026-05-23T10:00:00Z",
                "message": {"id": "m1", "content": [
                    {"type": "tool_use", "id": "r1", "name": "Read", "input": {"file_path": "a.py"}}
                ]}
            }) + "\n")
            path = Path(f.name)
        calls = read_session_tool_calls(path)
        self.assertEqual(len(calls), 0)


class ContentHelpersTests(unittest.TestCase):
    def test_content_size_none(self):
        self.assertEqual(content_size(None), 0)

    def test_content_size_string(self):
        self.assertEqual(content_size("hello"), 5)

    def test_content_size_list(self):
        content = [{"type": "text", "text": "hello"}]
        self.assertEqual(content_size(content), 5)

    def test_content_to_text_string(self):
        self.assertEqual(content_to_text("hello"), "hello")

    def test_content_to_text_list(self):
        content = [{"type": "text", "text": "line1"}, {"type": "text", "text": "line2"}]
        self.assertIn("line1", content_to_text(content))
        self.assertIn("line2", content_to_text(content))

    def test_content_to_text_none(self):
        self.assertEqual(content_to_text(None), "")


class InferStatusTests(unittest.TestCase):
    def test_success(self):
        status, code = infer_status([{"type": "text", "text": "ok"}], False, "Bash")
        self.assertEqual(status, "success")

    def test_failed_by_is_error(self):
        status, code = infer_status("output", True, "Bash")
        self.assertEqual(status, "failed")

    def test_failed_by_exit_code(self):
        status, code = infer_status([{"type": "text", "text": "Exit code 1"}], False, "Bash")
        self.assertEqual(status, "failed")
        self.assertEqual(code, 1)

    def test_timeout(self):
        status, code = infer_status([{"type": "text", "text": "timed out"}], False, "Bash")
        self.assertEqual(status, "timeout")

    def test_unknown_tool(self):
        status, code = infer_status("ok", False, "SomeUnknownTool")
        self.assertEqual(status, "unknown")


class DurationEstimationTests(unittest.TestCase):
    def test_valid_timestamps(self):
        ms = estimate_duration_ms("2026-05-23T10:00:00Z", "2026-05-23T10:00:01Z")
        self.assertEqual(ms, 1000)

    def test_empty_timestamps(self):
        self.assertEqual(estimate_duration_ms("", ""), 0)
        self.assertEqual(estimate_duration_ms("2026-05-23T10:00:00Z", ""), 0)


if __name__ == "__main__":
    unittest.main()
