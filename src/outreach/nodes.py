"""LangGraph nodes for outreach.

Per-target steps run inside Send/map nodes — there's one task per target,
each task is sequential (enrich → draft → review → deliver) but the targets
themselves run in parallel."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import structlog
import yaml
from azure.core.exceptions import AzureError
from b2b_toolkit import get_adapters

from outreach.drafting import (
    review_brand_voice,
    rewrite_draft,
    write_draft,
)
from outreach.enrichment import enrich_target
from outreach.state import OutreachState

log = structlog.get_logger()


def _drafts_dir() -> Path:
    p = Path(os.environ.get("OUTREACH_DRAFTS_DIR", "drafts"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _event(kind: str, **detail: Any) -> dict[str, Any]:
    return {"at": datetime.now(UTC).isoformat(), "kind": kind, **detail}


async def load_targets(state: OutreachState) -> dict[str, Any]:
    path = Path(state["targets_path"])
    data = yaml.safe_load(path.read_text())
    targets = data["targets"]
    log.info("outreach.targets.loaded", count=len(targets), path=str(path))
    return {
        "targets": targets,
        "events": [_event("targets_loaded", count=len(targets))],
    }


async def _per_target(target: dict, tone: str, sender_upn: str) -> dict[str, Any]:
    """Sequential per-target pipeline. Returns a dict that the parallel
    fan-in node aggregates into state lists."""
    company = target["company"]
    log.info("outreach.target.start", company=company)

    enrichment = await enrich_target(target)

    draft = await write_draft(target, enrichment, tone=tone)
    review = await review_brand_voice(draft, target)
    if review.get("verdict") == "rewrite":
        draft = await rewrite_draft(target, enrichment, draft, review, tone=tone)
        review = await review_brand_voice(draft, target)

    # Deliver as a draft into M365 mailbox (mock or real)
    delivery: dict[str, Any]
    if not sender_upn:
        delivery = {"company": company, "skipped": True, "reason": "no_sender_upn"}
    else:
        adapters = get_adapters()
        try:
            html = (
                "<p>"
                + draft["body"].replace("\n\n", "</p><p>").replace("\n", "<br>")
                + "</p>"
            )
            d = await adapters.m365_mailer.create_draft(
                sender_upn=sender_upn,
                to=[target["contact_email"]],
                subject=draft["subject"],
                body_html=html,
            )
            delivery = {
                "company": company,
                "draft_id": d.draft_id,
                "to": d.to,
                "subject": d.subject,
                "web_link": d.web_link,
            }
        # Delivery is best-effort: a Graph or auth failure is recorded against
        # the company and the run continues. Anything that is not a transport or
        # Azure credential failure is a real bug and still propagates.
        except (httpx.HTTPError, AzureError) as e:
            delivery = {"company": company, "error": str(e)[:300]}

    # Also persist to disk for audit / inspection
    slug = company.lower().replace(" ", "-")
    Path(_drafts_dir() / f"{slug}.md").write_text(
        f"# To: {target['contact_email']}\n# Subject: {draft['subject']}\n\n{draft['body']}\n"
    )

    return {
        "enrichment": {
            "company": company,
            **{k: v for k, v in enrichment.items() if k != "company"},
        },
        "draft": {"company": company, **draft},
        "review": {"company": company, **review},
        "delivery": delivery,
    }


async def process_targets(state: OutreachState) -> dict[str, Any]:
    """Fan out per-target pipelines in parallel."""
    tone = state.get("tone", "peer-cynical")
    sender_upn = state.get("sender_upn") or ""
    targets = state["targets"]
    results = await asyncio.gather(*[_per_target(t, tone, sender_upn) for t in targets])

    enrichments = [r["enrichment"] for r in results]
    drafts = [r["draft"] for r in results]
    reviews = [r["review"] for r in results]
    delivery = [r["delivery"] for r in results]

    delivered = sum(1 for d in delivery if d.get("draft_id"))
    skipped = sum(1 for d in delivery if d.get("skipped"))
    errored = sum(1 for d in delivery if d.get("error"))
    log.info(
        "outreach.batch.done", delivered=delivered, skipped=skipped, errored=errored
    )

    return {
        "enrichments": enrichments,
        "drafts": drafts,
        "reviews": reviews,
        "delivery": delivery,
        "events": [
            _event(
                "outreach_batch",
                delivered=delivered,
                skipped=skipped,
                errored=errored,
                total=len(targets),
            )
        ],
    }
