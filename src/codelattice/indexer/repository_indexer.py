"""Orchestrates repository indexing: discovery, parsing, ingestion, state tracking."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from codelattice.config.settings import get_settings
from codelattice.graph.ingester import build_data_points, ingest_data_points
from codelattice.indexer.file_discovery import DiscoveredFile, discover_files
from codelattice.indexer.file_hasher import hash_file
from codelattice.indexer.incremental_state import IncrementalState
from codelattice.parser.tree_sitter_parser import parse_file

logger = logging.getLogger(__name__)

# Per-repo locks — allows concurrent indexing of different repos while
# preventing concurrent indexing of the same repo.
_index_locks: dict[str, asyncio.Lock] = {}

# Set to True to request cancellation of the current indexing operation.
_cancel_requested = False


def _get_index_lock(repo_id: str) -> asyncio.Lock:
    """Get or create an asyncio.Lock for a specific repo."""
    if repo_id not in _index_locks:
        _index_locks[repo_id] = asyncio.Lock()
    return _index_locks[repo_id]


def request_cancel_indexing() -> bool:
    """Request cancellation of the currently running indexing operation.

    Returns True if an indexing operation was running and cancellation was
    requested, False if nothing was running.
    """
    global _cancel_requested
    if any(lock.locked() for lock in _index_locks.values()):
        _cancel_requested = True
        logger.info("Indexing cancellation requested")
        return True
    return False


def is_indexing() -> bool:
    """Return True if any indexing operation is currently in progress."""
    return any(lock.locked() for lock in _index_locks.values())


class IndexAlreadyRunningError(Exception):
    """Raised when an indexing operation is already in progress."""

    pass


class IndexCancelledError(Exception):
    """Raised when an indexing operation is cancelled by the user."""

    pass


# ---------------------------------------------------------------------------
# PID-based lock file so CLI commands can detect a running MCP server.
# ---------------------------------------------------------------------------


def _get_pid_lock_path() -> Path:
    """Return the path to the CodeLattice server PID lock file."""
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings.data_dir / "codelattice_server.pid"


def write_server_pid_lock() -> None:
    """Write the current PID to the lock file (called by the MCP server on startup)."""
    _get_pid_lock_path().write_text(str(os.getpid()))
    logger.info("Wrote server PID lock: %s (pid=%d)", _get_pid_lock_path(), os.getpid())


def remove_server_pid_lock() -> None:
    """Remove the PID lock file (called by the MCP server on shutdown)."""
    lock = _get_pid_lock_path()
    try:
        lock.unlink(missing_ok=True)
    except OSError:
        pass


def is_server_running() -> tuple[bool, int | None]:
    """Check if an CodeLattice MCP server is currently running.

    Returns:
        (is_running, pid) — pid is None if no lock file or process is dead.
    """
    lock = _get_pid_lock_path()
    if not lock.exists():
        return False, None
    try:
        pid = int(lock.read_text().strip())
        # Check if process is alive (signal 0 doesn't kill, just checks)
        os.kill(pid, 0)
        return True, pid
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        # Stale lock file — process is gone
        lock.unlink(missing_ok=True)
        return False, None


@dataclass
class IndexResult:
    """Result of an indexing operation."""

    repo_id: str
    repo_path: str
    new_files: int = 0
    changed_files: int = 0
    deleted_files: int = 0
    unchanged_files: int = 0
    total_entities: int = 0
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    cancelled: bool = False


def _make_repo_id(repo_path: Path) -> str:
    """Generate a stable repo ID from the absolute path."""
    return hashlib.sha256(str(repo_path.resolve()).encode()).hexdigest()[:16]


def _get_state_db() -> IncrementalState:
    """Get or create the incremental state database."""
    settings = get_settings()
    db_path = settings.data_dir / "codelattice_state.db"
    return IncrementalState(db_path)


async def index_repository(
    repo_path: str | Path,
    incremental: bool = True,
    languages: list[str] | None = None,
) -> IndexResult:
    """Index or re-index a code repository.

    Only one indexing operation can run at a time within a process.  If
    another call is already in progress, this raises
    ``IndexAlreadyRunningError`` rather than blocking.

    Args:
        repo_path: Path to the repository root.
        incremental: If True, only process changed files.
        languages: Optional language filter.

    Returns:
        IndexResult with statistics.

    Raises:
        IndexAlreadyRunningError: If another indexing operation is in progress.
    """
    global _cancel_requested

    repo_path_resolved = Path(repo_path).resolve()
    repo_id = _make_repo_id(repo_path_resolved)
    lock = _get_index_lock(repo_id)

    if lock.locked():
        raise IndexAlreadyRunningError(
            f"Indexing is already in progress for {repo_path_resolved}. "
            "Wait for it to finish or cancel it before starting another."
        )

    _cancel_requested = False
    async with lock:
        try:
            return await _index_repository_impl(
                repo_path=repo_path,
                incremental=incremental,
                languages=languages,
            )
        finally:
            _cancel_requested = False


async def _index_repository_impl(
    repo_path: str | Path,
    incremental: bool = True,
    languages: list[str] | None = None,
) -> IndexResult:
    """Inner implementation of index_repository (runs under _index_lock)."""
    start_time = time.time()
    repo_path = Path(repo_path).resolve()
    repo_id = _make_repo_id(repo_path)
    settings = get_settings()
    state = _get_state_db()

    result = IndexResult(repo_id=repo_id, repo_path=str(repo_path))

    try:
        # Discover files
        discovered = discover_files(
            repo_path,
            languages=languages,
            max_file_size_kb=settings.codelattice_max_file_size_kb,
        )
        current_files = {f.relative_path: f for f in discovered}

        # Get stored state
        stored_files = state.get_all_files(repo_id) if incremental else {}

        # Classify files
        current_paths = set(current_files.keys())
        stored_paths = set(stored_files.keys())

        new_paths = current_paths - stored_paths
        deleted_paths = stored_paths - current_paths
        common_paths = current_paths & stored_paths

        # Detect changed files
        changed_paths = set()
        for path in common_paths:
            file_hash = hash_file(current_files[path].path)
            if file_hash != stored_files[path].content_hash:
                changed_paths.add(path)

        unchanged_paths = common_paths - changed_paths

        result.new_files = len(new_paths)
        result.changed_files = len(changed_paths)
        result.deleted_files = len(deleted_paths)
        result.unchanged_files = len(unchanged_paths)

        # Process deletions
        for path in deleted_paths:
            try:
                state.remove_file(repo_id, path)
            except Exception as e:
                result.errors.append(f"Error removing {path}: {e}")

        # Process changed files (remove old entities first)
        for path in changed_paths:
            try:
                state.remove_file(repo_id, path)
            except Exception as e:
                result.errors.append(f"Error removing old state for {path}: {e}")

        # Process new + changed files
        files_to_index = [current_files[p] for p in sorted(new_paths | changed_paths)]

        total_entities = 0
        batch: list = []
        batch_size = settings.codelattice_batch_size

        for i, discovered_file in enumerate(files_to_index, 1):
            # --- Cancellation check (between files) ---
            if _cancel_requested:
                result.cancelled = True
                result.errors.append(f"Cancelled after {i - 1}/{len(files_to_index)} files")
                logger.info("Indexing cancelled after %d/%d files", i - 1, len(files_to_index))
                break

            file_start = time.time()
            try:
                parse_result = parse_file(
                    discovered_file.path,
                    discovered_file.language,
                )
                if parse_result.error:
                    result.errors.append(
                        f"Parse error in {discovered_file.relative_path}: {parse_result.error}"
                    )
                    # Continue with partial results if we got any entities
                    if not parse_result.entities:
                        continue

                # Use relative path in parse result for consistency
                parse_result.file_path = Path(discovered_file.relative_path)

                data_points, entity_map = build_data_points(parse_result, repo_id)
                batch.extend(data_points)
                total_entities += len(data_points)

                # Record file state
                file_hash = hash_file(discovered_file.path)
                state.record_file(
                    repo_id,
                    discovered_file.relative_path,
                    file_hash,
                    discovered_file.language,
                    len(data_points),
                )
                state.record_entities(repo_id, discovered_file.relative_path, entity_map)

                # Flush batch if large enough
                if len(batch) >= batch_size:
                    if _cancel_requested:
                        result.cancelled = True
                        result.errors.append(
                            f"Cancelled before ingestion at {i}/{len(files_to_index)} files"
                        )
                        break
                    await ingest_data_points(batch, repo_id=repo_id)
                    logger.info("Ingested batch (%d/%d files processed)", i, len(files_to_index))
                    batch = []

            except Exception as e:
                result.errors.append(f"Error indexing {discovered_file.relative_path}: {e}")
                logger.exception("Error indexing %s", discovered_file.relative_path)
            finally:
                elapsed = time.time() - file_start
                if elapsed > 5.0:
                    logger.warning(
                        "Slow file: %s took %.1fs to process",
                        discovered_file.relative_path,
                        elapsed,
                    )

        # Flush remaining batch (skip if cancelled)
        if batch and not _cancel_requested:
            await ingest_data_points(batch, repo_id=repo_id)

        result.total_entities = total_entities

        # Update repo stats
        all_files = state.get_all_files(repo_id)
        total_file_count = len(all_files)
        total_entity_count = sum(f.entity_count for f in all_files.values())
        state.record_repo(repo_id, str(repo_path), total_file_count, total_entity_count)

    finally:
        state.close()
        result.duration_seconds = time.time() - start_time

    return result


def detect_stale_files(repo_path: str | Path) -> dict:
    """Quickly check which indexed files have changed since last index.

    Only compares hashes — does NOT re-parse or re-ingest.

    Returns:
        Dict with stale file info: {is_stale, changed, new, deleted, total_indexed}.
    """
    repo_path = Path(repo_path).resolve()
    repo_id = _make_repo_id(repo_path)
    settings = get_settings()
    state = _get_state_db()

    try:
        stored_files = state.get_all_files(repo_id)
        if not stored_files:
            return {"is_stale": True, "reason": "not_indexed", "total_indexed": 0}

        discovered = discover_files(
            repo_path,
            max_file_size_kb=settings.codelattice_max_file_size_kb,
        )
        current_files = {f.relative_path: f for f in discovered}
        current_paths = set(current_files.keys())
        stored_paths = set(stored_files.keys())

        new_paths = current_paths - stored_paths
        deleted_paths = stored_paths - current_paths
        common_paths = current_paths & stored_paths

        changed_paths = set()
        for path in common_paths:
            file_hash = hash_file(current_files[path].path)
            if file_hash != stored_files[path].content_hash:
                changed_paths.add(path)

        is_stale = bool(new_paths or deleted_paths or changed_paths)
        return {
            "is_stale": is_stale,
            "changed": sorted(changed_paths),
            "new": sorted(new_paths),
            "deleted": sorted(deleted_paths),
            "total_indexed": len(stored_files),
        }
    finally:
        state.close()


async def refresh_changed_files(repo_path: str | Path) -> IndexResult:
    """Re-index only the files that have changed since last index.

    This is a convenience wrapper around index_repository with incremental=True,
    designed to be called after code edits for fast knowledge base updates.
    """
    return await index_repository(repo_path=repo_path, incremental=True)


def get_index_status(repo_path: str | Path | None = None) -> dict:
    """Get indexing status and statistics.

    Args:
        repo_path: Optional path to check a specific repo.

    Returns:
        Status dict with stats.
    """
    state = _get_state_db()
    try:
        if repo_path:
            repo_path = Path(repo_path).resolve()
            repo_id = _make_repo_id(repo_path)
            stats = state.get_repo_stats(repo_id)
            if not stats:
                return {"indexed": False, "repo_path": str(repo_path)}

            files = state.get_all_files(repo_id)
            language_counts: dict[str, int] = {}
            for f in files.values():
                language_counts[f.language] = language_counts.get(f.language, 0) + 1

            return {
                "indexed": True,
                "repo_path": stats["repo_path"],
                "repo_id": repo_id,
                "total_files": stats["total_files"],
                "total_entities": stats["total_entities"],
                "last_indexed_at": stats["last_incremental_at"],
                "languages": language_counts,
            }
        else:
            repos = state.get_all_repos()
            return {
                "repos": [
                    {
                        "repo_path": r["repo_path"],
                        "total_files": r["total_files"],
                        "total_entities": r["total_entities"],
                        "last_indexed_at": r["last_incremental_at"],
                    }
                    for r in repos
                ]
            }
    finally:
        state.close()
