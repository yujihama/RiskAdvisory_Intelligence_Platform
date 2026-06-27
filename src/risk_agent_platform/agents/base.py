from __future__ import annotations

from risk_agent_platform.a2a import AgentRunContext
from risk_agent_platform.schemas import AgentCard, AgentFinding, AgentTask


class BaseAgent:
    name = "base-agent"
    description = "Base agent"
    skills: list[str] = []
    modes: list[str] = []

    def card(self) -> AgentCard:
        return AgentCard(
            name=self.name,
            description=self.description,
            skills=self.skills,
            modes=self.modes,
        )

    def handle(self, task: AgentTask, context: AgentRunContext) -> AgentFinding:
        raise NotImplementedError
