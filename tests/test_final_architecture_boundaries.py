import json
import threading
import time
from datetime import date
from dataclasses import replace
from pathlib import Path
import shutil

import pytest

from risk_agent_platform.config import Settings
from risk_agent_platform.a2a_sdk_adapter import sdk_agent_card_dict
from risk_agent_platform.embeddings import create_embedding_provider
from risk_agent_platform.evidence_repository import EvidenceRepository
from risk_agent_platform.final_agents import _analysis_plan_from_text, _decision_for_event, _deterministic_analysis_plan
from risk_agent_platform.mcp_gateway import MCPGateway
from risk_agent_platform.model_profiles import ModelProfileRouter
from risk_agent_platform.query_sanitizer import sanitize_query
from risk_agent_platform.risk_discovery import RiskDiscoveryDeepAgent, _candidate_to_event, _discovery_context_event
import risk_agent_platform.run_discovery as run_discovery
import risk_agent_platform.run_discovery_evaluation as run_discovery_evaluation
from risk_agent_platform.schemas import (
    AgentCard,
    AgentTaskResult,
    DiscoveredRisk,
    EvidenceItem,
    KnowledgeApplicationFinding,
    RiskDiscoveryRequest,
    RiskDiscoveryResult,
    RiskDiscoveryScope,
    RiskEvent,
)
from risk_agent_platform.source_reliability import score_source
from risk_agent_platform.tool_policy import RAW_STRUCTURED_DATA_TOOLS, agent_llm_tools
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


class _NoStructuredCandidateRunner:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def synthesize(self, *_args, **_kwargs) -> str:
        return "no structured candidates"


class _RecordingCandidateRunner:
    candidates: list[dict[str, object]] = []
    sample_payloads: list[str] = []

    def __init__(self, *_args, tools=None, **_kwargs) -> None:
        self.tools = {item.name: item for item in tools or []}

    def synthesize(self, *_args, **_kwargs) -> str:
        self.tools["discovery_list_datasets"].invoke({"client_id": "demo_client"})
        sample = self.tools["discovery_sample_dataset"].invoke(
            {"client_id": "demo_client", "dataset": "payments", "limit": 3}
        )
        type(self).sample_payloads.append(sample)
        self.tools["discovery_load_expert_pack"].invoke({})
        self.tools["discovery_record_candidates"].invoke(
            {"candidates_json": json.dumps({"candidates": self.candidates})}
        )
        return ""


class _WebDiscoveryRunner:
    def __init__(self, *_args, tools=None, **_kwargs) -> None:
        self.tools = {item.name: item for item in tools or []}

    def synthesize(self, *_args, **_kwargs) -> str:
        search_payload = self.tools["discovery_search_event_context"].invoke(
            {"query": "Taiwan Strait semiconductor component logistics disruption", "max_results": 3}
        )
        search = json.loads(search_payload)
        self.tools["discovery_extract_event_source"].invoke({"url": search["results"][0]["url"]})
        self.tools["discovery_record_event_facts"].invoke(
            {
                "event_facts_json": json.dumps(
                    {
                        "affected_geographies": ["Taiwan Strait"],
                        "affected_industries": ["semiconductors", "electronics"],
                        "infrastructure_chokepoints": ["sea freight lanes", "air cargo routes"],
                        "critical_goods_or_services": ["semiconductor components", "electronic assemblies"],
                        "regulatory_or_sanctions_signals": [],
                        "financial_or_payment_signals": [],
                        "supply_chain_tier_risks": ["sub-tier semiconductor component allocation"],
                        "time_horizons": ["near-term logistics delay"],
                        "source_refs": [{"title": "Taiwan semiconductor logistics disruption", "url": search["results"][0]["url"]}],
                        "uncertainties": ["client-specific component dependency is not yet validated"],
                    }
                )
            }
        )
        self.tools["discovery_record_candidates"].invoke(
            {
                "candidates_json": json.dumps(
                    {
                        "candidates": [
                            {
                                "candidate_id": "DISC-WEB-SUP",
                                "title": "Semiconductor component allocation and logistics delay risk",
                                "risk_type": "supplier_resilience",
                                "risk_themes": ["supplier_resilience", "logistics", "semiconductor_components"],
                                "affected_categories": ["critical_parts", "air_cargo", "sea_freight"],
                                "description": (
                                    "Taiwan Strait disruption could delay sea and air freight while sub-tier "
                                    "semiconductor component allocation affects electronic assemblies."
                                ),
                                "urgency": "high",
                                "scope_matches": ["web:event_facts"],
                                "rationale": "Discovery web intelligence linked logistics disruption to semiconductor component supply.",
                            }
                        ]
                    }
                )
            }
        )
        return ""


def _recorded_scope_candidates() -> list[dict[str, object]]:
    return [
        {
            "candidate_id": "DISC-PAY",
            "title": "Urgent supplier payment and cash mobility disruption",
            "risk_type": "payment_disruption",
            "risk_themes": ["payment", "cash", "liquidity"],
            "affected_categories": ["cross_border_payments"],
            "description": "Bank routing, currency, liquidity, and near-term supplier payment execution may be disrupted.",
            "urgency": "high",
            "scope_matches": [],
            "rationale": "Treasury-facing payment execution exposure.",
        },
        {
            "candidate_id": "DISC-LEGAL",
            "title": "Sanctions export-control and contract obligation review",
            "risk_type": "legal_compliance",
            "risk_themes": ["sanctions", "export_control", "contract_obligation"],
            "affected_categories": ["contracts", "counterparties"],
            "description": "Sanctions, export, beneficial ownership, contract notice, and force majeure questions may arise.",
            "urgency": "high",
            "scope_matches": [],
            "rationale": "Legal-facing counterparty and contract exposure.",
        },
        {
            "candidate_id": "DISC-ACCT",
            "title": "Accounting provision impairment and disclosure pressure",
            "risk_type": "accounting_disclosure",
            "risk_themes": ["provision_trigger", "impairment_trigger", "disclosure_pressure"],
            "affected_categories": ["financial_reporting", "auditor_evidence_pack"],
            "description": "Provision, impairment, disclosure, materiality, and auditor evidence requirements may change.",
            "urgency": "medium",
            "scope_matches": [],
            "rationale": "Accounting-facing reporting exposure.",
        },
    ]


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


def test_discovery_web_context_preserves_public_event_geography():
    request = RiskDiscoveryRequest(
        event_title="Taiwan contingency",
        event_description="A Taiwan Strait contingency may disrupt logistics.",
        countries=["Taiwan"],
        scope=RiskDiscoveryScope(client_id="fujifilm_dummy", scope_text="Fujifilm logistics"),
    )
    event_payload = _discovery_context_event(
        request,
        {"scope_interpretation": {"matched_domains": ["logistics"], "primary_risk_types": ["supplier_resilience"]}},
    )

    result = sanitize_query(
        "Taiwan contingency Fujifilm logistics shipping disruption",
        RiskEvent.model_validate(event_payload),
        confidential_terms=["fujifilm_dummy", "Fujifilm"],
    )

    assert "Taiwan" in result.sanitized
    assert "Fujifilm" not in result.sanitized


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


def test_orchestrator_uses_deterministic_plan_for_canonical_supplier_risk():
    event = _event().model_copy(update={"risk_type": "supplier_resilience"})

    plan = _deterministic_analysis_plan(event)

    assert plan is not None
    assert plan.selected_agents == [
        "client-context-agent",
        "source-intelligence-agent",
        "procurement-risk-agent",
        "expert-as-code-agent",
        "evidence-redteam-agent",
    ]
    assert "treasury-risk-agent" in plan.skipped_agents
    assert "legal-risk-agent" in plan.skipped_agents
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


def test_decision_synthesis_uses_supplier_logistics_decision_for_supplier_risk():
    event = _event().model_copy(update={"risk_type": "supplier_resilience"})

    decision = _decision_for_event(
        event,
        "decision-001",
        [{"evidence_id": "evidence-001"}],
        ["DECISION-CONSOLIDATION-SUPPLIER-001"],
    )

    assert "logistics continuity" in decision.decision
    assert decision.owner == "Procurement / Operations / Logistics"
    assert "payment" not in decision.decision.lower()
    assert "DECISION-CONSOLIDATION-SUPPLIER-001" in decision.expert_knowledge_ids


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
    primitives = gateway.call("mcp-expert-knowledge", "load_primitives", {})
    scope_rules = gateway.call("mcp-expert-knowledge", "load_scope_relevance_rules", {})
    decision_rules = gateway.call("mcp-expert-knowledge", "load_decision_consolidation_rules", {})
    version = gateway.call("mcp-expert-knowledge", "load_knowledge_pack_version", {})
    refs = gateway.call("mcp-expert-knowledge", "load_source_refs", {})
    reliability = gateway.call("mcp-expert-knowledge", "load_source_reliability_seed", {})

    assert len(cases) >= 14 and cases[0]["case_id"]
    assert len(questions) >= 24 and questions[0]["question_id"]
    assert len(notes) >= 11 and notes[0]["note_id"]
    assert len(primitives) >= 20 and primitives[0]["id"]
    assert len(scope_rules) >= 10 and scope_rules[0]["rule_id"]
    assert len(decision_rules) >= 4 and decision_rules[0]["rule_id"]
    assert version["pack_id"]
    assert refs
    assert reliability["high_reliability_domains"]


def test_structured_data_risk_feature_sample_redacts_raw_identifiers():
    gateway = MCPGateway(Settings.load(Path.cwd()), embedded=True)

    result = gateway.call(
        "mcp-structured-data",
        "risk_feature_sample",
        {"client_id": "demo_client", "dataset": "payments", "limit": 2},
    )

    assert result["dataset"] == "payments"
    assert result["features"]
    first = result["features"][0]
    assert first["amount_bucket"]
    assert first["currency"] == "USD"
    assert first["country"] == "Noveria"
    assert "payment_id" not in first
    assert "supplier_id" not in first
    assert "amount" not in first
    assert "bank_name" not in first
    assert {"payment_id", "supplier_id", "amount", "bank_name"}.issubset(set(result["redaction_policy"]["omitted_fields"]))

    safe_summary = gateway.call(
        "mcp-structured-data",
        "summarize_payment_exposure_safe",
        {"client_id": "demo_client", "country": "Noveria"},
    )
    assert safe_summary["payment_count"] == 1
    assert "items" not in safe_summary
    assert "total_amount" not in safe_summary
    assert safe_summary["features"][0]["amount_bucket"] == "1m_5m"

    contract_summary = gateway.call(
        "mcp-structured-data",
        "summarize_contract_exposure_safe",
        {"client_id": "demo_client"},
    )
    assert contract_summary["contract_count"] == 2
    assert "items" not in contract_summary
    assert contract_summary["features"][0]["has_sanctions_clause"] is True


def test_deepagent_tool_policy_keeps_raw_structured_tools_out_of_llm_slots():
    discovery_structured = agent_llm_tools("risk-discovery-agent", "mcp-structured-data")
    assert "risk_feature_sample" in discovery_structured
    assert "sample_rows" not in discovery_structured
    discovery_web = agent_llm_tools("risk-discovery-agent", "mcp-web-search")
    assert {"search_authoritative_sources", "extract_url"}.issubset(discovery_web)

    for agent_name in ("treasury-risk-agent", "legal-risk-agent", "accounting-risk-agent"):
        allowed = agent_llm_tools(agent_name, "mcp-structured-data")
        assert allowed
        assert not (allowed & RAW_STRUCTURED_DATA_TOOLS)
        assert all(tool_name.endswith("_safe") for tool_name in allowed)
    assert "search_evidence" in agent_llm_tools("evidence-redteam-agent", "mcp-evidence-ledger")
    assert "find_risk_paths" in agent_llm_tools("evidence-redteam-agent", "mcp-neo4j")


def test_risk_discovery_profile_defaults_to_qwen37_max(monkeypatch):
    monkeypatch.delenv("RISK_DISCOVERY_MODEL", raising=False)
    router = ModelProfileRouter(Path.cwd() / "config" / "model_profiles.yaml")

    profile = router.select_for_agent("risk-discovery-agent")

    assert profile.name == "risk_discovery"
    assert profile.model == "qwen/qwen3.7-max"
    assert profile.max_tokens == 8192


def test_risk_discovery_generates_scope_filtered_event_without_llm_tools(tmp_path, monkeypatch):
    monkeypatch.setattr("risk_agent_platform.risk_discovery.DeepAgentRunner", _NoStructuredCandidateRunner)
    root = Path.cwd()
    shutil.copytree(root / "data" / "clients" / "demo_client", tmp_path / "data" / "clients" / "demo_client")
    shutil.copytree(root / "data" / "expert_knowledge", tmp_path / "data" / "expert_knowledge")
    settings = replace(Settings.load(root), project_root=tmp_path, data_dir=tmp_path / "data")
    request = RiskDiscoveryRequest(
        event_title="Iran war escalation affecting supplier payments",
        event_description="Shipping, sanctions screening, and supplier payments may be disrupted.",
        countries=["Iran"],
        max_risks=2,
        scope=RiskDiscoveryScope(
            client_id="demo_client",
            scope_type="department",
            scope_name="Treasury",
            department="Treasury",
            metadata={"industry": "manufacturing"},
        ),
    )

    result = RiskDiscoveryDeepAgent(settings, embedded_mcp=True).discover(request)

    assert result.selected_event is not None
    assert result.selected_event.client_id == "demo_client"
    assert result.selected_event.risk_type == "payment_disruption"
    assert len(result.selected_events) == len(result.selected_candidates)
    assert result.selected_events[0].scenario_id == result.selected_event.scenario_id
    assert all(candidate.selected_for_analysis for candidate in result.selected_candidates)
    assert result.selected_candidates[0].selected_for_analysis is True
    assert result.selected_candidates[0].relevance_score >= 50
    assert result.metadata["fallback_used"] is True
    assert result.metadata["scope_relevance_rule_count"] >= 10


def test_risk_discovery_normal_path_records_candidates_and_scope_changes_selection(tmp_path, monkeypatch):
    monkeypatch.setattr("risk_agent_platform.risk_discovery.DeepAgentRunner", _RecordingCandidateRunner)
    _RecordingCandidateRunner.candidates = _recorded_scope_candidates()
    _RecordingCandidateRunner.sample_payloads = []
    root = Path.cwd()
    shutil.copytree(root / "data" / "clients" / "demo_client", tmp_path / "data" / "clients" / "demo_client")
    shutil.copytree(root / "data" / "expert_knowledge", tmp_path / "data" / "expert_knowledge")
    settings = replace(Settings.load(root), project_root=tmp_path, data_dir=tmp_path / "data")

    selected_by_department: dict[str, RiskDiscoveryResult] = {}
    for department in ("Treasury", "Legal", "Accounting"):
        request = RiskDiscoveryRequest(
            event_title="Geopolitical disruption requiring functional triage",
            event_description="The event may affect operations and control execution.",
            countries=["Iran"],
            scope=RiskDiscoveryScope(
                client_id="demo_client",
                scope_type="department",
                scope_name=department,
                department=department,
                metadata={"industry": "services"},
            ),
        )
        selected_by_department[department] = RiskDiscoveryDeepAgent(settings, embedded_mcp=True).discover(request)

    assert selected_by_department["Treasury"].metadata["fallback_used"] is False
    assert selected_by_department["Treasury"].metadata["discovery_confidence"] == "agent_recorded_candidates"
    assert selected_by_department["Treasury"].metadata["structured_sample_view"] == "risk_feature_sample"
    assert selected_by_department["Treasury"].selected_candidates[0].risk_type == "payment_disruption"
    assert selected_by_department["Legal"].selected_candidates[0].risk_type == "legal_compliance"
    assert selected_by_department["Accounting"].selected_candidates[0].risk_type == "accounting_disclosure"
    assert selected_by_department["Treasury"].rejected_candidates
    assert selected_by_department["Treasury"].rejected_candidates[0].reason
    assert _RecordingCandidateRunner.sample_payloads
    assert "bank_name" not in _RecordingCandidateRunner.sample_payloads[0]
    assert "amount_bucket" in _RecordingCandidateRunner.sample_payloads[0]


def test_risk_discovery_adds_department_primary_coverage_when_llm_misses_it(tmp_path, monkeypatch):
    monkeypatch.setattr("risk_agent_platform.risk_discovery.DeepAgentRunner", _RecordingCandidateRunner)
    _RecordingCandidateRunner.candidates = [
        {
            "candidate_id": "DISC-SUP",
            "title": "Supplier logistics continuity review",
            "risk_type": "supplier_resilience",
            "risk_themes": ["supplier", "logistics"],
            "affected_categories": ["operations"],
            "description": "Supplier continuity and logistics lanes may be disrupted.",
            "urgency": "medium",
            "scope_matches": [],
            "rationale": "LLM recorded only supplier continuity.",
        },
        {
            "candidate_id": "DISC-ACC",
            "title": "Financial reporting follow-up",
            "risk_type": "accounting_disclosure",
            "risk_themes": ["disclosure", "materiality"],
            "affected_categories": ["financial_reporting"],
            "description": "Management may later need reporting evidence.",
            "urgency": "medium",
            "scope_matches": [],
            "rationale": "LLM recorded only reporting follow-up.",
        },
    ]
    root = Path.cwd()
    shutil.copytree(root / "data" / "clients" / "demo_client", tmp_path / "data" / "clients" / "demo_client")
    shutil.copytree(root / "data" / "expert_knowledge", tmp_path / "data" / "expert_knowledge")
    settings = replace(Settings.load(root), project_root=tmp_path, data_dir=tmp_path / "data")
    request = RiskDiscoveryRequest(
        event_title="New sanctions and export controls for restricted counterparties",
        event_description="A sanctions package may affect contract performance, notices, export controls, and counterparty due diligence.",
        countries=["Iran"],
        scope=RiskDiscoveryScope(
            client_id="demo_client",
            scope_type="department",
            scope_name="Legal",
            department="Legal",
            metadata={"industry": "manufacturing"},
        ),
    )

    result = RiskDiscoveryDeepAgent(settings, embedded_mcp=True).discover(request)

    assert result.metadata["fallback_used"] is False
    assert result.metadata["coverage_augmented_candidate_count"] >= 1
    assert result.selected_candidates[0].risk_type == "legal_compliance"
    assert any("SCOPE-DEPT-LEGAL-001:coverage_primary" in candidate.scope_matches for candidate in result.selected_candidates)


def test_risk_discovery_uses_natural_language_scope_without_department_mapping(tmp_path, monkeypatch):
    monkeypatch.setattr("risk_agent_platform.risk_discovery.DeepAgentRunner", _RecordingCandidateRunner)
    _RecordingCandidateRunner.candidates = [
        {
            "candidate_id": "DISC-ACC",
            "title": "Reporting follow-up after logistics disruption",
            "risk_type": "accounting_disclosure",
            "risk_themes": ["disclosure"],
            "affected_categories": ["financial_reporting"],
            "description": "Disclosure may be needed later if the disruption becomes material.",
            "urgency": "medium",
            "scope_matches": [],
            "rationale": "LLM missed the direct logistics risk.",
        }
    ]
    root = Path.cwd()
    shutil.copytree(root / "data" / "clients" / "fujifilm_dummy", tmp_path / "data" / "clients" / "fujifilm_dummy")
    shutil.copytree(root / "data" / "expert_knowledge", tmp_path / "data" / "expert_knowledge")
    settings = replace(Settings.load(root), project_root=tmp_path, data_dir=tmp_path / "data")
    request = RiskDiscoveryRequest(
        event_title="Taiwan contingency",
        event_description="A Taiwan Strait contingency may disrupt sea and air logistics.",
        countries=["Taiwan"],
        scope=RiskDiscoveryScope(
            client_id="fujifilm_dummy",
            scope_text="富士フイルムの物流。海上輸送、航空輸送、港湾、通関、3PL、重要部材の輸送遅延、代替ルートを含む。",
        ),
    )

    result = RiskDiscoveryDeepAgent(settings, embedded_mcp=True).discover(request)

    assert result.metadata["fallback_used"] is False
    assert "logistics" in result.metadata["scope_interpretation"]["matched_domains"]
    assert result.metadata["coverage_augmented_candidate_count"] >= 1
    assert result.selected_candidates[0].risk_type == "supplier_resilience"
    assert result.selected_candidates[0].scope_matches[0] == "SCOPE-TEXT-PRIMARY:coverage_primary"
    assert "executive_resilience" not in {candidate.risk_type for candidate in result.selected_candidates}


def test_risk_discovery_preserves_distinct_same_type_scenarios(tmp_path, monkeypatch):
    monkeypatch.setattr("risk_agent_platform.risk_discovery.DeepAgentRunner", _RecordingCandidateRunner)
    _RecordingCandidateRunner.candidates = [
        {
            "candidate_id": "DISC-SEA",
            "title": "Taiwan Strait sea freight route disruption",
            "risk_type": "supplier_resilience",
            "risk_themes": ["supplier_resilience", "logistics", "sea_freight"],
            "affected_categories": ["sea_transport", "port_operations"],
            "description": "Sea freight and port logistics may stop or reroute through congested alternate lanes.",
            "urgency": "high",
            "scope_matches": ["logistics"],
            "rationale": "Sea freight is a distinct logistics disruption mechanism.",
        },
        {
            "candidate_id": "DISC-3PL",
            "title": "3PL and customs clearance disruption",
            "risk_type": "supplier_resilience",
            "risk_themes": ["supplier_resilience", "3pl", "customs"],
            "affected_categories": ["3pl", "customs_clearance"],
            "description": "3PL warehousing, freight forwarding, and customs clearance may stop even if inventory exists.",
            "urgency": "high",
            "scope_matches": ["3pl", "customs"],
            "rationale": "3PL and customs failure is distinct from ocean route loss.",
        },
        {
            "candidate_id": "DISC-CHIP",
            "title": "Semiconductor component allocation disruption",
            "risk_type": "supplier_resilience",
            "risk_themes": ["supplier_resilience", "semiconductor_components", "critical_parts"],
            "affected_categories": ["critical_parts", "supplier_tiers"],
            "description": "Sub-tier semiconductor component suppliers may allocate scarce parts to other customers.",
            "urgency": "high",
            "scope_matches": ["critical parts"],
            "rationale": "Critical component allocation is distinct from physical transport failure.",
        },
    ]
    root = Path.cwd()
    shutil.copytree(root / "data" / "clients" / "fujifilm_dummy", tmp_path / "data" / "clients" / "fujifilm_dummy")
    shutil.copytree(root / "data" / "expert_knowledge", tmp_path / "data" / "expert_knowledge")
    settings = replace(Settings.load(root), project_root=tmp_path, data_dir=tmp_path / "data")
    request = RiskDiscoveryRequest(
        event_title="Taiwan contingency",
        event_description="A Taiwan Strait contingency may disrupt sea freight, 3PL, customs, and critical components.",
        countries=["Taiwan"],
        scope=RiskDiscoveryScope(
            client_id="fujifilm_dummy",
            scope_text="Fujifilm logistics including sea freight, air cargo, customs, 3PL, suppliers, and critical parts.",
        ),
    )

    result = RiskDiscoveryDeepAgent(settings, embedded_mcp=True).discover(request)

    selected_ids = {candidate.candidate_id for candidate in result.selected_candidates}
    assert {"DISC-SEA", "DISC-3PL", "DISC-CHIP"}.issubset(selected_ids)
    assert not any("duplicate selected risk_type" in candidate.reason for candidate in result.rejected_candidates)


def test_risk_discovery_records_bounded_web_event_facts_for_candidate_generation(tmp_path, monkeypatch):
    monkeypatch.setattr("risk_agent_platform.risk_discovery.DeepAgentRunner", _WebDiscoveryRunner)
    root = Path.cwd()
    shutil.copytree(root / "data" / "clients" / "fujifilm_dummy", tmp_path / "data" / "clients" / "fujifilm_dummy")
    shutil.copytree(root / "data" / "expert_knowledge", tmp_path / "data" / "expert_knowledge")
    settings = replace(Settings.load(root), project_root=tmp_path, data_dir=tmp_path / "data")
    original_call = MCPGateway.call

    def fake_call(self, server_name, tool_name, arguments=None):
        if server_name == "mcp-web-search" and tool_name == "search_authoritative_sources":
            assert "fujifilm" not in (arguments or {})["query"].lower()
            return {
                "query": (arguments or {})["query"],
                "query_hash": "test-query-hash",
                "results": [
                    {
                        "title": "Taiwan semiconductor logistics disruption",
                        "url": "https://example.test/taiwan-semiconductor-logistics",
                        "content": "Taiwan semiconductor component suppliers depend on sea freight and air cargo lanes.",
                    }
                ],
            }
        if server_name == "mcp-web-search" and tool_name == "extract_url":
            return {
                "url": (arguments or {})["url"],
                "result": {
                    "results": [
                        {
                            "url": (arguments or {})["url"],
                            "raw_content": "Semiconductor component disruption can affect electronics manufacturing tiers.",
                        }
                    ]
                },
            }
        return original_call(self, server_name, tool_name, arguments)

    monkeypatch.setattr(MCPGateway, "call", fake_call)
    request = RiskDiscoveryRequest(
        event_title="Taiwan contingency",
        event_description="A Taiwan Strait contingency may disrupt sea and air logistics.",
        countries=["Taiwan"],
        scope=RiskDiscoveryScope(
            client_id="fujifilm_dummy",
            scope_text="Fujifilm logistics including sea freight, air cargo, customs, suppliers, and critical parts.",
        ),
    )

    result = RiskDiscoveryDeepAgent(settings, embedded_mcp=True).discover(request)

    assert result.metadata["fallback_used"] is False
    assert result.metadata["web_search_count"] == 1
    assert result.metadata["web_extraction_count"] == 1
    assert result.metadata["web_searches"][0]["query_hash"] == "test-query-hash"
    assert "semiconductors" in result.metadata["event_facts"]["affected_industries"]
    assert "semiconductor" in result.selected_candidates[0].description.lower()
    assert result.selected_candidates[0].risk_type == "supplier_resilience"


def test_risk_discovery_preserves_rejected_candidate_reasons_without_llm_tools(tmp_path, monkeypatch):
    monkeypatch.setattr("risk_agent_platform.risk_discovery.DeepAgentRunner", _NoStructuredCandidateRunner)
    root = Path.cwd()
    shutil.copytree(root / "data" / "clients" / "demo_client", tmp_path / "data" / "clients" / "demo_client")
    shutil.copytree(root / "data" / "expert_knowledge", tmp_path / "data" / "expert_knowledge")
    settings = replace(Settings.load(root), project_root=tmp_path, data_dir=tmp_path / "data")
    request = RiskDiscoveryRequest(
        event_title="Localized administrative filing disruption",
        event_description="A month-end timing issue may affect close work.",
        countries=[],
        scope=RiskDiscoveryScope(
            client_id="demo_client",
            scope_type="department",
            scope_name="Investor Relations",
            department="Investor Relations",
        ),
    )

    result = RiskDiscoveryDeepAgent(settings, embedded_mcp=True).discover(request)

    assert result.selected_event is not None
    assert result.rejected_candidates
    assert all("below threshold" in candidate.reason for candidate in result.rejected_candidates)


def test_discovery_analysis_modes_default_to_all_selected():
    assert run_discovery.DEFAULT_ANALYSIS_MODE == "all-selected"
    assert run_discovery.DEFAULT_ANALYSIS_CONCURRENCY == 5

    request = RiskDiscoveryRequest(
        event_title="Iran war escalation",
        event_description="Shipping, sanctions, and payments may be disrupted.",
        countries=["Iran"],
        max_risks=3,
        scope=RiskDiscoveryScope(client_id="demo_client", scope_type="company", scope_name="Demo Company"),
    )
    first = _event()
    second = first.model_copy(
        update={
            "scenario_id": "scenario_test_002",
            "title": "Supplier continuity review",
            "risk_type": "supplier_resilience",
        }
    )
    result = RiskDiscoveryResult(
        request=request,
        selected_candidates=[
            DiscoveredRisk(
                candidate_id="DISC-001",
                title=first.title,
                risk_type=first.risk_type,
                description=first.description,
                relevance_score=90,
                rationale="test",
                selected_for_analysis=True,
            ),
            DiscoveredRisk(
                candidate_id="DISC-002",
                title=second.title,
                risk_type=second.risk_type,
                description=second.description,
                relevance_score=80,
                rationale="test",
                selected_for_analysis=True,
            ),
        ],
        selected_event=first,
        selected_events=[first, second],
    )

    assert run_discovery._events_for_analysis(result, "all-selected", top_n=3) == [first, second]
    assert run_discovery._events_for_analysis(result, "auto", top_n=3) == [first, second]
    assert run_discovery._events_for_analysis(result, "top", top_n=3) == [first]
    assert run_discovery._events_for_analysis(result, "top-n", top_n=1) == [first]
    assert run_discovery._events_for_analysis(result, "top-n", top_n=2) == [first, second]

    natural_scope_result = result.model_copy(
        update={
            "metadata": {
                "scope_interpretation": {
                    "source": "scope_text",
                    "primary_risk_types": ["supplier_resilience"],
                }
            }
        }
    )
    assert run_discovery._events_for_analysis(natural_scope_result, "auto", top_n=3) == [second]


def test_run_discovery_analyzes_selected_events_with_bounded_parallelism(tmp_path, monkeypatch):
    settings = replace(Settings.load(Path.cwd()), project_root=tmp_path, data_dir=Path.cwd() / "data")
    base_event = _event()
    events = [
        base_event.model_copy(update={"scenario_id": f"scenario_parallel_{idx}", "title": f"Parallel risk {idx}"})
        for idx in range(5)
    ]
    lock = threading.Lock()
    active = 0
    max_active = 0

    class _ParallelOrchestrator:
        def run_task(self, request):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return AgentTaskResult(
                task_id=request.task.task_id,
                parent_task_id=request.task.parent_task_id,
                trace_id=request.task.trace_id,
                agent_name="orchestrator-agent",
                status="completed",
            )

    monkeypatch.setattr(run_discovery, "create_orchestrator_service", lambda *_args, **_kwargs: _ParallelOrchestrator())
    monkeypatch.setattr(run_discovery, "create_embedded_a2a_apps", lambda *_args, **_kwargs: {})

    records = run_discovery._run_analysis_records(
        settings,
        events,
        embedded_services=True,
        concurrency=run_discovery.DEFAULT_ANALYSIS_CONCURRENCY,
    )

    assert max_active > 1
    assert [record["scenario_id"] for record in records] == [event.scenario_id for event in events]
    assert run_discovery._bounded_analysis_concurrency(5, len(events)) == 5


def test_risk_discovery_scenario_ids_keep_candidate_identity():
    request = RiskDiscoveryRequest(
        event_title="Regional conflict escalation affecting manufacturing continuity",
        event_description="Disruption may affect multiple modes.",
        countries=["Taiwan"],
        scope=RiskDiscoveryScope(client_id="fujifilm_dummy", scope_text="物流と支払いと法務を含む"),
    )
    first = DiscoveredRisk(
        candidate_id="DISC-001",
        title="Supplier continuity",
        risk_type="supplier_resilience",
        description="Supplier continuity risk.",
        rationale="test",
    )
    second = first.model_copy(update={"candidate_id": "DISC-AUG-EXEC", "risk_type": "executive_resilience"})

    first_id = _candidate_to_event(first, request).scenario_id
    second_id = _candidate_to_event(second, request).scenario_id

    assert first_id != second_id
    assert first_id.endswith("_disc_001")
    assert second_id.endswith("_disc_aug_exec")

    japanese_request = request.model_copy(
        update={
            "event_title": "台湾有事",
            "event_description": "台湾海峡の物流寸断",
        }
    )
    japanese_id = _candidate_to_event(first, japanese_request).scenario_id
    event_hash = japanese_id.split("_")[-3]
    assert japanese_id.startswith("scenario_discovered_fujifilm_dummy_")
    assert len(event_hash) == 8
    assert all(char in "0123456789abcdef" for char in event_hash)
    assert japanese_id.endswith("_disc_001")


def test_run_analysis_blocks_template_fallback_without_explicit_allow(tmp_path, monkeypatch, capsys):
    class _FallbackDiscovery:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def discover(self, request: RiskDiscoveryRequest) -> RiskDiscoveryResult:
            event = _event().model_copy(
                update={
                    "scenario_id": "scenario_fallback_blocked",
                    "client_id": request.scope.client_id,
                    "title": "Fallback candidate",
                    "risk_type": "payment_disruption",
                }
            )
            return RiskDiscoveryResult(
                request=request,
                selected_candidates=[
                    DiscoveredRisk(
                        candidate_id="DISC-FALLBACK",
                        title=event.title,
                        risk_type=event.risk_type,
                        description=event.description,
                        relevance_score=80,
                        rationale="template fallback",
                        selected_for_analysis=True,
                    )
                ],
                selected_event=event,
                selected_events=[event],
                metadata={"fallback_used": True, "discovery_confidence": "template_fallback"},
            )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_discovery, "RiskDiscoveryDeepAgent", _FallbackDiscovery)
    monkeypatch.setattr(
        run_discovery,
        "create_orchestrator_service",
        lambda *_args, **_kwargs: pytest.fail("fallback analysis should be blocked before orchestrator creation"),
    )

    status = run_discovery.main(
        [
            "--event-title",
            "Fallback event",
            "--client-id",
            "demo_client",
            "--scope-type",
            "department",
            "--scope-name",
            "Treasury",
            "--department",
            "Treasury",
            "--run-analysis",
        ]
    )

    output = capsys.readouterr().out
    assert status == 2
    assert "fallback_used=true" in output
    assert "discovery_confidence=template_fallback" in output
    assert "analysis_status=blocked:fallback_used" in output


def test_portfolio_summary_integrates_multi_risk_outputs(tmp_path):
    request = RiskDiscoveryRequest(
        event_title="Iran war escalation",
        event_description="Shipping, sanctions, and payments may be disrupted.",
        countries=["Iran"],
        max_risks=3,
        scope=RiskDiscoveryScope(client_id="demo_client", scope_type="company", scope_name="Demo Company"),
    )
    first = _event()
    second = first.model_copy(
        update={
            "scenario_id": "scenario_test_002",
            "title": "Supplier continuity review",
            "risk_type": "supplier_resilience",
        }
    )
    result = RiskDiscoveryResult(
        request=request,
        selected_candidates=[
            DiscoveredRisk(
                candidate_id="DISC-001",
                title=first.title,
                risk_type=first.risk_type,
                description=first.description,
                relevance_score=90,
                rationale="test",
                selected_for_analysis=True,
            ),
            DiscoveredRisk(
                candidate_id="DISC-002",
                title=second.title,
                risk_type=second.risk_type,
                description=second.description,
                relevance_score=80,
                rationale="test",
                selected_for_analysis=True,
            ),
        ],
        selected_event=first,
        selected_events=[first, second],
    )
    settings = replace(Settings.load(Path.cwd()), project_root=tmp_path, data_dir=Path.cwd() / "data")
    records = [
        {
            "scenario_id": first.scenario_id,
            "title": first.title,
            "risk_type": first.risk_type,
            "risk_themes": first.risk_themes,
            "urgency": first.urgency,
            "status": "completed",
            "trace_id": "trace-001",
            "output_dir": str(tmp_path / "outputs" / first.scenario_id),
            "decision_count": 1,
            "decisions": [
                {
                    "decision": "Confirm payment route and sanction-screening owner.",
                    "owner": "Treasury",
                    "deadline": "2026-07-02",
                    "priority": 1,
                    "review_required": True,
                },
                {
                    "decision": "Complete sanctions check before payment release.",
                    "owner": "Treasury",
                    "deadline": "2026-07-02",
                    "priority": 2,
                    "review_required": True,
                }
            ],
            "evidence_count": 2,
            "evidence_domains": ["home.treasury.gov", "www.sec.gov"],
            "orchestrator_finding": {"review_required": True},
        },
        {
            "scenario_id": second.scenario_id,
            "title": second.title,
            "risk_type": second.risk_type,
            "risk_themes": second.risk_themes,
            "urgency": second.urgency,
            "status": "completed",
            "trace_id": "trace-002",
            "output_dir": str(tmp_path / "outputs" / second.scenario_id),
            "decision_count": 1,
            "decisions": [
                {
                    "decision": "Check alternate supplier readiness.",
                    "owner": "Procurement",
                    "deadline": "2026-07-05",
                    "priority": 4,
                    "review_required": False,
                },
                {
                    "decision": "Perform sanctions check before supplier contract execution.",
                    "owner": "Legal",
                    "deadline": "2026-07-04",
                    "priority": 2,
                    "review_required": True,
                }
            ],
            "evidence_count": 3,
            "evidence_domains": ["www.reuters.com"],
            "orchestrator_finding": {"review_required": False},
        },
    ]

    paths = run_discovery._write_portfolio_summary(settings, result, records)

    summary = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    markdown = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert summary["portfolio_overview"]["analysis_count"] == 2
    assert summary["portfolio_overview"]["completed_count"] == 2
    assert summary["portfolio_overview"]["total_decisions"] == 4
    assert summary["portfolio_overview"]["total_evidence"] == 5
    assert summary["portfolio_overview"]["review_required_scenarios"] == [first.scenario_id, second.scenario_id]
    assert summary["portfolio_overview"]["priority_decisions"][0]["decision"].startswith("Confirm payment route")
    sanctions_group = [
        item
        for item in summary["portfolio_overview"]["consolidated_decisions"]
        if item["group_id"] == "sanctions_review"
    ][0]
    assert sanctions_group["source_count"] == 3
    assert sanctions_group["rule_id"] == "DECISION-CONSOLIDATION-SANCTIONS-001"
    assert sanctions_group["required_owners"] == ["Legal"]
    assert sanctions_group["owner_gap"] == []
    supplier_group = [
        item
        for item in summary["portfolio_overview"]["consolidated_decisions"]
        if item["group_id"] == "supplier_continuity"
    ][0]
    assert supplier_group["owner_gap"] == ["Operations"]
    assert summary["portfolio_overview"]["decision_conflicts"]
    assert "## Portfolio Overview" in markdown
    assert "## Priority Decisions" in markdown
    assert "## Consolidated Decisions" in markdown


def test_risk_discovery_evaluation_cases_compute_quality_metrics():
    class _EvaluationDiscovery:
        def discover(self, request: RiskDiscoveryRequest) -> RiskDiscoveryResult:
            by_department = {
                "Treasury": (
                    ["payment_disruption"],
                    "SCOPE-DEPT-TREASURY-001",
                    [
                        "Which pending payments are near term and routed through affected bank countries?",
                        "Which alternate payment routes are available without increasing sanctions risk?",
                    ],
                ),
                "Legal": (
                    ["legal_compliance"],
                    "SCOPE-DEPT-LEGAL-001",
                    [
                        "Which contracts include sanctions, force majeure, notice, or termination clauses?",
                        "Which counterparties require beneficial ownership or restricted party review?",
                    ],
                ),
                "Accounting": (
                    ["accounting_disclosure"],
                    "SCOPE-DEPT-ACCOUNTING-001",
                    [
                        "Which exposures could become material for impairment, provision, or disclosure?",
                        "What evidence package is required for auditor review?",
                    ],
                ),
                "Executive": (
                    ["supplier_resilience", "payment_disruption", "legal_compliance", "executive_resilience"],
                    "SCOPE-IND-MANUFACTURING-001",
                    [
                        "Which critical suppliers have low inventory runway or no qualified alternative source?",
                        "Which pending payments are near term and routed through affected bank countries?",
                        "Which selected risks require executive cross-functional decision ownership?",
                        "Which evidence gaps block immediate mitigation decisions?",
                    ],
                ),
            }
            selected_types, rubric_id, questions = by_department[request.scope.department or "Executive"]
            candidates = [
                DiscoveredRisk(
                    candidate_id=f"DISC-{idx:03d}",
                    title=f"{risk_type} candidate",
                    risk_type=risk_type,
                    description=f"{risk_type} description",
                    relevance_score=90 - idx,
                    rationale="evaluation fake",
                    selected_for_analysis=True,
                    scope_matches=[f"{rubric_id}:term"],
                )
                for idx, risk_type in enumerate(selected_types, start=1)
            ]
            event = RiskEvent(
                scenario_id=f"scenario_eval_{request.scope.department or 'executive'}",
                client_id=request.scope.client_id,
                title=candidates[0].title,
                risk_type=candidates[0].risk_type,
                description=candidates[0].description,
                event_date=date(2026, 6, 28),
                urgency="high",
            )
            return RiskDiscoveryResult(
                request=request,
                selected_candidates=candidates,
                selected_event=event,
                selected_events=[event],
                metadata={
                    "fallback_used": False,
                    "discovery_confidence": "agent_recorded_candidates",
                    "additional_questions": questions,
                    "unknowns": [],
                },
            )

    path = Path("data/evaluation/risk_discovery_cases.jsonl")
    cases = run_discovery_evaluation.load_cases(path)
    report = run_discovery_evaluation.evaluate_cases(
        Settings.load(Path.cwd()),
        cases,
        embedded_mcp=True,
        discovery_factory=lambda *_args: _EvaluationDiscovery(),
    )

    assert report["summary"]["passed"] is True
    assert report["summary"]["average_recall"] == 1.0
    assert report["summary"]["forbidden_top_violation_count"] == 0
    assert report["summary"]["average_question_match"] > 0.9
    assert report["summary"]["average_question_semantic_match"] == 1.0
    assert report["summary"]["average_missing_data_category_match"] == 1.0
    assert report["summary"]["average_reason_quality"] == 1.0
    assert report["summary"]["average_expert_rubric_coverage"] == 1.0
    first_case = report["cases"][0]
    assert first_case["selected_candidate_titles"]
    assert first_case["selected_candidate_rationales"]
    assert first_case["selected_candidate_scope_matches"]
    assert "rejected_risk_types" in first_case
    assert "rejected_reasons" in first_case
    assert "coverage_augmented_candidate_count" in first_case
    assert "raw_candidate_count" in first_case


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
