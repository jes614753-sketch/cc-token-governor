from __future__ import annotations

import json
from pathlib import Path


class StateStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else Path.cwd() / ".cc-governor-state.json"
        self.data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"reads": {}, "failed_commands": {}, "events": []}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"reads": {}, "failed_commands": {}, "events": []}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def read_count(self, session_id: str, file_path: str) -> int:
        return int(self.data.setdefault("reads", {}).get(session_id, {}).get(file_path, 0))

    def record_read(self, session_id: str, file_path: str) -> None:
        reads = self.data.setdefault("reads", {}).setdefault(session_id, {})
        reads[file_path] = int(reads.get(file_path, 0)) + 1
        self.save()

    def failed_command_count(self, session_id: str, command_hash: str) -> int:
        return int(self.data.setdefault("failed_commands", {}).get(session_id, {}).get(command_hash, 0))

    def record_command_result(self, session_id: str, command_hash: str, status: str) -> None:
        commands = self.data.setdefault("failed_commands", {}).setdefault(session_id, {})
        if status in {"failed", "timeout"}:
            commands[command_hash] = int(commands.get(command_hash, 0)) + 1
        elif status == "success":
            commands.pop(command_hash, None)
        self.save()

    def record_event(self, event: dict) -> None:
        events = self.data.setdefault("events", [])
        events.append(event)
        self.data["events"] = events[-200:]
        self.save()
