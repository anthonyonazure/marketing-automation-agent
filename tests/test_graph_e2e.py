import os
from pathlib import Path

import pytest

from outreach.graph import build_graph
from outreach.state import OutreachState

TARGETS = Path(__file__).resolve().parents[1] / "targets" / "sample.yaml"


@pytest.mark.asyncio
async def test_full_run_produces_one_draft_per_target(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTREACH_DRAFTS_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    graph = build_graph().compile()
    initial: OutreachState = {
        "run_id": "test-run",
        "targets_path": str(TARGETS),
        "tone": "peer-cynical",
        "sender_upn": "demo@mock.tenant",  # mock mailer accepts anything
        "events": [],
        "errors": [],
    }
    final = await graph.ainvoke(initial)

    targets = final["targets"]
    drafts = final["drafts"]
    reviews = final["reviews"]
    delivery = final["delivery"]

    assert len(drafts) == len(targets)
    assert len(reviews) == len(targets)
    assert len(delivery) == len(targets)

    # Stub reviewer marks all drafts as 'send'
    assert all(r["verdict"] == "send" for r in reviews)

    # All deliveries got a draft_id from the mock mailer
    assert all(d.get("draft_id") for d in delivery)

    # Each draft persisted to disk
    for t in targets:
        slug = t["company"].lower().replace(" ", "-")
        assert (tmp_path / f"{slug}.md").exists()

    # Each draft anchors on a real signal from the YAML
    for t, d in zip(targets, drafts):
        signal = (t.get("public_signals") or [""])[0]
        # Either the subject or the body should contain a substring of the signal
        sig_words = [w for w in signal.split() if len(w) > 4][:3]
        body_subj = (d["subject"] + d["body"]).lower()
        assert any(w.lower() in body_subj for w in sig_words), (
            f"draft for {t['company']} doesn't anchor on signal {signal!r}"
        )


@pytest.mark.asyncio
async def test_skips_delivery_when_no_sender_upn(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTREACH_DRAFTS_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    graph = build_graph().compile()
    final = await graph.ainvoke(
        {"run_id": "x", "targets_path": str(TARGETS), "tone": "neutral", "sender_upn": "", "events": [], "errors": []}
    )
    assert all(d.get("skipped") and d.get("reason") == "no_sender_upn" for d in final["delivery"])
