from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cc_token_governor.models import Finding, Policy


def default_policies() -> list[Policy]:
    return [
        Policy(
            id="avoid-repeated-read",
            trigger={"tool_name": "Read", "same_file_read_count_gte": 2},
            action="warn",
            message="This file was already read in this session. Reuse existing context unless the file changed or exact line numbers are needed.",
            confidence="high",
        ),
        Policy(
            id="stop-death-loop",
            trigger={"tool_name": ["Bash", "PowerShell"], "same_failed_command_count_gte": 2},
            action="block",
            message="This command already failed twice. Analyze the failure and choose a different fix before retrying.",
            confidence="high",
        ),
        Policy(
            id="avoid-large-edit",
            trigger={"tool_name": ["Edit", "Write", "MultiEdit"], "tool_input_size_bytes_gte": 20_000},
            action="warn",
            message="This edit/write input is large. Prefer a smaller targeted patch instead of rewriting the whole file.",
            confidence="high",
        ),
        Policy(
            id="cap-bash-output",
            trigger={"tool_name": ["Bash", "PowerShell"], "risky_output_command": True},
            action="warn",
            message="Limit shell output with rg/head/tail/selectors before sending large logs into context.",
            confidence="medium",
        ),
    ]


def compile_policies(findings: list[Finding]) -> list[Policy]:
    policies = {policy.id: policy for policy in default_policies()}
    categories = {finding.category for finding in findings}
    if "toxic_file" in categories:
        policies["avoid-toxic-files"] = Policy(
            id="avoid-toxic-files",
            trigger={"tool_name": ["Read", "Edit"], "toxic_file_path": True},
            action="warn",
            message="This path looks like a dependency, build artifact, lockfile, media, or cache file. Use glob/listing first; avoid reading it unless required.",
            confidence="high",
        )
    return list(policies.values())


def load_findings(path: str | Path) -> list[Finding]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_findings: list[dict[str, Any]] = []
    if isinstance(data.get("findings"), list):
        raw_findings = data["findings"]
    elif isinstance(data.get("findings"), dict):
        for values in data["findings"].values():
            raw_findings.extend(values)
    return [Finding.from_dict(item) for item in raw_findings]


def write_policy_file(policies: list[Policy], path: str | Path) -> None:
    payload = {
        "schema_version": 1,
        "policies": [policy.to_dict() for policy in policies],
    }
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_policy_file(path: str | Path | None = None) -> list[Policy]:
    if not path:
        return default_policies()
    p = Path(path)
    if not p.exists():
        return default_policies()
    data = json.loads(p.read_text(encoding="utf-8"))
    return [Policy.from_dict(item) for item in data.get("policies", [])] or default_policies()
