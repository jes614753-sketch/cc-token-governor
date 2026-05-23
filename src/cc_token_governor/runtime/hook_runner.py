from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from cc_token_governor.learning.store import LearningStore
from cc_token_governor.policy.compiler import load_policy_file
from cc_token_governor.runtime.state import StateStore


def run_pre_tool_use(
    payload: dict[str, Any],
    policy_path: str | Path | None = None,
    state_path: str | Path | None = None,
) -> dict[str, Any]:
    load_policy_file(policy_path)  # Load now to validate policy file; MVP uses default policy semantics.
    state = StateStore(state_path)
    tool_name, tool_input = extract_tool(payload)
    session_id = extract_session_id(payload)

    if tool_name == "Read":
        file_path = tool_input.get("file_path", "")
        if file_path:
            count = state.read_count(session_id, file_path)
            state.record_read(session_id, file_path)
            if count >= 1:
                decision = {
                    "decision": "approve",
                    "additionalContext": (
                        f"{file_path} was already read {count} time(s) in this session. "
                        "Reuse existing context unless it changed or exact line numbers are needed."
                    ),
                    "reason": "Repeated file read warning.",
                }
                state.record_event({"type": "warn", "policy": "avoid-repeated-read", "file_path": file_path})
                return decision

    if tool_name in ("Bash", "PowerShell"):
        command = tool_input.get("command", "")
        command_hash = hash_text(command) if command else ""
        if command_hash:
            failed_count = state.failed_command_count(session_id, command_hash)
            if failed_count >= 2:
                decision = {
                    "decision": "block",
                    "reason": "The same command has already failed twice.",
                    "additionalContext": (
                        f"Recent failing command: {shorten(command)}. "
                        "Analyze the error, change the hypothesis, or run a narrower diagnostic command before retrying."
                    ),
                }
                state.record_event({"type": "block", "policy": "stop-death-loop", "command_hash": command_hash})
                return decision
        if is_risky_output_command(command):
            return {
                "decision": "approve",
                "additionalContext": "This shell command may emit large output. Prefer rg/head/tail or a narrower selector.",
                "reason": "Potential bloated shell output.",
            }

    if tool_name in ("Edit", "Write", "MultiEdit"):
        input_size = len(json.dumps(tool_input, ensure_ascii=False).encode("utf-8"))
        if input_size >= 20_000:
            return {
                "decision": "approve",
                "additionalContext": "This edit/write payload is large. Prefer a targeted patch instead of full-file rewrite.",
                "reason": "Large edit warning.",
            }

    return {"decision": "approve"}


def run_post_tool_use(
    payload: dict[str, Any],
    state_path: str | Path | None = None,
) -> dict[str, Any]:
    state = StateStore(state_path)
    tool_name, tool_input = extract_tool(payload)
    session_id = extract_session_id(payload)
    if tool_name in ("Bash", "PowerShell"):
        command = tool_input.get("command", "")
        status = infer_payload_status(payload)
        if command:
            state.record_command_result(session_id, hash_text(command), status)
    return {"decision": "approve"}


def run_user_prompt_submit(
    payload: dict[str, Any],
    db_path: str | Path | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    prompt = payload.get("prompt") or payload.get("user_prompt") or payload.get("message") or ""
    project = payload.get("project_root") or payload.get("cwd") or "."
    store = LearningStore(db_path)
    rules = store.suggest(prompt, project_root=project, limit=limit)
    if not rules:
        return {"decision": "approve"}
    lines = ["Relevant learned project rules:"]
    for rule in rules:
        lines.append(f"- {rule['correction']}")
    return {"decision": "approve", "additionalContext": "\n".join(lines)}


def extract_tool(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if "tool_name" in payload:
        return payload.get("tool_name", ""), payload.get("tool_input", {}) or payload.get("input", {}) or {}
    tool = payload.get("tool", {}) or {}
    if isinstance(tool, dict):
        return tool.get("name", ""), tool.get("input", {}) or {}
    return payload.get("name", ""), payload.get("input", {}) or {}


def extract_session_id(payload: dict[str, Any]) -> str:
    return payload.get("session_id") or payload.get("sessionId") or payload.get("conversation_id") or "default"


def infer_payload_status(payload: dict[str, Any]) -> str:
    if payload.get("is_error") is True:
        return "failed"
    text = json.dumps(payload.get("tool_result", payload.get("result", "")), ensure_ascii=False)
    if "timed out" in text.lower() or "timeout" in text.lower():
        return "timeout"
    match = re.search(r"Exit code\s+(-?\d+)", text, flags=re.IGNORECASE)
    if match and int(match.group(1)) != 0:
        return "failed"
    return payload.get("status") or "success"


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def shorten(value: str, limit: int = 120) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else compact[: limit - 3] + "..."


def is_risky_output_command(command: str) -> bool:
    if not command:
        return False
    lower = command.lower()
    broad = any(token in lower for token in ["cat ", "type ", "get-content", "find .", "ls -r", "dir /s"])
    guarded = any(token in lower for token in ["head", "tail", "select-object -first", "select-object -last", "rg "])
    return broad and not guarded
