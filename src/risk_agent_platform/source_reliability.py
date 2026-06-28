from __future__ import annotations

from urllib.parse import urlparse

from risk_agent_platform.schemas import Confidence, RiskEvent


HIGH_RELIABILITY_DOMAINS = {
    "congress.gov",
    "home.treasury.gov",
    "treasury.gov",
    "sec.gov",
    "bis.doc.gov",
    "federalregister.gov",
    "europa.eu",
    "consilium.europa.eu",
    "un.org",
    "worldbank.org",
    "imf.org",
    "oecd.org",
    "weforum.org",
    "ir.fujifilm.com",
    "fujifilm.com",
}

MEDIUM_RELIABILITY_DOMAINS = {
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "bbc.co.uk",
    "ft.com",
    "wsj.com",
    "bloomberg.com",
    "cnbc.com",
    "cnbcafrica.com",
    "nikkei.com",
    "csis.org",
}

LOW_RELIABILITY_MARKERS = {
    "blog",
    "medium.com",
    "substack.com",
    "wordpress.com",
    "skilldynamics.com",
}


def score_source(result: dict[str, object], event: RiskEvent) -> dict[str, Confidence | str | None]:
    url = str(result.get("url") or "")
    domain = normalize_domain(urlparse(url).netloc)
    reliability = reliability_for_domain(domain)
    client_relevance = relevance_for_result(result, event)
    confidence = _combine(reliability, client_relevance)
    return {
        "source_domain": domain or None,
        "reliability": reliability,
        "client_relevance": client_relevance,
        "confidence": confidence,
    }


def normalize_domain(domain: str) -> str:
    domain = domain.lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def reliability_for_domain(domain: str) -> Confidence:
    domain = normalize_domain(domain)
    if not domain:
        return "low"
    if domain.endswith(".gov") or any(domain == item or domain.endswith(f".{item}") for item in HIGH_RELIABILITY_DOMAINS):
        return "high"
    if any(domain == item or domain.endswith(f".{item}") for item in MEDIUM_RELIABILITY_DOMAINS):
        return "medium"
    if any(marker in domain for marker in LOW_RELIABILITY_MARKERS):
        return "low"
    if domain.endswith(".edu") or domain.endswith(".ac.jp"):
        return "medium"
    return "medium"


def relevance_for_result(result: dict[str, object], event: RiskEvent) -> Confidence:
    haystack = " ".join(
        str(result.get(key) or "")
        for key in ("title", "content", "raw_content", "url")
    ).lower()
    terms = [*event.countries, event.risk_type, *event.risk_themes, *event.affected_categories]
    matches = sum(1 for term in terms if term and term.lower().replace("_", " ") in haystack)
    if matches >= 3:
        return "high"
    if matches >= 1:
        return "medium"
    return "low"


def _combine(reliability: Confidence, relevance: Confidence) -> Confidence:
    rank = {"low": 0, "medium": 1, "high": 2}
    score = min(rank[reliability], rank[relevance])
    for label, value in rank.items():
        if value == score:
            return label  # pragma: no cover - exhaustive over fixed map
    return "low"
