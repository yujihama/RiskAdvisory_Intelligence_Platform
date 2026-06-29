from __future__ import annotations

import json
from pathlib import Path
from collections.abc import Sequence
from typing import Any, TypeVar

from deepagents import create_deep_agent
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from risk_agent_platform.config import Settings
from risk_agent_platform.model_profiles import ModelProfileRouter
from risk_agent_platform.tracing import TraceRecorder, observed_marker


StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


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

    def synthesize(self, prompt: str, *, max_chars: int | None = None) -> str:
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
            return content if max_chars is None else content[:max_chars]

    def synthesize_structured(
        self,
        prompt: str,
        output_model: type[StructuredModel],
        *,
        max_chars: int = 4000,
        provider_first: bool | None = None,
        allow_text_fallback: bool = True,
    ) -> StructuredModel:
        with self.tracer.span(
            "openrouter_structured_call",
            {
                "agent_name": self.agent_name,
                "model_name": self.profile.model,
                "output_model": output_model.__name__,
                "input_summary": prompt[:500],
            },
        ):
            use_provider = True if provider_first is None else provider_first
            if use_provider:
                try:
                    model = self.router.chat_model(self.settings, self.profile)
                    graph = create_deep_agent(
                        model=model,
                        tools=self.tools,
                        system_prompt=self.system_prompt,
                        name=self.agent_name,
                        response_format=output_model,
                    )
                    result: dict[str, Any] = graph.invoke({"messages": [{"role": "user", "content": prompt}]})
                    if "structured_response" not in result:
                        raise RuntimeError("DeepAgent response_format result did not include structured_response.")
                    parsed = _validate_structured_result(result["structured_response"], output_model)
                    self.tracer.event(
                        "openrouter_structured_result",
                        {
                            "agent_name": self.agent_name,
                            "model_name": self.profile.model,
                            "output_model": output_model.__name__,
                            "validation": "deepagent_response_format",
                        },
                    )
                    return parsed
                except Exception as structured_exc:
                    structured_error = str(structured_exc)[:300]
                    if not allow_text_fallback:
                        raise
            else:
                structured_error = "provider_structured_disabled"
                if not allow_text_fallback:
                    raise RuntimeError("Provider-native structured output is required but disabled.")
            fallback_prompt = (
                "Return only JSON that conforms to this JSON schema. Do not include prose or markdown fences.\n"
                f"json_schema={json.dumps(output_model.model_json_schema(), ensure_ascii=False)}\n\n"
                f"{prompt}"
            )
            text = self.synthesize(fallback_prompt, max_chars=max_chars)
            parsed = _validate_structured_result(_json_object_from_text(text) or text, output_model)
            self.tracer.event(
                "openrouter_structured_result",
                {
                    "agent_name": self.agent_name,
                    "model_name": self.profile.model,
                    "output_model": output_model.__name__,
                    "validation": "text_fallback_pydantic",
                    "structured_error": structured_error,
                },
            )
            return parsed


def _validate_structured_result(value: Any, output_model: type[StructuredModel]) -> StructuredModel:
    if isinstance(value, output_model):
        return value
    if isinstance(value, dict):
        return output_model.model_validate(value)
    if isinstance(value, str):
        data = _json_object_from_text(value)
        if data is not None:
            return output_model.model_validate(data)
        return output_model.model_validate_json(value)
    return output_model.model_validate(value)


def _json_object_from_text(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        value = json.loads(stripped)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            value = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None
