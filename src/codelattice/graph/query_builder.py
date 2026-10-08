"""Build search queries from MCP tool parameters."""

from __future__ import annotations

from codelattice.graph import searcher
from codelattice.graph.searcher import SearchResult


async def search_code(
    query: str,
    top_k: int = 10,
    language: str | None = None,
    file_pattern: str | None = None,
    repo_id: str | None = None,
) -> list[SearchResult]:
    """Execute a semantic code search with optional filters."""
    # Enrich query with language context if provided
    enriched = query
    if language:
        enriched = f"{language} {query}"

    results = await searcher.semantic_search(enriched, top_k=top_k * 2, repo_id=repo_id)

    # Post-filter
    filtered = []
    for r in results:
        if language and r.file_path:
            ext_map = {
                "python": (".py",),
                "typescript": (".ts", ".tsx"),
                "javascript": (".js", ".jsx"),
            }
            exts = ext_map.get(language.lower(), ())
            if exts and not any(r.file_path.endswith(e) for e in exts):
                continue

        if file_pattern and r.file_path:
            import fnmatch

            if not fnmatch.fnmatch(r.file_path, file_pattern):
                continue

        filtered.append(r)

    return filtered[:top_k]


async def find_symbol(
    name: str,
    kind: str | None = None,
    include_relationships: bool = True,
    repo_id: str | None = None,
) -> list[SearchResult]:
    """Find a specific symbol and optionally its relationships."""
    results = await searcher.search_by_name(name, kind=kind, repo_id=repo_id)

    if include_relationships and results:
        primary = results[0]
        edges = await searcher.get_node_edges(
            str(getattr(primary, "_node_id", "")), repo_id=repo_id
        )
        if edges:
            results[0].relationships = edges

    return results


async def get_dependencies(
    target: str, depth: int = 1, repo_id: str | None = None
) -> list[SearchResult]:
    """Get what a file or symbol depends on."""
    query = f"imports dependencies of {target}"
    return await searcher.semantic_search(query, top_k=20, repo_id=repo_id)


async def get_dependents(
    target: str, depth: int = 1, repo_id: str | None = None
) -> list[SearchResult]:
    """Get what depends on a file or symbol (reverse dependencies)."""
    query = f"what imports or calls or uses {target}"
    return await searcher.semantic_search(query, top_k=20, repo_id=repo_id)
