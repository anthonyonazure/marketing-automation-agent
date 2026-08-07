"""Eval harness runner.

Generates a draft for every target in evals/targets-eval.yaml, scores each
against evals.assertions.ALL_ASSERTIONS, and writes:
  - evals/results/<run-id>.json (machine readable)
  - evals/results/<run-id>.md   (human readable summary)

Run with stub LLM (no API key) for a fast deterministic baseline, or with
ANTHROPIC_API_KEY set to score the real model. Cost is roughly:
  20 targets × 2 LLM calls (draft + review) × ~1500 tokens = ~$0.04 / run

Trigger:
  outreach evals                          (default targets-eval.yaml)
  outreach evals --targets <other.yaml>
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from evals.assertions import evaluate_draft
from outreach.drafting import write_draft

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_TARGETS = EVAL_DIR / "targets-eval.yaml"
RESULTS_DIR = EVAL_DIR / "results"


async def run_eval(targets_path: Path, *, tone: str = "peer-cynical") -> dict:
    targets = yaml.safe_load(targets_path.read_text())["targets"]

    async def _one(target: dict) -> dict:
        # Skip the network call entirely in eval — eval is about draft quality,
        # not enrichment, and example.com domains never resolve anyway.
        enrichment: dict[str, Any] = {
            "page_title": None,
            "first_paragraphs": [],
            "fetch_ok": False,
        }
        draft = await write_draft(target, enrichment, tone=tone)
        return evaluate_draft(draft, target)

    scored = await asyncio.gather(*[_one(t) for t in targets])

    pass_count = sum(1 for s in scored if s["passed"])
    failures_by_assertion: Counter[str] = Counter()
    for s in scored:
        for r in s["results"]:
            if not r["passed"]:
                failures_by_assertion[r["assertion"]] += 1

    return {
        "run_id": uuid.uuid4().hex[:10],
        "ran_at": datetime.now(UTC).isoformat(),
        "target_count": len(targets),
        "pass_count": pass_count,
        "fail_count": len(targets) - pass_count,
        "pass_rate_pct": round(pass_count / max(len(targets), 1) * 100, 1),
        "model": "stub"
        if not os.environ.get("ANTHROPIC_API_KEY")
        else os.environ.get("OUTREACH_MODEL", "claude-sonnet-4-6"),
        "failures_by_assertion": dict(failures_by_assertion),
        "per_target": scored,
    }


def write_reports(report: dict) -> tuple[Path, Path]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    rid = report["run_id"]
    json_path = RESULTS_DIR / f"{rid}.json"
    md_path = RESULTS_DIR / f"{rid}.md"

    json_path.write_text(json.dumps(report, indent=2, default=str))

    lines = [
        f"# Eval run `{rid}`",
        "",
        f"- **Ran:** {report['ran_at']}",
        f"- **Model:** `{report['model']}`",
        f"- **Pass rate:** {report['pass_rate_pct']}% ({report['pass_count']} / {report['target_count']})",
        "",
        "## Failures by assertion",
        "",
        "| Assertion | Failures |",
        "|---|---|",
    ]
    for name, _ in sorted(report["failures_by_assertion"].items(), key=lambda x: -x[1]):
        lines.append(f"| `{name}` | {report['failures_by_assertion'][name]} |")
    if not report["failures_by_assertion"]:
        lines.append("| _no failures_ | 0 |")

    lines += [
        "",
        "## Per-target detail",
        "",
        "| Company | Subject | Passed |",
        "|---|---|---|",
    ]
    for s in report["per_target"]:
        mark = "✓" if s["passed"] else "✗"
        subj = (s["subject"] or "")[:60].replace("|", "\\|")
        lines.append(f"| {s['company']} | {subj} | {mark} |")

    md_path.write_text("\n".join(lines))
    return json_path, md_path


async def main(targets_path: Path | None = None) -> dict:
    report = await run_eval(targets_path or DEFAULT_TARGETS)
    json_path, md_path = write_reports(report)
    print(
        f"Pass rate: {report['pass_rate_pct']}%  ({report['pass_count']}/{report['target_count']})"
    )
    print(f"Reports:  {md_path}  +  {json_path}")
    return report


if __name__ == "__main__":
    asyncio.run(main())
