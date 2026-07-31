"""Detect which meeting prompt domain pack to use from transcript content."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

DOMAIN_GENERAL = "general"
DOMAIN_FED_GRC = "fed_grc"
DOMAIN_AUTO = "auto"

# Strong signals: federal / GRC / compliance tooling (word or multi-word).
_FED_GRC_PATTERNS: Sequence[Tuple[str, re.Pattern[str]]] = (
    ("federal reserve", re.compile(r"\bfederal\s+reserve\b", re.I)),
    ("fednow", re.compile(r"\bfed\s*now\b", re.I)),
    ("fedramp", re.compile(r"\bfed\s*ramp\b", re.I)),
    ("oscal", re.compile(r"\boscal\b", re.I)),
    ("ato", re.compile(r"\b(?:c)?ato\b", re.I)),  # ATO / cATO
    ("poam", re.compile(r"\bpoa\s*&?\s*m\b|\bpoam\b", re.I)),
    ("ssp", re.compile(r"\bssp\b", re.I)),
    ("xacta", re.compile(r"\bxacta\b|\bzacta\b", re.I)),
    ("grc", re.compile(r"\bgrc\b", re.I)),
    ("governance", re.compile(r"\bgovernance\b", re.I)),
    ("compliance", re.compile(r"\bcompliance\b", re.I)),
    ("authorization boundary", re.compile(r"\bauthorization\s+boundary\b", re.I)),
    ("continuous authorization", re.compile(r"\bcontinuous\s+authorization\b", re.I)),
    ("control inheritance", re.compile(r"\binheritance\b", re.I)),
    ("inspec", re.compile(r"\binspec\b", re.I)),
    ("regscale", re.compile(r"\bregscale\b", re.I)),
    ("nist", re.compile(r"\bnist\b", re.I)),
    ("fisma", re.compile(r"\bfisma\b", re.I)),
    ("omb", re.compile(r"\bomb\b", re.I)),
    ("raci", re.compile(r"\braci\b", re.I)),
    ("poam&m", re.compile(r"\bplan\s+of\s+action\b", re.I)),
)

# Architecture / systems architecture (broader; needs at least one hit + optional boost)
_ARCH_PATTERNS: Sequence[Tuple[str, re.Pattern[str]]] = (
    ("architecture", re.compile(r"\barchitecture\b", re.I)),
    ("system architecture", re.compile(r"\bsystem\s+architecture\b", re.I)),
    ("solution architecture", re.compile(r"\bsolution\s+architecture\b", re.I)),
    ("cloud architecture", re.compile(r"\bcloud\s+architecture\b", re.I)),
    ("data mesh", re.compile(r"\bdata\s+mesh\b", re.I)),
    ("reference architecture", re.compile(r"\breference\s+architecture\b", re.I)),
    ("architectural", re.compile(r"\barchitectural\b", re.I)),
)

# Policy / governance-adjacent (weaker alone)
_GOV_SOFT: Sequence[Tuple[str, re.Pattern[str]]] = (
    ("policy", re.compile(r"\bpolic(?:y|ies)\b", re.I)),
    ("audit", re.compile(r"\baudit(?:s|ing|or)?\b", re.I)),
    ("control", re.compile(r"\bcontrols?\b", re.I)),
    ("risk management", re.compile(r"\brisk\s+management\b", re.I)),
    ("authority to operate", re.compile(r"\bauthority\s+to\s+operate\b", re.I)),
)


@dataclass(frozen=True)
class DomainDetection:
    domain: str  # general | fed_grc
    matched: Tuple[str, ...] = ()
    reason: str = ""


def detect_meeting_domain(
    transcript: str,
    *,
    max_chars: int = 12_000,
) -> DomainDetection:
    """
    Choose general vs fed_grc from transcript content.

    Default is general. Switch to fed_grc when Federal Reserve / GRC / compliance
    signals appear, or when architecture language co-occurs with governance/systems
    context (to avoid every casual "architecture" joke flipping the pack).
    """
    text = (transcript or "").strip()
    if not text:
        return DomainDetection(domain=DOMAIN_GENERAL, reason="empty transcript")

    window = text[:max_chars]
    fed_hits: List[str] = []
    for label, pattern in _FED_GRC_PATTERNS:
        if pattern.search(window):
            fed_hits.append(label)

    arch_hits: List[str] = []
    for label, pattern in _ARCH_PATTERNS:
        if pattern.search(window):
            arch_hits.append(label)

    soft_hits: List[str] = []
    for label, pattern in _GOV_SOFT:
        if pattern.search(window):
            soft_hits.append(label)

    # Strong federal/GRC terms alone are enough.
    if fed_hits:
        return DomainDetection(
            domain=DOMAIN_FED_GRC,
            matched=tuple(fed_hits[:8]),
            reason="federal/GRC terminology",
        )

    # Architecture + soft governance → fed_grc (architecture ownership debates, etc.)
    if arch_hits and soft_hits:
        return DomainDetection(
            domain=DOMAIN_FED_GRC,
            matched=tuple((arch_hits + soft_hits)[:8]),
            reason="architecture + governance language",
        )

    # Multiple soft governance signals (policy + audit + controls, etc.)
    if len(soft_hits) >= 2:
        return DomainDetection(
            domain=DOMAIN_FED_GRC,
            matched=tuple(soft_hits[:8]),
            reason="governance language",
        )

    # Strong multi-word architecture phrases alone
    strong_arch = [
        h
        for h in arch_hits
        if h
        in {
            "system architecture",
            "solution architecture",
            "cloud architecture",
            "reference architecture",
            "data mesh",
        }
    ]
    if strong_arch:
        return DomainDetection(
            domain=DOMAIN_FED_GRC,
            matched=tuple(strong_arch[:8]),
            reason="systems architecture language",
        )

    return DomainDetection(domain=DOMAIN_GENERAL, reason="no domain signals")


def resolve_meeting_domain(
    configured: str,
    transcript: str,
) -> DomainDetection:
    """
    Resolve config value to a concrete domain.

    - ``general`` / ``fed_grc``: force that pack
    - ``auto`` (default recommended): detect from transcript; start general
    """
    key = (configured or DOMAIN_AUTO).strip().lower()
    if key in (DOMAIN_GENERAL, DOMAIN_FED_GRC):
        return DomainDetection(
            domain=key,
            matched=(),
            reason=f"configured meeting_domain={key}",
        )
    # auto or unknown → detect
    return detect_meeting_domain(transcript)
