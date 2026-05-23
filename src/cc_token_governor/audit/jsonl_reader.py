"""JSONL session reader with schema version detection and graceful degradation."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from cc_token_governor.models import ToolCall

logger = logging.getLogger(__name__)

PROJECTS_DIR = Path.home() / ".claude" / "projects"

# Known schema versions and their entry structure markers.
# v1 (current): entries have "type" field ("assistant", "user"), "message" with "content" blocks.
SCHEMA_V1_MARKERS = {"type", "message"}


def _detect_schema_version(entries: list[dict[str, Any]]) -> str:
    """Detect the JSONL schema version from a sample of entries.

    Returns: "v1", "v2", or "unknown".
    """
    if not entries:
        return "unknown"

    sample = entries[:5]
    for entry in sample:
        keys = set(entry.keys())
        if keys >= SCHEMA_V1_MARKERS:
            return "v1"
        # Future: add v2 markers here

    return "unknown"


def iter_jsonl_files(path: str | Path | None = None) -> list[Path]:
    root = Path(path) if path else PROJECTS_DIR
    if root.is_file():
        return [root]
    if not root.exists():
        return []
    return sorted(
        p for p in root.rglob("*.jsonl")
        if "subagents" not in p.parts and "tool-results" not in p.parts
    )


def read_tool_calls(path: str | Path | None = None) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for file_path in iter_jsonl_files(path):
        calls.extend(read_session_tool_calls(file_path))
    return calls


def _parse_entries(jsonl_path: Path) -> list[dict[str, Any]]:
    """Parse all valid JSON lines from a file, skipping corrupt lines."""
    entries = []
    with open(jsonl_path, "r", encoding="utf-8") as handle:
        for line_num, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                logger.debug("Skipping invalid JSON at %s:%d", jsonl_path, line_num)
                continue
    return entries


def read_session_tool_calls(jsonl_path: Path) -> list[ToolCall]:
    """Read tool calls from a JSONL session file with version detection."""
    entries = _parse_entries(jsonl_path)
    version = _detect_schema_version(entries)

    if version == "v1":
        return _read_v1(jsonl_path, entries)
    elif version == "unknown":
        logger.warning(
            "Unknown JSONL schema in %s — attempting v1 fallback. "
            "Results may be incomplete. Consider updating cc-token-governor.",
            jsonl_path,
        )
        return _read_v1(jsonl_path, entries)

    return []


def _read_v1(jsonl_path: Path, entries: list[dict[str, Any]]) -> list[ToolCall]:
    """Parse tool calls from v1 schema entries."""
    session_id = jsonl_path.stem
    tool_uses: dict[str, dict[str, Any]] = {}
    tool_results: dict[str, dict[str, Any]] = {}

    for entry in entries:
        if entry.get("type") == "assistant" and not entry.get("isSidechain"):
            message = entry.get("message", {})
            for block in message.get("content", []) or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_uses[block.get("id", "")] = {
                        "name": block.get("name", ""),
                        "input": block.get("input", {}) or {},
                        "timestamp": entry.get("timestamp", ""),
                    }

        elif entry.get("type") == "user":
            message = entry.get("message", {})
            content = message.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tool_results[block.get("tool_use_id", "")] = {
                        "content": block.get("content", []),
                        "is_error": bool(block.get("is_error", False)),
                        "timestamp": entry.get("timestamp", ""),
                        "toolUseResult": block.get("toolUseResult", {}),
                    }

    calls: list[ToolCall] = []
    for tool_use_id, use in tool_uses.items():
        result = tool_results.get(tool_use_id, {})
        tool_input = use.get("input", {}) or {}
        result_content = result.get("content", [])
        command = tool_input.get("command") if use.get("name") in ("Bash", "PowerShell") else None
        file_path = tool_input.get("file_path")
        status, exit_code = infer_status(result_content, result.get("is_error", False), use.get("name", ""))

        calls.append(ToolCall(
            session_id=session_id,
            tool_use_id=tool_use_id,
            tool_name=use.get("name", ""),
            timestamp_start=use.get("timestamp", ""),
            timestamp_end=result.get("timestamp", ""),
            duration_ms_estimated=estimate_duration_ms(use.get("timestamp", ""), result.get("timestamp", "")),
            tool_input_size_bytes=len(json.dumps(tool_input, ensure_ascii=False).encode("utf-8")),
            tool_result_size_bytes=content_size(result_content),
            file_path=file_path,
            file_name=Path(file_path).name if file_path else None,
            file_extension=(Path(file_path).suffix.lstrip(".").lower() or None) if file_path else None,
            bash_command_text=command,
            bash_command_hash=hash_text(command) if command else None,
            tool_status=status,
            exit_code=exit_code,
            is_error=bool(result.get("is_error", False)),
        ))
    return calls


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def estimate_duration_ms(start: str, end: str) -> int:
    start_dt = parse_timestamp(start)
    end_dt = parse_timestamp(end)
    if not start_dt or not end_dt:
        return 0
    return max(int((end_dt - start_dt).total_seconds() * 1000), 0)


def content_size(content: Any) -> int:
    if content is None:
        return 0
    if isinstance(content, str):
        return len(content.encode("utf-8"))
    total = 0
    if isinstance(content, list):
        for item in content:
            if isinstance(item, str):
                total += len(item.encode("utf-8"))
            elif isinstance(item, dict):
                if item.get("type") == "text":
                    total += len(str(item.get("text", "")).encode("utf-8"))
                elif item.get("type") == "image":
                    total += len(str(item.get("source", {}).get("data", "")).encode("utf-8"))
    return total


def infer_status(content: Any, is_error: bool, tool_name: str) -> tuple[str, int | None]:
    text = content_to_text(content)
    exit_code = None
    match = re.search(r"Exit code\s+(-?\d+)", text, flags=re.IGNORECASE)
    if match:
        exit_code = int(match.group(1))
    if "timed out" in text.lower() or "timeout" in text.lower():
        return "timeout", exit_code
    if is_error or (exit_code is not None and exit_code != 0):
        return "failed", exit_code
    if tool_name in ("Bash", "PowerShell", "Read", "Edit", "Write", "MultiEdit"):
        return "success", exit_code
    return "unknown", exit_code


def content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(parts)
    return ""
