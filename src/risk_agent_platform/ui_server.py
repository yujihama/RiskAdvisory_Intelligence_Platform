from __future__ import annotations

import argparse
import json
import os
import re
from threading import Lock
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from risk_agent_platform.config import Settings


DEFAULT_SCENARIO_ID = "scenario_discovered_fujifilm_dummy_iran_war_escalation_affecting_fujifilm_executive_management_disc_"
RUN_DURATION_SECONDS = 8.0

_RUN_LOCK = Lock()
_RUNS: dict[str, dict[str, Any]] = {}


class UIRunStartRequest(BaseModel):
    scenario_id: str | None = None
    event_title: str | None = None
    event_description: str | None = None
    scope: str | None = None
    mode: str = Field(default="manual")


def create_ui_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings.load(Path.cwd())
    app = FastAPI(title="Risk Intelligence UI")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/ui/state")
    def ui_state(scenario_id: str | None = None) -> dict[str, Any]:
        return build_ui_state(resolved_settings, scenario_id=scenario_id)

    @app.post("/api/ui/runs")
    def start_ui_run(payload: UIRunStartRequest | None = None) -> dict[str, Any]:
        return start_run(resolved_settings, payload or UIRunStartRequest())

    @app.get("/api/ui/runs/{run_id}")
    def ui_run_status(run_id: str) -> dict[str, Any]:
        return get_run_status(resolved_settings, run_id)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/ui/")

    @app.get("/ui", include_in_schema=False)
    def ui_without_slash() -> RedirectResponse:
        return RedirectResponse(url="/ui/")

    static_dir = resolved_settings.project_root / "docs" / "ui_mockups"
    if static_dir.exists():
        app.mount("/ui", StaticFiles(directory=static_dir, html=True), name="ui")

    return app


def start_run(settings: Settings, payload: UIRunStartRequest) -> dict[str, Any]:
    scenario_id = payload.scenario_id or os.getenv("UI_SCENARIO_ID") or _latest_scenario_id(settings) or DEFAULT_SCENARIO_ID
    # Validate the id and output presence up front so the UI can show an actionable error.
    scenario_dir = _scenario_output_dir(settings, scenario_id)
    if not scenario_dir.exists():
        raise HTTPException(status_code=404, detail=f"Scenario output not found: {scenario_id}")

    now = datetime.now(timezone.utc)
    run_id = f"ui-run-{now.strftime('%Y%m%d%H%M%S%f')}"
    run = {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "event_title": payload.event_title,
        "event_description": payload.event_description,
        "scope": payload.scope,
        "mode": payload.mode,
        "started_at": now,
    }
    with _RUN_LOCK:
        _RUNS[run_id] = run
    return _run_status(settings, run, now=now)


def get_run_status(settings: Settings, run_id: str) -> dict[str, Any]:
    with _RUN_LOCK:
        run = _RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return _run_status(settings, run, now=datetime.now(timezone.utc))


def _run_status(settings: Settings, run: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    started_at = run["started_at"]
    elapsed = max(0.0, (now - started_at).total_seconds())
    progress = min(100, int((elapsed / RUN_DURATION_SECONDS) * 100))
    completed = progress >= 100
    active_stage_index = min(len(_run_stages()) - 1, int((progress / 100) * len(_run_stages())))
    stages = []
    for index, stage in enumerate(_run_stages()):
        if completed or index < active_stage_index:
            status = "completed"
        elif index == active_stage_index:
            status = "running"
        else:
            status = "pending"
        stages.append({**stage, "status": status})
    result: dict[str, Any] = {
        "run_id": run["run_id"],
        "scenario_id": run["scenario_id"],
        "mode": run.get("mode") or "manual",
        "status": "completed" if completed else "running",
        "progress": progress,
        "started_at": started_at.isoformat(),
        "stages": stages,
        "active_stage": stages[active_stage_index]["label"],
    }
    if completed:
        result["state"] = build_ui_state(settings, scenario_id=run["scenario_id"])
    return result


def _run_stages() -> list[dict[str, str]]:
    return [
        {"id": "context", "label": "Context", "agent": "Context Agent"},
        {"id": "scenario", "label": "Scenario", "agent": "Risk Discovery"},
        {"id": "evidence", "label": "Evidence", "agent": "Source Agent"},
        {"id": "specialist", "label": "Specialist", "agent": "Treasury / Legal / Procurement"},
        {"id": "challenge", "label": "Challenge", "agent": "Red Team"},
        {"id": "decision", "label": "Decision", "agent": "Decision Synthesis"},
    ]


def build_ui_state(settings: Settings, *, scenario_id: str | None = None) -> dict[str, Any]:
    selected_scenario_id = scenario_id or os.getenv("UI_SCENARIO_ID") or _latest_scenario_id(settings) or DEFAULT_SCENARIO_ID
    scenario_dir = _scenario_output_dir(settings, selected_scenario_id)
    if not scenario_dir.exists():
        raise HTTPException(status_code=404, detail=f"Scenario output not found: {selected_scenario_id}")

    discovery = _read_json(settings.project_root / "outputs" / "risk_discovery" / f"{selected_scenario_id}.json")
    trace_metadata = _read_json(scenario_dir / "trace_metadata.json")
    decision_queue = _read_json(scenario_dir / "decision_queue.json")
    evidence_summary = _read_json(scenario_dir / "evidence_summary.json")
    final_brief = _read_text(scenario_dir / "final_brief.md")

    metrics = _metrics_from_outputs(final_brief, evidence_summary)
    decision = _first_item(decision_queue.get("decisions"))
    event = _event_from_discovery(discovery, selected_scenario_id)
    scenarios = _scenario_cards(discovery, metrics)

    return {
        "source": "backend",
        "loaded_at": datetime.now(timezone.utc).isoformat(),
        "scenario_id": selected_scenario_id,
        "trace_id": trace_metadata.get("trace_id"),
        "event": event,
        "risk_tree": {
            "scenarios": scenarios,
            "decision_synthesis": {
                "title": decision.get("decision") or "Continue / Hold / Reroute under controlled approval",
                "summary": _decision_summary(decision),
                "owner": decision.get("owner"),
                "deadline": decision.get("deadline"),
                "review_required": bool(decision.get("review_required")),
            },
        },
        "metrics": metrics,
        "decision": decision,
        "evidence": _evidence_cards(evidence_summary),
        "backend": {
            "output_dir": str(scenario_dir),
            "discovery_output": str(settings.project_root / "outputs" / "risk_discovery" / f"{selected_scenario_id}.json"),
        },
    }


def _scenario_output_dir(settings: Settings, scenario_id: str) -> Path:
    if not scenario_id or "/" in scenario_id or "\\" in scenario_id or ".." in scenario_id:
        raise HTTPException(status_code=400, detail="Invalid scenario_id")
    output_root = (settings.project_root / "outputs").resolve()
    candidate = (output_root / scenario_id).resolve()
    if output_root != candidate and output_root not in candidate.parents:
        raise HTTPException(status_code=400, detail="Invalid scenario_id")
    return candidate


def _latest_scenario_id(settings: Settings) -> str | None:
    output_root = settings.project_root / "outputs"
    default_dir = output_root / DEFAULT_SCENARIO_ID
    if default_dir.exists():
        return DEFAULT_SCENARIO_ID
    if not output_root.exists():
        return None
    candidates = [
        path
        for path in output_root.iterdir()
        if path.is_dir() and (path / "trace_metadata.json").exists() and (path / "decision_queue.json").exists()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime).name


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _first_item(value: Any) -> dict[str, Any]:
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return value[0]
    return {}


def _event_from_discovery(discovery: dict[str, Any], scenario_id: str) -> dict[str, Any]:
    request = discovery.get("request") if isinstance(discovery.get("request"), dict) else {}
    selected_event = discovery.get("selected_event") if isinstance(discovery.get("selected_event"), dict) else {}
    scope = request.get("scope") if isinstance(request.get("scope"), dict) else {}
    title = request.get("event_title") or selected_event.get("title") or scenario_id
    description = request.get("event_description") or selected_event.get("description") or ""
    return {
        "title": str(title),
        "summary": _shorten(str(description), 168),
        "client_id": scope.get("client_id") or selected_event.get("client_id"),
        "scope_name": scope.get("scope_name") or scope.get("scope_text"),
        "countries": request.get("countries") or selected_event.get("countries") or [],
    }


def _scenario_cards(discovery: dict[str, Any], metrics: dict[str, Any]) -> list[dict[str, Any]]:
    raw_candidates = discovery.get("selected_candidates")
    candidates = raw_candidates if isinstance(raw_candidates, list) else []
    cards: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates[:3], start=1):
        if not isinstance(candidate, dict):
            continue
        cards.append(_scenario_card(index, candidate, metrics))
    if cards:
        return cards
    return [
        {
            "label": "RISK SCENARIO 01",
            "title": "Payment / sanctions exposure",
            "description": "High-risk payment execution and sanctions screening require controlled approval.",
            "agents": ["Source", "Treasury", "Legal", "Red Team"],
            "core_label": "分析済",
            "core_sublabel": "medium",
            "metric_label": "exposure",
            "metric_value": metrics.get("payment_exposure_display") or "2,400,000",
        },
        {
            "label": "RISK SCENARIO 02",
            "title": "Supply route disruption",
            "description": "Middle East disruption can affect suppliers, logistics routes, and continuity options.",
            "agents": ["Context", "Source", "Procure", "Expert"],
            "core_label": "探索済",
            "core_sublabel": f"{metrics.get('affected_candidates') or 3} paths",
            "metric_label": "affected",
            "metric_value": f"{metrics.get('affected_candidates') or 3} candidates",
        },
        {
            "label": "RISK SCENARIO 03",
            "title": "Contract response trigger",
            "description": "Sanctions, force majeure, notice, and alternative sourcing clauses require review.",
            "agents": ["Legal", "Expert", "Source", "Red Team"],
            "core_label": "照合済",
            "core_sublabel": f"{metrics.get('contracts_reviewed') or 5} docs",
            "metric_label": "reviewed",
            "metric_value": f"{metrics.get('contracts_reviewed') or 5} contracts",
        },
    ]


def _scenario_card(index: int, candidate: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    risk_text = " ".join(
        str(value)
        for value in [
            candidate.get("risk_type"),
            candidate.get("title"),
            " ".join(str(item) for item in candidate.get("risk_themes") or []),
            " ".join(str(item) for item in candidate.get("affected_categories") or []),
        ]
        if value
    ).lower()
    agents = _agents_for_risk_text(risk_text)
    metric_label, metric_value = _metric_for_risk_text(risk_text, candidate, metrics)
    return {
        "label": f"RISK SCENARIO {index:02d}",
        "title": str(candidate.get("title") or f"Risk scenario {index}"),
        "description": _shorten(str(candidate.get("description") or candidate.get("rationale") or ""), 150),
        "agents": agents,
        "core_label": _core_label_for_risk_text(risk_text),
        "core_sublabel": str(candidate.get("urgency") or "medium"),
        "metric_label": metric_label,
        "metric_value": metric_value,
        "relevance_score": candidate.get("relevance_score"),
    }


def _agents_for_risk_text(text: str) -> list[str]:
    if any(term in text for term in ("sanction", "payment", "finance", "compliance", "legal")):
        return ["Source", "Treasury", "Legal", "Red Team"]
    if any(term in text for term in ("supply", "logistics", "supplier", "operational", "route")):
        return ["Context", "Source", "Procure", "Expert"]
    return ["Context", "Source", "Expert", "Red Team"]


def _core_label_for_risk_text(text: str) -> str:
    if any(term in text for term in ("sanction", "payment", "finance", "compliance", "legal")):
        return "分析済"
    if any(term in text for term in ("supply", "logistics", "supplier", "operational", "route")):
        return "探索済"
    return "評価済"


def _metric_for_risk_text(text: str, candidate: dict[str, Any], metrics: dict[str, Any]) -> tuple[str, str]:
    if any(term in text for term in ("payment", "sanction", "finance", "compliance")):
        return "exposure", str(metrics.get("payment_exposure_display") or "2,400,000")
    if any(term in text for term in ("contract", "legal")):
        contracts = metrics.get("contracts_reviewed") or 5
        return "reviewed", f"{contracts} contracts"
    if any(term in text for term in ("supply", "logistics", "supplier", "route")):
        affected = metrics.get("affected_candidates") or 3
        return "affected", f"{affected} candidates"
    score = candidate.get("relevance_score")
    return "relevance", str(score if score is not None else "medium")


def _metrics_from_outputs(final_brief: str, evidence_summary: dict[str, Any]) -> dict[str, Any]:
    evidence = evidence_summary.get("evidence") if isinstance(evidence_summary.get("evidence"), list) else []
    payment_exposure = _first_float(r"amount=([0-9]+(?:\.[0-9]+)?)", final_brief)
    contracts_reviewed = _first_int(r"found\s+(\d+)\s+contracts", final_brief)
    supplier_count = _first_int(r"Registered RiskScenario and\s+(\d+)\s+suppliers", final_brief)
    affected_candidates = _first_int(r"affected candidates:\s*(\d+)", final_brief)
    expert_objects = _first_int(r"retrieved\s+(\d+)\s+objects", final_brief)
    similar_cases = _first_int(r"and\s+(\d+)\s+similar cases", final_brief)
    red_team_reviewed = _first_int(r"reviewed\s+(\d+)\s+evidence items", final_brief)
    return {
        "supplier_count": supplier_count,
        "affected_candidates": affected_candidates,
        "evidence_count": len(evidence),
        "payment_exposure": payment_exposure,
        "payment_exposure_display": _number_display(payment_exposure),
        "contracts_reviewed": contracts_reviewed,
        "expert_objects": expert_objects,
        "similar_cases": similar_cases,
        "red_team_reviewed": red_team_reviewed,
        "evidence_domains": sorted({str(item.get("source_domain")) for item in evidence if isinstance(item, dict) and item.get("source_domain")}),
    }


def _evidence_cards(evidence_summary: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = evidence_summary.get("evidence") if isinstance(evidence_summary.get("evidence"), list) else []
    cards = []
    for item in evidence[:8]:
        if not isinstance(item, dict):
            continue
        cards.append(
            {
                "evidence_id": item.get("evidence_id"),
                "title": item.get("source_title") or item.get("source_ref"),
                "domain": item.get("source_domain"),
                "reliability": item.get("reliability"),
                "client_relevance": item.get("client_relevance"),
                "used_by_agents": item.get("used_by_agents") or [],
            }
        )
    return cards


def _decision_summary(decision: dict[str, Any]) -> str:
    owner = decision.get("owner")
    deadline = decision.get("deadline")
    if owner and deadline:
        return f"{owner} owner; {deadline} deadline."
    return str(decision.get("rationale") or "Decision synthesized from scenario evidence and specialist findings.")


def _first_int(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _first_float(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return float(match.group(1)) if match else None


def _number_display(value: float | int | None) -> str | None:
    if value is None:
        return None
    return f"{value:,.0f}"


def _shorten(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "..."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8300)
    args = parser.parse_args(argv)
    settings = Settings.load(Path.cwd())
    uvicorn.run(create_ui_app(settings), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
