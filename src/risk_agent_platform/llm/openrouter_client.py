from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from risk_agent_platform.config import OpenRouterSettings
from risk_agent_platform.llm.model_router import LLMProfile


@dataclass(frozen=True)
class ChatResult:
    content: str
    model: str
    usage: dict[str, Any]
    raw: dict[str, Any]


class OpenRouterClient:
    def __init__(self, settings: OpenRouterSettings) -> None:
        self.settings = settings

    def chat(self, messages: list[dict[str, str]], profile: LLMProfile | None = None) -> ChatResult:
        if not self.settings.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required")
        selected_model = profile.model if profile else self.settings.model
        payload: dict[str, Any] = {
            "model": selected_model,
            "messages": messages,
            "temperature": profile.temperature if profile else self.settings.temperature,
            "max_tokens": profile.max_tokens if profile else self.settings.max_tokens,
        }
        raw = self._post_chat_completions(payload)
        choices = raw.get("choices") or []
        if not choices:
            raise RuntimeError(f"OpenRouter response did not include choices: {str(raw)[:500]}")
        content = choices[0].get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(f"OpenRouter response did not include message content: {str(raw)[:500]}")
        return ChatResult(
            content=content,
            model=str(raw.get("model") or selected_model),
            usage=dict(raw.get("usage") or {}),
            raw=raw,
        )

    def smoke_test(self, *, max_tokens: int = 16) -> ChatResult:
        profile = LLMProfile(
            provider="openrouter",
            model=self.settings.model,
            temperature=0.0,
            max_tokens=max_tokens,
        )
        return self.chat(
            [
                {"role": "system", "content": "Return one short sentence."},
                {"role": "user", "content": "Say 'risk platform ready' in exactly those words."},
            ],
            profile=profile,
        )

    def _post_chat_completions(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = self.settings.base_url.rstrip("/") + "/chat/completions"
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }
        if self.settings.app_url:
            headers["HTTP-Referer"] = self.settings.app_url
        if self.settings.app_title:
            headers["X-Title"] = self.settings.app_title

        last_error: Exception | None = None
        for attempt in range(self.settings.max_retries + 1):
            request = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=self.settings.timeout_seconds) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"OpenRouter HTTP {exc.code}: {error_body[:1000]}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                if attempt < self.settings.max_retries:
                    time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"OpenRouter request failed: {last_error}") from last_error
