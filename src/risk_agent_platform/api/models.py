from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from risk_agent_platform.run_discovery import DEFAULT_ANALYSIS_CONCURRENCY
from risk_agent_platform.schemas import (
    DecisionAction,
    DecisionActionType,
    DecisionState,
    RiskDiscoveryRequest,
    RiskDiscoveryScope,
    RiskEvent,
    StrictModel,
)


ScopeType = Literal[
    "company",
    "business_unit",
    "department",
    "region",
    "site",
    "supplier",
    "customer",
    "contract",
    "product",
    "portfolio",
]

AnalysisMode = Literal["auto", "all-selected", "top", "top-n"]
JobType = Literal["discovery", "scenario"]
JobStatus = Literal["submitted", "working", "completed", "failed"]


class DiscoveryJobRequest(StrictModel):
    """Mirrors the `discover-risks` CLI parameters (see cli.py) as a JSON request body."""

    event_title: str
    event_description: str = ""
    client_id: str
    scope_text: str | None = None
    scope_type: ScopeType = "company"
    scope_name: str | None = None
    department: str | None = None
    industry: str | None = None
    region: str | None = None
    site_id: str | None = None
    countries: list[str] = Field(default_factory=list)
    event_date: date | None = None
    max_risks: int = 3
    run_analysis: bool = False
    allow_fallback_analysis: bool = False
    analysis_mode: AnalysisMode = "auto"
    top_n: int = 3
    analysis_concurrency: int = DEFAULT_ANALYSIS_CONCURRENCY
    embedded_services: bool = False

    @field_validator("max_risks")
    @classmethod
    def max_risks_range(cls, value: int) -> int:
        if not 1 <= value <= 10:
            raise ValueError("max_risks must be between 1 and 10")
        return value

    def to_discovery_request(self) -> RiskDiscoveryRequest:
        return RiskDiscoveryRequest(
            event_title=self.event_title,
            event_description=self.event_description,
            countries=self.countries,
            event_date=self.event_date,
            max_risks=self.max_risks,
            scope=RiskDiscoveryScope(
                client_id=self.client_id,
                scope_text=self.scope_text,
                scope_type=self.scope_type,
                scope_name=self.scope_name,
                department=self.department,
                region=self.region,
                site_id=self.site_id,
                metadata={"industry": self.industry} if self.industry else {},
            ),
        )

    def to_options(self) -> dict[str, Any]:
        return {
            "run_analysis": self.run_analysis,
            "allow_fallback_analysis": self.allow_fallback_analysis,
            "analysis_mode": self.analysis_mode,
            "top_n": self.top_n,
            "analysis_concurrency": self.analysis_concurrency,
            "embedded_services": self.embedded_services,
        }


class ScenarioJobRequest(StrictModel):
    """Either an inline RiskEvent-shaped scenario, or a path to a JSON file under data/scenarios/."""

    event: RiskEvent | None = None
    scenario_path: str | None = None
    embedded_services: bool = False

    @model_validator(mode="after")
    def _check_exactly_one_source(self) -> "ScenarioJobRequest":
        if (self.event is None) == (self.scenario_path is None):
            raise ValueError("Provide exactly one of 'event' or 'scenario_path'")
        return self


class JobSubmittedResponse(StrictModel):
    job_id: str


class JobStatusResponse(StrictModel):
    job_id: str
    job_type: JobType
    status: JobStatus
    trace_id: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class JobListResponse(StrictModel):
    jobs: list[JobStatusResponse]


class ArtifactListResponse(StrictModel):
    scenario_id: str
    artifacts: list[str]


class DecisionActionRequest(StrictModel):
    action: DecisionActionType
    actor: str
    reason: str = ""
    new_owner: str | None = None


class DecisionLogResponse(StrictModel):
    scenario_id: str
    actions: list[DecisionAction]
    states: dict[str, DecisionState]
    summary: dict[str, Any]
