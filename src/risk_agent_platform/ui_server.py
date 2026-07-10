from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from risk_agent_platform.api.app import create_app as create_platform_app
from risk_agent_platform.api.jobs import JobRecord
from risk_agent_platform.config import Settings
from risk_agent_platform.decision_log import DecisionLogStore, ScenarioNotFoundError


DEFAULT_SCENARIO_ID = "scenario_discovered_fujifilm_dummy_iran_war_escalation_affecting_fujifilm_executive_management_disc_"


def create_ui_app(
    settings: Settings | None = None,
    *,
    job_db_path: Path | None = None,
    max_workers: int = 2,
) -> FastAPI:
    resolved_settings = settings or Settings.load(Path.cwd())
    app = create_platform_app(resolved_settings, job_db_path=job_db_path, max_workers=max_workers)
    app.title = "Risk Intelligence Decision Cockpit"

    @app.get("/api/ui/state")
    def ui_state(scenario_id: str | None = None) -> dict[str, Any]:
        return build_ui_state(
            resolved_settings,
            scenario_id=scenario_id,
            jobs=app.state.store.list_jobs(),
        )

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


def build_ui_state(
    settings: Settings,
    *,
    scenario_id: str | None = None,
    jobs: list[JobRecord] | None = None,
) -> dict[str, Any]:
    selected_scenario_id = scenario_id or os.getenv("UI_SCENARIO_ID") or _latest_scenario_id(settings) or DEFAULT_SCENARIO_ID
    scenario_dir = _scenario_output_dir(settings, selected_scenario_id)
    if not scenario_dir.exists():
        raise HTTPException(status_code=404, detail=f"Scenario output not found: {selected_scenario_id}")

    discovery = _read_json(settings.project_root / "outputs" / "risk_discovery" / f"{selected_scenario_id}.json")
    trace_metadata = _read_json(scenario_dir / "trace_metadata.json")
    decision_queue = _read_json(scenario_dir / "decision_queue.json")
    evidence_summary = _read_json(scenario_dir / "evidence_summary.json")
    assumptions_and_unknowns = _read_json(scenario_dir / "assumptions_and_unknowns.json")
    final_brief = _read_text(scenario_dir / "final_brief.md")

    metrics = _metrics_from_outputs(final_brief, evidence_summary)
    raw_decisions = [item for item in decision_queue.get("decisions", []) if isinstance(item, dict)]
    raw_decisions.sort(key=lambda item: int(item.get("priority") or 999))
    decision_log_store = DecisionLogStore(settings)
    try:
        states = decision_log_store.all_current_states(selected_scenario_id)
    except ScenarioNotFoundError:
        states = {}
    actions = decision_log_store.list_actions(selected_scenario_id)
    decisions = [_decision_with_state(item, states, actions) for item in raw_decisions]
    decision = next(
        (item for item in decisions if item.get("state") not in {"approved", "rejected"}),
        _first_item(decisions),
    )
    matching_job = _latest_job_for_scenario(jobs or [], selected_scenario_id)
    event_payload = _event_payload_from_discovery(discovery, selected_scenario_id) or _event_payload_from_job(
        matching_job,
        selected_scenario_id,
    )
    event = _event_from_discovery(discovery, selected_scenario_id, fallback_event=event_payload)
    scenarios = _scenario_cards(discovery, metrics)
    evidence = _evidence_cards(
        evidence_summary,
        linked_ids={str(item) for item in decision.get("evidence_ids", []) if item},
    )
    risk_assessment = _risk_assessment_summary(assumptions_and_unknowns)
    assumptions, unknowns = _insight_lists(assumptions_and_unknowns)
    job = _job_summary(matching_job, trace_metadata, scenario_dir)
    scenario_queue = _scenario_queue(settings, selected_scenario_id, decision_log_store)
    activity = _activity_items(actions, job, scenario_dir, decisions)
    contradiction_count = sum(len(item.get("contradicts") or []) for item in evidence)

    return {
        "source": "backend",
        "loaded_at": datetime.now(timezone.utc).isoformat(),
        "scenario_id": selected_scenario_id,
        "trace_id": trace_metadata.get("trace_id"),
        "scenario_queue": scenario_queue,
        "job": job,
        "event": event,
        "event_payload": event_payload,
        "can_rerun": event_payload is not None,
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
        "decisions": decisions,
        "decision_states": states,
        "risk_assessment": risk_assessment,
        "assumptions": assumptions,
        "unknowns": unknowns,
        "contradiction_count": contradiction_count,
        "evidence": evidence,
        "activity": activity,
        "backend": {
            "output_dir": str(scenario_dir),
            "discovery_output": str(settings.project_root / "outputs" / "risk_discovery" / f"{selected_scenario_id}.json"),
        },
    }


def _decision_with_state(
    decision: dict[str, Any],
    states: dict[str, str],
    actions: list[Any],
) -> dict[str, Any]:
    enriched = dict(decision)
    decision_id = str(decision.get("decision_id") or "")
    enriched["state"] = states.get(decision_id, "pending")
    effective_owner = decision.get("owner")
    for action in actions:
        if action.decision_id == decision_id and action.action == "reassign" and action.new_owner:
            effective_owner = action.new_owner
    enriched["effective_owner"] = effective_owner
    enriched["action_count"] = sum(1 for action in actions if action.decision_id == decision_id)
    enriched["allowed_actions"] = _allowed_actions(str(enriched["state"])) if decision_id else []
    latest_action = next((action for action in reversed(actions) if action.decision_id == decision_id), None)
    enriched["latest_action"] = latest_action.model_dump(mode="json") if latest_action else None
    return enriched


def _allowed_actions(state: str) -> list[str]:
    return {
        "pending": ["approve", "reject", "hold", "request_recheck", "reassign"],
        "held": ["approve", "reject", "request_recheck", "reassign"],
        "recheck_requested": ["approve", "reject", "hold", "reassign"],
        "approved": [],
        "rejected": [],
    }.get(state, [])


def _scenario_queue(
    settings: Settings,
    selected_scenario_id: str,
    decision_log_store: DecisionLogStore,
) -> list[dict[str, Any]]:
    output_root = settings.project_root / "outputs"
    if not output_root.exists():
        return []
    paths = [
        path
        for path in output_root.iterdir()
        if path.is_dir() and (path / "decision_queue.json").exists()
    ]
    paths.sort(key=lambda path: (path.name != selected_scenario_id, -path.stat().st_mtime))
    cards: list[dict[str, Any]] = []
    for path in paths:
        queue = _read_json(path / "decision_queue.json")
        raw_decisions = [item for item in queue.get("decisions", []) if isinstance(item, dict)]
        raw_decisions.sort(key=lambda item: int(item.get("priority") or 999))
        try:
            states = decision_log_store.all_current_states(path.name)
        except ScenarioNotFoundError:
            states = {}
        actions = decision_log_store.list_actions(path.name)
        decisions = [_decision_with_state(item, states, actions) for item in raw_decisions]
        decision = next(
            (item for item in decisions if item.get("state") not in {"approved", "rejected"}),
            _first_item(decisions),
        )
        state = str(decision.get("state") or "pending")
        title = _brief_title(_read_text(path / "final_brief.md")) or str(decision.get("decision") or path.name)
        cards.append(
            {
                "scenario_id": path.name,
                "title": _shorten(title, 86),
                "owner": decision.get("effective_owner") or decision.get("owner"),
                "deadline": decision.get("deadline"),
                "priority": decision.get("priority"),
                "state": state,
                "review_required": bool(decision.get("review_required")),
                "selected": path.name == selected_scenario_id,
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return cards


def _brief_title(final_brief: str) -> str:
    for line in final_brief.splitlines():
        if line.startswith("# "):
            return line[2:].removeprefix("Executive Brief:").strip()
    return ""


def _latest_job_for_scenario(jobs: list[JobRecord], scenario_id: str) -> JobRecord | None:
    return next((job for job in jobs if _job_matches_scenario(job, scenario_id)), None)


def _job_matches_scenario(job: JobRecord, scenario_id: str) -> bool:
    result = job.result_summary or {}
    if result.get("scenario_id") == scenario_id or scenario_id in (result.get("scenario_ids") or []):
        return True
    event = job.request_payload.get("event")
    return isinstance(event, dict) and event.get("scenario_id") == scenario_id


def _job_summary(
    job: JobRecord | None,
    trace_metadata: dict[str, Any],
    scenario_dir: Path,
) -> dict[str, Any]:
    if job is None:
        return {
            "job_id": None,
            "status": "completed",
            "trace_id": trace_metadata.get("trace_id"),
            "created_at": datetime.fromtimestamp(scenario_dir.stat().st_mtime, tz=timezone.utc).isoformat(),
            "started_at": None,
            "finished_at": None,
            "error": None,
        }
    return {
        "job_id": job.job_id,
        "status": job.status,
        "trace_id": job.trace_id,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error": job.error_message,
    }


def _activity_items(
    actions: list[Any],
    job: dict[str, Any],
    scenario_dir: Path,
    decisions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    labels = {
        "approve": "承認",
        "reject": "却下",
        "hold": "保留",
        "request_recheck": "再評価を依頼",
        "reassign": "担当変更",
    }
    decision_titles = {
        str(decision.get("decision_id")): str(decision.get("decision") or decision.get("decision_id"))
        for decision in decisions
        if decision.get("decision_id")
    }
    items = [
        {
            "kind": "decision",
            "label": labels.get(action.action, action.action),
            "detail": action.reason or action.new_state,
            "actor": action.actor,
            "reason": action.reason or None,
            "new_owner": action.new_owner,
            "new_state": action.new_state,
            "decision_id": action.decision_id,
            "decision_title": decision_titles.get(action.decision_id) or action.decision_id,
            "created_at": action.created_at.isoformat(),
        }
        for action in reversed(actions)
    ]
    job_status = {
        "submitted": "分析を受付",
        "working": "分析を実行中",
        "completed": "分析完了・レビュー待ち",
        "failed": "分析に失敗",
    }.get(str(job.get("status")), str(job.get("status") or "分析状態不明"))
    items.append(
        {
            "kind": "job",
            "label": job_status,
            "detail": job.get("error") or "Risk Intelligence Agent",
            "actor": "Risk Intelligence Agent",
            "reason": None,
            "new_owner": None,
            "new_state": None,
            "decision_id": None,
            "decision_title": None,
            "created_at": job.get("finished_at")
            or job.get("started_at")
            or job.get("created_at")
            or datetime.fromtimestamp(scenario_dir.stat().st_mtime, tz=timezone.utc).isoformat(),
        }
    )
    return items


def _event_payload_from_discovery(discovery: dict[str, Any], scenario_id: str) -> dict[str, Any] | None:
    candidates: list[Any] = [discovery.get("selected_event"), *(discovery.get("selected_events") or [])]
    for candidate in candidates:
        if not isinstance(candidate, dict) or candidate.get("scenario_id") != scenario_id:
            continue
        required = {"scenario_id", "client_id", "title", "risk_type", "description", "event_date"}
        if required.issubset(candidate):
            return candidate
    return None


def _event_payload_from_job(job: JobRecord | None, scenario_id: str) -> dict[str, Any] | None:
    if job is None:
        return None
    event = job.request_payload.get("event")
    if not isinstance(event, dict) or event.get("scenario_id") != scenario_id:
        return None
    required = {"scenario_id", "client_id", "title", "risk_type", "description", "event_date"}
    return dict(event) if required.issubset(event) else None


def _risk_assessment_summary(assumptions_and_unknowns: dict[str, Any]) -> dict[str, Any]:
    findings = assumptions_and_unknowns.get("findings")
    items = findings if isinstance(findings, list) else []
    preferred = next(
        (
            item
            for item in items
            if isinstance(item, dict)
            and item.get("agent_name") == "treasury-risk-agent"
            and isinstance(item.get("risk_score"), int)
        ),
        None,
    )
    scored = preferred or next(
        (item for item in items if isinstance(item, dict) and isinstance(item.get("risk_score"), int)),
        {},
    )
    return {
        "risk_score": scored.get("risk_score"),
        "confidence": scored.get("confidence"),
        "source_agent": scored.get("agent_name"),
    }


def _insight_lists(assumptions_and_unknowns: dict[str, Any]) -> tuple[list[str], list[str]]:
    findings = assumptions_and_unknowns.get("findings")
    items = findings if isinstance(findings, list) else []
    assumptions: list[str] = []
    unknowns: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        for value, target in ((item.get("assumptions"), assumptions), (item.get("unknowns"), unknowns)):
            if not isinstance(value, list):
                continue
            for text in value:
                normalized = str(text).strip()
                if normalized and normalized not in target:
                    target.append(normalized)
    return assumptions[:8], unknowns[:8]


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


def _event_from_discovery(
    discovery: dict[str, Any],
    scenario_id: str,
    *,
    fallback_event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = discovery.get("request") if isinstance(discovery.get("request"), dict) else {}
    selected_event = discovery.get("selected_event") if isinstance(discovery.get("selected_event"), dict) else {}
    fallback = fallback_event or {}
    scope = request.get("scope") if isinstance(request.get("scope"), dict) else {}
    title = request.get("event_title") or selected_event.get("title") or fallback.get("title") or scenario_id
    description = request.get("event_description") or selected_event.get("description") or fallback.get("description") or ""
    return {
        "title": str(title),
        "summary": _shorten(str(description), 168),
        "client_id": scope.get("client_id") or selected_event.get("client_id") or fallback.get("client_id"),
        "scope_name": scope.get("scope_name") or scope.get("scope_text"),
        "countries": request.get("countries") or selected_event.get("countries") or fallback.get("countries") or [],
        "risk_type": selected_event.get("risk_type") or fallback.get("risk_type"),
        "risk_themes": selected_event.get("risk_themes") or fallback.get("risk_themes") or [],
        "affected_categories": selected_event.get("affected_categories") or fallback.get("affected_categories") or [],
        "urgency": selected_event.get("urgency") or fallback.get("urgency"),
    }


def _scenario_cards(discovery: dict[str, Any], metrics: dict[str, Any]) -> list[dict[str, Any]]:
    raw_candidates = discovery.get("selected_candidates")
    candidates = raw_candidates if isinstance(raw_candidates, list) else []
    cards: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates[:3], start=1):
        if not isinstance(candidate, dict):
            continue
        cards.append(_scenario_card(index, candidate, metrics))
    return cards


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
        return "exposure", str(metrics.get("payment_exposure_display") or "—")
    if any(term in text for term in ("contract", "legal")):
        contracts = metrics.get("contracts_reviewed")
        return "reviewed", f"{contracts} contracts" if contracts is not None else "—"
    if any(term in text for term in ("supply", "logistics", "supplier", "route")):
        affected = metrics.get("affected_candidates")
        return "affected", f"{affected} candidates" if affected is not None else "—"
    score = candidate.get("relevance_score")
    return "relevance", str(score if score is not None else "—")


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


def _evidence_cards(
    evidence_summary: dict[str, Any],
    *,
    linked_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    evidence = evidence_summary.get("evidence") if isinstance(evidence_summary.get("evidence"), list) else []
    if linked_ids is not None:
        evidence = [
            item
            for item in evidence
            if isinstance(item, dict) and str(item.get("evidence_id") or "") in linked_ids
        ]
    cards = []
    for item in evidence[:8]:
        if not isinstance(item, dict):
            continue
        cards.append(
            {
                "evidence_id": item.get("evidence_id"),
                "title": item.get("source_title") or item.get("source_ref"),
                "domain": item.get("source_domain"),
                "source_url": item.get("source_url"),
                "summary": _shorten(str(item.get("summary") or ""), 240),
                "reliability": item.get("reliability"),
                "client_relevance": item.get("client_relevance"),
                "confidence": item.get("confidence"),
                "supports": item.get("supports") or [],
                "contradicts": item.get("contradicts") or [],
                "used_by_agents": item.get("used_by_agents") or [],
                "retrieved_at": item.get("retrieved_at"),
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
