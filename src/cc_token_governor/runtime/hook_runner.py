"""Hook runner — policy-driven runtime decisions for Claude Code hooks."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from cc_token_governor.learning.store import LearningStore
from cc_token_governor.policy.compiler import load_policy_file
from cc_token_governor.policy.evaluator import (
    SAFETY_BLOCK_BROKEN_STATE,
    PolicyEvaluator,
)
from cc_token_governor.runtime.state import StateStore


def _build_evaluator(policy_path: str | Path | None = None) -> PolicyEvaluator:
    policies = load_policy_file(policy_path)
    return PolicyEvaluator(policies)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _shorten(value: str, limit: int = 120) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else compact[: limit - 3] + "..."


def _is_risky_output_command(command: str) -> bool:
    if not command:
        return False
    lower = command.lower()
    broad = any(token in lower for token in ["cat ", "type ", "get-content", "find .", "ls -r", "dir /s"])
    guarded = any(token in lower for token in ["head", "tail", "select-object -first", "select-object -last", "rg "])
    return broad and not guarded


def _extract_tool(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if "tool_name" in payload:
        return payload.get("tool_name", ""), payload.get("tool_input", {}) or payload.get("input", {}) or {}
    tool = payload.get("tool", {}) or {}
    if isinstance(tool, dict):
        return tool.get("name", ""), tool.get("input", {}) or {}
    return payload.get("name", ""), payload.get("input", {}) or {}


def _extract_session_id(payload: dict[str, Any]) -> str:
    return payload.get("session_id") or payload.get("sessionId") or payload.get("conversation_id") or "default"


def _infer_payload_status(payload: dict[str, Any]) -> str:
    if payload.get("is_error") is True:
        return "failed"
    text = json.dumps(payload.get("tool_result", payload.get("result", "")), ensure_ascii=False)
    if "timed out" in text.lower() or "timeout" in text.lower():
        return "timeout"
    match = re.search(r"Exit code\s+(-?\d+)", text, flags=re.IGNORECASE)
    if match and int(match.group(1)) != 0:
        return "failed"
    return payload.get("status") or "success"


def run_pre_tool_use(
    payload: dict[str, Any],
    policy_path: str | Path | None = None,
    state_path: str | Path | None = None,
) -> dict[str, Any]:
    """Evaluate a PreToolUse hook payload against policies.

    Safety invariants (non-configurable):
    - Block if state store is corrupted.

    Governance rules (policy-driven via PolicyEvaluator):
    - Repeated file reads → warn
    - Death loops → block
    - Large edits → warn
    - Risky output commands → warn
    """
    # Safety invariant: state integrity
    try:
        state = StateStore(state_path)
    except Exception:
        return {
            "decision": "block",
            "reason": "Governor state file is corrupted. Delete it and retry.",
            "policy_id": SAFETY_BLOCK_BROKEN_STATE,
        }

    tool_name, tool_input = _extract_tool(payload)
    session_id = _extract_session_id(payload)
    evaluator = _build_evaluator(policy_path)

    # Build context signals for the evaluator
    signals: dict[str, Any] = {}

    if tool_name == "Read":
        file_path = tool_input.get("file_path", "")
        if file_path:
            count = state.read_count(session_id, file_path)
            state.record_read(session_id, file_path)
            signals["same_file_read_count"] = count + 1

    if tool_name in ("Bash", "PowerShell"):
        command = tool_input.get("command", "")
        command_hash = _hash_text(command) if command else ""
        if command_hash:
            failed_count = state.failed_command_count(session_id, command_hash)
            signals["same_failed_command_count"] = failed_count
        signals["risky_output_command"] = _is_risky_output_command(command)

    if tool_name in ("Edit", "Write", "MultiEdit"):
        input_size = len(json.dumps(tool_input, ensure_ascii=False).encode("utf-8"))
        signals["tool_input_size_bytes"] = input_size

    # Let the policy evaluator decide
    result = evaluator.evaluate(tool_name, tool_input, signals)

    # Record events for blocking/warning decisions
    if result.get("decision") in ("block", "warn"):
        state.record_event({
            "type": result["decision"],
            "policy": result.get("policy_id", ""),
            "tool_name": tool_name,
        })

    return result


def run_post_tool_use(
    payload: dict[str, Any],
    state_path: str | Path | None = None,
) -> dict[str, Any]:
    """Record command results for death-loop tracking."""
    try:
        state = StateStore(state_path)
    except Exception:
        return {"decision": "approve"}

    tool_name, tool_input = _extract_tool(payload)
    session_id = _extract_session_id(payload)

    if tool_name in ("Bash", "PowerShell"):
        command = tool_input.get("command", "")
        status = _infer_payload_status(payload)
        if command:
            state.record_command_result(session_id, _hash_text(command), status)

    return {"decision": "approve"}


def run_user_prompt_submit(
    payload: dict[str, Any],
    db_path: str | Path | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Inject learned rules as context for the next prompt."""
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
