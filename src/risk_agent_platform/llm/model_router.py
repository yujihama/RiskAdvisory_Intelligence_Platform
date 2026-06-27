from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from risk_agent_platform.config import DEFAULT_OPENROUTER_MODEL


@dataclass(frozen=True)
class LLMProfile:
    provider: str
    model: str
    temperature: float
    max_tokens: int


class ModelRouter:
    def __init__(self, profiles_path: Path) -> None:
        self.profiles_path = profiles_path
        self._raw = self._load(profiles_path)

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {"llm_profiles": {}, "fallbacks": {}}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def select(self, *, task_type: str, agent: str | None = None, mode: str | None = None) -> LLMProfile:
        profiles = self._raw.get("llm_profiles", {})
        data = profiles.get(task_type) or profiles.get("domain_reasoning") or {}
        model_env = data.get("model_env")
        model = os.getenv(str(model_env)) if model_env else None
        return LLMProfile(
            provider=str(data.get("provider", "openrouter")),
            model=model or str(data.get("default_model", DEFAULT_OPENROUTER_MODEL)),
            temperature=float(data.get("temperature", 0.2)),
            max_tokens=int(data.get("max_tokens", 4000)),
        )

    def fallbacks_for(self, task_type: str) -> list[str]:
        fallbacks = self._raw.get("fallbacks", {})
        values = fallbacks.get(task_type, [])
        return [str(value) for value in values]
