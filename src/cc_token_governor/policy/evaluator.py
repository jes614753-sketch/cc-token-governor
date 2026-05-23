"""Policy evaluator — drives runtime decisions from policy files."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cc_token_governor.models import Policy


# Safety invariants: these are NEVER policy-configurable.
# They protect against runtime corruption and must always fire.
SAFETY_BLOCK_BROKEN_STATE = "safety:broken-state"
SAFETY_BLOCK_RECURSIVE_HOOK = "safety:recursive-hook"


def _match_trigger(
    trigger: dict[str, Any],
    tool_name: str,
    tool_input: dict[str, Any],
    signals: dict[str, Any],
) -> bool:
    """Check whether a policy trigger matches the current context."""
    # Tool name filter
    trigger_tools = trigger.get("tool_name")
    if trigger_tools:
        if isinstance(trigger_tools, str):
            trigger_tools = [trigger_tools]
        if tool_name not in trigger_tools:
            return False

    # Numeric signal comparisons
    for key, threshold in trigger.items():
        if key == "tool_name":
            continue
        if key.endswith("_gte"):
            signal_key = key[: -len("_gte")]
            value = signals.get(signal_key, 0)
            if not isinstance(value, (int, float)) or value < threshold:
                return False
        elif key.endswith("_lte"):
            signal_key = key[: -len("_lte")]
            value = signals.get(signal_key, 0)
            if not isinstance(value, (int, float)) or value > threshold:
                return False

    # Boolean signal flags
    for key, expected in trigger.items():
        if key in ("tool_name",) or key.endswith("_gte") or key.endswith("_lte"):
            continue
        if isinstance(expected, bool):
            if signals.get(key, False) != expected:
                return False

    return True


class PolicyEvaluator:
    """Evaluates tool calls against a set of policies and produces decisions.

    Design note (Codex feedback): safety invariants are hardcoded and cannot be
    disabled by policy configuration. Only governance rules are policy-driven.
    """

    def __init__(self, policies: list[Policy] | None = None):
        self.policies = policies or []

    def evaluate(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        signals: dict[str, Any],
    ) -> dict[str, Any]:
        """Evaluate a tool call against all loaded policies.

        Returns a decision dict with keys: decision, reason, additionalContext.
        """
        for policy in self.policies:
            if _match_trigger(policy.trigger, tool_name, tool_input, signals):
                return {
                    "decision": policy.action,
                    "reason": policy.message,
                    "policy_id": policy.id,
                    "confidence": policy.confidence,
                }

        return {"decision": "approve"}

    @classmethod
    def from_file(cls, path: str | Path) -> "PolicyEvaluator":
        """Load evaluator from a governor-policy.json file."""
        p = Path(path)
        if not p.exists():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            policies = [Policy.from_dict(item) for item in data.get("policies", [])]
            return cls(policies)
        except (json.JSONDecodeError, KeyError):
            return cls()

    @classmethod
    def from_defaults(cls) -> "PolicyEvaluator":
        """Load evaluator with default policies."""
        from cc_token_governor.policy.compiler import default_policies
        return cls(default_policies())
