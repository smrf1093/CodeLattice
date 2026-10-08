"""Discovers and parses SKILL.md files from multiple locations."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from codelattice.advisor.models import Skill
from codelattice.config.settings import get_settings

logger = logging.getLogger(__name__)

# Priority boosts by source location
_SOURCE_BOOST = {
    "builtin": 0,
    "user": 10,
    "project": 20,
}


def _builtin_skills_dir() -> Path:
    """Return the path to built-in skills shipped with CodeLattice."""
    return Path(__file__).parent / "skills"


def _user_skills_dir() -> Path:
    """Return the path to user-installed skills (~/.codelattice/skills/)."""
    return get_settings().data_dir / "skills"


def _project_skills_dir(repo_path: str | Path) -> Path:
    """Return the path to project-specific skills ({repo}/.codelattice/skills/)."""
    return Path(repo_path) / ".codelattice" / "skills"


def parse_skill_md(path: Path, source: str) -> Skill:
    """Parse a SKILL.md file into a Skill instance.

    Args:
        path: Path to the SKILL.md file.
        source: One of "builtin", "user", "project".

    Returns:
        Parsed Skill instance.

    Raises:
        ValueError: If frontmatter is missing or invalid.
    """
    content = path.read_text(encoding="utf-8")

    # Split YAML frontmatter from body
    if not content.startswith("---"):
        raise ValueError(f"SKILL.md must start with YAML frontmatter (---): {path}")

    parts = content.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"SKILL.md must have closing --- for frontmatter: {path}")

    frontmatter_str = parts[1].strip()
    body = parts[2].strip()

    frontmatter = yaml.safe_load(frontmatter_str)
    if not isinstance(frontmatter, dict):
        raise ValueError(f"SKILL.md frontmatter must be a YAML mapping: {path}")

    # Extract fields
    name = frontmatter.get("name", "")
    description = frontmatter.get("description", "")
    category = frontmatter.get("category", "custom")
    domains = frontmatter.get("domains", [])
    triggers = frontmatter.get("triggers", [])
    priority = frontmatter.get("priority", 50)
    depends_on = frontmatter.get("depends-on", [])
    metadata = frontmatter.get("metadata", {})

    # Ensure list types
    if isinstance(domains, str):
        domains = [domains]
    if isinstance(triggers, str):
        triggers = [triggers]
    if isinstance(depends_on, str):
        depends_on = [depends_on]

    # Apply source priority boost
    priority = min(100, priority + _SOURCE_BOOST.get(source, 0))

    return Skill(
        name=name,
        description=description,
        category=category,
        domains=domains,
        triggers=triggers,
        priority=priority,
        depends_on=depends_on,
        body=body,
        source=source,
        path=path,
        metadata=metadata,
    )


def _scan_directory(directory: Path, source: str) -> list[Skill]:
    """Scan a directory for */SKILL.md files and parse them."""
    skills = []
    if not directory.exists():
        return skills

    for child in sorted(directory.iterdir()):
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.exists():
            continue
        try:
            skill = parse_skill_md(skill_md, source)
            # Validate name matches directory name
            if skill.name != child.name:
                logger.warning(
                    "Skill name %r doesn't match directory name %r in %s, skipping",
                    skill.name,
                    child.name,
                    skill_md,
                )
                continue
            skills.append(skill)
        except Exception as e:
            logger.warning("Failed to parse %s: %s", skill_md, e)

    return skills


def discover_skills(repo_path: str | Path | None = None) -> list[Skill]:
    """Discover all skills from built-in, user, and project locations.

    Skills are returned in priority order (builtin first, project last).
    The registry handles conflict resolution.

    Args:
        repo_path: Optional path to the active repository for project skills.

    Returns:
        List of all discovered Skill instances.
    """
    all_skills: list[Skill] = []

    # 1. Built-in skills
    builtin = _scan_directory(_builtin_skills_dir(), "builtin")
    logger.info("Discovered %d built-in skills", len(builtin))
    all_skills.extend(builtin)

    # 2. User skills
    user = _scan_directory(_user_skills_dir(), "user")
    if user:
        logger.info("Discovered %d user skills", len(user))
    all_skills.extend(user)

    # 3. Project skills
    if repo_path:
        project = _scan_directory(_project_skills_dir(repo_path), "project")
        if project:
            logger.info("Discovered %d project skills from %s", len(project), repo_path)
        all_skills.extend(project)

    return all_skills
