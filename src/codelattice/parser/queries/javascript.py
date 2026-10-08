"""Tree-sitter query patterns for JavaScript (and JSX).

Shares most patterns with TypeScript but without type annotations.
"""

FUNCTION_QUERY = """
(function_declaration
  name: (identifier) @function.name
  parameters: (formal_parameters) @function.params
  body: (statement_block) @function.body) @function.def

(variable_declarator
  name: (identifier) @function.name
  value: (arrow_function
    parameters: (formal_parameters) @function.params
    body: (_) @function.body)) @function.arrow

(lexical_declaration
  (variable_declarator
    name: (identifier) @function.name
    value: (arrow_function
      parameters: (formal_parameters) @function.params
      body: (_) @function.body))) @function.const_arrow
"""

CLASS_QUERY = """
(class_declaration
  name: (identifier) @class.name
  (class_heritage
    (_) @class.base)?
  body: (class_body) @class.body) @class.def
"""

METHOD_QUERY = """
(class_declaration
  name: (identifier) @method.class_name
  body: (class_body
    (method_definition
      name: (property_identifier) @method.name
      parameters: (formal_parameters) @method.params
      body: (statement_block) @method.body) @method.def))
"""

IMPORT_QUERY = """
(import_statement
  (import_clause
    (named_imports
      (import_specifier
        name: (identifier) @import.name))*
    (identifier)? @import.default)
  source: (string) @import.source) @import.def
"""

EXPORT_QUERY = """
(export_statement
  declaration: (_) @export.declaration) @export.def

(export_statement
  source: (string) @export.source) @export.reexport
"""

CALL_QUERY = """
(call_expression
  function: (identifier) @call.name) @call.expr

(call_expression
  function: (member_expression
    object: (_) @call.object
    property: (property_identifier) @call.method)) @call.member
"""

VARIABLE_QUERY = """
(lexical_declaration
  (variable_declarator
    name: (identifier) @var.name
    value: (_) @var.value)) @var.def
"""

ALL_QUERIES = {
    "function": FUNCTION_QUERY,
    "class": CLASS_QUERY,
    "method": METHOD_QUERY,
    "import": IMPORT_QUERY,
    "export": EXPORT_QUERY,
    "call": CALL_QUERY,
    "variable": VARIABLE_QUERY,
}
