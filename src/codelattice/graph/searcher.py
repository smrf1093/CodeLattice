"""Code-aware search layer querying per-repo vector + graph stores directly.

Each repo has its own LanceDB + SQLite graph databases.  When ``repo_id`` is
provided, only that repo is searched.  When ``repo_id`` is None, we fan
out across all indexed repos and merge results by score.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# LanceDB collection names created by index_data_points.
# Pattern: {TypeName}_{field_name}
SEARCH_COLLECTIONS = [
    "CodeFunction_name",
    "CodeFunction_signature",
    "CodeFunction_docstring",
    "CodeClass_name",
    "CodeClass_signature",
    "CodeClass_docstring",
    "CodeFile_file_path",
    "CodeFile_summary",
    "CodeImport_source_module",
    "CodeImport_import_statement",
    "CodeVariable_name",
]

# Quick-lookup subset (fewer collections -> faster)
QUICK_COLLECTIONS = [
    "CodeFunction_name",
    "CodeClass_name",
    "CodeFile_summary",
    "CodeVariable_name",
]


@dataclass
class SearchResult:
    """A single search result."""

    name: str = ""
    kind: str = ""
    file_path: str = ""
    start_line: int = 0
    end_line: int = 0
    signature: str = ""
    docstring: str | None = None
    relevance: float = 0.0
    relationships: list[dict[str, Any]] = field(default_factory=list)


def _node_to_result(node: dict, score: float = 0.0) -> SearchResult:
    """Convert a graph-engine node dict into a SearchResult."""
    return SearchResult(
        name=node.get("name", node.get("file_path", "")),
        kind=node.get("kind", node.get("type", "")),
        file_path=node.get("file_path", ""),
        start_line=node.get("start_line", 0),
        end_line=node.get("end_line", 0),
        signature=node.get("signature", ""),
        docstring=node.get("docstring"),
        relevance=1.0 - score,  # LanceDB: score 0 = best, we invert
    )


async def _get_engine_pairs(repo_id: str | None) -> list[tuple]:
    """Return list of (graph, vec) pairs to search.

    If *repo_id* is given, returns only that repo's engines.
    Otherwise returns engines for every indexed repo.
    """
    from codelattice.graph.engines import get_all_engines, get_engines

    if repo_id:
        graph, vec = await get_engines(repo_id)
        return [(graph, vec)]

    all_engines = await get_all_engines()
    return list(all_engines.values())


async def _vector_search(
    vec, query: str, collections: list[str], limit: int
) -> list[tuple[str, float]]:
    """Search across multiple LanceDB collections, deduplicate by ID."""
    seen: dict[str, float] = {}
    for coll_name in collections:
        try:
            has = await vec.has_collection(coll_name)
            if not has:
                continue
            results = await vec.search(coll_name, query_text=query, limit=limit)
            for r in results:
                rid = str(r.get("id", "") if isinstance(r, dict) else getattr(r, "id", ""))
                score = float(
                    r.get("score", 1.0) if isinstance(r, dict) else getattr(r, "score", 1.0)
                )
                if rid and (rid not in seen or score < seen[rid]):
                    seen[rid] = score
        except Exception as e:
            logger.debug("Search in %s failed: %s", coll_name, e)
            continue

    # Sort by score ascending (0 = best match in LanceDB)
    return sorted(seen.items(), key=lambda x: x[1])[:limit]


async def _hydrate(graph, id_scores: list[tuple[str, float]]) -> list[SearchResult]:
    """Look up full node data from the graph engine."""
    results = []
    for node_id, score in id_scores:
        try:
            node = await graph.get_node(node_id)
            if node:
                node_dict = node if isinstance(node, dict) else node.__dict__
                results.append(_node_to_result(node_dict, score))
        except Exception as e:
            logger.debug("Failed to hydrate node %s: %s", node_id, e)
    return results


async def _search_one_repo(
    graph, vec, query: str, collections: list[str], limit: int
) -> list[SearchResult]:
    """Run vector search + hydration against a single repo's engines."""
    id_scores = await _vector_search(vec, query, collections, limit=limit * 2)
    return await _hydrate(graph, id_scores[:limit])


async def _search_all_repos(
    query: str,
    collections: list[str],
    limit: int,
    repo_id: str | None = None,
) -> list[SearchResult]:
    """Search one or all repos, merging results by relevance score."""
    pairs = await _get_engine_pairs(repo_id)
    if not pairs:
        return []

    all_results: list[SearchResult] = []
    for graph, vec in pairs:
        results = await _search_one_repo(graph, vec, query, collections, limit)
        all_results.extend(results)

    # Sort by relevance descending, deduplicate by (name, file_path, start_line)
    all_results.sort(key=lambda r: r.relevance, reverse=True)
    seen = set()
    deduped = []
    for r in all_results:
        key = (r.name, r.file_path, r.start_line)
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    return deduped[:limit]


async def semantic_search(
    query: str, top_k: int = 10, repo_id: str | None = None
) -> list[SearchResult]:
    """Semantic search across indexed code entities."""
    return await _search_all_repos(query, SEARCH_COLLECTIONS, top_k, repo_id)


async def quick_search(
    query: str, top_k: int = 10, repo_id: str | None = None
) -> list[SearchResult]:
    """Faster search using only name/summary collections."""
    return await _search_all_repos(query, QUICK_COLLECTIONS, top_k, repo_id)


async def search_by_name(
    name: str, kind: str | None = None, top_k: int = 20, repo_id: str | None = None
) -> list[SearchResult]:
    """Search for a specific symbol by name."""
    name_collections = [c for c in SEARCH_COLLECTIONS if c.endswith("_name")]
    query = f"{kind} {name}" if kind else name
    results = await _search_all_repos(query, name_collections, top_k * 3, repo_id)

    # Post-filter by name match
    name_lower = name.lower()
    filtered = []
    for r in results:
        r_name = (r.name or "").lower()
        if name_lower in r_name or r_name in name_lower:
            if kind and r.kind and kind.lower() != r.kind.lower():
                continue
            filtered.append(r)

    return (filtered or results)[:top_k]


async def get_node_edges(node_id: str, repo_id: str | None = None) -> list[dict[str, Any]]:
    """Get edges (relationships) for a node from the graph."""
    pairs = await _get_engine_pairs(repo_id)
    for graph, _vec in pairs:
        try:
            edges = await graph.get_edges(node_id)
            if not edges:
                continue
            result = []
            for edge in edges:
                if isinstance(edge, dict):
                    result.append(edge)
                elif isinstance(edge, (list, tuple)) and len(edge) >= 3:
                    result.append(
                        {
                            "source": str(edge[0]),
                            "relationship": str(edge[1]),
                            "target": str(edge[2]),
                        }
                    )
                else:
                    result.append({"raw": str(edge)})
            if result:
                return result
        except Exception as e:
            logger.debug("Failed to get edges for %s: %s", node_id, e)
    return []
