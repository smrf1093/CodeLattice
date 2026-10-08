"""DataPoint subclasses representing code entities in the knowledge graph."""

from __future__ import annotations

from typing import Any, Optional

from cognee.infrastructure.engine import DataPoint
from pydantic import SkipValidation


class CodeFile(DataPoint):
    """A source code file in the repository."""

    file_path: str
    language: str
    repo_id: str
    line_count: int = 0
    summary: str = ""
    contains_symbols: SkipValidation[Any] = None
    imports: SkipValidation[Any] = None
    exports: SkipValidation[Any] = None

    metadata: dict = {"index_fields": ["summary", "file_path"]}


class CodeFunction(DataPoint):
    """A function, method, or arrow function."""

    name: str
    qualified_name: str = ""
    kind: str = "function"  # function, method, arrow, generator
    signature: str = ""
    docstring: Optional[str] = None
    start_line: int = 0
    end_line: int = 0
    file_path: str = ""
    parameters: Optional[str] = None
    return_type: Optional[str] = None
    calls: SkipValidation[Any] = None
    defined_in: SkipValidation[Any] = None

    metadata: dict = {"index_fields": ["name", "signature", "docstring"]}


class CodeClass(DataPoint):
    """A class, interface, or type alias."""

    name: str
    kind: str = "class"  # class, interface, type_alias
    signature: str = ""
    docstring: Optional[str] = None
    start_line: int = 0
    end_line: int = 0
    file_path: str = ""
    methods: SkipValidation[Any] = None
    inherits_from: SkipValidation[Any] = None
    defined_in: SkipValidation[Any] = None

    metadata: dict = {"index_fields": ["name", "signature", "docstring"]}


class CodeImport(DataPoint):
    """An import statement."""

    source_module: str
    imported_names: list[str] = []
    is_default: bool = False
    is_namespace: bool = False
    file_path: str = ""
    import_statement: str = ""
    resolves_to: SkipValidation[Any] = None

    metadata: dict = {"index_fields": ["source_module", "import_statement"]}


class CodeExport(DataPoint):
    """An export declaration."""

    name: str
    kind: str = "named"  # named, default, re-export
    file_path: str = ""
    exports_symbol: SkipValidation[Any] = None

    metadata: dict = {"index_fields": ["name"]}


class CodeVariable(DataPoint):
    """A module-level variable or constant."""

    name: str
    kind: str = "const"  # const, let, var, assignment
    type_annotation: Optional[str] = None
    file_path: str = ""
    start_line: int = 0
    defined_in: SkipValidation[Any] = None

    metadata: dict = {"index_fields": ["name"]}
