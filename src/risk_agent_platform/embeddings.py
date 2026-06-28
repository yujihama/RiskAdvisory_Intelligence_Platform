from __future__ import annotations

import math
from typing import Protocol

import httpx

from risk_agent_platform.config import Settings
from risk_agent_platform.vector import VECTOR_SIZE, deterministic_embedding


class EmbeddingProvider(Protocol):
    name: str

    def embed(self, text: str) -> list[float]:
        raise NotImplementedError


class DeterministicEmbeddingProvider:
    name = "deterministic"

    def embed(self, text: str) -> list[float]:
        return deterministic_embedding(text)


class OpenRouterEmbeddingProvider:
    name = "openrouter"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def embed(self, text: str) -> list[float]:
        api_key = self.settings.openrouter.api_key
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required for OpenRouter embeddings")
        base_url = self.settings.embeddings.base_url.rstrip("/")
        response = httpx.post(
            f"{base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self.settings.embeddings.model, "input": text or "empty"},
            timeout=self.settings.embeddings.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        vector = payload["data"][0]["embedding"]
        return resize_and_normalize([float(value) for value in vector], VECTOR_SIZE)


class AutoEmbeddingProvider:
    name = "auto"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.real_provider = OpenRouterEmbeddingProvider(settings)
        self.fallback_provider = DeterministicEmbeddingProvider()
        self.last_provider_name = self.real_provider.name

    def embed(self, text: str) -> list[float]:
        try:
            vector = self.real_provider.embed(text)
        except Exception:
            if not self.settings.embeddings.fallback_to_deterministic:
                raise
            self.last_provider_name = "deterministic_fallback"
            return self.fallback_provider.embed(text)
        self.last_provider_name = self.real_provider.name
        return vector


def create_embedding_provider(settings: Settings) -> EmbeddingProvider:
    provider = settings.embeddings.provider.lower()
    if provider in {"deterministic", "hash", "local-test"}:
        return DeterministicEmbeddingProvider()
    if provider in {"openrouter", "real"}:
        return AutoEmbeddingProvider(settings)
    raise ValueError(f"Unsupported EMBEDDING_PROVIDER: {settings.embeddings.provider}")


def resize_and_normalize(vector: list[float], size: int = VECTOR_SIZE) -> list[float]:
    if not vector:
        return deterministic_embedding("empty", size=size)
    resized = [0.0] * size
    for idx, value in enumerate(vector):
        resized[idx % size] += value
    norm = math.sqrt(sum(value * value for value in resized)) or 1.0
    return [value / norm for value in resized]
