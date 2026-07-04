from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response

from risk_agent_platform.api.artifacts import (
    ArtifactNotFoundError,
    ArtifactPathError,
    artifact_media_type,
    list_artifacts,
    resolve_artifact_path,
    resolve_scenario_input_path,
)
from risk_agent_platform.api.jobs import JOB_STATUSES, JobRecord, JobStore
from risk_agent_platform.api.models import (
    ArtifactListResponse,
    DiscoveryJobRequest,
    JobListResponse,
    JobStatusResponse,
    JobSubmittedResponse,
    ScenarioJobRequest,
)
from risk_agent_platform.api.runner import JobRunner
from risk_agent_platform.config import Settings
from risk_agent_platform.schemas import RiskEvent


logger = logging.getLogger(__name__)


def default_job_db_path(settings: Settings) -> Path:
    override = os.getenv("PLATFORM_API_JOB_DB")
    if override:
        return Path(override)
    return settings.project_root / "outputs" / "api_jobs.sqlite3"


def _job_to_response(record: JobRecord) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=record.job_id,
        job_type=record.job_type,
        status=record.status,
        trace_id=record.trace_id,
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
        result=record.result_summary,
        error=record.error_message,
    )


def create_app(
    settings: Settings | None = None,
    *,
    job_db_path: Path | None = None,
    max_workers: int = 2,
) -> FastAPI:
    settings = settings or Settings.load(Path.cwd())
    store = JobStore(job_db_path or default_job_db_path(settings))
    runner = JobRunner(settings, store, max_workers=max_workers)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        recovered = store.recover_orphans()
        if recovered:
            logger.warning("recovered %s orphaned job(s) from a previous process on startup", recovered)
        try:
            yield
        finally:
            runner.shutdown()

    app = FastAPI(title="Risk Advisory Intelligence Platform API", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.state.runner = runner

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/discoveries", status_code=202, response_model=JobSubmittedResponse)
    def submit_discovery(body: DiscoveryJobRequest) -> JobSubmittedResponse:
        request = body.to_discovery_request()
        job_id = f"job_{uuid4().hex}"
        trace_id = str(uuid4())
        store.create_job(job_id, "discovery", trace_id, body.model_dump(mode="json"))
        runner.submit_discovery(job_id, trace_id, request, body.to_options())
        return JobSubmittedResponse(job_id=job_id)

    @app.post("/v1/scenarios", status_code=202, response_model=JobSubmittedResponse)
    def submit_scenario(body: ScenarioJobRequest) -> JobSubmittedResponse:
        event = body.event
        if event is None:
            scenarios_root = settings.project_root / "data" / "scenarios"
            try:
                path = resolve_scenario_input_path(scenarios_root, body.scenario_path or "")
            except ArtifactPathError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except ArtifactNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            event = RiskEvent.model_validate(json.loads(path.read_text(encoding="utf-8")))

        job_id = f"job_{uuid4().hex}"
        trace_id = str(uuid4())
        store.create_job(job_id, "scenario", trace_id, body.model_dump(mode="json"))
        runner.submit_scenario(job_id, trace_id, event, embedded_services=body.embedded_services)
        return JobSubmittedResponse(job_id=job_id)

    @app.get("/v1/jobs/{job_id}", response_model=JobStatusResponse)
    def get_job(job_id: str) -> JobStatusResponse:
        record = store.get_job(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        return _job_to_response(record)

    @app.get("/v1/jobs", response_model=JobListResponse)
    def list_jobs(status: str | None = Query(default=None)) -> JobListResponse:
        if status is not None and status not in JOB_STATUSES:
            raise HTTPException(status_code=422, detail=f"invalid status filter: {status!r}")
        records = store.list_jobs(status)
        return JobListResponse(jobs=[_job_to_response(record) for record in records])

    @app.get("/v1/scenarios/{scenario_id}/artifacts", response_model=ArtifactListResponse)
    def artifacts_index(scenario_id: str) -> ArtifactListResponse:
        outputs_root = settings.project_root / "outputs"
        try:
            names = list_artifacts(outputs_root, scenario_id)
        except ArtifactPathError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not names and not (outputs_root / scenario_id).is_dir():
            raise HTTPException(status_code=404, detail=f"no artifacts found for scenario_id={scenario_id!r}")
        return ArtifactListResponse(scenario_id=scenario_id, artifacts=names)

    @app.get("/v1/scenarios/{scenario_id}/artifacts/{name:path}")
    def artifact_content(scenario_id: str, name: str) -> Response:
        outputs_root = settings.project_root / "outputs"
        try:
            path = resolve_artifact_path(outputs_root, scenario_id, name)
        except ArtifactPathError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ArtifactNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(content=path.read_bytes(), media_type=artifact_media_type(name))

    return app
