---
name: codelattice
description: "Use for any question about a codebase — finding code by meaning, locating a symbol, tracing what a file depends on or what depends on it, or summarizing a file without reading it. Indexes Python, TypeScript and JavaScript into a local code knowledge graph (tree-sitter + embeddings) and answers through the codelattice MCP tools. Trigger: /codelattice"
---

# /codelattice

Index a repository into a local code knowledge graph, then answer code questions from the graph instead of grepping and reading whole files.

## Usage

```
/codelattice                       # index the current directory (incremental)
/codelattice <path>                # index a specific path
/codelattice <path> --full         # force a full re-index
/codelattice status                # show what is indexed
/codelattice stats                 # show token savings
/codelattice "<question>"          # answer a code question from the graph
```

## What You Must Do When Invoked

If the user invoked `/codelattice --help` or `/codelattice -h` with no other arguments, print the `## Usage` block above verbatim and stop.

If no path was given, use `.` (the current directory). Do not ask the user for a path.

### Step 1 - Make sure CodeLattice is installed

```bash
command -v codelattice >/dev/null 2>&1 && codelattice --version || echo "NOT_INSTALLED"
```

If it prints `NOT_INSTALLED`, tell the user to run `uv tool install codelattice && codelattice install` (or `pipx install codelattice`) and stop.

### Step 2 - Index (for a path, `--full`, or no argument)

If the `mcp__codelattice__index_repository` tool is available, call it with the absolute path (`incremental=false` when `--full` was given). Otherwise run the CLI:

```bash
codelattice index "<absolute path>"          # add --full when requested
```

Indexing is incremental: unchanged files are skipped, so re-running it is cheap. The first run downloads a small local embedding model (~90 MB, once).

Report the result in one or two lines: files indexed, entities found, time taken, and any errors.

If the `mcp__codelattice__*` tools are not available in this session, tell the user to restart Claude Code once so the MCP server registered by `codelattice install` is loaded.

### Step 3 - Status and stats

- `status` → call `mcp__codelattice__index_status`, or run `codelattice status`.
- `stats` → call `mcp__codelattice__usage_stats`, or run `codelattice stats`.

### Step 4 - Answering a question

Use the MCP tools, most specific first:

- `search_code` — find code by meaning ("where is the retry logic for HTTP calls")
- `find_symbol` — a function, class or variable by name, with its callers and callees
- `get_dependencies` — what a file or symbol imports, calls or inherits from
- `get_dependents` — what depends on a file or symbol (impact analysis before a refactor)
- `get_file_summary` — the structure of a file without reading it

Then `Read` only the specific file and line range the tools returned. If results look stale, call `refresh_index` (incremental) and retry.

Secondary tools, only when asked: `advise` and `list_skills` (best-practice guides, not code search), `cancel_indexing`.

## Rules

- Prefer CodeLattice tools over Grep/Glob/find for exploring code; use Grep only for exact strings or after CodeLattice has pointed you to the right files.
- Include this rule in any subagent prompt that explores code.
- After large code changes, call `refresh_index` so the graph stays current.
- Supported languages: Python, TypeScript, JavaScript.
