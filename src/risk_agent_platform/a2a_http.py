from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import httpx
from fastapi import FastAPI, Request

from risk_agent_platform.a2a_sdk_adapter import sdk_agent_card_dict
from risk_agent_platform.config import Settings
from risk_agent_platform.schemas import AgentCard, AgentTaskRequest, AgentTaskResult
from risk_agent_platform.tracing import TraceRecorder


class A2AService:
    name: str

    def card(self) -> AgentCard:
        raise NotImplementedError

    def run_task(self, request: AgentTaskRequest) -> AgentTaskResult:
        raise NotImplementedError


def create_a2a_app(service: A2AService) -> FastAPI:
    app = FastAPI(title=service.name)

    @app.get("/.well-known/agent-card.json")
    def agent_card(request: Request) -> dict[str, Any]:
        return sdk_agent_card_dict(service.card(), base_url=str(request.base_url).rstrip("/"))

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "agent": service.name}

    @app.post("/a2a")
    def a2a(request: AgentTaskRequest) -> dict[str, Any]:
        return service.run_task(request).model_dump(mode="json")

    return app


class A2AHttpClient:
    def __init__(
        self,
        service_urls: Mapping[str, str],
        embedded_apps: Mapping[str, FastAPI] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.service_urls = dict(service_urls)
        self.embedded_apps = dict(embedded_apps or {})
        self.settings = settings

    def send_task(self, agent_name: str, request: AgentTaskRequest) -> AgentTaskResult:
        return _run_async(self.asend_task(agent_name, request))

    async def asend_task(self, agent_name: str, request: AgentTaskRequest) -> AgentTaskResult:
        tracer = TraceRecorder(self.settings, request.task.trace_id) if self.settings else None
        span = tracer.span(
            "a2a_call",
            {
                "agent_name": agent_name,
                "task_id": request.task.task_id,
                "parent_task_id": request.task.parent_task_id,
                "scenario_id": request.task.scenario_id,
                "client_id": request.task.client_id,
            },
        ) if tracer else _nullcontext()
        with span:
            result = await self._send(agent_name, request)
            if tracer:
                tracer.event(
                    "a2a_result",
                    {
                        "agent_name": agent_name,
                        "task_id": request.task.task_id,
                        "status": result.status,
                        "error": result.error.message if result.error else None,
                    },
                )
            return result

    async def _send(self, agent_name: str, request: AgentTaskRequest) -> AgentTaskResult:
        if agent_name in self.embedded_apps:
            transport = httpx.ASGITransport(app=self.embedded_apps[agent_name])
            async with httpx.AsyncClient(transport=transport, base_url="http://embedded") as client:
                response = await client.post("/a2a", json=request.model_dump(mode="json"), timeout=120)
                response.raise_for_status()
                return AgentTaskResult.model_validate(response.json())
        try:
            base_url = self.service_urls[agent_name].rstrip("/")
        except KeyError as exc:
            raise ValueError(f"No A2A URL configured for {agent_name}") from exc
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(f"{base_url}/a2a", json=request.model_dump(mode="json"))
            response.raise_for_status()
            return AgentTaskResult.model_validate(response.json())


def _run_async(awaitable: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    raise RuntimeError("A2AHttpClient.send_task cannot run inside an active event loop; use asend_task instead")


class _nullcontext:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_args: object) -> None:
        return None
