"""CLI entry points for CodeLattice."""

from __future__ import annotations

import asyncio
import json

import click

from codelattice import __version__
from codelattice.config.settings import apply_cognee_env


@click.group()
@click.version_option(__version__, prog_name="codelattice")
def main():
    """CodeLattice — code knowledge graph for Claude Code.

    \b
    Setup:
      uv tool install codelattice
      codelattice install          # then, in Claude Code:  /codelattice .
    """


@main.command()
@click.option("--project", is_flag=True, help="Install into the current repo instead of user-wide")
def install(project: bool):
    """Install the /codelattice skill and register the MCP server with Claude Code."""
    from codelattice.install import install as _install

    _install(project=project)


@main.command()
@click.option("--project", is_flag=True, help="Uninstall from the current repo")
def uninstall(project: bool):
    """Remove the /codelattice skill and MCP server registration."""
    from codelattice.install import uninstall as _uninstall

    _uninstall(project=project)


@main.group()
def claude():
    """Always-on Claude Code integration for the current project."""


@claude.command(name="install")
@click.option(
    "--project", is_flag=True, help="Use the bare `codelattice` command (for committed config)"
)
def claude_install(project: bool):
    """Write the CodeLattice section to CLAUDE.md and add a PreToolUse hook."""
    from codelattice.install import claude_install as _claude_install

    _claude_install(project=project)


@claude.command(name="uninstall")
def claude_uninstall():
    """Remove the CodeLattice CLAUDE.md section and PreToolUse hook."""
    from codelattice.install import claude_uninstall as _claude_uninstall

    _claude_uninstall()


@main.command(name="hook-guard", hidden=True)
def hook_guard():
    """PreToolUse hook: nudge raw Grep/Glob toward CodeLattice in indexed repos."""
    from codelattice.install import run_hook_guard

    run_hook_guard()


@main.command()
@click.option(
    "--transport",
    default="stdio",
    type=click.Choice(["stdio", "http"]),
    help="MCP transport mode (default: stdio)",
)
@click.option("--port", default=8000, help="Port for HTTP transport (default: 8000)")
def serve(transport: str, port: int):
    """Start the CodeLattice MCP server."""
    apply_cognee_env()
    from codelattice.server.mcp_server import run_server

    run_server(transport=transport)


@main.command()
@click.argument("path")
@click.option("--full", is_flag=True, help="Force full re-index (ignore incremental state)")
@click.option(
    "--languages", "-l", multiple=True, help="Languages to index (python, typescript, javascript)"
)
def index(path: str, full: bool, languages: tuple[str, ...]):
    """Index a code repository."""
    apply_cognee_env()

    async def _run():
        from codelattice.indexer.repository_indexer import index_repository

        result = await index_repository(
            repo_path=path,
            incremental=not full,
            languages=list(languages) if languages else None,
        )
        click.echo(
            json.dumps(
                {
                    "status": "completed",
                    "repo_path": result.repo_path,
                    "new_files": result.new_files,
                    "changed_files": result.changed_files,
                    "deleted_files": result.deleted_files,
                    "unchanged_files": result.unchanged_files,
                    "total_entities": result.total_entities,
                    "duration_seconds": round(result.duration_seconds, 2),
                    "errors": result.errors[:10] if result.errors else [],
                },
                indent=2,
            )
        )

    asyncio.run(_run())


@main.command()
@click.argument("path", required=False)
def status(path: str | None):
    """Show indexing status for a repository (or all repos)."""
    from codelattice.indexer.repository_indexer import get_index_status

    result = get_index_status(repo_path=path)
    click.echo(json.dumps(result, indent=2))


@main.command()
@click.option("--days", "-d", default=7, help="Number of days to show (default: 7)")
@click.option("--reset", is_flag=True, help="Reset all usage statistics")
def stats(days: int, reset: bool):
    """Show token usage statistics and savings report."""
    from codelattice.stats.tracker import get_tracker

    tracker = get_tracker()

    if reset:
        result = tracker.reset()
        click.echo(json.dumps(result, indent=2))
        return

    summary = tracker.get_summary(days=days)

    # Pretty-print the summary
    click.echo("\n=== CodeLattice Token Savings Report ===\n")
    click.echo(f"  Period:            {summary['period']}")
    click.echo(f"  Total tool calls:  {summary['total_calls']}")
    click.echo(f"  CodeLattice tokens:   {summary['total_codelattice_tokens']:,}")
    click.echo(f"  Traditional est.:  {summary['total_traditional_estimate']:,}")
    click.echo(f"  Tokens saved:      {summary['total_tokens_saved']:,}")
    click.echo(f"  Savings:           {summary['overall_savings']}")
    click.echo(f"\n  Lifetime calls:    {summary['lifetime_calls']}")
    click.echo(f"  Lifetime saved:    {summary['lifetime_saved']:,} tokens")

    if summary.get("daily"):
        click.echo("\n--- Daily Breakdown ---\n")
        click.echo(
            f"  {'Date':<12} {'Calls':>6} {'CodeLattice':>10} {'Traditional':>12} {'Saved':>10} {'%':>7}"
        )
        click.echo(f"  {'-' * 12} {'-' * 6} {'-' * 10} {'-' * 12} {'-' * 10} {'-' * 7}")
        for day in summary["daily"]:
            click.echo(
                f"  {day['date']:<12} {day['calls']:>6} "
                f"{day['codelattice_tokens']:>10,} {day['traditional_estimate']:>12,} "
                f"{day['saved']:>10,} {day['savings_pct']:>7}"
            )

    click.echo()


if __name__ == "__main__":
    main()
