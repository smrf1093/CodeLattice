"""MCP tool implementations (business logic)."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from codelattice.graph import query_builder
from codelattice.graph.searcher import semantic_search
from codelattice.indexer.repository_indexer import (
    IndexAlreadyRunningError,
    IndexResult,
    detect_stale_files,
    get_index_status,
    index_repository,
    is_indexing,
    refresh_changed_files,
    request_cancel_indexing,
)
from codelattice.server.formatters import (
    format_index_result,
    format_search_results,
)
from codelattice.stats.tracker import get_tracker

logger = logging.getLogger(__name__)

# Tracks the last-indexed repo path and its repo_id
_active_repo_path: str | None = None
_active_repo_id: str | None = None


def _make_repo_id(repo_path: str) -> str:
    """Generate a stable repo ID from an absolute path (matches repository_indexer)."""
    return hashlib.sha256(str(Path(repo_path).resolve()).encode()).hexdigest()[:16]


def _set_active_repo(path: str) -> None:
    global _active_repo_path, _active_repo_id
    _active_repo_path = path
    _active_repo_id = _make_repo_id(path)


def _get_active_repo() -> str | None:
    return _active_repo_path


def _get_active_repo_id() -> str | None:
    return _active_repo_id


def _check_staleness() -> dict | None:
    """Check if the active repo has stale files. Returns warning dict or None."""
    repo = _get_active_repo()
    if not repo:
        return None
    try:
        stale_info = detect_stale_files(repo)
        if stale_info.get("is_stale"):
            changed = stale_info.get("changed", [])
            new = stale_info.get("new", [])
            deleted = stale_info.get("deleted", [])
            total = len(changed) + len(new) + len(deleted)
            files_preview = (changed + new + deleted)[:5]
            return {
                "stale_warning": f"{total} file(s) changed since last index. "
                "Call refresh_index to update the knowledge base.",
                "changed_files": files_preview,
            }
    except Exception as e:
        logger.debug("Staleness check failed: %s", e)
    return None


async def tool_index_repository(
    path: str,
    incremental: bool = True,
    languages: list[str] | None = None,
) -> dict:
    """Index or re-index a code repository into the knowledge graph."""
    _set_active_repo(path)
    try:
        result = await index_repository(
            repo_path=path,
            incremental=incremental,
            languages=languages,
        )
    except IndexAlreadyRunningError:
        return {
            "error": "An indexing operation is already in progress. "
            "Please wait for it to finish before starting another.",
            "status": "busy",
        }

    # Auto-start file watcher for this repo
    from codelattice.indexer.watcher import start_watching

    watcher_task = start_watching(path)

    out = format_index_result(result)
    if watcher_task:
        out["file_watcher"] = "active"
    return out


async def tool_refresh_index(
    path: str | None = None,
) -> dict:
    """Re-index only changed files since last index. Fast post-edit update."""
    repo = path or _get_active_repo()
    if not repo:
        return {
            "error": "No repository path provided and no active repo. Call index_repository first."
        }
    _set_active_repo(repo)
    try:
        result = await refresh_changed_files(repo_path=repo)
    except IndexAlreadyRunningError:
        return {
            "error": "An indexing operation is already in progress. "
            "Please wait for it to finish before starting another.",
            "status": "busy",
        }
    return format_index_result(result)


def _add_stale_warning(response: dict) -> dict:
    """Attach a stale warning to a search response if files have changed."""
    warning = _check_staleness()
    if warning:
        response["_stale"] = warning
    return response


async def tool_search_code(
    query: str,
    top_k: int = 10,
    language: str | None = None,
    file_pattern: str | None = None,
) -> dict:
    """Semantic search across indexed code."""
    repo_id = _get_active_repo_id()
    results = await query_builder.search_code(
        query=query,
        top_k=top_k,
        language=language,
        file_pattern=file_pattern,
        repo_id=repo_id,
    )
    response = _add_stale_warning(format_search_results(results, query))
    get_tracker().record("search_code", response, query=query)
    return response


async def tool_find_symbol(
    name: str,
    kind: str | None = None,
    include_relationships: bool = True,
) -> dict:
    """Find a specific symbol and its relationships."""
    repo_id = _get_active_repo_id()
    results = await query_builder.find_symbol(
        name=name,
        kind=kind,
        include_relationships=include_relationships,
        repo_id=repo_id,
    )
    response = _add_stale_warning(format_search_results(results, name))
    get_tracker().record("find_symbol", response, query=name)
    return response


async def tool_get_dependencies(
    target: str,
    depth: int = 1,
) -> dict:
    """Get what a file or symbol depends on."""
    repo_id = _get_active_repo_id()
    results = await query_builder.get_dependencies(target=target, depth=depth, repo_id=repo_id)
    response = _add_stale_warning(format_search_results(results, f"dependencies of {target}"))
    get_tracker().record("get_dependencies", response, query=target)
    return response


async def tool_get_dependents(
    target: str,
    depth: int = 1,
) -> dict:
    """Get what depends on a file or symbol."""
    repo_id = _get_active_repo_id()
    results = await query_builder.get_dependents(target=target, depth=depth, repo_id=repo_id)
    response = _add_stale_warning(format_search_results(results, f"dependents of {target}"))
    get_tracker().record("get_dependents", response, query=target)
    return response


async def tool_get_file_summary(path: str) -> dict:
    """Get a structural summary of a file."""
    repo_id = _get_active_repo_id()

    # Search for the CodeFile entity
    results = await semantic_search(f"file {path}", top_k=5, repo_id=repo_id)

    # Find the matching file
    for r in results:
        if r.file_path and (r.file_path == path or r.file_path.endswith(path)):
            response = {
                "file": r.file_path,
                "summary": r.signature or r.docstring or "",
                "kind": r.kind,
            }
            get_tracker().record("get_file_summary", response, query=path)
            return response

    # Fallback: search for all entities in that file
    all_results = await semantic_search(path, top_k=30, repo_id=repo_id)
    file_entities = [r for r in all_results if r.file_path and r.file_path.endswith(path)]

    functions = [r for r in file_entities if r.kind in ("function", "method", "arrow")]
    classes = [r for r in file_entities if r.kind in ("class", "interface", "type_alias")]
    imports = [r for r in file_entities if r.kind == "import"]

    response = {
        "file": path,
        "functions": [
            {"name": f.name, "signature": f.signature, "lines": [f.start_line, f.end_line]}
            for f in functions
        ],
        "classes": [
            {"name": c.name, "signature": c.signature, "lines": [c.start_line, c.end_line]}
            for c in classes
        ],
        "imports": [{"module": i.name, "signature": i.signature} for i in imports],
    }
    get_tracker().record("get_file_summary", response, query=path)
    return response


async def tool_index_status(path: str | None = None) -> dict:
    """Check indexing status and statistics."""
    return get_index_status(repo_path=path)


async def tool_cancel_indexing() -> dict:
    """Cancel the currently running indexing operation."""
    if not is_indexing():
        return {"status": "idle", "message": "No indexing operation is currently running."}

    cancelled = request_cancel_indexing()
    if cancelled:
        return {
            "status": "cancelling",
            "message": "Cancellation requested. The indexing operation will stop after the current file.",
        }
    return {"status": "idle", "message": "No indexing operation is currently running."}


async def tool_usage_stats(days: int = 7) -> dict:
    """Get usage statistics and token savings report."""
    return get_tracker().get_summary(days=days)


async def tool_usage_stats_reset() -> dict:
    """Reset all usage statistics."""
    return get_tracker().reset()


# ---------------------------------------------------------------------------
# Advisor tools
# ---------------------------------------------------------------------------

_advisor_registry = None


async def _ensure_advisor() -> None:
    """Lazy-initialize the advisor skill registry on first use."""
    global _advisor_registry
    if _advisor_registry is not None:
        return

    from codelattice.config.settings import get_settings

    if not get_settings().codelattice_advisor_enabled:
        return

    from codelattice.advisor.registry import SkillRegistry

    _advisor_registry = SkillRegistry()
    await _advisor_registry.load_all(repo_path=_get_active_repo())


def _detect_project_frameworks() -> set[str]:
    """Detect frameworks in the active repo (reuses file_discovery)."""
    repo = _get_active_repo()
    if not repo:
        return set()
    try:
        from codelattice.indexer.file_discovery import _detect_frameworks

        return _detect_frameworks(Path(repo))
    except Exception:
        return set()


async def tool_advise(query: str, top_k: int = 3) -> dict:
    """Get best-practice advice relevant to a query.

    Matches the query against loaded skills using semantic similarity
    and returns relevant framework, pattern, or principle guidance.
    """
    await _ensure_advisor()
    if _advisor_registry is None:
        return {"error": "Advisor is disabled. Set CODELATTICE_ADVISOR_ENABLED=true to enable."}

    from codelattice.advisor.formatter import format_advise_response
    from codelattice.config.settings import get_settings

    frameworks = _detect_project_frameworks()
    matches = await _advisor_registry.match(query, top_k=top_k, project_frameworks=frameworks)

    response = format_advise_response(
        matches, query, min_similarity=get_settings().codelattice_advisor_min_similarity
    )

    if frameworks:
        response["detected_frameworks"] = sorted(frameworks)

    get_tracker().record("advise", response, query=query)
    return response


async def tool_list_skills() -> dict:
    """List all loaded advisor skills with metadata."""
    await _ensure_advisor()
    if _advisor_registry is None:
        return {"error": "Advisor is disabled. Set CODELATTICE_ADVISOR_ENABLED=true to enable."}

    from codelattice.advisor.formatter import format_skill_list

    response = format_skill_list(_advisor_registry.skills)
    if _advisor_registry.conflicts:
        response["conflicts"] = _advisor_registry.conflicts

    return response
