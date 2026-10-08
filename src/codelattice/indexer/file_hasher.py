"""Content hashing for file change detection."""

from __future__ import annotations

import hashlib
from pathlib import Path


def hash_file(path: Path) -> str:
    """Compute SHA-256 hash of file contents."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
