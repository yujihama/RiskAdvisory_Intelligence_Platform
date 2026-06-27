from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


Confidence = Literal["low", "medium", "high"]
SourceType = Literal["user_input", "external_source", "client_data", "expert_knowledge", "derived", "hypothesis"]
ConfidenceLayer = Literal["source_backed", "derived", "hypothesis", "assumption", "unknown"]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RiskEvent(StrictModel):
    scenario_id: str
    client_id: str
    title: str
    risk_type: str
    countries: list[str] = Field(default_factory=list)
    risk_themes: list[str] = Field(default_factory=list)
    affected_categories: list[str] = Field(default_factory=list)
    description: str
    event_date: date
    urgency: Literal["low", "medium", "high"] = "medium"


class AgentTask(StrictModel):
    task_id: str
    scenario_id: str
    client_id: str
    requested_by: str
    objective: str
    mode: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    expected_output_schema: str
    trace_id: str


class AgentCard(StrictModel):
    name: str
    description: str
    version: str = "0.1.0"
    skills: list[str]
    modes: list[str] = Field(default_factory=list)
    input_schema: str = "AgentTask"
    output_schema: str = "AgentFinding"
    endpoints: dict[str, str] = Field(
        default_factory=lambda: {
            "agent_card": "/.well-known/agent-card.json",
            "a2a": "/a2a",
            "health": "/healthz",
        }
    )


class EvidenceItem(StrictModel):
    evidence_id: str
    scenario_id: str
    source_type: SourceType
    source_ref: str
    summary: str
    supports: list[str] = Field(default_factory=list)
    contradicts: list[str] = Field(default_factory=list)
    reliability: Confidence = "medium"
    client_relevance: Confidence = "medium"
    used_by_agents: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=now_utc)


class ClientAsset(StrictModel):
    asset_id: str
    asset_type: str
    name: str
    country: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    confidence_layer: ConfidenceLayer = "source_backed"
    source_ref: str | None = None


class AssetRelation(StrictModel):
    source_asset_id: str
    target_asset_id: str
    relation_type: str
    rationale: str
    confidence_layer: ConfidenceLayer = "source_backed"
    source_ref: str | None = None


class ClientContext(StrictModel):
    scenario_id: str
    client_id: str
    assets: list[ClientAsset] = Field(default_factory=list)
    relations: list[AssetRelation] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    context_sufficiency: Confidence = "low"


class AgentFinding(StrictModel):
    agent_name: str
    mode: str
    summary: str
    risk_score: int | None = None
    confidence: Confidence = "medium"
    evidence_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    review_required: bool = False
    rationale: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("risk_score")
    @classmethod
    def risk_score_range(cls, value: int | None) -> int | None:
        if value is not None and not 0 <= value <= 100:
            raise ValueError("risk_score must be between 0 and 100")
        return value


class KnowledgeObject(StrictModel):
    id: str
    domain: Literal["treasury", "legal", "accounting", "procurement", "executive", "cross_functional"]
    object_type: Literal[
        "red_flag",
        "rubric",
        "rule",
        "pattern",
        "playbook",
        "language_guardrail",
        "review_trigger",
        "evidence_standard",
    ]
    title: str
    description: str
    conditions: list[str] = Field(default_factory=list)
    output_effects: list[str] = Field(default_factory=list)
    evidence_requirements: list[str] = Field(default_factory=list)
    expert_confidence: Confidence
    source_case_ids: list[str] = Field(default_factory=list)
    version: str


class ExpertAssessment(StrictModel):
    knowledge_object_ids: list[str] = Field(default_factory=list)
    review_required: bool = False
    recommended_guardrails: list[str] = Field(default_factory=list)
    additional_questions: list[str] = Field(default_factory=list)
    score_adjustments: dict[str, int] = Field(default_factory=dict)
    red_team_observations: list[str] = Field(default_factory=list)


class DecisionItem(StrictModel):
    decision: str
    owner: str
    deadline: str
    rationale: str
    options: list[str]
    evidence_ids: list[str] = Field(default_factory=list)
    expert_knowledge_ids: list[str] = Field(default_factory=list)
    risk_if_delayed: str
    review_required: bool
    priority: int = 999


class ScenarioResult(StrictModel):
    scenario_id: str
    client_id: str
    artifact_dir: str
    findings: list[AgentFinding]
    decisions: list[DecisionItem]
    evidence: list[EvidenceItem]
    final_brief_path: str
