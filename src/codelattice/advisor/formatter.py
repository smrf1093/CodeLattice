"""Format advisor results with progressive disclosure."""

from __future__ import annotations

from codelattice.advisor.models import MatchResult


def format_match_result(match: MatchResult, include_body: bool = False) -> dict:
    """Format a single match result.

    Args:
        match: The match result to format.
        include_body: If True, include the full skill body (for primary match).
    """
    out: dict = {
        "name": match.skill.name,
        "category": match.skill.category,
        "description": match.skill.description,
        "score": round(match.score, 3),
        "reasons": match.reasons,
    }
    if match.skill.domains:
        out["domains"] = match.skill.domains
    if include_body:
        out["content"] = match.skill.body
    return out


def format_advise_response(
    matches: list[MatchResult],
    query: str,
    min_similarity: float = 0.3,
) -> dict:
    """Format the full advise tool response with progressive disclosure.

    Primary match (rank 1): includes full skill body.
    Secondary matches: metadata only (name, description, score).
    """
    # Filter by minimum similarity
    relevant = [m for m in matches if m.score >= min_similarity]

    if not relevant:
        return {
            "query": query,
            "results": [],
            "total": 0,
            "message": "No relevant skills found for this query.",
        }

    results = []
    for i, match in enumerate(relevant):
        # Primary skill gets full body, secondary skills get metadata only
        include_body = i == 0
        results.append(format_match_result(match, include_body=include_body))

    return {
        "query": query,
        "results": results,
        "total": len(results),
    }


def format_skill_list(skills: dict) -> dict:
    """Format the list_skills response."""
    entries = []
    for name, skill in sorted(skills.items()):
        entries.append(
            {
                "name": skill.name,
                "category": skill.category,
                "description": skill.description,
                "domains": skill.domains,
                "source": skill.source,
                "priority": skill.priority,
            }
        )
    return {"skills": entries, "total": len(entries)}
