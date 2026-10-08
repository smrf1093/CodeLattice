"""Semantic skill matching using FastEmbed embeddings and cosine similarity."""

from __future__ import annotations

import logging
import math

from codelattice.advisor.models import MatchResult, Skill

logger = logging.getLogger(__name__)

# Boost constants
TRIGGER_BOOST = 0.3
FRAMEWORK_BOOST = 0.2


def _cosine_similarity(a, b) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(float(x) * float(y) for x, y in zip(a, b))
    norm_a = math.sqrt(sum(float(x) ** 2 for x in a))
    norm_b = math.sqrt(sum(float(x) ** 2 for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


class SkillMatcher:
    """Matches queries to skills using embedding similarity + heuristic boosts."""

    def __init__(self, skills: list[Skill]) -> None:
        self._skills = skills
        self._embeddings: dict[str, list[float]] = {}  # skill name -> embedding

    async def initialize(self) -> None:
        """Pre-embed all skill descriptions for fast matching."""
        if not self._skills:
            return

        from codelattice.graph.engines import _get_embedding_engine

        emb = _get_embedding_engine()

        # Build the text to embed: description + domains + triggers for richer signal
        texts = []
        for skill in self._skills:
            text = f"{skill.description} {' '.join(skill.domains)} {' '.join(skill.triggers)}"
            texts.append(text)

        try:
            vectors = await emb.embed_text(texts)
            for skill, vec in zip(self._skills, vectors):
                self._embeddings[skill.name] = vec
            logger.info("Embedded %d skill descriptions", len(self._embeddings))
        except Exception as e:
            logger.warning("Failed to embed skill descriptions: %s", e)

    async def match(
        self,
        query: str,
        top_k: int = 3,
        project_frameworks: set[str] | None = None,
    ) -> list[MatchResult]:
        """Match a query to the most relevant skills.

        Scoring:
        1. Cosine similarity between query embedding and skill embedding (0-1)
        2. Trigger boost (+0.3): if query contains a trigger phrase
        3. Framework boost (+0.2): if skill domain matches project frameworks
        """
        if not self._embeddings:
            return []

        from codelattice.graph.engines import _get_embedding_engine

        emb = _get_embedding_engine()

        try:
            query_vectors = await emb.embed_text([query])
            query_vec = query_vectors[0]
        except Exception as e:
            logger.warning("Failed to embed query: %s", e)
            return []

        query_lower = query.lower()
        results: list[MatchResult] = []

        for skill in self._skills:
            skill_vec = self._embeddings.get(skill.name)
            if skill_vec is None:
                continue

            # Base similarity score
            sim = _cosine_similarity(query_vec, skill_vec)
            reasons = [f"similarity={sim:.3f}"]

            # Trigger boost
            trigger_matched = False
            for trigger in skill.triggers:
                if trigger.lower() in query_lower:
                    sim += TRIGGER_BOOST
                    reasons.append(f"trigger match: {trigger!r}")
                    trigger_matched = True
                    break

            # Framework boost
            if project_frameworks:
                matching_domains = set(skill.domains) & project_frameworks
                if matching_domains:
                    sim += FRAMEWORK_BOOST
                    reasons.append(f"framework match: {matching_domains}")

            results.append(MatchResult(skill=skill, score=sim, reasons=reasons))

        # Sort by score descending
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]
