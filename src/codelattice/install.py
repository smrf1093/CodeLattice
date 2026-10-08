"""Install / uninstall CodeLattice into Claude Code.

Mirrors the graphify setup flow:

    uv tool install codelattice     # put the `codelattice` CLI on PATH
    codelattice install             # skill + MCP server, user-wide
    /codelattice .                  # inside Claude Code: index the repo

``codelattice install --project`` writes the same pieces into the current repo
(``.claude/skills``, ``.claude/CLAUDE.md``, ``.mcp.json``) so they can be committed.

``codelattice claude install`` is the optional always-on step: a CLAUDE.md
section in the project plus a PreToolUse hook that nudges Grep/Glob calls
toward the CodeLattice tools once the repo is indexed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import click

_PKG_DIR = Path(__file__).parent
_SKILL_SRC = _PKG_DIR / "skill" / "SKILL.md"
_CLAUDE_MD_SRC = _PKG_DIR / "always_on" / "claude-md.md"

_SERVER_NAME = "codelattice"
_MARKER_START = "<!-- codelattice:start -->"
_MARKER_END = "<!-- codelattice:end -->"


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def _claude_config_dir() -> Path:
    """User-level Claude Code config dir, honoring CLAUDE_CONFIG_DIR."""
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env).expanduser() if env else Path.home() / ".claude"


def _resolve_exe(project: bool = False) -> str:
    """Absolute path to the `codelattice` executable, or the bare command.

    A project-scoped install is committed and shared, so it uses the bare
    command and lets PATH resolve it on each machine.
    """
    if project:
        return "codelattice"
    found = shutil.which("codelattice")
    if not found:
        for name in ("codelattice", "codelattice.exe"):
            candidate = Path(sys.executable).parent / name
            if candidate.exists():
                found = str(candidate)
                break
    return (found or "codelattice").replace("\\", "/")


# ---------------------------------------------------------------------------
# Marker sections (CLAUDE.md)
# ---------------------------------------------------------------------------


def _wrap(body: str) -> str:
    return f"{_MARKER_START}\n{body.rstrip()}\n{_MARKER_END}"


def _upsert_section(path: Path, body: str) -> bool:
    """Add or replace the CodeLattice section in *path*. Returns True if changed."""
    section = _wrap(body)
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    pattern = re.compile(re.escape(_MARKER_START) + r".*?" + re.escape(_MARKER_END), re.DOTALL)
    if pattern.search(content):
        new = pattern.sub(lambda _: section, content)
    elif content:
        new = content.rstrip("\n") + "\n\n" + section + "\n"
    else:
        new = section + "\n"
    if new == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding="utf-8")
    return True


def _remove_section(path: Path) -> bool:
    if not path.exists():
        return False
    content = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"\n*" + re.escape(_MARKER_START) + r".*?" + re.escape(_MARKER_END) + r"\n?", re.DOTALL
    )
    new = pattern.sub("\n", content).strip("\n")
    if new == content.strip("\n"):
        return False
    if new:
        path.write_text(new + "\n", encoding="utf-8")
    else:
        path.unlink()
    return True


def _skill_registration(skill_ref: str) -> str:
    return (
        "# codelattice\n"
        f"- **codelattice** (`{skill_ref}`) - code knowledge graph: semantic code search, symbols, dependencies. "
        "Trigger: `/codelattice`\n"
        "When the user types `/codelattice`, use the installed codelattice skill "
        "before doing anything else."
    )


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError as e:
        raise click.ClickException(f"{path} is not valid JSON ({e}); fix it and re-run.")
    if not isinstance(data, dict):
        raise click.ClickException(f"{path} is not a JSON object; refusing to modify it.")
    return data


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# MCP server registration
# ---------------------------------------------------------------------------


def _mcp_entry(project: bool) -> dict:
    return {"type": "stdio", "command": _resolve_exe(project), "args": ["serve"], "env": {}}


def _claude_mcp(*args: str) -> bool:
    """Run `claude mcp <args>`; False if the CLI is missing or the call failed."""
    claude = shutil.which("claude")
    if not claude:
        return False
    try:
        res = subprocess.run(
            [claude, "mcp", *args], capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return res.returncode == 0


def _register_mcp_user() -> str:
    """Register the server at user scope. Prefers the `claude` CLI, since Claude
    Code rewrites ~/.claude.json while running; falls back to editing it."""
    entry = _mcp_entry(project=False)
    _claude_mcp("remove", _SERVER_NAME, "-s", "user")
    if _claude_mcp("add-json", _SERVER_NAME, json.dumps(entry), "-s", "user"):
        return f"claude mcp (user scope) -> {entry['command']} serve"
    path = Path.home() / ".claude.json"
    config = _read_json(path)
    config.setdefault("mcpServers", {})[_SERVER_NAME] = entry
    _write_json(path, config)
    return f"{path} -> {entry['command']} serve"


def _unregister_mcp_user() -> bool:
    if _claude_mcp("remove", _SERVER_NAME, "-s", "user"):
        return True
    path = Path.home() / ".claude.json"
    config = _read_json(path)
    if config.get("mcpServers", {}).pop(_SERVER_NAME, None) is None:
        return False
    _write_json(path, config)
    return True


def _register_mcp_project(project_dir: Path) -> Path:
    path = project_dir / ".mcp.json"
    config = _read_json(path)
    config.setdefault("mcpServers", {})[_SERVER_NAME] = _mcp_entry(project=True)
    _write_json(path, config)
    return path


def _unregister_mcp_project(project_dir: Path) -> bool:
    path = project_dir / ".mcp.json"
    config = _read_json(path)
    if config.get("mcpServers", {}).pop(_SERVER_NAME, None) is None:
        return False
    if config["mcpServers"] or set(config) - {"mcpServers"}:
        _write_json(path, config)
    else:
        path.unlink()
    return True


# ---------------------------------------------------------------------------
# install / uninstall
# ---------------------------------------------------------------------------


def install(project: bool = False, project_dir: Path | None = None) -> None:
    """Install the /codelattice skill and register the MCP server."""
    project_dir = (project_dir or Path(".")).resolve()

    if project:
        skill_dst = project_dir / ".claude" / "skills" / "codelattice" / "SKILL.md"
        claude_md = project_dir / ".claude" / "CLAUDE.md"
        skill_ref = ".claude/skills/codelattice/SKILL.md"
    else:
        config_dir = _claude_config_dir()
        skill_dst = config_dir / "skills" / "codelattice" / "SKILL.md"
        claude_md = config_dir / "CLAUDE.md"
        skill_ref = (
            "~/.claude/skills/codelattice/SKILL.md"
            if config_dir == Path.home() / ".claude"
            else str(skill_dst)
        )

    skill_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_SKILL_SRC, skill_dst)
    click.echo(f"  skill installed  ->  {skill_dst}")

    _upsert_section(claude_md, _skill_registration(skill_ref))
    click.echo(f"  CLAUDE.md        ->  {claude_md}")

    if project:
        mcp_path = _register_mcp_project(project_dir)
        click.echo(f"  MCP server       ->  {mcp_path}")
        click.echo("\nProject-scoped install. Add to version control:")
        click.echo("  git add .claude/skills/codelattice .claude/CLAUDE.md .mcp.json")
    else:
        click.echo(f"  MCP server       ->  {_register_mcp_user()}")

    click.echo("\nDone. Restart Claude Code (so it loads the MCP server), then type:\n")
    click.echo("  /codelattice .\n")


def uninstall(project: bool = False, project_dir: Path | None = None) -> None:
    """Remove the skill, its CLAUDE.md registration and the MCP server."""
    project_dir = (project_dir or Path(".")).resolve()
    if project:
        skill_dir = project_dir / ".claude" / "skills" / "codelattice"
        claude_md = project_dir / ".claude" / "CLAUDE.md"
        mcp_removed = _unregister_mcp_project(project_dir)
    else:
        config_dir = _claude_config_dir()
        skill_dir = config_dir / "skills" / "codelattice"
        claude_md = config_dir / "CLAUDE.md"
        mcp_removed = _unregister_mcp_user()

    if skill_dir.exists():
        shutil.rmtree(skill_dir)
        click.echo(f"  skill removed    ->  {skill_dir}")
    if _remove_section(claude_md):
        click.echo(f"  CLAUDE.md        ->  section removed from {claude_md}")
    if mcp_removed:
        click.echo("  MCP server       ->  unregistered")
    click.echo(
        "\nCodeLattice uninstalled. Indexed data stays in ~/.codelattice (delete it to free space)."
    )


# ---------------------------------------------------------------------------
# claude install / uninstall (always-on CLAUDE.md section + PreToolUse hook)
# ---------------------------------------------------------------------------

_HOOK_MATCHER = "Bash|Grep|Glob"


def _hook_entry(project: bool) -> dict:
    exe = _resolve_exe(project)
    if " " in exe:
        exe = f'"{exe}"'
    return {
        "matcher": _HOOK_MATCHER,
        "hooks": [{"type": "command", "command": f"{exe} hook-guard", "timeout": 10}],
    }


def _is_our_hook(h: object) -> bool:
    return isinstance(h, dict) and "codelattice hook-guard" in json.dumps(h).replace('"', "")


def _strip_hook(settings_path: Path) -> bool:
    if not settings_path.exists():
        return False
    settings = _read_json(settings_path)
    pre = settings.get("hooks", {}).get("PreToolUse")
    if not isinstance(pre, list):
        return False
    kept = [h for h in pre if not _is_our_hook(h)]
    if len(kept) == len(pre):
        return False
    if kept:
        settings["hooks"]["PreToolUse"] = kept
    else:
        del settings["hooks"]["PreToolUse"]
        if not settings["hooks"]:
            del settings["hooks"]
    _write_json(settings_path, settings)
    return True


def claude_install(project_dir: Path | None = None, project: bool = False) -> None:
    """Write the CodeLattice section to CLAUDE.md and add the PreToolUse hook."""
    project_dir = (project_dir or Path(".")).resolve()
    claude_md = project_dir / "CLAUDE.md"
    changed = _upsert_section(claude_md, _CLAUDE_MD_SRC.read_text(encoding="utf-8"))
    click.echo(f"  CLAUDE.md              ->  {claude_md}" + ("" if changed else " (no change)"))

    settings_path = project_dir / ".claude" / "settings.json"
    _strip_hook(settings_path)
    settings = _read_json(settings_path)
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict) or not isinstance(hooks.setdefault("PreToolUse", []), list):
        raise click.ClickException(
            f"Unexpected 'hooks' shape in {settings_path}; not modifying it."
        )
    hooks["PreToolUse"].append(_hook_entry(project))
    _write_json(settings_path, settings)
    click.echo(f"  .claude/settings.json  ->  PreToolUse hook registered ({_HOOK_MATCHER})")

    click.echo("\nClaude Code will now prefer CodeLattice tools over grep for this project.")


def claude_uninstall(project_dir: Path | None = None) -> None:
    project_dir = (project_dir or Path(".")).resolve()
    if _remove_section(project_dir / "CLAUDE.md"):
        click.echo("  CLAUDE.md              ->  section removed")
    for name in ("settings.json", "settings.local.json"):
        if _strip_hook(project_dir / ".claude" / name):
            click.echo(f"  .claude/{name:<14} ->  PreToolUse hook removed")


# ---------------------------------------------------------------------------
# hook-guard (runs on every matched tool call — must be fast and fail open)
# ---------------------------------------------------------------------------

_NUDGE = json.dumps(
    {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                "This repo is indexed by CodeLattice. Before grepping or globbing raw "
                "files, use the codelattice MCP tools: search_code (by meaning), "
                "find_symbol (by name, with callers/callees), get_dependencies / "
                "get_dependents, get_file_summary. Grep is fine for exact strings or "
                "once CodeLattice has pointed you to the right files."
            ),
        }
    },
    separators=(",", ":"),
)

_SEARCH_COMMANDS = {"grep", "egrep", "rg", "ag", "ack", "find", "fd"}


def _indexed_root(start: Path) -> Path | None:
    """Return the nearest ancestor of *start* that has a CodeLattice index."""
    data_dir = Path(os.environ.get("CODELATTICE_DATA_DIR", "~/.codelattice")).expanduser()
    repos = data_dir / "repos"
    if not repos.is_dir():
        return None
    for p in (start, *start.parents):
        repo_id = hashlib.sha256(str(p).encode()).hexdigest()[:16]
        if (repos / repo_id / "graph.db").is_file():
            return p
    return None


def run_hook_guard() -> None:
    """Read a PreToolUse payload on stdin; print a nudge if it is a raw search in an
    indexed repo. Any error prints nothing, so a tool call is never blocked."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        tool = payload.get("tool_name", "")
        if tool == "Bash":
            words = str(payload.get("tool_input", {}).get("command", "")).split()
            if not words or not (words[0] in _SEARCH_COMMANDS or words[:2] == ["git", "grep"]):
                return
        elif tool not in ("Grep", "Glob"):
            return
        cwd = Path(payload.get("cwd") or os.getcwd()).resolve()
        if _indexed_root(cwd) is not None:
            sys.stdout.write(_NUDGE + "\n")
    except Exception:  # noqa: BLE001 — a hook must never break the tool call
        return
