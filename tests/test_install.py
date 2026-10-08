"""Tests for `codelattice install` / `claude install` / `hook-guard`."""

import hashlib
import io
import json

import pytest

from codelattice import install as inst


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolated HOME with no `claude` CLI on PATH (forces the JSON fallback)."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(inst.shutil, "which", lambda name: None)
    return h


def test_user_install_and_uninstall(home):
    inst.install()

    skill = home / ".claude" / "skills" / "codelattice" / "SKILL.md"
    assert skill.read_text().startswith("---\nname: codelattice")
    claude_md = (home / ".claude" / "CLAUDE.md").read_text()
    assert "Trigger: `/codelattice`" in claude_md
    server = json.loads((home / ".claude.json").read_text())["mcpServers"]["codelattice"]
    assert server["args"] == ["serve"]

    # Idempotent: a second install leaves one section
    inst.install()
    assert (home / ".claude" / "CLAUDE.md").read_text().count(inst._MARKER_START) == 1

    inst.uninstall()
    assert not skill.exists()
    assert not (home / ".claude" / "CLAUDE.md").exists()
    assert "codelattice" not in json.loads((home / ".claude.json").read_text())["mcpServers"]


def test_project_install_uses_bare_command(home, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))

    inst.install(project=True, project_dir=repo)

    assert (repo / ".claude" / "skills" / "codelattice" / "SKILL.md").exists()
    servers = json.loads((repo / ".mcp.json").read_text())["mcpServers"]
    assert servers["codelattice"]["command"] == "codelattice"
    assert "other" in servers

    inst.uninstall(project=True, project_dir=repo)
    assert list(json.loads((repo / ".mcp.json").read_text())["mcpServers"]) == ["other"]


def test_claude_install_preserves_existing_content(home, tmp_path):
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    (repo / "CLAUDE.md").write_text("# My project\n\nKeep me.\n")
    other_hook = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}
    (repo / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"PreToolUse": [other_hook]}})
    )

    inst.claude_install(project_dir=repo)
    inst.claude_install(project_dir=repo)  # re-run must not duplicate

    md = (repo / "CLAUDE.md").read_text()
    assert md.startswith("# My project") and md.count(inst._MARKER_START) == 1
    pre = json.loads((repo / ".claude" / "settings.json").read_text())["hooks"]["PreToolUse"]
    assert pre[0] == other_hook and len(pre) == 2

    inst.claude_uninstall(project_dir=repo)
    assert (repo / "CLAUDE.md").read_text() == "# My project\n\nKeep me.\n"
    pre = json.loads((repo / ".claude" / "settings.json").read_text())["hooks"]["PreToolUse"]
    assert pre == [other_hook]


def _run_guard(monkeypatch, capsys, payload):
    monkeypatch.setattr(inst.sys, "stdin", io.StringIO(json.dumps(payload)))
    inst.run_hook_guard()
    return capsys.readouterr().out


def test_hook_guard_nudges_only_in_indexed_repos(tmp_path, monkeypatch, capsys):
    data = tmp_path / "data"
    monkeypatch.setenv("CODELATTICE_DATA_DIR", str(data))
    repo = (tmp_path / "repo").resolve()
    (repo / "src").mkdir(parents=True)

    grep = {"tool_name": "Grep", "cwd": str(repo / "src"), "tool_input": {"pattern": "x"}}
    assert _run_guard(monkeypatch, capsys, grep) == ""

    repo_id = hashlib.sha256(str(repo).encode()).hexdigest()[:16]
    (data / "repos" / repo_id).mkdir(parents=True)
    (data / "repos" / repo_id / "graph.db").touch()

    assert "search_code" in _run_guard(monkeypatch, capsys, grep)
    bash_rg = {"tool_name": "Bash", "cwd": str(repo), "tool_input": {"command": "rg foo src"}}
    assert "search_code" in _run_guard(monkeypatch, capsys, bash_rg)
    bash_ls = {"tool_name": "Bash", "cwd": str(repo), "tool_input": {"command": "fdisk -l"}}
    assert _run_guard(monkeypatch, capsys, bash_ls) == ""
    read = {"tool_name": "Read", "cwd": str(repo), "tool_input": {"file_path": "a.py"}}
    assert _run_guard(monkeypatch, capsys, read) == ""


def test_hook_guard_fails_open_on_bad_input(monkeypatch, capsys):
    monkeypatch.setattr(inst.sys, "stdin", io.StringIO("not json"))
    inst.run_hook_guard()
    assert capsys.readouterr().out == ""
