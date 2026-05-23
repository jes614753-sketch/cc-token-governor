from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path


class LearningStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else Path.home() / ".cc-token-governor" / "rules.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init(self) -> None:
        with closing(self.connect()) as con:
            con.execute(
                """
                create table if not exists rules (
                    id integer primary key autoincrement,
                    project_root text not null,
                    scope text not null default 'project',
                    pattern text not null default '',
                    correction text not null,
                    tool_name text not null default '',
                    file_glob text not null default '',
                    confidence real not null default 0.7,
                    success_count integer not null default 0,
                    last_used_at text not null default '',
                    created_from text not null default 'manual',
                    created_at text not null
                )
                """
            )
            try:
                con.execute(
                    "create virtual table if not exists rules_fts using fts5(rule_id unindexed, correction, pattern, tool_name, file_glob)"
                )
            except sqlite3.OperationalError:
                pass
            con.commit()

    def learn(
        self,
        correction: str,
        project_root: str = ".",
        scope: str = "project",
        pattern: str = "",
        tool_name: str = "",
        file_glob: str = "",
        confidence: float = 0.7,
        created_from: str = "manual",
    ) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        with closing(self.connect()) as con:
            cur = con.execute(
                """
                insert into rules
                (project_root, scope, pattern, correction, tool_name, file_glob, confidence, created_from, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (str(Path(project_root).resolve()), scope, pattern, correction, tool_name, file_glob, confidence, created_from, now),
            )
            rule_id = int(cur.lastrowid)
            try:
                con.execute(
                    "insert into rules_fts (rule_id, correction, pattern, tool_name, file_glob) values (?, ?, ?, ?, ?)",
                    (rule_id, correction, pattern, tool_name, file_glob),
                )
            except sqlite3.OperationalError:
                pass
            con.commit()
            return rule_id

    def suggest(self, prompt: str, project_root: str = ".", limit: int = 5) -> list[dict]:
        project = str(Path(project_root).resolve())
        tokens = [t for t in prompt.replace('"', " ").split() if len(t) > 1]
        query = " OR ".join(tokens[:8]) if tokens else prompt
        with closing(self.connect()) as con:
            con.row_factory = sqlite3.Row
            try:
                rows = con.execute(
                    """
                    select r.*
                    from rules r
                    join rules_fts f on f.rule_id = r.id
                    where r.project_root in (?, '.')
                    and rules_fts match ?
                    order by r.confidence desc, r.success_count desc, r.id desc
                    limit ?
                    """,
                    (project, query or "*", limit),
                ).fetchall()
            except sqlite3.OperationalError:
                like = f"%{prompt[:64]}%" if prompt else "%"
                rows = con.execute(
                    """
                    select * from rules
                    where project_root in (?, '.')
                    and (correction like ? or pattern like ? or tool_name like ? or file_glob like ?)
                    order by confidence desc, success_count desc, id desc
                    limit ?
                    """,
                    (project, like, like, like, like, limit),
                ).fetchall()
            if not rows:
                rows = con.execute(
                    """
                    select * from rules
                    where project_root in (?, '.')
                    order by confidence desc, success_count desc, id desc
                    limit ?
                    """,
                    (project, limit),
                ).fetchall()
            result = [dict(row) for row in rows]
        return result
