from __future__ import annotations

from collections import defaultdict

from cc_token_governor.models import Finding, ToolCall
from cc_token_governor.toxicity import classify_toxic

LARGE_OUTPUT_BYTES = 20_000
CRITICAL_OUTPUT_BYTES = 100_000
LARGE_EDIT_BYTES = 20_000
FAILURE_STATUSES = {"failed", "timeout"}

def audit_tool_calls(tool_calls: list[ToolCall]) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(find_repeated_reads(tool_calls))
    findings.extend(find_toxic_files(tool_calls))
    findings.extend(find_bloated_output(tool_calls))
    findings.extend(find_death_loops(tool_calls))
    findings.extend(find_large_edits(tool_calls))
    return findings


def find_repeated_reads(tool_calls: list[ToolCall]) -> list[Finding]:
    grouped: dict[tuple[str, str], list[ToolCall]] = defaultdict(list)
    for call in tool_calls:
        if call.tool_name == "Read" and call.file_path:
            grouped[(call.session_id, call.file_path)].append(call)

    findings = []
    for (_session, file_path), calls in grouped.items():
        if len(calls) < 2:
            continue
        findings.append(Finding(
            severity="medium",
            category="repeated_read",
            message=f"{file_path} was read {len(calls)} times in one session.",
            evidence={
                "file_path": file_path,
                "read_count": len(calls),
                "session_id": calls[0].session_id,
            },
            estimated_waste_tokens=sum(c.tool_result_size_bytes for c in calls[1:]) // 4,
            recommended_policy="avoid-repeated-read",
            confidence="high",
        ))
    return findings


def find_toxic_files(tool_calls: list[ToolCall]) -> list[Finding]:
    findings = []
    for call in tool_calls:
        if call.tool_name not in ("Read", "Edit") or not call.file_path:
            continue
        category = classify_toxic(call.file_path)
        if not category:
            continue
        findings.append(Finding(
            severity="high" if category == "lockfile" else "medium",
            category="toxic_file",
            message=f"{call.file_path} matches toxic file pattern {category}.",
            evidence={
                "file_path": call.file_path,
                "poison_category": category,
                "size_bytes": call.tool_result_size_bytes,
            },
            estimated_waste_tokens=call.tool_result_size_bytes // 4,
            recommended_policy="avoid-toxic-files",
            confidence="high",
        ))
    return findings


def find_bloated_output(tool_calls: list[ToolCall]) -> list[Finding]:
    findings = []
    for call in tool_calls:
        if call.tool_name not in ("Bash", "PowerShell"):
            continue
        if call.tool_result_size_bytes < LARGE_OUTPUT_BYTES:
            continue
        severity = "critical" if call.tool_result_size_bytes >= CRITICAL_OUTPUT_BYTES else "high"
        findings.append(Finding(
            severity=severity,
            category="bloated_output",
            message=f"{call.tool_name} output was {call.tool_result_size_bytes} bytes.",
            evidence={
                "command": shorten(call.bash_command_text),
                "command_hash": call.bash_command_hash,
                "output_bytes": call.tool_result_size_bytes,
            },
            estimated_waste_tokens=call.tool_result_size_bytes // 4,
            recommended_policy="cap-bash-output",
            confidence="high",
        ))
    return findings


def find_death_loops(tool_calls: list[ToolCall]) -> list[Finding]:
    findings = []
    by_session: dict[str, list[ToolCall]] = defaultdict(list)
    for call in tool_calls:
        if call.tool_name in ("Bash", "PowerShell"):
            by_session[call.session_id].append(call)

    for session_id, calls in by_session.items():
        current: list[ToolCall] = []
        previous_hash = None
        for call in calls:
            key = call.bash_command_hash
            if call.tool_status in FAILURE_STATUSES and key and key == previous_hash:
                current.append(call)
            else:
                if len(current) >= 3:
                    findings.append(make_death_loop_finding(session_id, current))
                current = [call] if call.tool_status in FAILURE_STATUSES and key else []
                previous_hash = key
        if len(current) >= 3:
            findings.append(make_death_loop_finding(session_id, current))
    return findings


def find_large_edits(tool_calls: list[ToolCall]) -> list[Finding]:
    findings = []
    for call in tool_calls:
        if call.tool_name not in ("Edit", "Write", "MultiEdit"):
            continue
        if call.tool_input_size_bytes < LARGE_EDIT_BYTES:
            continue
        findings.append(Finding(
            severity="high",
            category="large_edit",
            message=f"{call.tool_name} input was {call.tool_input_size_bytes} bytes.",
            evidence={
                "file_path": call.file_path,
                "input_bytes": call.tool_input_size_bytes,
                "tool_name": call.tool_name,
            },
            estimated_waste_tokens=call.tool_input_size_bytes // 4,
            recommended_policy="avoid-large-edit",
            confidence="high",
        ))
    return findings


def make_death_loop_finding(session_id: str, calls: list[ToolCall]) -> Finding:
    return Finding(
        severity="high",
        category="death_loop",
        message=f"{shorten(calls[0].bash_command_text)} failed {len(calls)} times consecutively.",
        evidence={
            "session_id": session_id,
            "command": shorten(calls[0].bash_command_text),
            "command_hash": calls[0].bash_command_hash,
            "retry_count": len(calls),
            "statuses": [c.tool_status for c in calls],
        },
        estimated_waste_tokens=sum(c.tool_result_size_bytes for c in calls) // 4,
        recommended_policy="stop-death-loop",
        confidence="high",
    )


def shorten(value: str | None, limit: int = 120) -> str:
    if not value:
        return ""
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else compact[: limit - 3] + "..."
