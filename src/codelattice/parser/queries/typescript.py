"""Tree-sitter query patterns for TypeScript (and TSX)."""

FUNCTION_QUERY = """
(function_declaration
  name: (identifier) @function.name
  parameters: (formal_parameters) @function.params
  return_type: (type_annotation)? @function.return_type
  body: (statement_block) @function.body) @function.def

(variable_declarator
  name: (identifier) @function.name
  value: (arrow_function
    parameters: (formal_parameters) @function.params
    return_type: (type_annotation)? @function.return_type
    body: (_) @function.body)) @function.arrow

(lexical_declaration
  (variable_declarator
    name: (identifier) @function.name
    value: (arrow_function
      parameters: (formal_parameters) @function.params
      return_type: (type_annotation)? @function.return_type
      body: (_) @function.body))) @function.const_arrow
"""

CLASS_QUERY = """
(class_declaration
  name: (type_identifier) @class.name
  (class_heritage
    (extends_clause
      value: (_) @class.base))?
  body: (class_body) @class.body) @class.def
"""

METHOD_QUERY = """
(class_declaration
  name: (type_identifier) @method.class_name
  body: (class_body
    (method_definition
      name: (property_identifier) @method.name
      parameters: (formal_parameters) @method.params
      return_type: (type_annotation)? @method.return_type
      body: (statement_block) @method.body) @method.def))
"""

INTERFACE_QUERY = """
(interface_declaration
  name: (type_identifier) @interface.name
  body: (interface_body) @interface.body) @interface.def
"""

TYPE_ALIAS_QUERY = """
(type_alias_declaration
  name: (type_identifier) @type.name
  value: (_) @type.value) @type.def
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
    type: (type_annotation)? @var.type
    value: (_) @var.value)) @var.def
"""

ALL_QUERIES = {
    "function": FUNCTION_QUERY,
    "class": CLASS_QUERY,
    "method": METHOD_QUERY,
    "interface": INTERFACE_QUERY,
    "type_alias": TYPE_ALIAS_QUERY,
    "import": IMPORT_QUERY,
    "export": EXPORT_QUERY,
    "call": CALL_QUERY,
    "variable": VARIABLE_QUERY,
}
