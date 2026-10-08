# CodeLattice

Code knowledge graph for Claude Code. Reduces token usage by replacing brute-force file searching with intelligent, graph-aware code retrieval.

**Fully local and free** — no API keys, no Ollama, no external services. Uses FastEmbed for local CPU-based embeddings and file-based storage (LanceDB + SQLite).

## Install

Requires Python 3.11 or 3.12 and [Claude Code](https://claude.com/claude-code).

```bash
uv tool install codelattice      # recommended (uv fetches Python 3.12 if needed)
# or: pipx install codelattice
# or: pip install codelattice

codelattice install              # registers the /codelattice skill and MCP server with Claude Code
```

Restart Claude Code, then inside your project type:

```
/codelattice .
```

That indexes the repo. From then on, ask code questions as usual:

> "Search the codebase for authentication middleware"

> "Find the UserService class and show me its dependencies"

> "What files depend on the database module?"

Claude uses `search_code` and `find_symbol` instead of grep/glob, returning precise results with file paths and line numbers.

### What `codelattice install` does

| Writes | Purpose |
|--------|---------|
| `~/.claude/skills/codelattice/SKILL.md` | The `/codelattice` skill (index, status, stats, questions) |
| `~/.claude/CLAUDE.md` | A short registration so Claude knows the skill exists |
| Claude Code user MCP config | The `codelattice` MCP server (`codelattice serve`) |

Respects `CLAUDE_CONFIG_DIR`. Re-running it is safe; `codelattice uninstall` removes all three.

### Project-scoped install

To commit the setup into a repo so teammates get it on clone:

```bash
codelattice install --project    # .claude/skills/codelattice/, .claude/CLAUDE.md, .mcp.json
```

The committed config uses the bare `codelattice` command, so each machine resolves it from its own PATH.

### Always-on mode (optional)

```bash
codelattice claude install       # run once per project
```

Writes a CodeLattice section to the project's `CLAUDE.md` and adds a PreToolUse hook to `.claude/settings.json`. Once the repo is indexed, the hook reminds Claude to use CodeLattice tools whenever it reaches for Grep, Glob, or a `grep`/`rg`/`find` shell command. It never blocks a tool call. Undo with `codelattice claude uninstall`.

### Install from source

```bash
uv tool install git+https://github.com/smrf1093/CodeLattice.git
codelattice install
```

## Use Cases

- **Semantic code search**: Search for "authentication middleware" across a Python project and instantly find the relevant functions by meaning, without knowing exact file names or function names.
- **Pre-refactoring impact analysis**: Before refactoring a utility function, run `find_symbol` and `get_dependents` to see every file and function that depends on it.
- **Onboarding to unfamiliar codebases**: Index a new TypeScript monorepo and use `get_file_summary` to quickly understand the structure of unfamiliar files without reading their full contents.
- **Keeping search fresh after edits**: After making edits to several files, call `refresh_index` to update the knowledge graph, then use `search_code` to verify your changes are reflected.
- **Understanding code dependencies**: Use `get_dependencies` to trace what a module imports and calls, helping you understand unfamiliar code before making changes.

## CodeLattice vs graphify

[graphify](https://github.com/Graphify-Labs/graphify) is the best-known tool in this space, and CodeLattice deliberately copies its setup flow (`uv tool install` → `install` → slash command). The two solve different problems, though:

| | **CodeLattice** | **graphify** |
|---|---|---|
| **Goal** | Cut the tokens Claude spends *finding* code during everyday coding tasks | Turn any folder (code, docs, papers, images, video) into a knowledge graph you can explore |
| **Inputs** | Python, TypeScript, JavaScript source | ~37 tree-sitter languages plus docs, PDFs, images, video |
| **Code extraction** | tree-sitter, fully local | tree-sitter, fully local |
| **Non-code extraction** | — | LLM pass (your assistant's model or an API key) |
| **Retrieval** | Semantic vector search (local FastEmbed embeddings) **plus** graph lookups: callers, callees, imports, base classes | Graph traversal (BFS/DFS, shortest path, explain). No vector store |
| **How Claude uses it** | MCP tools: `search_code`, `find_symbol`, `get_dependencies`, `get_dependents`, `get_file_summary` | Skill + CLI: `graphify query`, `path`, `explain`. MCP server is an optional extra |
| **Output** | Compact results (signatures, line numbers, relationships); Claude then reads only the lines it needs | `graphify-out/`: `graph.html`, `graph.json`, `GRAPH_REPORT.md` |
| **Where data lives** | `~/.codelattice/repos/<id>/` (SQLite + LanceDB). Nothing is written into your repo | `graphify-out/` inside the repo |
| **Freshness** | Hash-based incremental re-index; every response flags stale files; optional file watcher | `graphify update`, git commit/checkout hooks, `--watch` |
| **Extras** | Advisor guides (`advise`), built-in token-savings tracking (`codelattice stats`) | Community detection, "god nodes", interactive visualization, Neo4j/GraphML/Obsidian exports, PR impact analysis |
| **Assistants** | Claude Code | Claude Code, Codex, Cursor, Gemini CLI, Copilot, and ~15 more |
| **Setup** | `uv tool install codelattice` → `codelattice install` → `/codelattice .` | `uv tool install graphifyy` → `graphify install` → `/graphify .` |
| **Always-on** | `codelattice claude install` (CLAUDE.md + PreToolUse hook) | `graphify claude install` (CLAUDE.md + PreToolUse hook) |

**Pick CodeLattice** when you mostly want Claude to find the right function by meaning ("where do we retry failed payments?") and to answer impact questions before a refactor, at low token cost, without generated files in your repo.

**Pick graphify** when you want to understand a large or mixed corpus as a whole: architecture overviews, cross-document links, visual exploration, or support for many languages and assistants.

The two don't conflict. Both can be installed side by side, each with its own skill and its own CLAUDE.md section.

## How It Works

CodeLattice pre-indexes your codebase into a knowledge graph using [Cognee](https://github.com/topoteretes/cognee) and [tree-sitter](https://tree-sitter.github.io/), then exposes targeted retrieval tools via MCP. Instead of Claude doing 10-30 file reads and grep calls per task, it queries the graph and gets back signatures, line numbers, and relationships — then fetches only what it needs.

```
Codebase --> tree-sitter parsing --> per-repo knowledge graph (vectors + graph DB)
                                              |
Claude Code <-- MCP stdio <-- CodeLattice MCP Server <-- vector search + graph queries
```

No separate LLM is needed. CodeLattice writes directly to SQLite (graph) and LanceDB (vectors) — no LLM is called during indexing. Embeddings are generated locally by FastEmbed. At search time, Claude itself (already running in Claude Code) does all the reasoning.

### Per-Repository Isolation

Each indexed repository gets its own isolated database under `~/.codelattice/repos/{repo_id}/`:

```
~/.codelattice/repos/
├── a1b2c3d4e5f67890/     # Project A
│   ├── graph.db           # SQLite graph database (WAL mode)
│   └── vectors.lancedb/   # LanceDB vector database
├── f0e1d2c3b4a59876/     # Project B
│   ├── graph.db
│   └── vectors.lancedb/
└── ...
```

This means:
- **Parallel indexing** — different repos can be indexed concurrently (no shared lock)
- **Clean isolation** — corrupting or re-indexing one repo doesn't affect others
- **Scoped search** — queries target the active repo by default, avoiding cross-repo noise

## Supported Languages

- Python
- TypeScript / TSX
- JavaScript / JSX

## MCP Tools

| Tool | Description |
|------|-------------|
| `index_repository` | Parse and index a codebase (supports incremental updates) |
| `refresh_index` | Re-index only changed files — call after code edits |
| `search_code` | Semantic search across indexed code — replaces grep/glob |
| `find_symbol` | Find a function/class/variable with its dependency graph |
| `get_dependencies` | What does a file/symbol depend on (imports, calls, base classes) |
| `get_dependents` | What depends on a file/symbol (impact analysis) |
| `get_file_summary` | Structural summary of a file without reading full contents |
| `advise` | Get best-practice advice — frameworks, patterns, principles |
| `list_skills` | List all loaded advisor skills with metadata |
| `index_status` | Check indexing stats and pending changes |
| `usage_stats` | View token savings report (CodeLattice vs traditional) |

### Token Reduction

Tools return **signatures, names, line numbers, and docstrings** — not full source code. Claude uses its built-in `Read` tool with precise line numbers only when it needs the full source. This typically reduces exploration tokens by 5-10x.

## CLI Commands

```bash
codelattice install [--project]          # set up the skill + MCP server
codelattice uninstall [--project]        # remove them
codelattice claude install               # always-on CLAUDE.md section + PreToolUse hook
codelattice claude uninstall

codelattice index /path/to/project       # index (incremental); --full to rebuild
codelattice status [/path/to/project]    # indexing status
codelattice stats                        # token savings report
codelattice serve                        # MCP server (started by Claude Code)
```

## Measuring Token Savings

CodeLattice automatically tracks every search tool call and estimates how many tokens a traditional grep/read workflow would have used for the same query.

```bash
codelattice stats

# === CodeLattice Token Savings Report ===
#
#   Period:            Last 7 day(s)
#   Total tool calls:  47
#   CodeLattice tokens:   3,842
#   Traditional est.:  28,650
#   Tokens saved:      24,808
#   Savings:           86.6%
```

Or ask Claude: *"Show me the CodeLattice token savings stats"*

## Keeping the Knowledge Base Fresh

### Stale Detection (automatic)

Every search tool automatically checks if indexed files have changed. If they have, the response includes a `_stale` warning telling Claude to call `refresh_index`.

### `refresh_index` Tool (on-demand)

After making code edits, Claude (or you) can call `refresh_index` to re-index only the changed files. This is fast — it hashes files, detects what changed, and only re-parses those.

### File Watcher (automatic background)

When a repository is indexed, CodeLattice automatically starts a file watcher (if `watchfiles` is installed). It monitors the repository for changes and triggers incremental re-indexing with a 2-second debounce.

```bash
uv tool install "codelattice[watch]"
```

### How Incremental Indexing Works

CodeLattice tracks SHA-256 content hashes per file in SQLite. On re-index:
- Only new/changed files are parsed and ingested
- Deleted files have their entities removed from the graph
- Unchanged files are skipped entirely

## Advisor Skills

CodeLattice includes an extensible advisor system that provides best-practice guidance on frameworks, design patterns, and engineering principles. Claude can call the `advise` tool during planning or code review to get relevant guidance matched by semantic similarity.

### How It Works

Skills are `SKILL.md` files with YAML frontmatter + markdown body. When Claude calls `advise("how should I structure Django views?")`, CodeLattice:

1. Embeds the query using FastEmbed (same engine as code search)
2. Computes cosine similarity against all loaded skill descriptions
3. Applies boosts for trigger phrase matches and detected project frameworks
4. Returns the best-matching skill's full content, plus metadata for secondary matches

### Built-in Skills

| Skill | Category | Description |
|-------|----------|-------------|
| `django` | framework | Project structure, views, models, ORM, DRF |
| `react` | framework | Components, hooks, state management, performance |
| `solid-principles` | principle | SRP, OCP, LSP, ISP, DIP with examples |
| `strategy-pattern` | pattern | When and how to use the Strategy pattern |

### Skill Format

Each skill is a directory containing a `SKILL.md`:

```yaml
---
name: my-skill
description: What this skill does and when to use it.
category: framework          # framework | principle | pattern | tool | custom
domains:                     # For conflict detection + matching
  - django
  - python
triggers:                    # Phrases that boost this skill's match score
  - "django views"
priority: 50                 # 0-100, higher wins conflicts
depends-on:                  # Auto-include these skills in results
  - solid-principles
metadata:
  author: my-team
  version: "1.0"
---

# My Skill

Markdown body with guidance, examples, and best practices.
```

### Adding Custom Skills

Skills are discovered from three locations (in priority order):

| Location | Source | Priority Boost |
|----------|--------|---------------|
| `{repo}/.codelattice/skills/` | Project-specific (team overrides) | +20 |
| `~/.codelattice/skills/` | User-installed (personal) | +10 |
| `src/codelattice/advisor/skills/` | Built-in (ships with CodeLattice) | +0 |

To add a custom skill:

```bash
mkdir -p ~/.codelattice/skills/my-framework
# Create ~/.codelattice/skills/my-framework/SKILL.md with the format above
```

The skill name in frontmatter must match the directory name.

### Conflict Detection

- **Name collisions**: If two skills share the same name, the higher-priority one wins (project > user > built-in). A warning is logged.
- **Domain overlaps**: If two skills in the same category share >50% of their domains, a warning is flagged (non-fatal).

### Skill Composition

Skills can declare dependencies via `depends-on`. When the primary match has dependencies, those skills are automatically included in the response with a boosted score, ensuring Claude sees related guidance together (e.g., Django advice + SOLID principles).

## Configuration

All settings are in `.env` (see `.env.template`). **The defaults work with zero configuration.**

```bash
cp .env.template .env  # optional — only if you want to customize
```

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDING_PROVIDER` | `fastembed` | Embedding provider (local, no API key) |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model |
| `EMBEDDING_DIMENSIONS` | `384` | Embedding vector size |
| `VECTOR_DB_PROVIDER` | `lancedb` | Vector store (file-based) |
| `GRAPH_DATABASE_PROVIDER` | `sqlite` | Graph DB (file-based, WAL mode) |
| `DB_PROVIDER` | `sqlite` | Relational DB (file-based) |
| `CODELATTICE_DATA_DIR` | `~/.codelattice` | Where indexes are stored |
| `CODELATTICE_MAX_FILE_SIZE_KB` | `500` | Skip files larger than this |
| `CODELATTICE_BATCH_SIZE` | `200` | DataPoints per ingestion batch |

### Optional: Higher Quality Embeddings with Ollama

```env
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=nomic-embed-text:latest
EMBEDDING_ENDPOINT=http://localhost:11434/api/embed
EMBEDDING_DIMENSIONS=768
HUGGINGFACE_TOKENIZER=nomic-ai/nomic-embed-text-v1.5
```

### Optional: Cloud Embeddings with OpenAI

```env
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
EMBEDDING_API_KEY=sk-your-key-here
```

## Architecture

```
src/codelattice/
├── cli.py                      # `codelattice` command
├── install.py                  # install / uninstall / claude install / hook-guard
├── skill/SKILL.md              # The /codelattice skill copied by `install`
├── always_on/claude-md.md      # CLAUDE.md section written by `claude install`
├── config/settings.py          # Pydantic settings from .env
├── models/code_entities.py     # 6 DataPoint subclasses (CodeFile, CodeFunction, etc.)
├── parser/
│   ├── languages.py            # Language registry + tree-sitter grammar loading
│   ├── tree_sitter_parser.py   # Core parsing engine
│   └── queries/                # Tree-sitter S-expression patterns per language
├── indexer/
│   ├── file_discovery.py       # .gitignore-aware file walking
│   ├── file_hasher.py          # SHA-256 change detection
│   ├── incremental_state.py    # SQLite state tracking
│   ├── repository_indexer.py   # Orchestrator (per-repo locking)
│   └── watcher.py              # File watcher for auto re-indexing
├── graph/
│   ├── engines.py              # Per-repo SQLite + LanceDB engine cache
│   ├── sqlite_graph.py         # SQLite graph adapter (WAL mode, concurrent readers)
│   ├── ingester.py             # ParseResult -> DataPoints -> direct SQLite/LanceDB writes
│   ├── searcher.py             # Per-repo and cross-repo vector + graph queries
│   └── query_builder.py        # Tool params -> search queries
└── server/
    ├── mcp_server.py           # FastMCP server + tool registration
    ├── tools.py                # MCP tool implementations (repo-aware)
    └── formatters.py           # Token-efficient result formatting
```

## Development

```bash
git clone https://github.com/smrf1093/CodeLattice.git && cd CodeLattice
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/codelattice install    # points Claude Code at your working copy
.venv/bin/ruff check src/
.venv/bin/pytest
```

### Releasing

Bump `version` in `pyproject.toml` and `src/codelattice/__init__.py`, push, then create a GitHub release tagged `v<version>`. The `Publish to PyPI` workflow tests, builds and uploads it via PyPI trusted publishing.

## Built With

CodeLattice stands on the shoulders of these excellent open-source projects:

| Library | Role |
|---------|------|
| [Cognee](https://github.com/topoteretes/cognee) | Knowledge graph framework — data point modeling, vector infrastructure |
| [tree-sitter](https://github.com/tree-sitter/tree-sitter) | Incremental parsing for accurate code extraction across languages |
| [FastMCP](https://github.com/jlowin/fastmcp) | Model Context Protocol server framework for Claude Code integration |
| [FastEmbed](https://github.com/qdrant/fastembed) | Local CPU-based text embeddings — no API keys, no GPU required |
| [LanceDB](https://github.com/lancedb/lancedb) | Embedded vector database — file-based, zero-config |
| [Pydantic](https://github.com/pydantic/pydantic) | Settings management and data validation |
| [Astro](https://github.com/withastro/astro) | Landing page — static site generator with zero JS by default |
| [Tailwind CSS](https://github.com/tailwindlabs/tailwindcss) | Landing page styling |

## License

MIT
