"""
Tests for agents/lead_qualifier.py.
Claude API calls are mocked — no live API calls.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.lead_qualifier import (
    compute_score,
    qualify_lead,
    score_to_status,
    _fallback_reason,
    SCORE_WEIGHTS,
    QUALIFIED_THRESHOLD,
    NEEDS_REVIEW_THRESHOLD,
)


# ── unit: compute_score ─────────────────────────────────────────────────────


def test_score_website_present():
    r = {"website_status": "present", "ordering_status": "unknown"}
    score, bd = compute_score(r)
    assert bd.get("website_present") == SCORE_WEIGHTS["website_present"]


def test_score_website_not_found():
    r = {"website_status": "not_found"}
    score, bd = compute_score(r)
    assert bd.get("website_not_found") == SCORE_WEIGHTS["website_not_found"]
    assert score < 0


def test_score_ordering_not_found_adds_points():
    r = {"website_status": "present", "ordering_status": "not_found"}
    score, bd = compute_score(r)
    assert bd.get("ordering_not_found") == SCORE_WEIGHTS["ordering_not_found"]


def test_score_ordering_present_subtracts():
    r = {"website_status": "present", "ordering_status": "present"}
    score, _ = compute_score(r)
    r2 = {"website_status": "present", "ordering_status": "not_found"}
    score2, _ = compute_score(r2)
    assert score < score2


def test_score_email_found_adds_points():
    r = {"website_status": "present", "ordering_status": "unknown", "contact_email": "info@a.com"}
    r_no = {"website_status": "present", "ordering_status": "unknown"}
    s1, _ = compute_score(r)
    s2, _ = compute_score(r_no)
    assert s1 == s2 + SCORE_WEIGHTS["email_found"]


def test_score_phone_adds_points():
    r = {"website_status": "present", "phone": "555-1234"}
    r_no = {"website_status": "present"}
    s1, _ = compute_score(r)
    s2, _ = compute_score(r_no)
    assert s1 == s2 + SCORE_WEIGHTS["phone_present"]


def test_score_unknown_status_contributes_zero():
    r = {"website_status": "unknown", "ordering_status": "unknown"}
    score, bd = compute_score(r)
    assert score == 0
    assert "website_present" not in bd
    assert "website_not_found" not in bd


# ── unit: score_to_status ───────────────────────────────────────────────────


def test_status_qualified():
    assert score_to_status(QUALIFIED_THRESHOLD) == "qualified"
    assert score_to_status(QUALIFIED_THRESHOLD + 10) == "qualified"


def test_status_needs_review():
    assert score_to_status(NEEDS_REVIEW_THRESHOLD) == "needs_review"
    assert score_to_status(QUALIFIED_THRESHOLD - 1) == "needs_review"


def test_status_disqualified():
    assert score_to_status(NEEDS_REVIEW_THRESHOLD - 1) == "disqualified"
    assert score_to_status(-100) == "disqualified"


# ── unit: _fallback_reason ──────────────────────────────────────────────────


def test_fallback_reason_includes_positives():
    bd = {"website_present": 30, "email_found": 25}
    reason = _fallback_reason("qualified", bd)
    assert "website" in reason.lower() or "email" in reason.lower()


def test_fallback_reason_no_breakdown():
    reason = _fallback_reason("needs_review", {})
    assert "needs_review" in reason.lower()


# ── integration: qualify_lead (Claude mocked) ───────────────────────────────


async def test_qualify_lead_qualified(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    restaurant = {
        "name": "Best Burger",
        "website_status": "present",
        "ordering_status": "not_found",
        "contact_email": "info@bestburger.com",
        "phone": "555-0001",
    }
    with patch("agents.lead_qualifier._claude_reason", new=AsyncMock(return_value="Great prospect.")):
        result = await qualify_lead(restaurant)
    assert result["lead_status"] == "qualified"
    assert result["lead_score"] >= QUALIFIED_THRESHOLD
    assert result["lead_reason"] == "Great prospect."


async def test_qualify_lead_disqualified():
    restaurant = {"name": "Ghost", "website_status": "not_found"}
    with patch("agents.lead_qualifier._claude_reason", new=AsyncMock(return_value="No website.")):
        result = await qualify_lead(restaurant)
    assert result["lead_status"] == "disqualified"
    assert result["lead_score"] < NEEDS_REVIEW_THRESHOLD


async def test_qualify_lead_needs_review():
    restaurant = {"name": "Mid Cafe", "website_status": "present", "ordering_status": "unknown"}
    with patch("agents.lead_qualifier._claude_reason", new=AsyncMock(return_value="Has website.")):
        result = await qualify_lead(restaurant)
    # website_present(30) only → needs_review
    assert result["lead_status"] == "needs_review"


async def test_qualify_lead_fallback_when_no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    restaurant = {"name": "Fallback", "website_status": "present", "ordering_status": "not_found"}
    result = await qualify_lead(restaurant)
    # Should still work — falls back to deterministic reason
    assert result["lead_status"] in ("qualified", "needs_review", "disqualified")
    assert isinstance(result["lead_reason"], str)
    assert len(result["lead_reason"]) > 0


async def test_qualify_lead_returns_all_keys():
    restaurant = {"name": "Test", "website_status": "unknown"}
    with patch("agents.lead_qualifier._claude_reason", new=AsyncMock(return_value="OK")):
        result = await qualify_lead(restaurant)
    assert "lead_score" in result
    assert "lead_status" in result
    assert "lead_reason" in result
