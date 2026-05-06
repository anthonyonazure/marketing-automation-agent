import os

import pytest

from outreach.drafting import review_brand_voice, write_draft


@pytest.mark.asyncio
async def test_stub_draft_anchors_on_signal_when_no_api_key():
    os.environ.pop("ANTHROPIC_API_KEY", None)
    target = {
        "company": "Halberd Health",
        "industry": "healthtech",
        "contact_name": "Dana Reyes",
        "contact_role": "CISO",
        "public_signals": ["Series B announced 6 weeks ago ($42M)"],
        "pain_hypothesis": "scaling SOC capacity faster than they can hire",
        "contact_email": "x@y.z",
    }
    enrichment = {"page_title": None, "first_paragraphs": [], "fetch_ok": False}
    draft = await write_draft(target, enrichment, tone="peer-cynical")
    assert "Halberd Health" in draft["subject"]
    assert "Dana" in draft["body"]  # first name only — full name reads templated
    assert "Series B" in draft["body"]
    assert draft["body"].count("call") <= 2  # one CTA-ish reference
    assert "synergy" not in draft["body"].lower()


@pytest.mark.asyncio
async def test_stub_review_passes_clean_drafts():
    review = await review_brand_voice(
        {"subject": "ok", "body": "x"}, {"public_signals": ["signal A"]}
    )
    assert review["verdict"] == "send"
    assert review["violations"] == []
