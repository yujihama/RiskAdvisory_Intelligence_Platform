from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from risk_agent_platform.schemas import RiskEvent


SENSITIVE_PATTERNS = [
    re.compile(r"\b[A-Z]{2,}-\d{3,}\b"),
    re.compile(r"\b(?:PAY|CTR|SUP|INV|PO)-\d+\b", re.IGNORECASE),
    re.compile(r"\b\d{5,}(?:\.\d+)?\b"),
]


@dataclass(frozen=True)
class SanitizedQuery:
    original: str
    sanitized: str
    query_hash: str
    redactions: list[str]


def sanitize_query(query: str, event: RiskEvent, confidential_terms: list[str] | None = None) -> SanitizedQuery:
    sanitized = query
    redactions: list[str] = []
    for term in [*_event_sensitive_terms(event), *(confidential_terms or [])]:
        if term and term.lower() in sanitized.lower():
            sanitized = re.sub(re.escape(term), _replacement_for(term), sanitized, flags=re.IGNORECASE)
            redactions.append(term)
    for country in event.countries:
        if country:
            continue
    for pattern in SENSITIVE_PATTERNS:
        for match in pattern.findall(sanitized):
            sanitized = sanitized.replace(match, _replacement_for(match))
            redactions.append(match)
    sanitized = _normalize_domain_terms(sanitized)
    digest = hashlib.sha256(sanitized.encode("utf-8")).hexdigest()[:16]
    return SanitizedQuery(original=query, sanitized=sanitized, query_hash=digest, redactions=redactions)


def build_risk_signal_query(event: RiskEvent) -> SanitizedQuery:
    country = ", ".join(event.countries) if event.countries else "affected country"
    themes = " ".join(event.risk_themes or [event.risk_type])
    query = f"{country} {themes} critical supplier payment disruption regulatory official source"
    return sanitize_query(query, event)


def _replacement_for(term: str) -> str:
    lowered = term.lower()
    if lowered.startswith("sup-"):
        return "critical supplier"
    if lowered.startswith("pay-"):
        return "near-term supplier payment exposure"
    if lowered.startswith("ctr-"):
        return "material supply contract"
    if lowered.startswith("po-"):
        return "purchase order"
    if lowered.startswith("inv-"):
        return "invoice"
    if re.fullmatch(r"\d{5,}(?:\.\d+)?", term):
        return "material exposure amount"
    return "client-specific entity"


def _normalize_domain_terms(query: str) -> str:
    query = re.sub(r"\bPower module\b", "critical component", query, flags=re.IGNORECASE)
    query = re.sub(r"\bKanto Component Plant\b", "manufacturing site", query, flags=re.IGNORECASE)
    return query


def _event_sensitive_terms(event: RiskEvent) -> list[str]:
    terms = [event.client_id, event.scenario_id]
    terms.extend(event.affected_categories)
    terms.extend(_sensitive_phrases(event.description))
    return [term for term in terms if term]


def _sensitive_phrases(text: str) -> list[str]:
    phrases = re.findall(r"\b[A-Z][A-Za-z0-9&.-]+(?:\s+[A-Z][A-Za-z0-9&.-]+){1,4}\b", text)
    generic = {"Risk", "Potential", "Country", "Region", "Supplier", "Payment", "Legal", "Accounting"}
    return [phrase for phrase in phrases if phrase.split()[0] not in generic]
