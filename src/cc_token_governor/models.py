from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ToolCall:
    session_id: str
    tool_use_id: str
    tool_name: str
    timestamp_start: str = ""
    timestamp_end: str = ""
    duration_ms_estimated: int = 0
    tool_input_size_bytes: int = 0
    tool_result_size_bytes: int = 0
    file_path: str | None = None
    file_name: str | None = None
    file_extension: str | None = None
    bash_command_text: str | None = None
    bash_command_hash: str | None = None
    tool_status: str = "unknown"
    exit_code: int | None = None
    is_error: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolCall":
        known = {field.name for field in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    estimated_waste_tokens: int = 0
    estimated_waste_usd: float = 0.0
    recommended_policy: str = ""
    confidence: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Finding":
        if "details" in data and "evidence" not in data:
            data = {**data, "evidence": data.get("details", {})}
        known = {field.name for field in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Policy:
    id: str
    trigger: dict[str, Any]
    action: str
    message: str
    confidence: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Policy":
        known = {field.name for field in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class AuditReport:
    schema_version: int
    source: dict[str, Any]
    tool_calls: list[ToolCall]
    findings: list[Finding]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "findings": [f.to_dict() for f in self.findings],
        }
