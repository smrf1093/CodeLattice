"""Token-efficient result formatting for MCP tool responses."""

from __future__ import annotations

from codelattice.graph.searcher import SearchResult


def format_search_result(result: SearchResult) -> dict:
    """Format a single search result for MCP response."""
    out: dict = {}
    if result.file_path:
        out["file"] = result.file_path
    if result.name:
        out["name"] = result.name
    if result.kind:
        out["kind"] = result.kind
    if result.signature:
        out["signature"] = result.signature
    if result.start_line:
        out["lines"] = [result.start_line, result.end_line]
    if result.docstring:
        out["docstring"] = result.docstring
    if result.relevance:
        out["relevance"] = round(result.relevance, 3)
    if result.relationships:
        out["relationships"] = result.relationships
    return out


def format_search_results(results: list[SearchResult], query: str) -> dict:
    """Format a list of search results into an MCP response."""
    return {
        "results": [format_search_result(r) for r in results],
        "total": len(results),
        "query": query,
    }


def format_index_result(result) -> dict:
    """Format an IndexResult for MCP response."""
    out = {
        "status": "completed",
        "repo_path": result.repo_path,
        "new_files": result.new_files,
        "changed_files": result.changed_files,
        "deleted_files": result.deleted_files,
        "unchanged_files": result.unchanged_files,
        "total_entities": result.total_entities,
        "duration_seconds": round(result.duration_seconds, 2),
    }
    if result.errors:
        out["errors"] = result.errors[:20]  # Cap error list
    return out


def format_file_summary(file_data: dict) -> dict:
    """Format a file summary for MCP response."""
    return file_data
