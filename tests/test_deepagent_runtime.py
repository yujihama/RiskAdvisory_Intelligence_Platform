from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from risk_agent_platform.config import Settings
from risk_agent_platform.deepagent_runtime import DeepAgentRunner


class _StructuredAnswer(BaseModel):
    value: str


def test_synthesize_structured_uses_deepagent_response_format_by_default(monkeypatch):
    create_calls: list[dict[str, Any]] = []

    class _FakeGraph:
        def __init__(self, response_format: Any) -> None:
            self.response_format = response_format

        def invoke(self, _payload):
            if self.response_format is None:
                return {"messages": []}
            return {"structured_response": {"value": "ok"}}

    def fake_create_deep_agent(**kwargs):
        create_calls.append(kwargs)
        return _FakeGraph(kwargs.get("response_format"))

    monkeypatch.setattr("risk_agent_platform.deepagent_runtime.create_deep_agent", fake_create_deep_agent)
    monkeypatch.setattr(
        "risk_agent_platform.deepagent_runtime.ModelProfileRouter.chat_model",
        lambda *_args, **_kwargs: object(),
    )

    runner = DeepAgentRunner(Settings.load(Path.cwd()), "test-agent", "system prompt")
    result = runner.synthesize_structured("return a value", _StructuredAnswer)

    assert result == _StructuredAnswer(value="ok")
    assert create_calls[0].get("response_format") is None
    assert create_calls[1].get("response_format") is _StructuredAnswer
