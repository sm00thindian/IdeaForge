"""Tests for meeting domain auto-detection."""

from ideaforge.meeting_domain import (
    DOMAIN_FED_GRC,
    DOMAIN_GENERAL,
    detect_meeting_domain,
    resolve_meeting_domain,
)


def test_general_for_ordinary_standup():
    text = (
        "Daily standup. Russ renews the cert Wednesday night. "
        "David finishes velocity widgets Friday. No blockers."
    )
    result = detect_meeting_domain(text)
    assert result.domain == DOMAIN_GENERAL


def test_fed_grc_for_oscal_and_compliance():
    text = (
        "We need the OSCAL SSP updated before the FedRAMP ATO package leaves. "
        "Xacta inheritance for the boundary is still open."
    )
    result = detect_meeting_domain(text)
    assert result.domain == DOMAIN_FED_GRC
    assert result.matched


def test_fed_grc_for_federal_reserve():
    text = "Working session with Federal Reserve stakeholders on logging requirements."
    result = detect_meeting_domain(text)
    assert result.domain == DOMAIN_FED_GRC
    assert "federal reserve" in result.matched


def test_fed_grc_for_governance():
    text = "AI governance review and compliance policy alignment with legal."
    result = detect_meeting_domain(text)
    assert result.domain == DOMAIN_FED_GRC


def test_architecture_alone_not_enough():
    # Casual use of the word should not force fed pack without systems context.
    text = "We talked about the architecture of the picnic plan and who brings chips."
    result = detect_meeting_domain(text)
    assert result.domain == DOMAIN_GENERAL


def test_architecture_plus_controls():
    text = (
        "Solution architecture should own the compliance control list "
        "versus the operational vulnerability list."
    )
    result = detect_meeting_domain(text)
    assert result.domain == DOMAIN_FED_GRC


def test_resolve_auto_detects():
    det = resolve_meeting_domain("auto", "Discussed continuous authorization and cATO.")
    assert det.domain == DOMAIN_FED_GRC


def test_resolve_forced_general():
    det = resolve_meeting_domain(
        "general",
        "OSCAL SSP and FedRAMP ATO discussion.",
    )
    assert det.domain == DOMAIN_GENERAL
    assert "configured" in det.reason


def test_resolve_forced_fed_grc():
    det = resolve_meeting_domain("fed_grc", "Casual coffee chat.")
    assert det.domain == DOMAIN_FED_GRC
