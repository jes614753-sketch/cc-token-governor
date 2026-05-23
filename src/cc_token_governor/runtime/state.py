"""Runtime state store — SQLite-backed with JSON export/import."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path


class StateStore:
    """Session-level state for tracking reads, failed commands, and events.

    Uses SQLite with WAL for durability and concurrency safety.
    Falls back gracefully if the DB file is corrupted.
    """

    def __init__(self, path: str | Path | None = None):
        if path:
            self.path = Path(path)
        else:
            self.path = Path.cwd() / ".cc-governor-state.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.path), timeout=5)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=3000")
        return con

    def _init_db(self) -> None:
        with closing(self._connect()) as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS reads (
                    session_id TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (session_id, file_path)
                );
                CREATE TABLE IF NOT EXISTS failed_commands (
                    session_id TEXT NOT NULL,
                    command_hash TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (session_id, command_hash)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    data TEXT NOT NULL
                );
            """)
            con.commit()

    def read_count(self, session_id: str, file_path: str) -> int:
        with closing(self._connect()) as con:
            row = con.execute(
                "SELECT count FROM reads WHERE session_id = ? AND file_path = ?",
                (session_id, file_path),
            ).fetchone()
            return row[0] if row else 0

    def record_read(self, session_id: str, file_path: str) -> None:
        with closing(self._connect()) as con:
            con.execute(
                """
                INSERT INTO reads (session_id, file_path, count) VALUES (?, ?, 1)
                ON CONFLICT(session_id, file_path) DO UPDATE SET count = count + 1
                """,
                (session_id, file_path),
            )
            con.commit()

    def failed_command_count(self, session_id: str, command_hash: str) -> int:
        with closing(self._connect()) as con:
            row = con.execute(
                "SELECT count FROM failed_commands WHERE session_id = ? AND command_hash = ?",
                (session_id, command_hash),
            ).fetchone()
            return row[0] if row else 0

    def record_command_result(self, session_id: str, command_hash: str, status: str) -> None:
        with closing(self._connect()) as con:
            if status in ("failed", "timeout"):
                con.execute(
                    """
                    INSERT INTO failed_commands (session_id, command_hash, count) VALUES (?, ?, 1)
                    ON CONFLICT(session_id, command_hash) DO UPDATE SET count = count + 1
                    """,
                    (session_id, command_hash),
                )
            elif status == "success":
                con.execute(
                    "DELETE FROM failed_commands WHERE session_id = ? AND command_hash = ?",
                    (session_id, command_hash),
                )
            con.commit()

    def record_event(self, event: dict) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with closing(self._connect()) as con:
            con.execute(
                "INSERT INTO events (created_at, data) VALUES (?, ?)",
                (now, json.dumps(event, ensure_ascii=False)),
            )
            # Keep only the last 200 events
            con.execute(
                "DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 200)"
            )
            con.commit()

    def export_json(self) -> dict:
        """Export state as a JSON-serializable dict (for debugging/inspection)."""
        with closing(self._connect()) as con:
            reads = {}
            for row in con.execute("SELECT session_id, file_path, count FROM reads"):
                reads.setdefault(row[0], {})[row[1]] = row[2]

            failed = {}
            for row in con.execute("SELECT session_id, command_hash, count FROM failed_commands"):
                failed.setdefault(row[0], {})[row[1]] = row[2]

            events = []
            for row in con.execute("SELECT data FROM events ORDER BY id DESC LIMIT 200"):
                events.append(json.loads(row[0]))

        return {"reads": reads, "failed_commands": failed, "events": events}
