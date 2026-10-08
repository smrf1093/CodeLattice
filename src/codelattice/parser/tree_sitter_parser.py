"""Core tree-sitter parsing engine that extracts code entities from source files."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter

from codelattice.parser.languages import get_language, get_parser, get_queries

logger = logging.getLogger(__name__)

MAX_SIGNATURE_LINES = 3
MAX_INLINE_BODY_LINES = 20


@dataclass
class ParsedEntity:
    """A code entity extracted from a source file."""

    name: str
    kind: str  # function, method, class, interface, type_alias, import, export, variable, call
    start_line: int
    end_line: int
    signature: str = ""
    docstring: str | None = None
    parameters: str | None = None
    return_type: str | None = None
    parent_name: str | None = None  # class name for methods
    source_module: str | None = None  # for imports
    imported_names: list[str] = field(default_factory=list)
    is_default: bool = False
    export_kind: str | None = None  # for exports: named, default, re-export
    call_target: str | None = None  # for calls: what's being called
    type_annotation: str | None = None  # for variables


@dataclass
class ParseResult:
    """Result of parsing a single file."""

    file_path: Path
    language: str
    entities: list[ParsedEntity] = field(default_factory=list)
    line_count: int = 0
    error: str | None = None


def _node_text(node: tree_sitter.Node | None, source: bytes) -> str:
    """Extract text from a tree-sitter node."""
    if node is None:
        return ""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _get_signature(node: tree_sitter.Node, source: bytes) -> str:
    """Extract the signature (first few lines) of a node."""
    text = _node_text(node, source)
    lines = text.split("\n")
    if len(lines) <= MAX_SIGNATURE_LINES:
        return text.strip()
    return "\n".join(lines[:MAX_SIGNATURE_LINES]).strip() + " ..."


def _get_docstring(node: tree_sitter.Node, source: bytes, language: str) -> str | None:
    """Extract the docstring from a function/class body node."""
    if node is None or node.child_count == 0:
        return None

    if language == "python":
        # Python: first child of block that is an expression_statement containing a string
        body = node
        for child in body.children:
            if child.type == "expression_statement":
                for sc in child.children:
                    if sc.type == "string":
                        text = _node_text(sc, source)
                        # Strip triple quotes
                        for q in ('"""', "'''"):
                            if text.startswith(q) and text.endswith(q):
                                return text[3:-3].strip()
                        return text.strip('"').strip("'").strip()
                break
    else:
        # JS/TS: look for a comment node immediately before
        parent = node.parent
        if parent is not None:
            idx = None
            for i, child in enumerate(parent.children):
                if child.id == node.id:
                    idx = i
                    break
            if idx and idx > 0:
                prev = parent.children[idx - 1]
                if prev.type == "comment":
                    text = _node_text(prev, source)
                    return text.lstrip("/*").rstrip("*/").strip()
    return None


def _extract_functions(
    captures: dict[str, list[tree_sitter.Node]], source: bytes, language: str
) -> list[ParsedEntity]:
    """Extract function entities from tree-sitter captures."""
    entities = []

    # Regular function declarations
    for node in captures.get("function.def", []):
        name_nodes = captures.get("function.name", [])
        name_node = _find_child_capture(node, name_nodes)
        if not name_node:
            continue

        params_nodes = captures.get("function.params", [])
        params_node = _find_child_capture(node, params_nodes)

        ret_nodes = captures.get("function.return_type", [])
        ret_node = _find_child_capture(node, ret_nodes)

        body_nodes = captures.get("function.body", [])
        body_node = _find_child_capture(node, body_nodes)

        entities.append(
            ParsedEntity(
                name=_node_text(name_node, source),
                kind="function",
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                signature=_get_signature(node, source),
                docstring=_get_docstring(body_node, source, language),
                parameters=_node_text(params_node, source) if params_node else None,
                return_type=_node_text(ret_node, source) if ret_node else None,
            )
        )

    # Arrow functions / const function expressions
    for tag in ("function.arrow", "function.const_arrow"):
        for node in captures.get(tag, []):
            name_nodes = captures.get("function.name", [])
            name_node = _find_child_capture(node, name_nodes)
            if not name_node:
                continue

            params_nodes = captures.get("function.params", [])
            params_node = _find_child_capture(node, params_nodes)

            ret_nodes = captures.get("function.return_type", [])
            ret_node = _find_child_capture(node, ret_nodes)

            entities.append(
                ParsedEntity(
                    name=_node_text(name_node, source),
                    kind="arrow",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    signature=_get_signature(node, source),
                    parameters=_node_text(params_node, source) if params_node else None,
                    return_type=_node_text(ret_node, source) if ret_node else None,
                )
            )

    return entities


def _extract_classes(
    captures: dict[str, list[tree_sitter.Node]], source: bytes, language: str
) -> list[ParsedEntity]:
    """Extract class entities from tree-sitter captures."""
    entities = []
    for node in captures.get("class.def", []):
        name_nodes = captures.get("class.name", [])
        name_node = _find_child_capture(node, name_nodes)
        if not name_node:
            continue

        body_nodes = captures.get("class.body", [])
        body_node = _find_child_capture(node, body_nodes)

        base_nodes = captures.get("class.bases", captures.get("class.base", []))
        base_node = _find_child_capture(node, base_nodes) if base_nodes else None

        entities.append(
            ParsedEntity(
                name=_node_text(name_node, source),
                kind="class",
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                signature=_get_signature(node, source),
                docstring=_get_docstring(body_node, source, language),
                parent_name=_node_text(base_node, source) if base_node else None,
            )
        )

    return entities


def _extract_methods(
    captures: dict[str, list[tree_sitter.Node]], source: bytes, language: str
) -> list[ParsedEntity]:
    """Extract method entities from tree-sitter captures."""
    entities = []
    for node in captures.get("method.def", []):
        name_nodes = captures.get("method.name", [])
        name_node = _find_child_capture(node, name_nodes)
        if not name_node:
            continue

        class_name_nodes = captures.get("method.class_name", [])
        class_name_node = _find_closest_capture(node, class_name_nodes)

        params_nodes = captures.get("method.params", [])
        params_node = _find_child_capture(node, params_nodes)

        ret_nodes = captures.get("method.return_type", [])
        ret_node = _find_child_capture(node, ret_nodes)

        body_nodes = captures.get("method.body", [])
        body_node = _find_child_capture(node, body_nodes)

        entities.append(
            ParsedEntity(
                name=_node_text(name_node, source),
                kind="method",
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                signature=_get_signature(node, source),
                docstring=_get_docstring(body_node, source, language),
                parameters=_node_text(params_node, source) if params_node else None,
                return_type=_node_text(ret_node, source) if ret_node else None,
                parent_name=_node_text(class_name_node, source) if class_name_node else None,
            )
        )

    return entities


def _extract_interfaces(
    captures: dict[str, list[tree_sitter.Node]], source: bytes
) -> list[ParsedEntity]:
    """Extract interface entities (TypeScript only)."""
    entities = []
    for node in captures.get("interface.def", []):
        name_nodes = captures.get("interface.name", [])
        name_node = _find_child_capture(node, name_nodes)
        if not name_node:
            continue
        entities.append(
            ParsedEntity(
                name=_node_text(name_node, source),
                kind="interface",
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                signature=_get_signature(node, source),
            )
        )
    return entities


def _extract_type_aliases(
    captures: dict[str, list[tree_sitter.Node]], source: bytes
) -> list[ParsedEntity]:
    """Extract type alias entities (TypeScript only)."""
    entities = []
    for node in captures.get("type.def", []):
        name_nodes = captures.get("type.name", [])
        name_node = _find_child_capture(node, name_nodes)
        if not name_node:
            continue
        entities.append(
            ParsedEntity(
                name=_node_text(name_node, source),
                kind="type_alias",
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                signature=_get_signature(node, source),
            )
        )
    return entities


def _extract_imports(
    captures: dict[str, list[tree_sitter.Node]], source: bytes, language: str
) -> list[ParsedEntity]:
    """Extract import entities."""
    entities = []

    if language == "python":
        # import X
        for node in captures.get("import.def", []):
            mod_nodes = captures.get("import.module", [])
            mod_node = _find_child_capture(node, mod_nodes)
            if mod_node:
                entities.append(
                    ParsedEntity(
                        name=_node_text(mod_node, source),
                        kind="import",
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        source_module=_node_text(mod_node, source),
                        signature=_node_text(node, source).strip(),
                    )
                )

        # from X import Y
        for node in captures.get("import.from", []):
            mod_nodes = captures.get("import.module", [])
            mod_node = _find_child_capture(node, mod_nodes)
            name_nodes = captures.get("import.name", [])
            imported = []
            for nn in name_nodes:
                if _is_descendant(nn, node):
                    imported.append(_node_text(nn, source))
            entities.append(
                ParsedEntity(
                    name=_node_text(mod_node, source) if mod_node else "",
                    kind="import",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    source_module=_node_text(mod_node, source) if mod_node else "",
                    imported_names=imported,
                    signature=_node_text(node, source).strip(),
                )
            )
    else:
        # JS/TS imports
        for node in captures.get("import.def", []):
            source_nodes = captures.get("import.source", [])
            source_node = _find_child_capture(node, source_nodes)
            source_text = _node_text(source_node, source).strip("'\"") if source_node else ""

            name_nodes = captures.get("import.name", [])
            default_nodes = captures.get("import.default", [])
            imported = []
            is_default = False
            for nn in name_nodes:
                if _is_descendant(nn, node):
                    imported.append(_node_text(nn, source))
            for dn in default_nodes:
                if dn is not None and _is_descendant(dn, node):
                    imported.append(_node_text(dn, source))
                    is_default = True

            entities.append(
                ParsedEntity(
                    name=source_text,
                    kind="import",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    source_module=source_text,
                    imported_names=imported,
                    is_default=is_default,
                    signature=_node_text(node, source).strip(),
                )
            )

    return entities


def _extract_exports(
    captures: dict[str, list[tree_sitter.Node]], source: bytes
) -> list[ParsedEntity]:
    """Extract export entities (JS/TS only)."""
    entities = []
    for node in captures.get("export.def", []):
        decl_nodes = captures.get("export.declaration", [])
        decl_node = _find_child_capture(node, decl_nodes)
        name = ""
        if decl_node:
            # Try to find the name of the exported declaration
            for child in decl_node.children:
                if child.type in ("identifier", "type_identifier", "property_identifier"):
                    name = _node_text(child, source)
                    break
        entities.append(
            ParsedEntity(
                name=name,
                kind="export",
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                export_kind="named",
                signature=_get_signature(node, source),
            )
        )

    for node in captures.get("export.reexport", []):
        source_nodes = captures.get("export.source", [])
        source_node = _find_child_capture(node, source_nodes)
        entities.append(
            ParsedEntity(
                name=_node_text(source_node, source).strip("'\"") if source_node else "",
                kind="export",
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                export_kind="re-export",
                source_module=_node_text(source_node, source).strip("'\"") if source_node else "",
                signature=_node_text(node, source).strip(),
            )
        )

    return entities


def _extract_variables(
    captures: dict[str, list[tree_sitter.Node]], source: bytes
) -> list[ParsedEntity]:
    """Extract module-level variable declarations."""
    entities = []
    for node in captures.get("var.def", []):
        name_nodes = captures.get("var.name", [])
        name_node = _find_child_capture(node, name_nodes)
        if not name_node:
            continue

        type_nodes = captures.get("var.type", [])
        type_node = _find_child_capture(node, type_nodes)

        entities.append(
            ParsedEntity(
                name=_node_text(name_node, source),
                kind="variable",
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                signature=_node_text(node, source).strip().split("\n")[0],
                type_annotation=_node_text(type_node, source) if type_node else None,
            )
        )

    return entities


def _extract_calls(
    captures: dict[str, list[tree_sitter.Node]], source: bytes
) -> list[ParsedEntity]:
    """Extract function call expressions."""
    entities = []
    seen = set()

    for node in captures.get("call.expr", []):
        name_nodes = captures.get("call.name", [])
        name_node = _find_child_capture(node, name_nodes)
        if not name_node:
            continue
        name = _node_text(name_node, source)
        if name in seen:
            continue
        seen.add(name)
        entities.append(
            ParsedEntity(
                name=name,
                kind="call",
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                call_target=name,
            )
        )

    for node in captures.get("call.member", []):
        obj_nodes = captures.get("call.object", [])
        method_nodes = captures.get("call.method", [])
        obj_node = _find_child_capture(node, obj_nodes)
        method_node = _find_child_capture(node, method_nodes)
        if obj_node and method_node:
            target = f"{_node_text(obj_node, source)}.{_node_text(method_node, source)}"
            if target in seen:
                continue
            seen.add(target)
            entities.append(
                ParsedEntity(
                    name=_node_text(method_node, source),
                    kind="call",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    call_target=target,
                )
            )

    return entities


def _find_child_capture(
    parent_node: tree_sitter.Node, candidates: list[tree_sitter.Node]
) -> tree_sitter.Node | None:
    """Find a capture node that is a descendant of the parent node."""
    for node in candidates:
        if _is_descendant(node, parent_node):
            return node
    return None


def _find_closest_capture(
    target_node: tree_sitter.Node, candidates: list[tree_sitter.Node]
) -> tree_sitter.Node | None:
    """Find the capture node whose range most closely contains the target node."""
    best = None
    best_size = float("inf")
    for node in candidates:
        if node.start_byte <= target_node.start_byte and node.end_byte >= target_node.end_byte:
            size = node.end_byte - node.start_byte
            if size < best_size:
                best = node
                best_size = size
        # Also check ancestor relationship
        if _is_ancestor_of(node, target_node):
            return node
    return best


def _is_descendant(child: tree_sitter.Node, parent: tree_sitter.Node) -> bool:
    """Check if child is a descendant of parent (by byte range)."""
    return child.start_byte >= parent.start_byte and child.end_byte <= parent.end_byte


def _is_ancestor_of(candidate: tree_sitter.Node, target: tree_sitter.Node) -> bool:
    """Walk up from target to see if candidate is an ancestor."""
    node = target.parent
    while node is not None:
        if node.id == candidate.id:
            return True
        node = node.parent
    return False


# Cache for compiled queries keyed by (language, query_str) so we compile once
# and don't re-log the same warning on every file.
_query_cache: dict[tuple[str, str], tree_sitter.Query | None] = {}


def _run_query(
    language: str, query_str: str, tree: tree_sitter.Tree, ts_lang: tree_sitter.Language
) -> dict[str, list[tree_sitter.Node]]:
    """Run a tree-sitter query and return captures grouped by name.

    Uses QueryCursor.matches() which returns (pattern_idx, {name: [nodes]}).
    We merge all matches into a single dict for downstream extraction.
    """
    cache_key = (language, query_str)
    if cache_key in _query_cache:
        query = _query_cache[cache_key]
    else:
        try:
            query = tree_sitter.Query(ts_lang, query_str)
        except Exception as e:
            logger.warning("Failed to compile query for %s: %s", language, e)
            query = None
        _query_cache[cache_key] = query

    if query is None:
        return {}

    try:
        cursor = tree_sitter.QueryCursor(query)
        grouped: dict[str, list[tree_sitter.Node]] = {}
        for _pattern_idx, captures_dict in cursor.matches(tree.root_node):
            for name, nodes in captures_dict.items():
                grouped.setdefault(name, []).extend(nodes)
        return grouped
    except Exception as e:
        logger.warning("Failed to execute query for %s: %s", language, e)
        return {}


_QUERY_EXTRACTORS: dict[str, str] = {
    "function": "_extract_functions",
    "class": "_extract_classes",
    "method": "_extract_methods",
    "interface": "_extract_interfaces",
    "type_alias": "_extract_type_aliases",
    "import": "_extract_imports",
    "export": "_extract_exports",
    "assignment": "_extract_variables",
    "variable": "_extract_variables",
    "call": "_extract_calls",
}

# Extractors that need the language argument in addition to (captures, source).
_LANG_EXTRACTORS = {
    "_extract_functions",
    "_extract_imports",
    "_extract_classes",
    "_extract_methods",
}


def parse_file(file_path: Path, language: str) -> ParseResult:
    """Parse a source file and extract all code entities.

    Args:
        file_path: Path to the source file.
        language: Language identifier (python, typescript, tsx, javascript).

    Returns:
        ParseResult with all extracted entities.  On any unexpected error the
        result contains an ``error`` string and whatever entities were already
        collected — the indexer can still record partial results.
    """
    try:
        source = file_path.read_bytes()
    except (OSError, IOError) as e:
        return ParseResult(file_path=file_path, language=language, error=str(e))

    try:
        line_count = source.count(b"\n") + 1
        parser = get_parser(language)
        tree = parser.parse(source)
        ts_lang = get_language(language)
        queries = get_queries(language)
    except Exception as e:
        logger.exception("Failed to initialize parser for %s", file_path)
        return ParseResult(file_path=file_path, language=language, error=f"Parser init: {e}")

    all_entities: list[ParsedEntity] = []
    errors: list[str] = []

    for query_name, query_str in queries.items():
        extractor_name = _QUERY_EXTRACTORS.get(query_name)
        if extractor_name is None:
            continue

        try:
            captures = _run_query(language, query_str, tree, ts_lang)
            if not captures:
                continue

            extractor = globals()[extractor_name]
            if extractor_name in _LANG_EXTRACTORS:
                all_entities.extend(extractor(captures, source, language))
            else:
                all_entities.extend(extractor(captures, source))
        except Exception as e:
            errors.append(f"query '{query_name}': {e}")
            logger.warning("Error extracting %s from %s: %s", query_name, file_path, e)

    error_msg = "; ".join(errors) if errors else None
    return ParseResult(
        file_path=file_path,
        language=language,
        entities=all_entities,
        line_count=line_count,
        error=error_msg,
    )
