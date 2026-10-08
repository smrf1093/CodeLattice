"""File watcher for automatic background re-indexing on code changes."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from codelattice.parser.languages import EXTENSION_TO_LANGUAGE

logger = logging.getLogger(__name__)

# Debounce: wait this many seconds after last change before re-indexing
DEBOUNCE_SECONDS = 2.0

_watcher_tasks: dict[str, asyncio.Task] = {}


def _is_indexable_file(path: str) -> bool:
    """Check if a changed file is one we care about (supported language)."""
    return Path(path).suffix.lower() in EXTENSION_TO_LANGUAGE


async def _debounced_reindex(repo_path: str, debounce: float = DEBOUNCE_SECONDS) -> None:
    """Wait for changes to settle, then trigger incremental re-index."""
    await asyncio.sleep(debounce)
    try:
        from codelattice.indexer.repository_indexer import refresh_changed_files

        logger.info("File watcher triggering re-index for %s", repo_path)
        result = await refresh_changed_files(repo_path)
        logger.info(
            "Watcher re-index complete: %d new, %d changed, %d deleted (%.1fs)",
            result.new_files,
            result.changed_files,
            result.deleted_files,
            result.duration_seconds,
        )
    except Exception:
        logger.exception("Watcher re-index failed for %s", repo_path)


async def watch_repository(repo_path: str | Path) -> None:
    """Watch a repository for file changes and trigger automatic re-indexing.

    Uses watchfiles (Rust-backed) for efficient OS-level file watching.
    Changes are debounced — multiple rapid edits result in a single re-index.

    This coroutine runs indefinitely until cancelled.
    """
    try:
        from watchfiles import Change, awatch
    except ImportError:
        logger.warning(
            "watchfiles not installed — file watcher disabled. Install with: pip install watchfiles"
        )
        return

    repo_path = Path(repo_path).resolve()
    repo_str = str(repo_path)
    pending_task: asyncio.Task | None = None

    logger.info("File watcher started for %s", repo_str)

    try:
        async for changes in awatch(repo_str):
            # Filter to only indexable source files
            relevant = [
                (change_type, path) for change_type, path in changes if _is_indexable_file(path)
            ]
            if not relevant:
                continue

            change_summary = []
            for change_type, path in relevant:
                rel = str(Path(path).relative_to(repo_path))
                if change_type == Change.added:
                    change_summary.append(f"  + {rel}")
                elif change_type == Change.modified:
                    change_summary.append(f"  ~ {rel}")
                elif change_type == Change.deleted:
                    change_summary.append(f"  - {rel}")

            logger.info(
                "File changes detected (%d files):\n%s",
                len(relevant),
                "\n".join(change_summary),
            )

            # Cancel any pending debounced re-index and restart the timer
            if pending_task and not pending_task.done():
                pending_task.cancel()

            pending_task = asyncio.create_task(_debounced_reindex(repo_str))

    except asyncio.CancelledError:
        logger.info("File watcher stopped for %s", repo_str)
        if pending_task and not pending_task.done():
            pending_task.cancel()
        raise


def start_watching(repo_path: str | Path) -> asyncio.Task | None:
    """Start watching a repository in the background.

    Returns the asyncio Task, or None if watchfiles is not installed.
    Safe to call multiple times — only one watcher per repo path.
    """
    repo_str = str(Path(repo_path).resolve())

    # Don't start duplicate watchers
    existing = _watcher_tasks.get(repo_str)
    if existing and not existing.done():
        logger.debug("Watcher already running for %s", repo_str)
        return existing

    try:
        import watchfiles  # noqa: F401
    except ImportError:
        logger.info("watchfiles not installed, skipping file watcher")
        return None

    task = asyncio.create_task(watch_repository(repo_str))
    _watcher_tasks[repo_str] = task
    return task


def stop_watching(repo_path: str | Path) -> None:
    """Stop watching a repository."""
    repo_str = str(Path(repo_path).resolve())
    task = _watcher_tasks.pop(repo_str, None)
    if task and not task.done():
        task.cancel()
        logger.info("Stopped file watcher for %s", repo_str)


def stop_all_watchers() -> None:
    """Stop all active file watchers."""
    for repo_str, task in _watcher_tasks.items():
        if not task.done():
            task.cancel()
    _watcher_tasks.clear()
