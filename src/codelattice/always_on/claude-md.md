## CodeLattice

This project is indexed by CodeLattice, a local code knowledge graph exposed through the `codelattice` MCP tools.

Rules:
- For code exploration, prefer CodeLattice over Grep/Glob/find: `search_code` finds code by meaning, `find_symbol` finds a function/class/variable with its dependency graph, `get_dependencies` / `get_dependents` show what a file or symbol uses and what uses it, and `get_file_summary` shows a file's structure without reading it.
- Then `Read` only the file and line range CodeLattice returned, instead of scanning whole files.
- `advise` and `list_skills` are best-practice guides, not code search; use them only when asked.
- After modifying code, call `refresh_index` (incremental, fast) to keep the graph current.
