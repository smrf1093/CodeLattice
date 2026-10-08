"""Data models for the advisor skill system."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Valid skill name pattern: lowercase alphanumeric + hyphens, no leading/trailing/consecutive hyphens
_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
_VALID_CATEGORIES = {"framework", "principle", "pattern", "tool", "custom"}


@dataclass
class Skill:
    """A parsed SKILL.md with validated frontmatter and body content."""

    name: str
    description: str
    category: str
    domains: list[str]
    body: str
    source: str  # "builtin" | "user" | "project"
    path: Path

    # Optional fields with defaults
    triggers: list[str] = field(default_factory=list)
    priority: int = 50
    depends_on: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Validate name
        if not self.name or len(self.name) > 64:
            raise ValueError(f"Skill name must be 1-64 characters, got: {self.name!r}")
        if "--" in self.name:
            raise ValueError(f"Skill name must not contain consecutive hyphens: {self.name!r}")
        if not _NAME_RE.match(self.name):
            raise ValueError(f"Skill name must be lowercase alphanumeric + hyphens: {self.name!r}")

        # Validate description
        if not self.description or len(self.description) > 1024:
            raise ValueError("Skill description must be 1-1024 characters")

        # Validate category
        if self.category not in _VALID_CATEGORIES:
            raise ValueError(
                f"Skill category must be one of {_VALID_CATEGORIES}, got: {self.category!r}"
            )

        # Validate domains
        if not self.domains:
            raise ValueError("Skill must have at least one domain")

        # Clamp priority
        self.priority = max(0, min(100, self.priority))


@dataclass
class MatchResult:
    """A skill matched to a query with scoring details."""

    skill: Skill
    score: float
    reasons: list[str] = field(default_factory=list)
