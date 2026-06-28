from __future__ import annotations

from pathlib import Path
from collections.abc import Sequence
from typing import Any

from deepagents import create_deep_agent
from langchain_core.tools import BaseTool

from risk_agent_platform.config import Settings
from risk_agent_platform.model_profiles import ModelProfileRouter
from risk_agent_platform.tracing import TraceRecorder, observed_marker


class DeepAgentRunner:
    def __init__(
        self,
        settings: Settings,
        agent_name: str,
        system_prompt: str,
        tools: Sequence[BaseTool | Any] | None = None,
    ) -> None:
        self.settings = settings
        self.agent_name = agent_name
        self.system_prompt = system_prompt
        self.tools = list(tools or [])
        self.router = ModelProfileRouter(settings.project_root / "config" / "model_profiles.yaml")
        profile = self.router.select_for_agent(agent_name)
        self.profile = profile
        self.tracer = TraceRecorder(settings)
        model = self.router.chat_model(settings, profile)
        self.graph = create_deep_agent(
            model=model,
            tools=self.tools,
            system_prompt=system_prompt,
            name=agent_name,
        )

    def synthesize(self, prompt: str, *, max_chars: int = 600) -> str:
        with self.tracer.span(
            "openrouter_deepagent_call",
            {"agent_name": self.agent_name, "model_name": self.profile.model, "input_summary": prompt[:500]},
        ):
            if self.tracer.langfuse_enabled:
                observed_marker(self.agent_name)
            result: dict[str, Any] = self.graph.invoke({"messages": [{"role": "user", "content": prompt}]})
            content = str(result["messages"][-1].content)
            self.tracer.event(
                "openrouter_deepagent_result",
                {"agent_name": self.agent_name, "model_name": self.profile.model, "output_summary": content[:500]},
            )
            return content[:max_chars]
