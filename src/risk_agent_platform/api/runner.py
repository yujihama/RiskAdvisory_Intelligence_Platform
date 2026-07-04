from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from risk_agent_platform import run_discovery, run_scenario
from risk_agent_platform.api.artifacts import list_artifacts
from risk_agent_platform.api.jobs import JobStore
from risk_agent_platform.config import Settings
from risk_agent_platform.schemas import RiskDiscoveryRequest, RiskEvent
from risk_agent_platform.tracing import TraceRecorder


logger = logging.getLogger(__name__)


def execute_discovery_job(settings: Settings, request: RiskDiscoveryRequest, options: dict[str, Any]) -> dict[str, Any]:
    """Call target for a discovery job. Kept as a bare module function so tests can monkeypatch it directly."""
    return run_discovery.run_discovery_pipeline(
        settings,
        request,
        run_analysis=options["run_analysis"],
        allow_fallback_analysis=options["allow_fallback_analysis"],
        analysis_mode=options["analysis_mode"],
        top_n=options["top_n"],
        analysis_concurrency=options["analysis_concurrency"],
        embedded_services=options["embedded_services"],
    )


def execute_scenario_job(settings: Settings, event: RiskEvent, *, embedded_services: bool) -> tuple[Any, Any]:
    """Call target for a scenario job. Kept as a bare module function so tests can monkeypatch it directly."""
    return run_scenario.execute_scenario(settings, event, embedded_services=embedded_services)


def sanitize_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:500]


class JobRunner:
    def __init__(self, settings: Settings, store: JobStore, *, max_workers: int = 2) -> None:
        self.settings = settings
        self.store = store
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="platform-api-job")

    def submit_discovery(self, job_id: str, trace_id: str, request: RiskDiscoveryRequest, options: dict[str, Any]) -> None:
        self.executor.submit(self._run_discovery, job_id, trace_id, request, options)

    def submit_scenario(self, job_id: str, trace_id: str, event: RiskEvent, *, embedded_services: bool) -> None:
        self.executor.submit(self._run_scenario, job_id, trace_id, event, embedded_services)

    def shutdown(self, *, wait: bool = False) -> None:
        self.executor.shutdown(wait=wait)

    def _tracer(self, trace_id: str) -> TraceRecorder:
        return TraceRecorder(self.settings, trace_id)

    def _run_discovery(self, job_id: str, trace_id: str, request: RiskDiscoveryRequest, options: dict[str, Any]) -> None:
        self.store.mark_working(job_id)
        tracer = self._tracer(trace_id)
        tracer.event("api_job.working", {"job_id": job_id, "job_type": "discovery"})
        try:
            summary = execute_discovery_job(self.settings, request, options)
        except Exception as exc:
            logger.exception("platform API discovery job %s failed", job_id)
            tracer.event("api_job.failed", {"job_id": job_id, "error": str(exc)})
            self.store.mark_failed(job_id, sanitize_error(exc))
            return

        outputs_root = self.settings.project_root / "outputs"
        scenario_ids = list(summary.get("selected_scenario_ids") or [])
        result_summary: dict[str, Any] = {
            "discovery_status": summary["discovery_status"],
            "analysis_status": summary["analysis_status"],
            "selected_scenario_id": summary["selected_scenario_id"],
            "scenario_ids": scenario_ids,
            "discovery_output": summary["discovery_output"],
            "portfolio_summary_json": summary.get("portfolio_summary_json"),
            "portfolio_summary_md": summary.get("portfolio_summary_md"),
            "artifacts": {scenario_id: list_artifacts(outputs_root, scenario_id) for scenario_id in scenario_ids},
        }

        if summary["analysis_status"] == "failed":
            errors = [record.get("error") for record in summary.get("records", []) if record.get("error")]
            message = "; ".join(f"{error.get('code')}: {error.get('message')}" for error in errors if error)
            message = message or "one or more scenario analyses failed"
            tracer.event("api_job.failed", {"job_id": job_id, "error": message})
            self.store.mark_failed(job_id, message[:500])
            return

        tracer.event("api_job.completed", {"job_id": job_id, "analysis_status": summary["analysis_status"]})
        self.store.mark_completed(job_id, result_summary)

    def _run_scenario(self, job_id: str, trace_id: str, event: RiskEvent, embedded_services: bool) -> None:
        self.store.mark_working(job_id)
        tracer = self._tracer(trace_id)
        tracer.event("api_job.working", {"job_id": job_id, "job_type": "scenario", "scenario_id": event.scenario_id})
        try:
            result, output_dir = execute_scenario_job(self.settings, event, embedded_services=embedded_services)
        except Exception as exc:
            logger.exception("platform API scenario job %s failed", job_id)
            tracer.event("api_job.failed", {"job_id": job_id, "error": str(exc)})
            self.store.mark_failed(job_id, sanitize_error(exc))
            return

        outputs_root = self.settings.project_root / "outputs"
        result_summary = {
            "scenario_id": event.scenario_id,
            "status": result.status,
            "trace_id": result.trace_id,
            "output_dir": str(output_dir),
            "artifacts": list_artifacts(outputs_root, event.scenario_id),
        }

        if result.error:
            message = f"{result.error.code}: {result.error.message}"
            tracer.event("api_job.failed", {"job_id": job_id, "error": message})
            self.store.mark_failed(job_id, message[:500])
            return

        tracer.event("api_job.completed", {"job_id": job_id, "status": result.status})
        self.store.mark_completed(job_id, result_summary)
