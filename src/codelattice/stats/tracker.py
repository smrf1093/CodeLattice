"""Usage statistics tracker — measures token savings from CodeLattice vs traditional search.

Estimates token counts using the ~4 chars per token heuristic (standard for English/code).
Logs every tool call with:
  - codelattice_tokens: actual tokens in the CodeLattice response
  - traditional_tokens: estimated tokens if the same task used grep + file reads
  - tokens_saved: the difference

Writes daily stats to ~/.codelattice/usage_stats.json.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from codelattice.config.settings import get_settings

logger = logging.getLogger(__name__)

# Rough estimate: 1 token ≈ 4 characters for code/English text
CHARS_PER_TOKEN = 4

# Estimates for what traditional Claude CLI operations cost in tokens.
# These are conservative averages based on typical codebase exploration.
TRADITIONAL_ESTIMATES = {
    # search_code: typically requires 3-5 grep calls + reading results
    # Each grep returns ~500-2000 chars, then Claude reads 2-3 matching files (~3000 chars each)
    "search_code": {
        "grep_calls": 4,
        "grep_result_chars": 1200,
        "file_reads": 3,
        "file_read_chars": 3000,
    },
    # find_symbol: grep for name + read the file + read related files
    "find_symbol": {
        "grep_calls": 2,
        "grep_result_chars": 800,
        "file_reads": 2,
        "file_read_chars": 4000,
    },
    # get_dependencies: read the file + grep for imports + read imported files
    "get_dependencies": {
        "grep_calls": 3,
        "grep_result_chars": 600,
        "file_reads": 4,
        "file_read_chars": 3000,
    },
    # get_dependents: grep across whole codebase for references
    "get_dependents": {
        "grep_calls": 5,
        "grep_result_chars": 1500,
        "file_reads": 3,
        "file_read_chars": 3000,
    },
    # get_file_summary: read the entire file
    "get_file_summary": {
        "grep_calls": 0,
        "grep_result_chars": 0,
        "file_reads": 1,
        "file_read_chars": 8000,
    },
}


def _estimate_tokens(text: str | dict | list) -> int:
    """Estimate token count from a response object."""
    if isinstance(text, (dict, list)):
        text = json.dumps(text)
    return max(1, len(str(text)) // CHARS_PER_TOKEN)


def _estimate_traditional_tokens(tool_name: str, result_count: int) -> int:
    """Estimate how many tokens a traditional grep+read workflow would use."""
    est = TRADITIONAL_ESTIMATES.get(tool_name)
    if not est:
        return 0

    grep_tokens = (est["grep_calls"] * est["grep_result_chars"]) // CHARS_PER_TOKEN
    read_tokens = (est["file_reads"] * est["file_read_chars"]) // CHARS_PER_TOKEN

    # Scale by result count — more results = more files Claude would have read
    scale = max(1.0, result_count / 5.0)

    return int((grep_tokens + read_tokens) * scale)


@dataclass
class ToolCallRecord:
    """A single tool call record."""

    tool: str
    timestamp: float
    codelattice_tokens: int
    traditional_tokens: int
    tokens_saved: int
    result_count: int = 0
    query: str = ""


@dataclass
class DailyStats:
    """Aggregated stats for a single day."""

    date: str
    total_calls: int = 0
    total_codelattice_tokens: int = 0
    total_traditional_tokens: int = 0
    total_tokens_saved: int = 0
    calls_by_tool: dict[str, int] = field(default_factory=dict)
    savings_by_tool: dict[str, dict] = field(default_factory=dict)


class UsageTracker:
    """Tracks and persists usage statistics."""

    def __init__(self):
        self._stats_path = get_settings().data_dir / "usage_stats.json"
        self._today_calls: list[ToolCallRecord] = []
        self._data: dict = self._load()

    def _load(self) -> dict:
        """Load existing stats from disk."""
        if self._stats_path.exists():
            try:
                return json.loads(self._stats_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {"daily": {}, "lifetime": {"total_calls": 0, "total_saved": 0}}

    def _save(self) -> None:
        """Persist stats to disk."""
        self._stats_path.parent.mkdir(parents=True, exist_ok=True)
        self._stats_path.write_text(json.dumps(self._data, indent=2))

    def record(self, tool_name: str, response: dict, query: str = "") -> None:
        """Record a tool call and its token usage."""
        codelattice_tokens = _estimate_tokens(response)
        result_count = response.get("total", len(response.get("results", [])))
        traditional_tokens = _estimate_traditional_tokens(tool_name, result_count)
        tokens_saved = max(0, traditional_tokens - codelattice_tokens)

        record = ToolCallRecord(
            tool=tool_name,
            timestamp=time.time(),
            codelattice_tokens=codelattice_tokens,
            traditional_tokens=traditional_tokens,
            tokens_saved=tokens_saved,
            result_count=result_count,
            query=query,
        )
        self._today_calls.append(record)

        # Update daily stats
        today = date.today().isoformat()
        if today not in self._data["daily"]:
            self._data["daily"][today] = {
                "total_calls": 0,
                "total_codelattice_tokens": 0,
                "total_traditional_tokens": 0,
                "total_tokens_saved": 0,
                "calls_by_tool": {},
                "savings_by_tool": {},
            }

        day = self._data["daily"][today]
        day["total_calls"] += 1
        day["total_codelattice_tokens"] += codelattice_tokens
        day["total_traditional_tokens"] += traditional_tokens
        day["total_tokens_saved"] += tokens_saved
        day["calls_by_tool"][tool_name] = day["calls_by_tool"].get(tool_name, 0) + 1

        if tool_name not in day["savings_by_tool"]:
            day["savings_by_tool"][tool_name] = {
                "calls": 0,
                "codelattice_tokens": 0,
                "traditional_tokens": 0,
                "saved": 0,
            }
        ts = day["savings_by_tool"][tool_name]
        ts["calls"] += 1
        ts["codelattice_tokens"] += codelattice_tokens
        ts["traditional_tokens"] += traditional_tokens
        ts["saved"] += tokens_saved

        # Update lifetime
        self._data["lifetime"]["total_calls"] += 1
        self._data["lifetime"]["total_saved"] += tokens_saved

        self._save()

        logger.debug(
            "Tool %s: %d codelattice tokens vs ~%d traditional (%d saved)",
            tool_name,
            codelattice_tokens,
            traditional_tokens,
            tokens_saved,
        )

    def get_today_stats(self) -> dict:
        """Get stats for today."""
        today = date.today().isoformat()
        day = self._data["daily"].get(today)
        if not day:
            return {"date": today, "message": "No usage recorded today."}

        savings_pct = 0.0
        if day["total_traditional_tokens"] > 0:
            savings_pct = round(
                (day["total_tokens_saved"] / day["total_traditional_tokens"]) * 100, 1
            )

        return {
            "date": today,
            "total_calls": day["total_calls"],
            "codelattice_tokens": day["total_codelattice_tokens"],
            "traditional_estimate": day["total_traditional_tokens"],
            "tokens_saved": day["total_tokens_saved"],
            "savings_percentage": f"{savings_pct}%",
            "by_tool": day["savings_by_tool"],
        }

    def get_summary(self, days: int = 7) -> dict:
        """Get a summary of recent usage."""
        daily = self._data.get("daily", {})
        sorted_days = sorted(daily.keys(), reverse=True)[:days]

        total_calls = 0
        total_codelattice = 0
        total_traditional = 0
        total_saved = 0
        daily_breakdown = []

        for d in sorted_days:
            day = daily[d]
            total_calls += day["total_calls"]
            total_codelattice += day["total_codelattice_tokens"]
            total_traditional += day["total_traditional_tokens"]
            total_saved += day["total_tokens_saved"]

            day_pct = 0.0
            if day["total_traditional_tokens"] > 0:
                day_pct = round(
                    (day["total_tokens_saved"] / day["total_traditional_tokens"]) * 100, 1
                )
            daily_breakdown.append(
                {
                    "date": d,
                    "calls": day["total_calls"],
                    "codelattice_tokens": day["total_codelattice_tokens"],
                    "traditional_estimate": day["total_traditional_tokens"],
                    "saved": day["total_tokens_saved"],
                    "savings_pct": f"{day_pct}%",
                }
            )

        overall_pct = 0.0
        if total_traditional > 0:
            overall_pct = round((total_saved / total_traditional) * 100, 1)

        return {
            "period": f"Last {len(sorted_days)} day(s)",
            "total_calls": total_calls,
            "total_codelattice_tokens": total_codelattice,
            "total_traditional_estimate": total_traditional,
            "total_tokens_saved": total_saved,
            "overall_savings": f"{overall_pct}%",
            "daily": daily_breakdown,
            "lifetime_calls": self._data["lifetime"]["total_calls"],
            "lifetime_saved": self._data["lifetime"]["total_saved"],
        }

    def reset(self) -> dict:
        """Reset all stats."""
        self._data = {"daily": {}, "lifetime": {"total_calls": 0, "total_saved": 0}}
        self._today_calls = []
        self._save()
        return {"status": "reset", "message": "All usage stats cleared."}


# Singleton instance
_tracker: UsageTracker | None = None


def get_tracker() -> UsageTracker:
    global _tracker
    if _tracker is None:
        _tracker = UsageTracker()
    return _tracker
