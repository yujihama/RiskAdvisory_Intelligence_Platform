from __future__ import annotations

import json
import hashlib
import time
from uuid import UUID
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from langfuse import Langfuse, observe

from risk_agent_platform.config import Settings


class TraceRecorder:
    def __init__(self, settings: Settings, trace_id: str | None = None) -> None:
        self.settings = settings
        self.trace_id = trace_id or "unassigned"
        self.langfuse_trace_id = _langfuse_trace_id(self.trace_id)
        self.path = settings.project_root / "outputs" / "_traces" / f"{self.trace_id}.jsonl"
        self.langfuse_enabled = bool(settings.langfuse.host and settings.langfuse.public_key and settings.langfuse.secret_key)
        self._client: Langfuse | None = None
        if self.langfuse_enabled:
            self._client = Langfuse(
                host=settings.langfuse.host,
                public_key=settings.langfuse.public_key,
                secret_key=settings.langfuse.secret_key,
                environment="local",
            )

    def event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {"trace_id": self.trace_id, "event_type": event_type, **payload}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        if self._client:
            try:
                self._client.create_event(
                    trace_context={"trace_id": self.langfuse_trace_id},
                    name=event_type,
                    metadata=_metadata(payload),
                    level="ERROR" if event_type.endswith(".error") or payload.get("error") else "DEFAULT",
                    status_message=str(payload.get("error"))[:500] if payload.get("error") else None,
                )
            except Exception as exc:
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "trace_id": self.trace_id,
                                "event_type": "langfuse_event_error",
                                "error": str(exc),
                                "source_event_type": event_type,
                            },
                            ensure_ascii=False,
                            default=str,
                        )
                        + "\n"
                    )

    @contextmanager
    def span(self, event_type: str, payload: dict[str, Any]) -> Iterator[None]:
        start = time.perf_counter()
        self.event(f"{event_type}.start", payload)
        try:
            yield
        except Exception as exc:
            self.event(f"{event_type}.error", payload | {"error": str(exc), "latency_ms": _elapsed_ms(start)})
            raise
        else:
            self.event(f"{event_type}.end", payload | {"latency_ms": _elapsed_ms(start), "langfuse_enabled": self.langfuse_enabled})

    def flush(self) -> None:
        if self._client:
            self._client.flush()


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _langfuse_trace_id(trace_id: str) -> str:
    try:
        return UUID(trace_id).hex
    except ValueError:
        return hashlib.sha256(trace_id.encode("utf-8")).hexdigest()[:32]


def _metadata(payload: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key, value in payload.items():
        if key in {"input", "output"}:
            continue
        text = str(value)
        metadata[key] = text[:1000]
    return metadata


@observe(name="risk-platform-observed-call", as_type="span", capture_input=False, capture_output=False)
def observed_marker(name: str) -> str:
    return name
