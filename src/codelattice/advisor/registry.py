"""Skill registry with conflict detection and semantic matching."""

from __future__ import annotations

import logging
from pathlib import Path

from codelattice.advisor.loader import discover_skills
from codelattice.advisor.models import MatchResult, Skill

logger = logging.getLogger(__name__)


class SkillRegistry:
    """In-memory registry of loaded skills with conflict detection."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}  # name -> Skill
        self._domain_index: dict[str, list[str]] = {}  # domain -> [skill_names]
        self._conflicts: list[str] = []
        self._matcher: _SkillMatcher | None = None

    @property
    def skills(self) -> dict[str, Skill]:
        return dict(self._skills)

    @property
    def conflicts(self) -> list[str]:
        return list(self._conflicts)

    def register(self, skill: Skill) -> None:
        """Register a skill, handling name conflicts by priority."""
        existing = self._skills.get(skill.name)
        if existing:
            if skill.priority > existing.priority:
                msg = (
                    f"Skill name conflict: {skill.name!r} from {skill.source} "
                    f"(priority {skill.priority}) overrides {existing.source} "
                    f"(priority {existing.priority})"
                )
                logger.warning(msg)
                self._conflicts.append(msg)
                # Remove old skill's domains before replacing
                self._remove_from_domain_index(existing)
                self._skills[skill.name] = skill
                self._add_to_domain_index(skill)
            else:
                msg = (
                    f"Skill name conflict: {skill.name!r} from {skill.source} "
                    f"(priority {skill.priority}) dropped in favour of {existing.source} "
                    f"(priority {existing.priority})"
                )
                logger.warning(msg)
                self._conflicts.append(msg)
        else:
            self._skills[skill.name] = skill
            self._add_to_domain_index(skill)

    def _add_to_domain_index(self, skill: Skill) -> None:
        for domain in skill.domains:
            self._domain_index.setdefault(domain, []).append(skill.name)

    def _remove_from_domain_index(self, skill: Skill) -> None:
        for domain in skill.domains:
            names = self._domain_index.get(domain, [])
            if skill.name in names:
                names.remove(skill.name)

    def detect_domain_overlaps(self) -> list[str]:
        """Detect skills in the same category with >50% domain overlap."""
        warnings = []
        names = list(self._skills.keys())
        for i, name_a in enumerate(names):
            for name_b in names[i + 1 :]:
                skill_a = self._skills[name_a]
                skill_b = self._skills[name_b]
                if skill_a.category != skill_b.category:
                    continue
                domains_a = set(skill_a.domains)
                domains_b = set(skill_b.domains)
                if not domains_a or not domains_b:
                    continue
                overlap = domains_a & domains_b
                smaller = min(len(domains_a), len(domains_b))
                if smaller > 0 and len(overlap) / smaller > 0.5:
                    msg = (
                        f"Domain overlap: {name_a!r} and {name_b!r} "
                        f"(category={skill_a.category!r}) share domains {overlap}"
                    )
                    logger.warning(msg)
                    warnings.append(msg)
        return warnings

    async def load_all(self, repo_path: str | Path | None = None) -> None:
        """Discover and register all skills, then initialize the matcher."""
        all_skills = discover_skills(repo_path=repo_path)
        for skill in all_skills:
            self.register(skill)

        # Detect domain overlaps (non-fatal warnings)
        overlap_warnings = self.detect_domain_overlaps()
        self._conflicts.extend(overlap_warnings)

        logger.info(
            "Loaded %d skills (%d conflicts)",
            len(self._skills),
            len(self._conflicts),
        )

        # Initialize the semantic matcher
        from codelattice.advisor.matcher import SkillMatcher

        self._matcher = SkillMatcher(list(self._skills.values()))
        await self._matcher.initialize()

    async def match(
        self,
        query: str,
        top_k: int = 3,
        project_frameworks: set[str] | None = None,
    ) -> list[MatchResult]:
        """Match a query against registered skills using semantic similarity."""
        if not self._matcher:
            return []

        results = await self._matcher.match(
            query, top_k=top_k, project_frameworks=project_frameworks
        )

        # Expand depends-on: if top result has dependencies, boost or inject them
        if results:
            primary = results[0]
            dep_names = set(primary.skill.depends_on)
            if dep_names:
                boosted_score = primary.score * 0.8
                # Check if dependency is already in results — boost its score
                for r in results:
                    if r.skill.name in dep_names:
                        r.score = max(r.score, boosted_score)
                        r.reasons.append(f"dependency of {primary.skill.name}")
                        dep_names.discard(r.skill.name)
                # Inject any dependencies not already in results
                for dep_name in dep_names:
                    dep_skill = self._skills.get(dep_name)
                    if dep_skill:
                        results.append(
                            MatchResult(
                                skill=dep_skill,
                                score=boosted_score,
                                reasons=[f"dependency of {primary.skill.name}"],
                            )
                        )
                # Re-sort after boosting
                results.sort(key=lambda r: r.score, reverse=True)

        return results
