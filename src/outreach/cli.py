"""Typer CLI: outreach run --targets targets/sample.yaml [--tone peer-cynical]."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

import structlog
import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from outreach.graph import build_graph
from outreach.state import OutreachState

load_dotenv()

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()
log = structlog.get_logger()


@app.command()
def run(
    targets: str = typer.Option("targets/sample.yaml", "--targets", "-t", help="YAML file with target list"),
    tone: str = typer.Option(None, "--tone", help="Override OUTREACH_TONE env"),
    sender: str = typer.Option(None, "--sender", help="Override OUTREACH_SENDER_UPN env"),
    save_log: bool = typer.Option(True, help="Persist event log to out/"),
) -> None:
    """Generate personalized outreach drafts for a target list."""
    asyncio.run(_run(targets, tone, sender, save_log))


async def _run(targets_path: str, tone: str | None, sender: str | None, save_log: bool) -> None:
    run_id = uuid.uuid4().hex[:10]
    initial: OutreachState = {
        "run_id": run_id,
        "targets_path": targets_path,
        "tone": tone or os.environ.get("OUTREACH_TONE", "peer-cynical"),
        "sender_upn": sender or os.environ.get("OUTREACH_SENDER_UPN", ""),
        "events": [],
        "errors": [],
    }
    graph = build_graph().compile()
    console.rule(f"[bold cyan]Outreach run {run_id}[/]")

    final: OutreachState = {}
    async for ev in graph.astream(initial, stream_mode="values"):
        final = ev
        last = (ev.get("events") or [{}])[-1]
        if last:
            console.print(f"  [green]✓[/] {last.get('kind', '?')}")

    drafts = final.get("drafts") or []
    deliveries = final.get("delivery") or []

    table = Table(show_header=True, box=None)
    table.add_column("Company", min_width=22)
    table.add_column("Subject", min_width=40)
    table.add_column("Verdict", width=8)
    table.add_column("Draft", width=10)
    reviews_by_co = {r["company"]: r for r in final.get("reviews", [])}
    deliv_by_co = {d["company"]: d for d in deliveries}
    for d in drafts:
        co = d["company"]
        v = reviews_by_co.get(co, {}).get("verdict", "?")
        delv = deliv_by_co.get(co, {})
        delv_pill = "DRAFT" if delv.get("draft_id") else ("ERROR" if delv.get("error") else "—")
        table.add_row(co, d.get("subject", ""), v, delv_pill)
    console.rule("[bold cyan]Result[/]")
    console.print(table)

    out_dir = Path(os.environ.get("OUTREACH_DRAFTS_DIR", "drafts"))
    console.print(f"\n[dim]Drafts saved to: {out_dir}/[/]")

    if save_log:
        out = Path("out") / f"{run_id}.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(final, default=str, indent=2))
        console.print(f"[dim]Event log: {out}[/]")


@app.command()
def evals(
    targets: str = typer.Option("evals/targets-eval.yaml", "--targets", "-t"),
) -> None:
    """Run the eval harness — score generated drafts against deterministic
    quality assertions. With ANTHROPIC_API_KEY set, evaluates the real model;
    without, evaluates the stub fallback as a baseline."""
    from evals.run import main as run_eval

    report = asyncio.run(run_eval(Path(targets)))
    if report["fail_count"]:
        console.print(f"\n[red]{report['fail_count']} targets failed assertions.[/]")
        for name, n in sorted(report["failures_by_assertion"].items(), key=lambda x: -x[1]):
            console.print(f"  · `{name}`: {n} failure(s)")


@app.command()
def version() -> None:
    """Print agent version."""
    from outreach import __version__
    console.print(f"marketing-automation-agent {__version__}")


if __name__ == "__main__":
    app()
