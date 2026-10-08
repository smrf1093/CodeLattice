"""FastMCP server definition and tool registration for Claude CLI."""

from __future__ import annotations

import logging
import sys
from contextlib import redirect_stdout

# CRITICAL: Apply Cognee env vars BEFORE any Cognee module is imported.
# Cognee's EmbeddingConfig uses @lru_cache and reads env vars on first
# access.  If we don't set EMBEDDING_PROVIDER=fastembed early, Cognee
# defaults to OpenAI and the embedding engine gets stuck in infinite
# retry loops when no API key is set.
from codelattice.config.settings import apply_cognee_env

apply_cognee_env()

from mcp.server.fastmcp import FastMCP

from codelattice.server import tools

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "CodeLattice",
    json_response=True,
)

_initialized = False


async def _ensure_init():
    """Lazy initialization of Cognee configuration and database."""
    global _initialized
    if not _initialized:
        # apply_cognee_env() already called at module import time.
        # Create Cognee's internal tables (users, permissions, etc.)
        # Required before add_data_points or search can work.
        try:
            from cognee.infrastructure.databases.relational import get_relational_engine

            engine = get_relational_engine()
            await engine.create_database()
        except Exception as e:
            logger.warning("Failed to create Cognee DB tables: %s", e)
        _initialized = True


@mcp.tool()
async def index_repository(
    path: str,
    incremental: bool = True,
    languages: list[str] | None = None,
) -> dict:
    """Index or re-index a code repository into the knowledge graph.

    Args:
        path: Absolute path to the repository root.
        incremental: If True, only re-index changed files (default True).
        languages: Filter by languages. Options: "python", "typescript", "javascript".

    Returns:
        Summary with file counts, entity counts, and duration.
    """
    with redirect_stdout(sys.stderr):
        await _ensure_init()
        return await tools.tool_index_repository(
            path=path, incremental=incremental, languages=languages
        )


@mcp.tool()
async def refresh_index(
    path: str | None = None,
) -> dict:
    """Re-index only files that changed since last index. Call this after making
    code edits to keep the knowledge base up to date. Fast — only processes
    modified, new, or deleted files.

    Args:
        path: Repository path. If omitted, uses the last indexed repository.

    Returns:
        Summary of what was re-indexed (changed/new/deleted file counts).
    """
    with redirect_stdout(sys.stderr):
        await _ensure_init()
        return await tools.tool_refresh_index(path=path)


@mcp.tool()
async def search_code(
    query: str,
    top_k: int = 10,
    language: str | None = None,
    file_pattern: str | None = None,
) -> dict:
    """Semantic search across indexed code. Use this instead of grep/glob for
    finding relevant code by meaning.

    This is the PRIMARY tool for code exploration. Use it whenever you need to
    find functions, classes, modules, or any code by description.

    Args:
        query: Natural language description of what you're looking for.
               E.g. "authentication middleware", "database connection setup".
        top_k: Maximum results to return (default 10).
        language: Filter by language: "python", "typescript", "javascript".
        file_pattern: Filter by file path glob pattern (e.g. "src/api/**").

    Returns:
        Matching code entities with file paths, line numbers, and signatures.
    """
    with redirect_stdout(sys.stderr):
        await _ensure_init()
        return await tools.tool_search_code(
            query=query, top_k=top_k, language=language, file_pattern=file_pattern
        )


@mcp.tool()
async def find_symbol(
    name: str,
    kind: str | None = None,
    include_relationships: bool = True,
) -> dict:
    """Find a specific symbol (function, class, variable) and its relationships.

    Use this when you know the name (or partial name) of a symbol. Returns
    location, signature, and dependency graph (callers/callees).

    Args:
        name: Symbol name to find (fuzzy matched).
        kind: Filter by kind: "function", "class", "method", "interface", "type", "variable".
        include_relationships: Include callers, callees, parent class, etc (default True).

    Returns:
        Symbol details with location, signature, docstring, and dependency graph.
    """
    with redirect_stdout(sys.stderr):
        await _ensure_init()
        return await tools.tool_find_symbol(
            name=name, kind=kind, include_relationships=include_relationships
        )


@mcp.tool()
async def get_dependencies(
    target: str,
    depth: int = 1,
) -> dict:
    """Get what a file or symbol depends on (imports, called functions, base classes).

    Args:
        target: File path or symbol name.
        depth: Levels of dependencies to traverse (default 1).

    Returns:
        Dependency tree showing imports, calls, and inheritance.
    """
    with redirect_stdout(sys.stderr):
        await _ensure_init()
        return await tools.tool_get_dependencies(target=target, depth=depth)


@mcp.tool()
async def get_dependents(
    target: str,
    depth: int = 1,
) -> dict:
    """Get what depends on a file or symbol (reverse dependencies / impact analysis).

    Args:
        target: File path or symbol name.
        depth: Levels of reverse dependencies (default 1).

    Returns:
        List of files/symbols that import, call, or extend the target.
    """
    with redirect_stdout(sys.stderr):
        await _ensure_init()
        return await tools.tool_get_dependents(target=target, depth=depth)


@mcp.tool()
async def get_file_summary(
    path: str,
) -> dict:
    """Get a structural summary of a file without reading its full contents.
    Shows exports, classes, functions, and imports.

    Args:
        path: File path (relative to repo root or absolute).

    Returns:
        Structured summary: functions, classes, imports, line count.
    """
    with redirect_stdout(sys.stderr):
        await _ensure_init()
        return await tools.tool_get_file_summary(path=path)


@mcp.tool()
async def index_status(
    path: str | None = None,
) -> dict:
    """Check indexing status and statistics for repositories.

    Args:
        path: Repository path to check. If None, shows all indexed repos.

    Returns:
        Index stats: file count, entity count, last indexed time, languages.
    """
    with redirect_stdout(sys.stderr):
        await _ensure_init()
        return await tools.tool_index_status(path=path)


@mcp.tool()
async def cancel_indexing() -> dict:
    """Cancel the currently running indexing operation.

    Use this when indexing is taking too long or you need to stop it.

    Returns:
        Status of the cancellation request.
    """
    with redirect_stdout(sys.stderr):
        return await tools.tool_cancel_indexing()


@mcp.tool()
async def usage_stats(
    days: int = 7,
) -> dict:
    """View token savings statistics. Shows how many tokens CodeLattice saved
    compared to traditional grep/glob/read workflows.

    Args:
        days: Number of days to include in the report (default 7).

    Returns:
        Token usage report with daily breakdown, savings percentage, and
        per-tool statistics.
    """
    with redirect_stdout(sys.stderr):
        return await tools.tool_usage_stats(days=days)


@mcp.tool()
async def advise(
    query: str,
    top_k: int = 3,
) -> dict:
    """Get best-practice advice from loaded skill guides. Returns relevant
    framework guides, design patterns, or engineering principles.

    NOTE: This is NOT for finding code in the repository. Use search_code or
    find_symbol instead for code exploration. Only use advise when you need
    reference material on frameworks, patterns, or principles (e.g. "Django
    view best practices", "when to use Strategy pattern").

    Args:
        query: Natural language description of what you need advice on.
               E.g. "how to structure Django views", "when to use Strategy pattern".
        top_k: Maximum number of skills to return (default 3).

    Returns:
        Matched skills with relevance scores. Primary match includes full
        guidance content; secondary matches include metadata only.
    """
    with redirect_stdout(sys.stderr):
        await _ensure_init()
        return await tools.tool_advise(query=query, top_k=top_k)


@mcp.tool()
async def list_skills() -> dict:
    """List all available advisor skills (reference guides, not code).

    Returns:
        List of skills with name, category, description, domains, and source.
    """
    with redirect_stdout(sys.stderr):
        await _ensure_init()
        return await tools.tool_list_skills()


def run_server(transport: str = "stdio"):
    """Run the MCP server."""
    import atexit

    from codelattice.indexer.repository_indexer import (
        remove_server_pid_lock,
        write_server_pid_lock,
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    write_server_pid_lock()
    atexit.register(remove_server_pid_lock)

    try:
        mcp.run(transport=transport)
    finally:
        remove_server_pid_lock()
