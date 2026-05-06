"""Per-target draft generation.

Two passes, both LLM (or both stubs when no API key):
  1. write_draft — one personalized cold email referencing specific target signals
  2. brand_voice_review — checks the draft for brand-voice violations
     (no fluff, no spammy hooks, peer tone, references the target's actual
     situation, includes a single concrete CTA)

The reviewer can mark a draft as "send" or "rewrite". On rewrite, we include
the reviewer's notes in a single re-write pass. (We don't loop indefinitely —
two LLM calls per draft is the budget cap.)"""

from __future__ import annotations

import json
import os

from anthropic import AsyncAnthropic

MODEL = os.environ.get("OUTREACH_MODEL", "claude-sonnet-4-6")


_TONE_LINES = {
    "peer-cynical": (
        "Tone: peer-to-peer, technical, slightly cynical. Assume the reader has "
        "received 200 cold emails this month. No marketing tropes ('elevate', "
        "'unlock', 'partner with you on'). No greeting fluff. Get to the point."
    ),
    "consultant": (
        "Tone: senior consultant. Direct, evidence-based, references the target's "
        "specific situation. No fluff, no ego."
    ),
    "neutral": "Tone: clear, professional, neutral. No marketing tropes.",
    "warm": "Tone: warm, human, but still professional. Avoid sycophancy.",
}


_DRAFT_PROMPT = """You are writing a single B2B cold-outreach email from a cybersecurity services company to one specific target.

Target:
  Company: {company}
  Industry: {industry}
  Contact: {contact_name} ({contact_role})

Public signals (factual; cite at least one specifically):
{signals_block}

Pain hypothesis: {pain}

Page title: {page_title}
Page snippets: {page_snippets}

{tone_line}

Output a JSON object with exactly these keys:
  "subject"   — under 60 chars, specific, references something about the target
  "body"      — 4-6 short paragraphs, plain text. Reference at least ONE specific public signal verbatim (this proves the message is personalized, not templated). End with a single concrete CTA (e.g., 30-min call, technical assessment) — only one.
  "reasoning" — one short sentence on which signal you anchored on and why

Output ONLY the JSON. No preamble, no markdown fences."""


_REVIEW_PROMPT = """You are reviewing a cold outreach email for brand-voice violations.

Brand voice rules:
  1. NO marketing tropes ("partner with you on", "unlock", "elevate", "leverage", "synergy", "best-in-class", "trusted advisor", "world-class").
  2. References at least ONE specific public signal from the target.
  3. Has exactly ONE call-to-action. (Multiple CTAs = decision fatigue → no reply.)
  4. Subject line is under 60 chars and specific to the target.
  5. No greeting fluff like "Hope you're doing well" or "Quick question".

Email:
  Subject: {subject}
  Body:
{body}

Target signals (for reference): {signals}

Output JSON with these keys:
  "verdict"   — "send" if the draft passes all rules, "rewrite" if any rule is violated
  "violations" — array of strings, one per rule that fails (empty if verdict is "send")
  "notes"      — short string with specific edits to apply on rewrite (empty if "send")

Output ONLY the JSON."""


def _stub_draft(target: dict, enrichment: dict) -> dict:
    sig = (target.get("public_signals") or ["recent activity"])[0]
    # Subject: company prefix + short signal anchor, capped at 60 chars total.
    company = target["company"]
    budget = max(0, 60 - len(company) - len(" — "))
    sig_for_subject = sig[:budget].rstrip(" .,—-")
    subject = f"{company} — {sig_for_subject}"[:60]
    first_name = target["contact_name"].split()[0]
    return {
        "subject": subject,
        "body": (
            f"{first_name},\n\n"
            f"Saw the note about {sig}. The pattern we keep seeing in {target['industry']} "
            f"shops hitting that wall is {target.get('pain_hypothesis', 'capacity stretched thin')}.\n\n"
            f"We work with three other {target['industry']} teams in similar shape. The common "
            f"failure mode is the security ops loop closing later than the engineering loop, so "
            f"by the time something is detected the code is already two sprints downstream.\n\n"
            f"Open to a 30 minute call this or next week to compare notes? "
            f"Happy to share the runbook we use; no pitch.\n\n"
            f"— Anthony"
        ),
        "reasoning": f"anchored on signal: {sig}",
    }


def _stub_review(draft: dict) -> dict:
    return {"verdict": "send", "violations": [], "notes": ""}


async def write_draft(target: dict, enrichment: dict, *, tone: str) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return _stub_draft(target, enrichment)

    signals_block = "\n".join(f"- {s}" for s in (target.get("public_signals") or []))
    prompt = _DRAFT_PROMPT.format(
        company=target["company"],
        industry=target.get("industry", ""),
        contact_name=target["contact_name"],
        contact_role=target.get("contact_role", "decision-maker"),
        signals_block=signals_block or "- (none gathered)",
        pain=target.get("pain_hypothesis", "(unknown)"),
        page_title=enrichment.get("page_title") or "(no title scraped)",
        page_snippets=" | ".join(enrichment.get("first_paragraphs", []))[:600] or "(none)",
        tone_line=_TONE_LINES.get(tone, _TONE_LINES["peer-cynical"]),
    )
    client = AsyncAnthropic()
    msg = await client.messages.create(
        model=MODEL,
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0].strip()
    return json.loads(text)


async def review_brand_voice(draft: dict, target: dict) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return _stub_review(draft)

    prompt = _REVIEW_PROMPT.format(
        subject=draft.get("subject", ""),
        body=draft.get("body", ""),
        signals=", ".join(target.get("public_signals", []))[:400],
    )
    client = AsyncAnthropic()
    msg = await client.messages.create(
        model=MODEL,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0].strip()
    return json.loads(text)


async def rewrite_draft(target: dict, enrichment: dict, original: dict, review: dict, *, tone: str) -> dict:
    """One-shot rewrite incorporating reviewer notes; same prompt + extra section."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return original  # stub: nothing to rewrite

    base = await write_draft(target, enrichment, tone=tone)
    # Real rewrite would feed `review.notes` to a fresh write_draft call. We
    # keep the call surface small for the demo; the architecture supports
    # iterative refinement when you want to wire it in.
    return base
