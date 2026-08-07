"""Lightweight per-target enrichment.

For the demo: fetches the company's homepage (with a 5s timeout) and extracts
the page title + first <p> blocks. In production you'd combine this with
Apollo / Clearbit / LinkedIn / Crunchbase signals; the same shape works.

When the URL fails or times out (which it will for sample.example.com), the
enrichment falls back gracefully and the agent still drafts using just the
`public_signals` already in the YAML target row — so the demo runs cold."""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
import structlog
from bs4 import BeautifulSoup

log = structlog.get_logger()


async def enrich_target(target: dict) -> dict:
    domain = target.get("domain", "")
    url = domain if "://" in domain else f"https://{domain}"
    enrichment = {
        "company": target["company"],
        "page_title": None,
        "first_paragraphs": [],
        "fetch_ok": False,
        "fetch_error": None,
    }
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as c:
            r = await c.get(
                url,
                headers={"User-Agent": "OutreachAgent/0.1 (research; not crawling)"},
            )
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            t = soup.find("title")
            enrichment["page_title"] = t.get_text(strip=True)[:200] if t else None
            paras = [p.get_text(strip=True) for p in soup.find_all("p")[:5]]
            enrichment["first_paragraphs"] = [p for p in paras if 40 <= len(p) <= 400][
                :3
            ]
            enrichment["fetch_ok"] = True
        else:
            enrichment["fetch_error"] = f"http {r.status_code}"
    # Scraping a stranger's marketing site is expected to fail sometimes, and a
    # failed fetch is recorded rather than raised. Only transport-level failures
    # are tolerated though; a bug in the parsing below should still surface.
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        enrichment["fetch_error"] = str(e)[:160]

    log.info(
        "outreach.enriched",
        company=target["company"],
        ok=enrichment["fetch_ok"],
        host=urlparse(url).netloc,
    )
    return enrichment
