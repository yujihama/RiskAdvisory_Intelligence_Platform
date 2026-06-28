import json
from datetime import date
from dataclasses import replace
from pathlib import Path
import shutil

import pytest

from risk_agent_platform.config import Settings
from risk_agent_platform.a2a_sdk_adapter import sdk_agent_card_dict
from risk_agent_platform.embeddings import create_embedding_provider
from risk_agent_platform.evidence_repository import EvidenceRepository
from risk_agent_platform.final_agents import _analysis_plan_from_text
from risk_agent_platform.mcp_gateway import MCPGateway
from risk_agent_platform.query_sanitizer import sanitize_query
from risk_agent_platform.risk_discovery import RiskDiscoveryDeepAgent
import risk_agent_platform.run_discovery as run_discovery
import risk_agent_platform.run_discovery_evaluation as run_discovery_evaluation
from risk_agent_platform.schemas import (
    AgentCard,
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

    for agent_name in ("treasury-risk-agent", "legal-risk-agent", "accounting-risk-agent"):
        allowed = agent_llm_tools(agent_name, "mcp-structured-data")
        assert allowed
        assert not (allowed & RAW_STRUCTURED_DATA_TOOLS)
        assert all(tool_name.endswith("_safe") for tool_name in allowed)
    assert "search_evidence" in agent_llm_tools("evidence-redteam-agent", "mcp-evidence-ledger")
    assert "find_risk_paths" in agent_llm_tools("evidence-redteam-agent", "mcp-neo4j")


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
    assert run_discovery._events_for_analysis(result, "top", top_n=3) == [first]
    assert run_discovery._events_for_analysis(result, "top-n", top_n=1) == [first]
    assert run_discovery._events_for_analysis(result, "top-n", top_n=2) == [first, second]


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
