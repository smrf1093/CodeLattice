"""SQLite-backed graph adapter replacing Kuzu.

Uses WAL mode for concurrent reader access. Provides the same 4-method
async interface that the rest of CodeLattice consumes:

    add_nodes(nodes)       -- batch upsert DataPoint nodes
    add_edges(edges)       -- batch upsert relationship edges
    get_node(node_id)      -- retrieve single node as flat dict
    get_edges(node_id)     -- retrieve all edges (both directions)
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SqliteGraphAdapter:
    """SQLite graph database adapter with WAL mode for concurrent access."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                type TEXT NOT NULL DEFAULT '',
                properties TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS edges (
                from_id TEXT NOT NULL,
                to_id TEXT NOT NULL,
                relationship_name TEXT NOT NULL,
                properties TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (from_id, to_id, relationship_name)
            );

            CREATE INDEX IF NOT EXISTS idx_edges_from
                ON edges(from_id);
            CREATE INDEX IF NOT EXISTS idx_edges_to
                ON edges(to_id);
        """)
        self._conn.commit()

    async def initialize(self) -> None:
        """No-op async init for interface compatibility."""
        pass

    async def add_nodes(self, nodes: list) -> None:
        """Batch upsert nodes. Accepts DataPoint objects (calls model_dump)."""
        if not nodes:
            return
        now = datetime.now(timezone.utc).isoformat()
        params = []
        for node in nodes:
            props = node.model_dump() if hasattr(node, "model_dump") else vars(node)
            node_id = str(props.pop("id", ""))
            name = str(props.pop("name", ""))
            node_type = str(props.pop("type", ""))
            props.pop("metadata", None)
            props_json = json.dumps(props, default=str)
            params.append((
                node_id, name, node_type, props_json, now, now,
                # ON CONFLICT UPDATE values:
                name, node_type, props_json, now,
            ))
        self._conn.executemany(
            """INSERT INTO nodes (id, name, type, properties, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   name = ?,
                   type = ?,
                   properties = ?,
                   updated_at = ?""",
            params,
        )
        self._conn.commit()
        logger.debug("Wrote %d nodes", len(params))

    async def add_edges(
        self, edges: list[tuple[str, str, str, dict[str, Any]]]
    ) -> None:
        """Batch upsert edges. Each edge is (from_id, to_id, rel_name, props)."""
        if not edges:
            return
        now = datetime.now(timezone.utc).isoformat()
        params = []
        for from_id, to_id, rel_name, props in edges:
            props_json = json.dumps(props, default=str)
            params.append((
                from_id, to_id, rel_name, props_json, now, now,
                # ON CONFLICT UPDATE values:
                props_json, now,
            ))
        self._conn.executemany(
            """INSERT INTO edges
                   (from_id, to_id, relationship_name, properties,
                    created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(from_id, to_id, relationship_name)
               DO UPDATE SET
                   properties = ?,
                   updated_at = ?""",
            params,
        )
        self._conn.commit()
        logger.debug("Wrote %d edges", len(params))

    def _parse_node(self, row: sqlite3.Row) -> dict[str, Any]:
        """Convert a node row into a flat dict (properties merged in)."""
        result: dict[str, Any] = {
            "id": row["id"],
            "name": row["name"],
            "type": row["type"],
        }
        if row["properties"]:
            try:
                result.update(json.loads(row["properties"]))
            except json.JSONDecodeError:
                logger.warning("Bad JSON in node %s", row["id"])
        return result

    async def get_node(self, node_id: str) -> dict[str, Any] | None:
        """Retrieve a single node by ID, with properties merged into the dict."""
        row = self._conn.execute(
            "SELECT * FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        if not row:
            return None
        return self._parse_node(row)

    async def get_edges(
        self, node_id: str
    ) -> list[tuple[dict[str, Any], str, dict[str, Any]]]:
        """Retrieve all edges (both directions) for a node.

        Returns list of (source_dict, relationship_name, target_dict).
        """
        rows = self._conn.execute(
            """SELECT
                   n1.id AS n1_id, n1.name AS n1_name,
                   n1.type AS n1_type, n1.properties AS n1_props,
                   e.relationship_name,
                   n2.id AS n2_id, n2.name AS n2_name,
                   n2.type AS n2_type, n2.properties AS n2_props
               FROM edges e
               JOIN nodes n1 ON n1.id = e.from_id
               JOIN nodes n2 ON n2.id = e.to_id
               WHERE e.from_id = ? OR e.to_id = ?""",
            (node_id, node_id),
        ).fetchall()

        edges = []
        for row in rows:
            source: dict[str, Any] = {
                "id": row["n1_id"],
                "name": row["n1_name"],
                "type": row["n1_type"],
            }
            try:
                source.update(json.loads(row["n1_props"]))
            except (json.JSONDecodeError, TypeError):
                pass

            target: dict[str, Any] = {
                "id": row["n2_id"],
                "name": row["n2_name"],
                "type": row["n2_type"],
            }
            try:
                target.update(json.loads(row["n2_props"]))
            except (json.JSONDecodeError, TypeError):
                pass

            edges.append((source, row["relationship_name"], target))
        return edges

    def close(self) -> None:
        """Close the database connection."""
        try:
            self._conn.close()
        except Exception:
            pass
