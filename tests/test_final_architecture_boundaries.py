from datetime import date
from dataclasses import replace
from pathlib import Path

import pytest

from risk_agent_platform.config import Settings
from risk_agent_platform.a2a_sdk_adapter import sdk_agent_card_dict
from risk_agent_platform.embeddings import create_embedding_provider
from risk_agent_platform.evidence_repository import EvidenceRepository
from risk_agent_platform.final_agents import _analysis_plan_from_text
from risk_agent_platform.mcp_gateway import MCPGateway
from risk_agent_platform.query_sanitizer import sanitize_query
from risk_agent_platform.schemas import AgentCard, EvidenceItem, KnowledgeApplicationFinding, RiskEvent
from risk_agent_platform.source_reliability import score_source
from risk_agent_platform.vector import VECTOR_SIZE


def _event() -> RiskEvent:
    return RiskEvent(
        scenario_id="scenario_test_001",
        client_id="demo_client",
        title="Sensitive supplier payment review",
        risk_type="geopolitical_sanctions",
        countries=["Noveria"],
        risk_themes=["sanctions", "payment_disruption"],
        affected_categories=["Power module"],
        description="Kanto Component Plant and Alpha Supplier are confidential client-specific references.",
        event_date=date(2026, 6, 27),
        urgency="high",
    )


def test_query_sanitizer_removes_client_specific_terms():
    result = sanitize_query(
        "demo_client PAY-12345 250000 Power module Kanto Component Plant sanctions",
        _event(),
    )

    assert "demo_client" not in result.sanitized
    assert "PAY-12345" not in result.sanitized
    assert "250000" not in result.sanitized
    assert "Power module" not in result.sanitized
    assert "Kanto Component Plant" not in result.sanitized
    assert "near-term supplier payment exposure" in result.sanitized
    assert "material exposure amount" in result.sanitized


def test_query_sanitizer_uses_title_and_explicit_confidential_terms():
    event = _event().model_copy(update={"title": "Alpha Supplier payment review"})

    result = sanitize_query("Alpha Supplier Beta Site sanctions", event, confidential_terms=["Beta Site"])

    assert "Alpha Supplier" not in result.sanitized
    assert "Beta Site" not in result.sanitized
    assert result.redactions


def test_a2a_sdk_agent_card_adapter_emits_sdk_shape():
    card = AgentCard(
        name="source-intelligence-agent",
        description="Collects external evidence.",
        skills=["tavily_search"],
        modes=["source_intelligence"],
    )

    sdk_card = sdk_agent_card_dict(card, base_url="http://localhost:8101")

    assert sdk_card["protocolVersion"] == "0.3.0"
    assert sdk_card["preferredTransport"] == "HTTP+JSON"
    assert sdk_card["url"] == "http://localhost:8101/a2a"
    assert sdk_card["skills"][0]["id"] == "tavily_search"
    assert sdk_card["capabilities"]["stateTransitionHistory"] is True


def test_orchestrator_analysis_plan_parses_bounded_json_and_preserves_fixed_order():
    plan = _analysis_plan_from_text(
        """
        {
          "selected_agents": ["legal-risk-agent", "source-intelligence-agent", "client-context-agent"],
          "skipped_agents": ["treasury-risk-agent"],
          "recheck_conditions": ["new sanctions notice"],
          "exploration_questions": ["Which source is authoritative?"],
          "rationale": "bounded test"
        }
        """
    )

    assert plan is not None
    assert plan.selected_agents == ["client-context-agent", "source-intelligence-agent", "legal-risk-agent"]
    assert "treasury-risk-agent" in plan.skipped_agents
    assert plan.fallback_used is False


def test_knowledge_application_finding_is_structured():
    finding = KnowledgeApplicationFinding(
        similar_case_ids=["case_sanctions_payment_001"],
        rubric_ids=["standard_high_confidence_v1"],
        red_flags=["High-risk supplier payment requires joint review"],
        cta_note_ids=["cta_sanctions_payment_cue_001"],
        counterfactuals=["What if the supplier bank route is outside the event country?"],
        review_required=True,
        rationale="bounded expert selection",
    )

    assert finding.review_required is True
    assert finding.similar_case_ids == ["case_sanctions_payment_001"]


def test_source_reliability_scores_domain_classes():
    event = _event()

    official = score_source({"url": "https://home.treasury.gov/news", "title": "Noveria sanctions"}, event)
    blog = score_source({"url": "https://example.blog/post", "title": "Opinion"}, event)

    assert official["reliability"] == "high"
    assert official["client_relevance"] in {"medium", "high"}
    assert blog["reliability"] == "low"


def test_embedding_provider_can_use_deterministic_mode(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "deterministic")
    provider = create_embedding_provider(Settings.load(Path.cwd()))

    vector = provider.embed("sanctions payment exposure")

    assert provider.name == "deterministic"
    assert len(vector) == VECTOR_SIZE


def test_document_parser_uses_real_fastmcp_boundary(tmp_path):
    document = tmp_path / "note.md"
    document.write_text("# Contract note\n\nPayment review required.", encoding="utf-8")
    gateway = MCPGateway(Settings.load(Path.cwd()), embedded=True)

    result = gateway.call("mcp-document-parser", "parse_document", {"path": str(document)})

    assert result["parser"] == "text"
    assert result["pages"][0]["text"].startswith("# Contract note")
    assert any(item.startswith("docling:") for item in result["fallback_attempts"])


def test_llm_ocr_requires_real_input_not_placeholder():
    gateway = MCPGateway(Settings.load(Path.cwd()), embedded=True)

    with pytest.raises(Exception, match="image_path or pdf_path"):
        gateway.call("mcp-llm-ocr", "ocr_page", {"document_id": "doc1", "page_number": 1})


def test_expert_pack_exposes_case_question_and_cta_files():
    gateway = MCPGateway(Settings.load(Path.cwd()), embedded=True)

    cases = gateway.call("mcp-expert-knowledge", "load_case_bank", {})
    questions = gateway.call("mcp-expert-knowledge", "load_question_bank", {})
    notes = gateway.call("mcp-expert-knowledge", "load_cta_notes", {})

    assert cases and cases[0]["case_id"].startswith("case_")
    assert questions and questions[0]["question_id"].startswith("q_")
    assert notes and notes[0]["note_id"].startswith("cta_")


def test_evidence_repository_upserts_by_evidence_id(tmp_path):
    settings = replace(Settings.load(Path.cwd()), project_root=tmp_path, data_dir=tmp_path / "data")
    repo = EvidenceRepository(settings)
    first = EvidenceItem(
        evidence_id="ev-001",
        scenario_id="scenario-test",
        client_id="client-test",
        source_type="web",
        source_ref="https://example.test/one",
        summary="Older summary",
    )
    latest = first.model_copy(update={"summary": "Latest summary", "source_ref": "https://example.test/two"})

    repo.register(first, index_qdrant=False, index_neo4j=False)
    repo.register(latest, index_qdrant=False, index_neo4j=False)

    evidence = repo.list_by_scenario("scenario-test")
    assert len(evidence) == 1
    assert evidence[0].summary == "Latest summary"
    assert len(repo.path.read_text(encoding="utf-8").splitlines()) == 1
