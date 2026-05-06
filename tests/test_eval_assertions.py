"""Tests for evals.assertions — the deterministic quality rules."""

from __future__ import annotations

from evals.assertions import (
    body_anchors_on_real_signal,
    body_has_exactly_one_cta,
    body_paragraph_count_in_range,
    no_banned_tropes,
    subject_under_60_chars,
)


def _target():
    return {
        "company": "Acme",
        "contact_name": "Alex Doe",
        "industry": "fintech",
        "expected_anchor_keywords": ["Series B", "$42M"],
        "public_signals": ["Series B announced ($42M)"],
    }


def test_subject_too_long_fails():
    long = "x" * 65
    ok, _ = subject_under_60_chars({"subject": long}, _target())
    assert not ok


def test_subject_at_limit_passes():
    ok, _ = subject_under_60_chars({"subject": "x" * 60}, _target())
    assert ok


def test_anchor_assertion_passes_on_keyword_match():
    draft = {"body": "Saw the Series B announcement, exciting trajectory"}
    ok, _ = body_anchors_on_real_signal(draft, _target())
    assert ok


def test_anchor_assertion_fails_when_signal_missing():
    draft = {"body": "Generic blah blah blah no anchor"}
    ok, _ = body_anchors_on_real_signal(draft, _target())
    assert not ok


def test_paragraph_count_in_range():
    body = "p1.\n\np2.\n\np3.\n\np4."
    ok, _ = body_paragraph_count_in_range({"body": body}, _target())
    assert ok


def test_paragraph_count_too_few():
    body = "just one paragraph here"
    ok, _ = body_paragraph_count_in_range({"body": body}, _target())
    assert not ok


def test_one_cta_passes():
    body = "para 1\n\npara 2\n\nopen to a 30-minute call?\n\nthanks"
    ok, _ = body_has_exactly_one_cta({"body": body}, _target())
    assert ok


def test_two_ctas_fail():
    body = "open to a 30 minute call this week? or a quick chat?"
    ok, _ = body_has_exactly_one_cta({"body": body}, _target())
    assert not ok


def test_banned_tropes_rejected():
    draft = {"body": "let's leverage our synergy", "subject": "ok"}
    ok, _ = no_banned_tropes(draft, _target())
    assert not ok


def test_no_tropes_passes():
    draft = {"body": "clean professional copy", "subject": "ok"}
    ok, _ = no_banned_tropes(draft, _target())
    assert ok
