from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from risk_agent_platform.config import Settings
from risk_agent_platform.schemas import (
    AgentTaskResult,
    AssumptionItem,
    Confidence,
    DecisionChange,
    DecisionItem,
    RecheckEvaluation,
    RiskEvent,
    ScenarioDelta,
    ScoreChange,
    StrictModel,
    UnknownItem,
    now_utc,
)
from risk_agent_platform.stores.neo4j_store import Neo4jStore
from pydantic import Field


logger = logging.getLogger(__name__)

EVIDENCE_RECHECK_KEYWORDS = ["evidence", "source", "証拠", "情報源"]
SCORE_RECHECK_KEYWORDS = ["score", "risk level", "スコア"]
DECISION_RECHECK_KEYWORDS = ["decision", "意思決定", "decision queue"]


class SnapshotEvidence(StrictModel):
    evidence_id: str
    reliability: Confidence = "medium"
    confidence: Confidence = "medium"


class SnapshotFinding(StrictModel):
    agent_name: str
    risk_score: int | None = None
    review_required: bool = False


class RunSnapshot(StrictModel):
    scenario_id: str
    run_id: str
    trace_id: str
    generated_at: datetime = Field(default_factory=now_utc)
    evidence: list[SnapshotEvidence] = Field(default_factory=list)
    findings: list[SnapshotFinding] = Field(default_factory=list)
    decisions: list[DecisionItem] = Field(default_factory=list)
    assumptions: list[AssumptionItem] = Field(default_factory=list)
    unknowns: list[UnknownItem] = Field(default_factory=list)
    recheck_conditions: list[str] = Field(default_factory=list)


def new_run_id() -> str:
    now = datetime.now(timezone.utc)
    # Nanosecond epoch keeps run_ids strictly sortable even across rapid successive runs
    # where microsecond wall-clock timestamps could otherwise collide.
    return f"{now.strftime('%Y%m%dT%H%M%S')}_{time.time_ns()}_{uuid4().hex[:8]}"


def record_scenario_delta(settings: Settings, event: RiskEvent, result: AgentTaskResult) -> ScenarioDelta | None:
    """Snapshot a completed scenario run and record its delta against the previous run.

    Never raises: any failure is logged and, where possible, a degraded ScenarioDelta is written
    instead so the caller's analysis result is unaffected.
    """
    if result.status != "completed":
        return None
    run_id = new_run_id()
    try:
        current = _build_snapshot(settings, event, result, run_id)
        previous = _load_latest_snapshot(settings, event.scenario_id, exclude_run_id=run_id)
        delta = compute_delta(previous, current)
        summary_text = render_delta_summary(event, delta)
        _write_snapshot(settings, current)
        _write_delta(settings, delta)
        _write_delta_summary(settings, event.scenario_id, run_id, summary_text)
    except Exception as exc:  # noqa: BLE001 - delta recording must never fail the scenario
        logger.warning("scenario delta recording failed for %s: %s", event.scenario_id, exc)
        try:
            delta = ScenarioDelta(
                scenario_id=event.scenario_id,
                run_id=run_id,
                previous_run_id=None,
                degraded=True,
                degraded_reason=str(exc),
            )
            _write_delta(settings, delta)
            _write_delta_summary(settings, event.scenario_id, run_id, render_delta_summary(event, delta))
        except Exception as inner_exc:  # noqa: BLE001
            logger.warning("failed to write degraded scenario delta for %s: %s", event.scenario_id, inner_exc)
            return None
    _register_delta_in_neo4j(settings, delta)
    return delta


def load_previous_recheck_conditions(settings: Settings, scenario_id: str) -> list[str]:
    try:
        snapshot = _load_latest_snapshot(settings, scenario_id, exclude_run_id=None)
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to load previous recheck conditions for %s: %s", scenario_id, exc)
        return []
    return list(snapshot.recheck_conditions) if snapshot else []


def compute_delta(previous: RunSnapshot | None, current: RunSnapshot, *, now: datetime | None = None) -> ScenarioDelta:
    now = now or now_utc()
    if previous is None:
        return ScenarioDelta(
            scenario_id=current.scenario_id,
            run_id=current.run_id,
            previous_run_id=None,
            baseline=True,
        )

    evidence_added = sorted({item.evidence_id for item in current.evidence} - {item.evidence_id for item in previous.evidence})
    evidence_removed = sorted({item.evidence_id for item in previous.evidence} - {item.evidence_id for item in current.evidence})
    score_changes = _diff_scores(previous.findings, current.findings)
    decision_changes = _diff_decisions(previous.decisions, current.decisions)
    assumption_expirations = _diff_assumption_expirations(previous.assumptions, current.assumptions, now=now)
    unknown_resolutions = _diff_unknown_resolutions(previous.unknowns, current.unknowns)

    delta = ScenarioDelta(
        scenario_id=current.scenario_id,
        run_id=current.run_id,
        previous_run_id=previous.run_id,
        baseline=False,
        evidence_added=evidence_added,
        evidence_removed=evidence_removed,
        score_changes=score_changes,
        decision_changes=decision_changes,
        assumption_expirations=assumption_expirations,
        unknown_resolutions=unknown_resolutions,
    )
    recheck_triggers_fired = evaluate_recheck_conditions(previous.recheck_conditions, delta)
    return delta.model_copy(update={"recheck_triggers_fired": recheck_triggers_fired})


def evaluate_recheck_conditions(conditions: list[str], delta: ScenarioDelta) -> list[RecheckEvaluation]:
    evaluations: list[RecheckEvaluation] = []
    for condition in conditions:
        lowered = condition.lower()
        if any(keyword in lowered or keyword in condition for keyword in EVIDENCE_RECHECK_KEYWORDS):
            fired = bool(delta.evidence_added)
            evaluations.append(
                RecheckEvaluation(
                    condition=condition,
                    status="fired" if fired else "not_fired",
                    rationale="new evidence was recorded since the previous run" if fired else "no new evidence since the previous run",
                )
            )
        elif any(keyword in lowered or keyword in condition for keyword in SCORE_RECHECK_KEYWORDS):
            fired = bool(delta.score_changes)
            evaluations.append(
                RecheckEvaluation(
                    condition=condition,
                    status="fired" if fired else "not_fired",
                    rationale="agent risk scores changed since the previous run" if fired else "no risk score changes since the previous run",
                )
            )
        elif any(keyword in lowered or keyword in condition for keyword in DECISION_RECHECK_KEYWORDS):
            fired = bool(delta.decision_changes)
            evaluations.append(
                RecheckEvaluation(
                    condition=condition,
                    status="fired" if fired else "not_fired",
                    rationale="decisions were added, modified, or removed since the previous run" if fired else "no decision changes since the previous run",
                )
            )
        else:
            evaluations.append(
                RecheckEvaluation(condition=condition, status="not_evaluable", rationale="no deterministic signal mapping")
            )
    return evaluations


def render_delta_summary(event: RiskEvent, delta: ScenarioDelta) -> str:
    lines = [
        f"# Scenario Delta Summary: {event.title}",
        "",
        f"- Scenario ID: `{delta.scenario_id}`",
        f"- Run ID: `{delta.run_id}`",
        f"- Previous Run ID: `{delta.previous_run_id or 'None'}`",
        f"- Baseline: `{delta.baseline}`",
        f"- Generated At: `{delta.generated_at.isoformat()}`",
    ]
    if delta.degraded:
        lines.extend(["", f"## Degraded: {delta.degraded_reason or 'unknown reason'}"])
    if delta.baseline:
        lines.extend(
            [
                "",
                "## Summary",
                "This is the first recorded run for this scenario; no prior run exists for comparison.",
            ]
        )
        return "\n".join(lines) + "\n"

    has_changes = any(
        [
            delta.evidence_added,
            delta.evidence_removed,
            delta.score_changes,
            delta.decision_changes,
            delta.assumption_expirations,
            delta.unknown_resolutions,
        ]
    )
    lines.extend(["", "## Summary"])
    if not has_changes:
        lines.append("No changes detected since the previous run.")
    else:
        lines.append(
            f"{len(delta.evidence_added)} evidence added, {len(delta.evidence_removed)} evidence removed, "
            f"{len(delta.score_changes)} score changes, {len(delta.decision_changes)} decision changes, "
            f"{len(delta.assumption_expirations)} assumption expirations, {len(delta.unknown_resolutions)} unknown resolutions."
        )
    lines.extend(["", "## Evidence Added"])
    lines.extend([f"- `{item}`" for item in delta.evidence_added] or ["- None"])
    lines.extend(["", "## Evidence Removed"])
    lines.extend([f"- `{item}`" for item in delta.evidence_removed] or ["- None"])
    lines.extend(["", "## Score Changes"])
    lines.extend(
        [f"- {change.agent_name}: {change.previous_score} -> {change.current_score}" for change in delta.score_changes]
        or ["- None"]
    )
    lines.extend(["", "## Decision Changes"])
    decision_lines = []
    for change in delta.decision_changes:
        suffix = f" (changed: {', '.join(change.changed_fields)})" if change.changed_fields else ""
        decision_lines.append(f"- [{change.change_type}] `{change.decision_id}` {change.decision}{suffix}")
    lines.extend(decision_lines or ["- None"])
    lines.extend(["", "## Assumption Expirations"])
    lines.extend([f"- {item}" for item in delta.assumption_expirations] or ["- None"])
    lines.extend(["", "## Unknown Resolutions"])
    lines.extend([f"- {item}" for item in delta.unknown_resolutions] or ["- None"])
    lines.extend(["", "## Recheck Conditions Evaluated"])
    if delta.recheck_triggers_fired:
        for evaluation in delta.recheck_triggers_fired:
            lines.append(f"- [{evaluation.status}] {evaluation.condition} - {evaluation.rationale}")
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def _diff_scores(previous: list[SnapshotFinding], current: list[SnapshotFinding]) -> list[ScoreChange]:
    prev_scores = {finding.agent_name: finding.risk_score for finding in previous if finding.risk_score is not None}
    curr_scores = {finding.agent_name: finding.risk_score for finding in current if finding.risk_score is not None}
    changes = []
    for agent_name in sorted(set(prev_scores) & set(curr_scores)):
        if prev_scores[agent_name] != curr_scores[agent_name]:
            changes.append(
                ScoreChange(agent_name=agent_name, previous_score=prev_scores[agent_name], current_score=curr_scores[agent_name])
            )
    return changes


_DECISION_CHANGED_FIELDS = ("owner", "deadline", "priority", "review_required", "rationale")


def _decision_identity(decision: DecisionItem) -> str:
    return decision.decision_id or f"text:{decision.decision}"


def _diff_decisions(previous: list[DecisionItem], current: list[DecisionItem]) -> list[DecisionChange]:
    prev_by_id = {_decision_identity(item): item for item in previous}
    curr_by_id = {_decision_identity(item): item for item in current}
    changes: list[DecisionChange] = []
    for identity, decision in curr_by_id.items():
        if identity not in prev_by_id:
            changes.append(DecisionChange(change_type="added", decision_id=identity, decision=decision.decision))
    for identity, decision in prev_by_id.items():
        if identity not in curr_by_id:
            changes.append(DecisionChange(change_type="removed", decision_id=identity, decision=decision.decision))
    for identity in sorted(set(prev_by_id) & set(curr_by_id)):
        prev_decision = prev_by_id[identity]
        curr_decision = curr_by_id[identity]
        changed_fields = [
            field for field in _DECISION_CHANGED_FIELDS if getattr(prev_decision, field) != getattr(curr_decision, field)
        ]
        if changed_fields:
            changes.append(
                DecisionChange(change_type="modified", decision_id=identity, decision=curr_decision.decision, changed_fields=changed_fields)
            )
    return changes


def _diff_assumption_expirations(previous: list[AssumptionItem], current: list[AssumptionItem], *, now: datetime) -> list[str]:
    expirations: list[str] = []
    current_ids = {item.id for item in current}
    for item in current:
        if item.expires_at is not None and item.expires_at < now and item.description not in expirations:
            expirations.append(item.description)
    for item in previous:
        if item.id not in current_ids and item.expires_at is not None and item.description not in expirations:
            expirations.append(item.description)
    return expirations


def _diff_unknown_resolutions(previous: list[UnknownItem], current: list[UnknownItem]) -> list[str]:
    current_ids = {item.id for item in current}
    resolved: list[str] = []
    for item in previous:
        if item.id not in current_ids and item.description not in resolved:
            resolved.append(item.description)
    return resolved


def _build_snapshot(settings: Settings, event: RiskEvent, result: AgentTaskResult, run_id: str) -> RunSnapshot:
    output_dir = settings.project_root / "outputs" / event.scenario_id
    metadata = (result.finding.metadata if result.finding else {}) or {}
    findings_meta = metadata.get("findings") or []
    analysis_plan = metadata.get("analysis_plan") or {}
    recheck_conditions = _unique_strings(analysis_plan.get("recheck_conditions") if isinstance(analysis_plan, dict) else None)

    assumption_descriptions: list[str] = []
    unknown_descriptions: list[str] = []
    snapshot_findings: list[SnapshotFinding] = []
    for finding in findings_meta:
        if not isinstance(finding, dict):
            continue
        snapshot_findings.append(
            SnapshotFinding(
                agent_name=str(finding.get("agent_name") or ""),
                risk_score=finding.get("risk_score"),
                review_required=bool(finding.get("review_required")),
            )
        )
        for description in finding.get("assumptions") or []:
            text = str(description)
            if text not in assumption_descriptions:
                assumption_descriptions.append(text)
        for description in finding.get("unknowns") or []:
            text = str(description)
            if text not in unknown_descriptions:
                unknown_descriptions.append(text)
        finding_metadata = finding.get("metadata") or {}
        issue_exploration = finding_metadata.get("issue_exploration") if isinstance(finding_metadata, dict) else None
        if isinstance(issue_exploration, dict):
            for condition in issue_exploration.get("recheck_conditions") or []:
                text = str(condition)
                if text not in recheck_conditions:
                    recheck_conditions.append(text)

    evidence_data = _read_json(output_dir / "evidence_summary.json").get("evidence") or []
    evidence = [
        SnapshotEvidence(
            evidence_id=str(item["evidence_id"]),
            reliability=item.get("reliability") or "medium",
            confidence=item.get("confidence") or "medium",
        )
        for item in evidence_data
        if isinstance(item, dict) and item.get("evidence_id")
    ]

    decisions_data = _read_json(output_dir / "decision_queue.json").get("decisions") or []
    decisions = [DecisionItem.model_validate(item) for item in decisions_data if isinstance(item, dict)]

    assumptions = [
        AssumptionItem(
            id=_stable_id(event.scenario_id, "assumption", description),
            scenario_id=event.scenario_id,
            description=description,
        )
        for description in assumption_descriptions
    ]
    unknowns = [
        UnknownItem(
            id=_stable_id(event.scenario_id, "unknown", description),
            scenario_id=event.scenario_id,
            description=description,
        )
        for description in unknown_descriptions
    ]

    return RunSnapshot(
        scenario_id=event.scenario_id,
        run_id=run_id,
        trace_id=result.trace_id,
        evidence=evidence,
        findings=snapshot_findings,
        decisions=decisions,
        assumptions=assumptions,
        unknowns=unknowns,
        recheck_conditions=recheck_conditions,
    )


def _stable_id(scenario_id: str, kind: str, description: str) -> str:
    digest = hashlib.sha256(description.encode("utf-8")).hexdigest()[:12]
    return f"{scenario_id}_{kind}_{digest}"


def _unique_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for entry in value:
        text = str(entry)
        if text not in items:
            items.append(text)
    return items


def _runs_dir(settings: Settings, scenario_id: str) -> Path:
    return settings.project_root / "outputs" / scenario_id / "runs"


def _deltas_dir(settings: Settings, scenario_id: str) -> Path:
    return settings.project_root / "outputs" / scenario_id / "deltas"


def _load_latest_snapshot(settings: Settings, scenario_id: str, *, exclude_run_id: str | None = None) -> RunSnapshot | None:
    runs_dir = _runs_dir(settings, scenario_id)
    if not runs_dir.is_dir():
        return None
    candidates = sorted(
        (path for path in runs_dir.glob("*.json") if path.stem != exclude_run_id),
        key=lambda path: path.stem,
    )
    if not candidates:
        return None
    latest = candidates[-1]
    return RunSnapshot.model_validate_json(latest.read_text(encoding="utf-8"))


def _write_snapshot(settings: Settings, snapshot: RunSnapshot) -> None:
    runs_dir = _runs_dir(settings, snapshot.scenario_id)
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{snapshot.run_id}.json").write_text(
        json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _write_delta(settings: Settings, delta: ScenarioDelta) -> None:
    deltas_dir = _deltas_dir(settings, delta.scenario_id)
    deltas_dir.mkdir(parents=True, exist_ok=True)
    (deltas_dir / f"{delta.run_id}.json").write_text(
        json.dumps(delta.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _write_delta_summary(settings: Settings, scenario_id: str, run_id: str, text: str) -> None:
    deltas_dir = _deltas_dir(settings, scenario_id)
    deltas_dir.mkdir(parents=True, exist_ok=True)
    (deltas_dir / f"{run_id}_summary.md").write_text(text, encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _register_delta_in_neo4j(settings: Settings, delta: ScenarioDelta) -> None:
    try:
        store = Neo4jStore(settings)
        try:
            node_id = f"{delta.scenario_id}:{delta.run_id}"
            store.upsert_asset(
                "ScenarioDelta",
                node_id,
                {
                    "scenario_id": delta.scenario_id,
                    "run_id": delta.run_id,
                    "previous_run_id": delta.previous_run_id,
                    "baseline": delta.baseline,
                    "evidence_added_count": len(delta.evidence_added),
                    "evidence_removed_count": len(delta.evidence_removed),
                    "score_change_count": len(delta.score_changes),
                    "decision_change_count": len(delta.decision_changes),
                    "degraded": delta.degraded,
                    "generated_at": delta.generated_at.isoformat(),
                    "confidence_level": "derived",
                    "source_type": "derived",
                },
            )
            store.upsert_relation(delta.scenario_id, node_id, "HAS_DELTA", {"confidence_level": "derived"})
        finally:
            store.close()
    except Exception as exc:  # noqa: BLE001 - Neo4j registration is strictly best-effort
        logger.warning("neo4j delta registration failed for %s run %s: %s", delta.scenario_id, delta.run_id, exc)
