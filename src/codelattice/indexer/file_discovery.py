"""Gitignore-aware file discovery for code repositories.

Includes framework-aware exclusions so that generated / collected assets
from Django, Flask, FastAPI, React, Next.js, Nuxt.js, NestJS, Express,
and generic Node.js projects are not indexed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pathspec

from codelattice.parser.languages import EXTENSION_TO_LANGUAGE

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Always-excluded directories (safe for any project)
# ---------------------------------------------------------------------------

DEFAULT_EXCLUDES = {
    # Package managers / dependencies
    "node_modules",
    "bower_components",
    "site-packages",
    # Python caches & build
    "__pycache__",
    ".eggs",
    ".egg-info",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    # Virtual environments
    ".venv",
    "venv",
    # Version control
    ".git",
    # Build outputs
    "dist",
    "build",
    "out",
    "output",
    ".output",
    "target",
    # Framework caches / generated
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".turbo",
    ".parcel-cache",
    ".cache",
    "coverage",
    ".nyc_output",
    # Static / collected assets (Django collectstatic)
    "staticfiles",
    "static_root",
    "static_collected",
    "staticfiles_collected",
    # IDE / editor
    ".idea",
    ".vscode",
    # Rust / Java / Go
    ".gradle",
    ".cargo",
    # Deployment platform artifacts
    ".vercel",
    ".serverless",
    ".aws-sam",
    ".firebase",
    ".netlify",
    ".amplify",
    "cdk.out",
    # Node.js package manager caches
    ".yarn",
    ".pnp",
    ".pnpm-store",
    # Misc generated / non-code
    "logs",
    "temp",
    "tmp",
    "storybook-static",
    ".storybook",
    "typings",
}

# ---------------------------------------------------------------------------
# Filenames that are never worth indexing (lock files, generated decls, etc.)
# These are checked by exact filename match (case-sensitive).
# ---------------------------------------------------------------------------

_SKIP_FILENAMES = {
    # Lock files
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "bun.lockb",
    "bun.lock",
    # Auto-generated type declarations
    "next-env.d.ts",
    "react-app-env.d.ts",
    # Generated manifests / stats
    "staticfiles.json",
    "webpack-stats.json",
    # Alembic boilerplate
    "script.py.mako",
}

# File extensions that are never source code worth indexing.
_SKIP_EXTENSIONS = {
    ".mo",  # Compiled gettext translations
    ".pot",  # Translation templates
    ".snap",  # Jest snapshots
    ".map",  # Source maps (.js.map, .d.ts.map)
    ".tsbuildinfo",
    ".db",  # SQLite databases
    ".sqlite",
    ".sqlite3",
    ".pid",
    ".log",
    ".lock",  # Generic lock files
}

# ---------------------------------------------------------------------------
# Framework detection
# ---------------------------------------------------------------------------


def _detect_frameworks(repo_path: Path) -> set[str]:
    """Detect which frameworks are used in the project.

    Checks the repo root **and** immediate subdirectories to handle
    monorepo layouts (e.g. ``backend/manage.py``, ``frontend/package.json``).

    Returns a set of framework identifiers like
    {"django", "react", "nextjs", "nestjs", ...}.
    """
    detected: set[str] = set()

    # Gather search roots: repo root + immediate child directories.
    search_roots = [repo_path]
    try:
        search_roots.extend(
            child
            for child in repo_path.iterdir()
            if child.is_dir() and child.name not in DEFAULT_EXCLUDES
        )
    except OSError:
        pass

    for root in search_roots:
        # -- Django --
        if (root / "manage.py").exists():
            detected.add("django")

        # -- Flask / FastAPI --
        for name in ("app.py", "main.py", "wsgi.py", "application.py"):
            entry = root / name
            if entry.exists():
                try:
                    head = entry.read_text(errors="replace")[:4096]
                    if "flask" in head.lower() or "Flask(" in head:
                        detected.add("flask")
                    if "fastapi" in head.lower() or "FastAPI(" in head:
                        detected.add("fastapi")
                except OSError:
                    pass

        # -- Alembic --
        if (root / "alembic.ini").exists() or (root / "alembic").is_dir():
            detected.add("alembic")

        # -- Flask instance folder --
        if (root / "instance").is_dir():
            detected.add("flask")

        # -- Node / JS / TS frameworks --
        pkg_json = root / "package.json"
        if pkg_json.exists():
            detected.add("node")
            try:
                text = pkg_json.read_text(errors="replace")[:8192]
                if '"react"' in text:
                    detected.add("react")
                if '"next"' in text:
                    detected.add("nextjs")
                if '"nuxt"' in text:
                    detected.add("nuxtjs")
                if '"@nestjs/core"' in text:
                    detected.add("nestjs")
                if '"express"' in text:
                    detected.add("express")
            except OSError:
                pass

    return detected


# ---------------------------------------------------------------------------
# Framework-specific exclusion rules
# ---------------------------------------------------------------------------

# Directories excluded when a given framework is detected.
_FRAMEWORK_EXCLUDE_DIRS: dict[str, set[str]] = {
    "django": {
        "migrations",
        "locale",
        "fixtures",
        "media",
        "uploads",
        "webpack_bundles",
    },
    "flask": {
        "instance",
        "migrations",
        "uploads",
    },
    "fastapi": {
        "alembic",
        "migrations",
    },
    "alembic": {
        "alembic",
        "migrations",
    },
    "react": {
        "public",
        ".swc",
        ".babel_cache",
    },
    "nextjs": {
        "public",
    },
    "nuxtjs": {
        "public",
    },
    "nestjs": {
        ".prisma",
    },
    "express": {
        "public",
        "uploads",
        "seeders",
    },
    "node": set(),  # generic Node exclusions are already in DEFAULT_EXCLUDES
}

# Filename patterns excluded when a given framework is detected.
# Each value is a set of filename globs (matched with PurePath.match).
# NOTE: Most migration exclusions are handled via directory names above
# (e.g. "migrations" dir excluded entirely for Django/Flask/FastAPI).
_FRAMEWORK_EXCLUDE_PATTERNS: dict[str, set[str]] = {}


def _build_framework_excludes(
    frameworks: set[str],
) -> tuple[set[str], list[str]]:
    """Build the combined set of extra directory excludes and file patterns
    based on detected frameworks.

    Returns:
        (extra_dir_excludes, file_glob_patterns)
    """
    extra_dirs: set[str] = set()
    patterns: list[str] = []
    for fw in frameworks:
        extra_dirs |= _FRAMEWORK_EXCLUDE_DIRS.get(fw, set())
        patterns.extend(_FRAMEWORK_EXCLUDE_PATTERNS.get(fw, set()))
    return extra_dirs, patterns


# ---------------------------------------------------------------------------
# Minified / generated file detection
# ---------------------------------------------------------------------------

# Common suffixes for minified / bundled files.
_MINIFIED_SUFFIXES = (".min.js", ".min.css", ".bundle.js", ".chunk.js")

# Average line length threshold — files exceeding this are almost certainly
# minified or generated.
_MAX_AVG_LINE_LENGTH = 500


def _is_minified(file_path: Path, sample_bytes: int = 4096) -> bool:
    """Quick heuristic check for minified / generated files."""
    name = file_path.name.lower()
    if any(name.endswith(s) for s in _MINIFIED_SUFFIXES):
        return True
    try:
        head = file_path.read_bytes()[:sample_bytes]
        lines = head.split(b"\n")
        if len(lines) <= 1 and len(head) > 1000:
            return True  # Single giant line
        avg = len(head) / max(len(lines), 1)
        if avg > _MAX_AVG_LINE_LENGTH:
            return True
    except OSError:
        pass
    return False


# ---------------------------------------------------------------------------
# Gitignore loading
# ---------------------------------------------------------------------------


@dataclass
class DiscoveredFile:
    """A source file found during discovery."""

    path: Path
    relative_path: str
    language: str


def _load_gitignore(repo_path: Path) -> pathspec.PathSpec | None:
    """Load .gitignore patterns from the repository root."""
    gitignore = repo_path / ".gitignore"
    if not gitignore.exists():
        return None
    try:
        patterns = gitignore.read_text().splitlines()
        return pathspec.PathSpec.from_lines("gitwildmatch", patterns)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def discover_files(
    repo_path: Path,
    languages: list[str] | None = None,
    max_file_size_kb: int = 500,
) -> list[DiscoveredFile]:
    """Walk a repository and discover indexable source files.

    Automatically detects frameworks used in the project and applies
    appropriate exclusion rules for generated / collected files.

    Args:
        repo_path: Absolute path to the repository root.
        languages: Optional filter for specific languages.
        max_file_size_kb: Skip files larger than this (in KB).

    Returns:
        List of discovered source files.
    """
    repo_path = Path(repo_path).resolve()
    gitignore_spec = _load_gitignore(repo_path)
    max_bytes = max_file_size_kb * 1024

    # Detect frameworks and build exclusion rules
    frameworks = _detect_frameworks(repo_path)
    if frameworks:
        logger.info("Detected frameworks: %s", ", ".join(sorted(frameworks)))
    fw_extra_dirs, fw_patterns = _build_framework_excludes(frameworks)
    all_excluded_dirs = DEFAULT_EXCLUDES | fw_extra_dirs

    allowed_extensions = set(EXTENSION_TO_LANGUAGE.keys())
    if languages:
        allowed_extensions = {
            ext for ext, lang in EXTENSION_TO_LANGUAGE.items() if lang in languages
        }

    discovered: list[DiscoveredFile] = []

    for file_path in repo_path.rglob("*"):
        if not file_path.is_file():
            continue

        # Check directory excludes (default + framework-specific)
        parts = file_path.relative_to(repo_path).parts
        if any(p in all_excluded_dirs for p in parts):
            continue

        # Check extension — first against skip-extensions, then allowed
        ext = file_path.suffix.lower()
        if ext in _SKIP_EXTENSIONS:
            continue
        if ext not in allowed_extensions:
            continue

        # Check exact filename excludes
        if file_path.name in _SKIP_FILENAMES:
            continue

        # Check gitignore
        rel = str(file_path.relative_to(repo_path))
        if gitignore_spec and gitignore_spec.match_file(rel):
            continue

        # Check file size
        try:
            if file_path.stat().st_size > max_bytes:
                continue
        except OSError:
            continue

        # Skip minified / bundled files
        if _is_minified(file_path):
            continue

        # Check framework-specific file patterns (glob-style)
        if fw_patterns:
            from pathlib import PurePosixPath

            rel_posix = PurePosixPath(rel)
            if any(rel_posix.match(pat) for pat in fw_patterns):
                continue

        language = EXTENSION_TO_LANGUAGE[ext]
        discovered.append(
            DiscoveredFile(
                path=file_path,
                relative_path=rel,
                language=language,
            )
        )

    return discovered
