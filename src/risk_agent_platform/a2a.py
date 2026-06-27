from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from risk_agent_platform.config import Settings
from risk_agent_platform.mcp.evidence_ledger import EvidenceLedgerMCP
from risk_agent_platform.mcp.expert_knowledge import ExpertKnowledgeMCP
from risk_agent_platform.mcp.filesystem import FilesystemMCP
from risk_agent_platform.mcp.source_catalog import SourceCatalogMCP
from risk_agent_platform.mcp.structured_data import StructuredDataMCP
from risk_agent_platform.schemas import AgentCard, AgentFinding, AgentTask, RiskEvent


@dataclass
class AgentRunContext:
    settings: Settings
    risk_event: RiskEvent
    scenario_dir: Path
    filesystem: FilesystemMCP
    structured_data: StructuredDataMCP
    evidence_ledger: EvidenceLedgerMCP
    expert_knowledge: ExpertKnowledgeMCP
    source_catalog: SourceCatalogMCP
    trace_id: str = field(default_factory=lambda: str(uuid4()))
    state: dict[str, object] = field(default_factory=dict)


class A2AAgent(Protocol):
    name: str

    def card(self) -> AgentCard:
        ...

    def handle(self, task: AgentTask, context: AgentRunContext) -> AgentFinding:
        ...


class LocalA2ARegistry:
    def __init__(self) -> None:
        self._agents: dict[str, A2AAgent] = {}

    def register(self, agent: A2AAgent) -> None:
        self._agents[agent.name] = agent

    def agent_cards(self) -> list[AgentCard]:
        return [agent.card() for agent in self._agents.values()]

    def invoke(self, agent_name: str, task: AgentTask, context: AgentRunContext) -> AgentFinding:
        try:
            agent = self._agents[agent_name]
        except KeyError as exc:
            raise ValueError(f"Agent not registered: {agent_name}") from exc
        return agent.handle(task, context)
