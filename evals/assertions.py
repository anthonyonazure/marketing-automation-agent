"""Deterministic assertions over a generated draft.

Each assertion takes (draft: dict, target: dict) and returns
(passed: bool, detail: str). A draft passes the eval iff every assertion
passes.

These are intentionally hard rules, not LLM judgments — the same draft
should score identically every run, and the rules should be defensible
in front of an actual marketer."""

from __future__ import annotations

import re
from typing import Callable

# Brand voice tropes that fail the review pass. Add to this list as you
# find new patterns in the wild.
BANNED_TROPES = [
    "synergy",
    "leverage",
    "elevate",
    "unlock",
    "best-in-class",
    "world-class",
    "trusted advisor",
    "value add",
    "value-add",
    "circle back",
    "low-hanging fruit",
    "move the needle",
    "core competency",
    "thought leadership",
    "win-win",
]

# CTA verbs we count for the "exactly one CTA" rule. Multiple matches at
# different timestamps in the same paragraph are fine — the rule is about
# decision points, not surface mentions.
CTA_PATTERNS = [
    r"\b(?:30|fifteen|15|20|45)\s*[- ]?\s*minute\b",
    r"\bquick (?:call|chat)\b",
    r"\bjump on a (?:call|chat)\b",
    r"\bworth a (?:call|chat|conversation)\b",
    r"\bup for a (?:call|chat|demo)\b",
    r"\bdemo\b",
    r"\bschedule (?:a |some )?time\b",
    r"\bcalendly\b",
    r"\bbook (?:a |some )?time\b",
    r"\bopen to a (?:call|chat|conversation|conversation)\b",
]


# ---------- Assertions ----------

def subject_under_60_chars(draft: dict, target: dict) -> tuple[bool, str]:
    n = len(draft.get("subject") or "")
    return n <= 60, f"subject is {n} chars (limit 60)"


def subject_mentions_company_or_signal(draft: dict, target: dict) -> tuple[bool, str]:
    subject = (draft.get("subject") or "").lower()
    company = target["company"].lower()
    if company in subject:
        return True, "subject mentions company"
    for kw in target.get("expected_anchor_keywords", []):
        if kw.lower() in subject:
            return True, f"subject mentions anchor keyword {kw!r}"
    return False, "subject mentions neither company nor any anchor keyword"


def body_anchors_on_real_signal(draft: dict, target: dict) -> tuple[bool, str]:
    body = (draft.get("body") or "").lower()
    expected = target.get("expected_anchor_keywords", [])
    hit = next((k for k in expected if k.lower() in body), None)
    if hit:
        return True, f"body references anchor keyword {hit!r}"
    return False, f"body misses all expected anchors: {expected}"


def body_paragraph_count_in_range(draft: dict, target: dict) -> tuple[bool, str]:
    body = draft.get("body") or ""
    paragraphs = [p for p in re.split(r"\n\s*\n", body.strip()) if p.strip()]
    n = len(paragraphs)
    return 3 <= n <= 7, f"body has {n} paragraphs (want 3-7)"


def body_has_exactly_one_cta(draft: dict, target: dict) -> tuple[bool, str]:
    body = (draft.get("body") or "").lower()
    cta_hits = sum(1 for p in CTA_PATTERNS if re.search(p, body))
    return cta_hits == 1, f"{cta_hits} CTA matches (want exactly 1)"


def no_banned_tropes(draft: dict, target: dict) -> tuple[bool, str]:
    body = (draft.get("body") or "").lower()
    subject = (draft.get("subject") or "").lower()
    full = body + " " + subject
    hits = [t for t in BANNED_TROPES if t in full]
    return len(hits) == 0, f"tropes found: {hits}" if hits else "no tropes"


def body_addresses_contact_by_name(draft: dict, target: dict) -> tuple[bool, str]:
    body = draft.get("body") or ""
    name = target["contact_name"].split()[0]
    return name in body, f"body addresses {name!r}"


# Exposed list — the run harness iterates this
ALL_ASSERTIONS: list[Callable[[dict, dict], tuple[bool, str]]] = [
    subject_under_60_chars,
    subject_mentions_company_or_signal,
    body_anchors_on_real_signal,
    body_paragraph_count_in_range,
    body_has_exactly_one_cta,
    no_banned_tropes,
    body_addresses_contact_by_name,
]


def evaluate_draft(draft: dict, target: dict) -> dict:
    results = []
    for fn in ALL_ASSERTIONS:
        passed, detail = fn(draft, target)
        results.append({"assertion": fn.__name__, "passed": passed, "detail": detail})
    return {
        "company": target["company"],
        "subject": draft.get("subject"),
        "passed": all(r["passed"] for r in results),
        "results": results,
    }
