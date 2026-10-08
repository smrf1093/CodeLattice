"""Language registry for tree-sitter grammars."""

from __future__ import annotations

from pathlib import Path

import tree_sitter
import tree_sitter_javascript

# Individual grammar packages (Python 3.13 compatible)
import tree_sitter_python
import tree_sitter_typescript

from codelattice.parser.queries import javascript, python_queries, typescript

EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
}

SUPPORTED_LANGUAGES = {"python", "typescript", "tsx", "javascript"}


def _get_ts_language(lang: str) -> tree_sitter.Language:
    """Get the tree-sitter Language object for a language name."""
    if lang == "python":
        return tree_sitter.Language(tree_sitter_python.language())
    elif lang == "javascript":
        return tree_sitter.Language(tree_sitter_javascript.language())
    elif lang == "typescript":
        return tree_sitter.Language(tree_sitter_typescript.language_typescript())
    elif lang == "tsx":
        return tree_sitter.Language(tree_sitter_typescript.language_tsx())
    else:
        raise ValueError(f"Unsupported language: {lang}")


_parsers: dict[str, tree_sitter.Parser] = {}
_languages: dict[str, tree_sitter.Language] = {}


def get_parser(lang: str) -> tree_sitter.Parser:
    """Get or create a cached tree-sitter parser for a language."""
    if lang not in _parsers:
        ts_lang = _get_ts_language(lang)
        _languages[lang] = ts_lang
        parser = tree_sitter.Parser(ts_lang)
        _parsers[lang] = parser
    return _parsers[lang]


def get_language(lang: str) -> tree_sitter.Language:
    """Get the tree-sitter Language object (ensures parser is initialized)."""
    if lang not in _languages:
        get_parser(lang)
    return _languages[lang]


def get_queries(lang: str) -> dict[str, str]:
    """Get the query patterns dict for a language."""
    if lang == "python":
        return python_queries.ALL_QUERIES
    elif lang in ("typescript", "tsx"):
        return typescript.ALL_QUERIES
    elif lang == "javascript":
        return javascript.ALL_QUERIES
    else:
        raise ValueError(f"No queries for language: {lang}")


def detect_language(file_path: Path) -> str | None:
    """Detect language from file extension. Returns None if unsupported."""
    return EXTENSION_TO_LANGUAGE.get(file_path.suffix.lower())
