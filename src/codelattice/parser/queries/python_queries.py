"""Tree-sitter query patterns for Python."""

FUNCTION_QUERY = """
(function_definition
  name: (identifier) @function.name
  parameters: (parameters) @function.params
  return_type: (type)? @function.return_type
  body: (block) @function.body) @function.def
"""

CLASS_QUERY = """
(class_definition
  name: (identifier) @class.name
  superclasses: (argument_list)? @class.bases
  body: (block) @class.body) @class.def
"""

METHOD_QUERY = """
(class_definition
  name: (identifier) @method.class_name
  body: (block
    (function_definition
      name: (identifier) @method.name
      parameters: (parameters) @method.params
      return_type: (type)? @method.return_type
      body: (block) @method.body) @method.def))
"""

IMPORT_QUERY = """
(import_statement
  name: (dotted_name) @import.module) @import.def

(import_from_statement
  module_name: (dotted_name)? @import.module
  name: [
    (dotted_name) @import.name
    (aliased_import
      name: (dotted_name) @import.name
      alias: (identifier) @import.alias)
  ]) @import.from
"""

ASSIGNMENT_QUERY = """
(expression_statement
  (assignment
    left: (identifier) @var.name
    type: (type)? @var.type
    right: (_) @var.value)) @var.def
"""

CALL_QUERY = """
(call
  function: (identifier) @call.name) @call.expr

(call
  function: (attribute
    object: (_) @call.object
    attribute: (identifier) @call.method)) @call.member
"""

DECORATOR_QUERY = """
(decorated_definition
  (decorator
    (identifier) @decorator.name)
  definition: (_) @decorator.target) @decorated.def

(decorated_definition
  (decorator
    (call
      function: (identifier) @decorator.name))
  definition: (_) @decorator.target) @decorated.call
"""

ALL_QUERIES = {
    "function": FUNCTION_QUERY,
    "class": CLASS_QUERY,
    "method": METHOD_QUERY,
    "import": IMPORT_QUERY,
    "assignment": ASSIGNMENT_QUERY,
    "call": CALL_QUERY,
    "decorator": DECORATOR_QUERY,
}
