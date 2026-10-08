"""Transforms parsed code entities into Cognee DataPoints and ingests them.

Direct ingestion pipeline that bypasses Cognee's ``add_data_points()`` to
avoid the expensive recursive ``get_graph_from_model()`` traversal.  We
know our DataPoint structure exactly, so we can extract nodes + edges,
embed, and write to LanceDB/SQLite directly — the same approach the search
layer already uses for reading.
"""

from __future__ import annotations

import asyncio
import logging
import time

from cognee.infrastructure.engine import DataPoint

from codelattice.models.code_entities import (
    CodeClass,
    CodeExport,
    CodeFile,
    CodeFunction,
    CodeImport,
    CodeVariable,
)
from codelattice.parser.tree_sitter_parser import ParsedEntity, ParseResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Relationship field names on each entity type.  These are DataPoint fields
# that point to *other* DataPoints (i.e. graph edges) rather than scalar
# properties.  We need to know them so we can:
#   (a) exclude them when serialising node properties for the graph DB, and
#   (b) traverse them to build the edge list.
# ---------------------------------------------------------------------------

_RELATIONSHIP_FIELDS: dict[type, set[str]] = {
    CodeFile: {"contains_symbols", "imports", "exports"},
    CodeFunction: {"defined_in", "calls"},
    CodeClass: {"defined_in", "methods", "inherits_from"},
    CodeImport: {"resolves_to"},
    CodeExport: {"exports_symbol"},
    CodeVariable: {"defined_in"},
}


def _build_file_summary(entities: list[ParsedEntity]) -> str:
    """Build a structural summary string for a file."""
    functions = [e for e in entities if e.kind in ("function", "arrow")]
    classes = [e for e in entities if e.kind == "class"]
    methods = [e for e in entities if e.kind == "method"]
    imports = [e for e in entities if e.kind == "import"]
    exports = [e for e in entities if e.kind == "export"]
    interfaces = [e for e in entities if e.kind == "interface"]
    type_aliases = [e for e in entities if e.kind == "type_alias"]

    parts = []
    if classes:
        parts.append(f"Classes: {', '.join(c.name for c in classes)}")
    if interfaces:
        parts.append(f"Interfaces: {', '.join(i.name for i in interfaces)}")
    if type_aliases:
        parts.append(f"Types: {', '.join(t.name for t in type_aliases)}")
    if functions:
        parts.append(f"Functions: {', '.join(f.name for f in functions)}")
    if methods:
        parts.append(f"Methods: {', '.join(m.name for m in methods)}")
    if imports:
        modules = list(dict.fromkeys(i.source_module or i.name for i in imports))
        parts.append(f"Imports from: {', '.join(modules[:10])}")
    if exports:
        parts.append(f"Exports: {', '.join(e.name for e in exports if e.name)}")

    return "; ".join(parts) if parts else "Empty file"


def build_data_points(parse_result: ParseResult, repo_id: str) -> tuple[list, dict[str, str]]:
    """Convert a ParseResult into Cognee DataPoint instances.

    Args:
        parse_result: Result from tree-sitter parsing.
        repo_id: Repository identifier.

    Returns:
        Tuple of (list of DataPoints, dict mapping entity_id -> entity_type).
    """
    rel_path = str(parse_result.file_path)
    language = parse_result.language
    entities = parse_result.entities

    data_points = []
    entity_map: dict[str, str] = {}  # id -> type name

    # Build the CodeFile node
    file_summary = _build_file_summary(entities)
    code_file = CodeFile(
        file_path=rel_path,
        language=language,
        repo_id=repo_id,
        line_count=parse_result.line_count,
        summary=file_summary,
    )
    data_points.append(code_file)
    entity_map[str(code_file.id)] = "CodeFile"

    # Collect symbol DataPoints by name for relationship linking
    function_points: dict[str, CodeFunction] = {}
    class_points: dict[str, CodeClass] = {}
    import_points: list[CodeImport] = []
    export_points: list[CodeExport] = []
    variable_points: list[CodeVariable] = []

    # First pass: create all non-call entities
    for e in entities:
        if e.kind in ("function", "arrow", "generator"):
            dp = CodeFunction(
                name=e.name,
                qualified_name=e.name,
                kind=e.kind,
                signature=e.signature,
                docstring=e.docstring,
                start_line=e.start_line,
                end_line=e.end_line,
                file_path=rel_path,
                parameters=e.parameters,
                return_type=e.return_type,
                defined_in=code_file,
            )
            function_points[e.name] = dp
            data_points.append(dp)
            entity_map[str(dp.id)] = "CodeFunction"

        elif e.kind == "method":
            qualified = f"{e.parent_name}.{e.name}" if e.parent_name else e.name
            dp = CodeFunction(
                name=e.name,
                qualified_name=qualified,
                kind="method",
                signature=e.signature,
                docstring=e.docstring,
                start_line=e.start_line,
                end_line=e.end_line,
                file_path=rel_path,
                parameters=e.parameters,
                return_type=e.return_type,
            )
            function_points[qualified] = dp
            data_points.append(dp)
            entity_map[str(dp.id)] = "CodeFunction"

        elif e.kind == "class":
            dp = CodeClass(
                name=e.name,
                kind="class",
                signature=e.signature,
                docstring=e.docstring,
                start_line=e.start_line,
                end_line=e.end_line,
                file_path=rel_path,
                defined_in=code_file,
            )
            class_points[e.name] = dp
            data_points.append(dp)
            entity_map[str(dp.id)] = "CodeClass"

        elif e.kind == "interface":
            dp = CodeClass(
                name=e.name,
                kind="interface",
                signature=e.signature,
                start_line=e.start_line,
                end_line=e.end_line,
                file_path=rel_path,
                defined_in=code_file,
            )
            class_points[e.name] = dp
            data_points.append(dp)
            entity_map[str(dp.id)] = "CodeClass"

        elif e.kind == "type_alias":
            dp = CodeClass(
                name=e.name,
                kind="type_alias",
                signature=e.signature,
                start_line=e.start_line,
                end_line=e.end_line,
                file_path=rel_path,
                defined_in=code_file,
            )
            class_points[e.name] = dp
            data_points.append(dp)
            entity_map[str(dp.id)] = "CodeClass"

        elif e.kind == "import":
            dp = CodeImport(
                source_module=e.source_module or e.name,
                imported_names=e.imported_names,
                is_default=e.is_default,
                file_path=rel_path,
                import_statement=e.signature,
            )
            import_points.append(dp)
            data_points.append(dp)
            entity_map[str(dp.id)] = "CodeImport"

        elif e.kind == "export":
            dp = CodeExport(
                name=e.name,
                kind=e.export_kind or "named",
                file_path=rel_path,
            )
            export_points.append(dp)
            data_points.append(dp)
            entity_map[str(dp.id)] = "CodeExport"

        elif e.kind == "variable":
            dp = CodeVariable(
                name=e.name,
                kind="const",
                type_annotation=e.type_annotation,
                file_path=rel_path,
                start_line=e.start_line,
                defined_in=code_file,
            )
            variable_points.append(dp)
            data_points.append(dp)
            entity_map[str(dp.id)] = "CodeVariable"

    # Second pass: wire up relationships

    # File -> contains_symbols
    all_symbols = list(function_points.values()) + list(class_points.values()) + variable_points
    if all_symbols:
        code_file.contains_symbols = all_symbols

    # File -> imports
    if import_points:
        code_file.imports = import_points

    # File -> exports
    if export_points:
        code_file.exports = export_points

    # Methods -> class.methods
    for e in entities:
        if e.kind == "method" and e.parent_name and e.parent_name in class_points:
            qualified = f"{e.parent_name}.{e.name}"
            if qualified in function_points:
                cls = class_points[e.parent_name]
                method_dp = function_points[qualified]
                method_dp.defined_in = cls
                if cls.methods is None:
                    cls.methods = []
                if isinstance(cls.methods, list):
                    cls.methods.append(method_dp)
                else:
                    cls.methods = [cls.methods, method_dp]

    # Class inheritance
    for e in entities:
        if e.kind == "class" and e.parent_name:
            cls = class_points.get(e.name)
            base_names = [n.strip() for n in e.parent_name.split(",")]
            bases = []
            for bn in base_names:
                # Strip Python-style argument list parens
                bn = bn.strip("()")
                if bn in class_points:
                    bases.append(class_points[bn])
            if cls and bases:
                cls.inherits_from = bases if len(bases) > 1 else bases[0]

    # Export -> symbol linking
    for exp in export_points:
        if exp.name in function_points:
            exp.exports_symbol = function_points[exp.name]
        elif exp.name in class_points:
            exp.exports_symbol = class_points[exp.name]

    # Call graph edges: link function calls to known functions
    call_entities = [e for e in entities if e.kind == "call"]
    for call_e in call_entities:
        target = call_e.call_target
        if not target:
            continue
        # Find which function/method contains this call (by line range)
        caller = None
        for e in entities:
            if (
                e.kind in ("function", "arrow", "method")
                and e.start_line <= call_e.start_line <= e.end_line
            ):
                qname = f"{e.parent_name}.{e.name}" if e.parent_name else e.name
                caller = function_points.get(qname) or function_points.get(e.name)
                break

        callee = function_points.get(target)
        if caller and callee and caller is not callee:
            if caller.calls is None:
                caller.calls = []
            if isinstance(caller.calls, list):
                caller.calls.append(callee)
            else:
                caller.calls = [caller.calls, callee]

    return data_points, entity_map


# ---------------------------------------------------------------------------
# Direct ingestion — bypasses Cognee's add_data_points entirely.
# ---------------------------------------------------------------------------

_db_initialized = False


async def _ensure_cognee_db():
    """Create Cognee's internal DB tables if they don't exist yet."""
    global _db_initialized
    if not _db_initialized:
        try:
            from cognee.infrastructure.databases.relational import get_relational_engine

            engine = get_relational_engine()
            await engine.create_database()
        except Exception as e:
            logger.warning("Failed to create Cognee DB tables: %s", e)
        _db_initialized = True


def _flatten_data_points(
    data_points: list[DataPoint],
) -> tuple[
    list[DataPoint],
    list[tuple[str, str, str, dict]],
]:
    """Extract flat node list and edge tuples from our DataPoints.

    This replaces Cognee's recursive ``get_graph_from_model`` with a direct
    traversal that understands our exact entity types.  Since we built the
    DataPoints ourselves, we know exactly which fields are relationships.

    Returns:
        (nodes, edges) where edges are (from_id, to_id, relationship_name, {}).
    """
    seen_ids: set[str] = set()
    nodes: list[DataPoint] = []
    edges: list[tuple[str, str, str, dict]] = []

    def _ensure_node(dp: DataPoint) -> str:
        """Add a DataPoint as a node if not already seen. Returns its ID."""
        dp_id = str(dp.id)
        if dp_id not in seen_ids:
            seen_ids.add(dp_id)
            nodes.append(dp)
        return dp_id

    # First pass: register all input DataPoints as nodes
    for dp in data_points:
        _ensure_node(dp)

    # Second pass: extract edges from every DataPoint's relationship fields.
    # This is separate from node registration because a DataPoint discovered
    # as a relationship target (e.g. via CodeFile.contains_symbols) still
    # needs its own relationships traversed (e.g. CodeFunction.calls).
    for dp in data_points:
        dp_id = str(dp.id)
        rel_fields = _RELATIONSHIP_FIELDS.get(type(dp), set())
        for field_name in rel_fields:
            targets = getattr(dp, field_name, None)
            if targets is None:
                continue
            # Normalise to list
            if not isinstance(targets, list):
                targets = [targets]
            for target in targets:
                if not isinstance(target, DataPoint):
                    continue
                target_id = _ensure_node(target)
                edges.append((dp_id, target_id, field_name, {}))

    return nodes, edges


def _strip_relationships(nodes: list[DataPoint]) -> list[DataPoint]:
    """Create copies of DataPoints with relationship fields set to None.

    The graph adapter's ``add_nodes`` calls ``model_dump()`` then
    ``json.dumps()`` on each node's properties.  DataPoint references
    (e.g. ``defined_in``, ``calls``) are not JSON-serializable, so we
    must strip them before writing.  The relationships are already
    captured as separate edges.
    """
    cleaned = []
    for node in nodes:
        rel_fields = _RELATIONSHIP_FIELDS.get(type(node), set())
        if not rel_fields:
            cleaned.append(node)
            continue
        # Shallow copy with relationship fields nulled out
        copy = node.model_copy()
        for field_name in rel_fields:
            try:
                setattr(copy, field_name, None)
            except Exception:
                pass
        cleaned.append(copy)
    return cleaned


async def _write_graph_nodes(graph, nodes: list[DataPoint]) -> None:
    """Write nodes to SQLite graph in a single batch."""
    if not nodes:
        return
    clean_nodes = _strip_relationships(nodes)
    await graph.add_nodes(clean_nodes)


async def _write_graph_edges(graph, edges: list[tuple[str, str, str, dict]]) -> None:
    """Write edges to SQLite graph in a single batch."""
    if not edges:
        return
    await graph.add_edges(edges)


async def _write_vectors(
    vec,
    nodes: list[DataPoint],
) -> None:
    """Index all nodes into LanceDB vector collections.

    Uses the adapter's ``index_data_points`` which handles schema creation,
    embedding (via FastEmbed), and upsert.  We group by (type, field) and
    batch to match how Cognee's own ``index_data_points`` task works.

    The embedding is done per-collection by the adapter — this is slightly
    less optimal than one giant bulk call, but it's safe and correct, and
    the embedding engine caches the model so there's no reload overhead.
    """
    if not nodes:
        return

    from cognee.infrastructure.databases.vector.lancedb.LanceDBAdapter import IndexSchema

    # Group nodes by (type_name, field_name) for collection-level batching
    collections: dict[tuple[str, str], list[DataPoint]] = {}
    for node in nodes:
        type_name = type(node).__name__
        index_fields = node.metadata.get("index_fields", [])
        for field_name in index_fields:
            text = getattr(node, field_name, None)
            if not text:
                continue
            # Create an IndexSchema DataPoint for this (node, field) pair
            idx_dp = IndexSchema(id=str(node.id), text=str(text))
            collections.setdefault((type_name, field_name), []).append(idx_dp)

    # Write each collection — these go through the adapter which handles
    # embedding + LanceModel creation + merge_insert.
    for (type_name, field_name), idx_dps in collections.items():
        coll_name = f"{type_name}_{field_name}"
        try:
            # Ensure collection exists
            has = await vec.has_collection(coll_name)
            if not has:
                await vec.create_vector_index(type_name, field_name)
            # Write via the adapter's create_data_points which handles
            # embedding, LanceModel wrapping, and merge upsert.
            await vec.create_data_points(coll_name, idx_dps)
        except Exception as e:
            logger.warning("Failed to write collection %s: %s", coll_name, e)


async def ingest_data_points(data_points: list, repo_id: str) -> None:
    """Ingest DataPoints directly into SQLite graph + LanceDB vectors.

    This bypasses Cognee's ``add_data_points()`` which uses the expensive
    recursive ``get_graph_from_model()`` traversal.  Instead we:

    1. Flatten our known DataPoint structure into nodes + edges directly
       (replaces ``get_graph_from_model`` — saves ~5.6s)
    2. Write nodes + edges to SQLite in batch
    3. Write vectors to LanceDB per collection (adapter handles embedding)

    Graph writes and vector writes run concurrently via ``asyncio.gather``.

    Args:
        data_points: List of DataPoints to ingest.
        repo_id: Repository identifier (determines which per-repo DB to use).
    """
    if not data_points:
        return

    await _ensure_cognee_db()

    from codelattice.graph.engines import get_engines

    graph, vec = await get_engines(repo_id)

    t_start = time.time()

    # Phase 1: Flatten DataPoints into nodes + edges (instant, no I/O)
    t0 = time.time()
    nodes, edges = _flatten_data_points(data_points)
    logger.debug(
        "Flatten: %d nodes, %d edges in %.3fs",
        len(nodes),
        len(edges),
        time.time() - t0,
    )

    # Phase 2: Write graph and vectors concurrently.
    # SQLite and LanceDB are independent databases so these can overlap.
    t0 = time.time()
    graph_task = asyncio.gather(
        _write_graph_nodes(graph, nodes),
        _write_graph_edges(graph, edges),
    )
    vector_task = _write_vectors(vec, nodes)
    await asyncio.gather(graph_task, vector_task)
    logger.debug("Graph + vector writes in %.2fs", time.time() - t0)

    total_time = time.time() - t_start
    logger.info(
        "Ingested %d data points (%d nodes, %d edges) in %.2fs",
        len(data_points),
        len(nodes),
        len(edges),
        total_time,
    )
