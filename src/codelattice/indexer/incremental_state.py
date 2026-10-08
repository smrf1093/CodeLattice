"""SQLite-backed state tracking for incremental indexing."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FileState:
    """Stored state for an indexed file."""

    file_path: str
    content_hash: str
    language: str
    last_indexed_at: float
    entity_count: int = 0


class IncrementalState:
    """Manages indexing state in a SQLite database."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS indexed_files (
                repo_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                language TEXT NOT NULL,
                last_indexed_at REAL NOT NULL,
                entity_count INTEGER DEFAULT 0,
                PRIMARY KEY (repo_id, file_path)
            );

            CREATE TABLE IF NOT EXISTS indexed_repos (
                repo_id TEXT PRIMARY KEY,
                repo_path TEXT NOT NULL,
                last_full_index_at REAL,
                last_incremental_at REAL,
                total_files INTEGER DEFAULT 0,
                total_entities INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS entity_file_map (
                entity_id TEXT PRIMARY KEY,
                repo_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                entity_type TEXT NOT NULL
            );
        """)
        self._conn.commit()

    def get_file_state(self, repo_id: str, file_path: str) -> FileState | None:
        """Get the stored state for a file."""
        row = self._conn.execute(
            "SELECT * FROM indexed_files WHERE repo_id = ? AND file_path = ?",
            (repo_id, file_path),
        ).fetchone()
        if not row:
            return None
        return FileState(
            file_path=row["file_path"],
            content_hash=row["content_hash"],
            language=row["language"],
            last_indexed_at=row["last_indexed_at"],
            entity_count=row["entity_count"],
        )

    def get_all_files(self, repo_id: str) -> dict[str, FileState]:
        """Get all stored file states for a repo."""
        rows = self._conn.execute(
            "SELECT * FROM indexed_files WHERE repo_id = ?",
            (repo_id,),
        ).fetchall()
        return {
            row["file_path"]: FileState(
                file_path=row["file_path"],
                content_hash=row["content_hash"],
                language=row["language"],
                last_indexed_at=row["last_indexed_at"],
                entity_count=row["entity_count"],
            )
            for row in rows
        }

    def record_file(
        self, repo_id: str, file_path: str, content_hash: str, language: str, entity_count: int
    ) -> None:
        """Record or update the state of an indexed file."""
        self._conn.execute(
            """INSERT OR REPLACE INTO indexed_files
               (repo_id, file_path, content_hash, language, last_indexed_at, entity_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (repo_id, file_path, content_hash, language, time.time(), entity_count),
        )
        self._conn.commit()

    def remove_file(self, repo_id: str, file_path: str) -> None:
        """Remove a file's state."""
        self._conn.execute(
            "DELETE FROM indexed_files WHERE repo_id = ? AND file_path = ?",
            (repo_id, file_path),
        )
        self._conn.execute(
            "DELETE FROM entity_file_map WHERE repo_id = ? AND file_path = ?",
            (repo_id, file_path),
        )
        self._conn.commit()

    def record_entities(self, repo_id: str, file_path: str, entity_map: dict[str, str]) -> None:
        """Record which entity IDs belong to a file."""
        self._conn.executemany(
            """INSERT OR REPLACE INTO entity_file_map
               (entity_id, repo_id, file_path, entity_type)
               VALUES (?, ?, ?, ?)""",
            [(eid, repo_id, file_path, etype) for eid, etype in entity_map.items()],
        )
        self._conn.commit()

    def get_entity_ids_for_file(self, repo_id: str, file_path: str) -> list[str]:
        """Get all entity IDs that were created from a file."""
        rows = self._conn.execute(
            "SELECT entity_id FROM entity_file_map WHERE repo_id = ? AND file_path = ?",
            (repo_id, file_path),
        ).fetchall()
        return [row["entity_id"] for row in rows]

    def record_repo(
        self, repo_id: str, repo_path: str, total_files: int, total_entities: int
    ) -> None:
        """Record or update repo-level stats."""
        now = time.time()
        self._conn.execute(
            """INSERT OR REPLACE INTO indexed_repos
               (repo_id, repo_path, last_full_index_at, last_incremental_at,
                total_files, total_entities)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (repo_id, repo_path, now, now, total_files, total_entities),
        )
        self._conn.commit()

    def get_repo_stats(self, repo_id: str) -> dict | None:
        """Get repo-level stats."""
        row = self._conn.execute(
            "SELECT * FROM indexed_repos WHERE repo_id = ?",
            (repo_id,),
        ).fetchone()
        if not row:
            return None
        return dict(row)

    def get_all_repos(self) -> list[dict]:
        """Get stats for all indexed repos."""
        rows = self._conn.execute("SELECT * FROM indexed_repos").fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self._conn.close()
