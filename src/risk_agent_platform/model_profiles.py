from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from langchain_openai import ChatOpenAI

from risk_agent_platform.config import DEFAULT_OPENROUTER_MODEL, Settings


@dataclass(frozen=True)
class ModelProfile:
    name: str
    provider: str
    model: str
    temperature: float
    max_tokens: int


class ModelProfileRouter:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}

    def select_for_agent(self, agent_name: str) -> ModelProfile:
        profile_name = (self.raw.get("agent_profile_map") or {}).get(agent_name, "reasoning")
        return self.select(profile_name)

    def select(self, profile_name: str) -> ModelProfile:
        profiles: dict[str, Any] = self.raw.get("profiles") or {}
        data = profiles.get(profile_name) or profiles.get("reasoning") or {}
        model_env = data.get("model_env")
        model = os.getenv(str(model_env)) if model_env else None
        return ModelProfile(
            name=profile_name,
            provider=str(data.get("provider", "openrouter")),
            model=model or str(data.get("default_model", DEFAULT_OPENROUTER_MODEL)),
            temperature=float(data.get("temperature", 0)),
            max_tokens=int(data.get("max_tokens", 2048)),
        )

    def chat_model(self, settings: Settings, profile: ModelProfile) -> ChatOpenAI:
        if profile.provider != "openrouter":
            raise ValueError(f"Unsupported provider: {profile.provider}")
        if not settings.openrouter.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required for DeepAgent execution")
        return ChatOpenAI(
            model=profile.model,
            base_url=settings.openrouter.base_url,
            api_key=settings.openrouter.api_key,
            temperature=profile.temperature,
            max_completion_tokens=profile.max_tokens,
            timeout=settings.openrouter.timeout_seconds,
            max_retries=settings.openrouter.max_retries,
            default_headers=_openrouter_headers(settings),
        )


def _openrouter_headers(settings: Settings) -> dict[str, str]:
    headers: dict[str, str] = {}
    if settings.openrouter.app_url:
        headers["HTTP-Referer"] = settings.openrouter.app_url
    if settings.openrouter.app_title:
        headers["X-Title"] = settings.openrouter.app_title
    return headers
