"""Per-repo database engine management.

Each indexed repository gets its own SQLite graph DB and LanceDB vector DB
under ``~/.codelattice/repos/{repo_id}/``.  This module lazily creates and
caches adapter instances so that the rest of the codebase can simply call
``get_engines(repo_id)`` without worrying about paths or singletons.

The graph adapter uses SQLite in WAL mode for concurrent reader access.
LanceDB handles vector storage and embedding.
"""

from __future__ import annotations

import logging
from pathlib import Path

from codelattice.config.settings import get_settings

logger = logging.getLogger(__name__)

# Cache: repo_id -> (SqliteGraphAdapter, LanceDBAdapter)
_engine_cache: dict[str, tuple] = {}

# Shared embedding engine (stateless FastEmbed, expensive to load)
_embedding_engine = None


def repo_db_dir(repo_id: str) -> Path:
    """Return ``~/.codelattice/repos/{repo_id}/``, creating it if needed."""
    d = get_settings().data_dir / "repos" / repo_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_embedding_engine():
    """Return the shared FastEmbed embedding engine singleton."""
    global _embedding_engine
    if _embedding_engine is None:
        from cognee.infrastructure.databases.vector.embeddings import (
            get_embedding_engine as cognee_get_embedding_engine,
        )

        _embedding_engine = cognee_get_embedding_engine()
    return _embedding_engine


async def get_engines(repo_id: str):
    """Return ``(graph_adapter, vector_adapter)`` for a specific repo.

    Adapters are lazily created and cached for the lifetime of the process.
    """
    if repo_id in _engine_cache:
        return _engine_cache[repo_id]

    rd = repo_db_dir(repo_id)
    graph_path = str(rd / "graph.db")
    vector_path = str(rd / "vectors.lancedb")

    # Detect old Kuzu databases and warn
    old_kuzu = rd / "graph"
    if old_kuzu.exists() and not Path(graph_path).exists():
        logger.warning(
            "Repo %s has old Kuzu graph data at %s. "
            "Re-index required: data will be regenerated in SQLite. "
            "Old Kuzu files can be safely deleted.",
            repo_id,
            old_kuzu,
        )

    from codelattice.graph.sqlite_graph import SqliteGraphAdapter

    graph = SqliteGraphAdapter(db_path=graph_path)

    from cognee.infrastructure.databases.vector.lancedb.LanceDBAdapter import (
        LanceDBAdapter,
    )

    emb = _get_embedding_engine()
    vec = LanceDBAdapter(url=vector_path, api_key=None, embedding_engine=emb)

    _engine_cache[repo_id] = (graph, vec)
    logger.info("Created engines for repo %s at %s", repo_id, rd)
    return graph, vec


async def get_all_engines() -> dict[str, tuple]:
    """Return engines for every repo that has a DB directory.

    Scans ``~/.codelattice/repos/*/`` and lazily instantiates adapters for
    any repo_id not already cached.  Used for cross-repo search fan-out.
    """
    repos_dir = get_settings().data_dir / "repos"
    if not repos_dir.exists():
        return {}

    for child in repos_dir.iterdir():
        if child.is_dir() and child.name not in _engine_cache:
            # Detect new SQLite DB or old Kuzu directory
            if (child / "graph.db").exists() or (child / "graph").exists():
                await get_engines(child.name)

    return dict(_engine_cache)
