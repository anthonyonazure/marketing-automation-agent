"""LangGraph state for an outreach run.

Per-target processing happens in a fan-out: one node enriches per target,
one node drafts per target. The state-level lists accumulate across targets
via reducers."""

from __future__ import annotations

from operator import add
from typing import Annotated, Any, TypedDict


class OutreachState(TypedDict, total=False):
    run_id: str
    targets_path: str
    sender_upn: str
    tone: str

    # Loaded from targets YAML
    targets: list[dict[str, Any]]

    # Per-target enrichment artifacts (homepage page text, derived signals)
    enrichments: Annotated[list[dict[str, Any]], add]

    # Per-target generated drafts (subject, body, reasoning)
    drafts: Annotated[list[dict[str, Any]], add]

    # Per-target brand-voice review verdicts
    reviews: Annotated[list[dict[str, Any]], add]

    # Per-target M365 draft creation results (or stub)
    delivery: Annotated[list[dict[str, Any]], add]

    events: Annotated[list[dict[str, Any]], add]
    errors: Annotated[list[str], add]
