from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from risk_agent_platform.config import Settings
from risk_agent_platform.experimental_discovery import MultiLensDiscoveryExperimentResult, MultiLensRiskDiscoveryExperiment, write_experiment_outputs
from risk_agent_platform.run_discovery import _run_analysis_records, _write_portfolio_summary
from risk_agent_platform.schemas import DiscoveredRisk, RiskDiscoveryRequest, RiskDiscoveryResult, RiskDiscoveryScope, RiskEvent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-title")
    parser.add_argument("--event-description", default="")
    parser.add_argument("--client-id")
    parser.add_argument("--scope-text")
    parser.add_argument("--scope-type", default="company")
    parser.add_argument("--scope-name")
    parser.add_argument("--department")
    parser.add_argument("--industry")
    parser.add_argument("--region")
    parser.add_argument("--site-id")
    parser.add_argument("--country", action="append", default=[])
    parser.add_argument("--event-date", type=date.fromisoformat)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--analyze-existing-output",
        type=Path,
        help="Skip Discovery and run downstream Orchestrator/Domain/Decision analysis for aggregated scenarios in an experiment JSON.",
    )
    parser.add_argument("--run-analysis", action="store_true")
    parser.add_argument("--analysis-concurrency", type=int, default=3)
    parser.add_argument(
        "--reuse-completed-analysis",
        action="store_true",
        help="Reuse existing completed scenario output directories and only run missing downstream analyses.",
    )
    parser.add_argument("--embedded-services", action="store_true")
    args = parser.parse_args(argv)

    settings = Settings.load(Path.cwd())
    if args.analyze_existing_output:
        result = _load_experiment_result(args.analyze_existing_output)
        return _run_experiment_analysis(
            settings,
            result,
            embedded_services=args.embedded_services,
            concurrency=args.analysis_concurrency,
            reuse_completed=args.reuse_completed_analysis,
        )
    if not args.event_title or not args.client_id:
        parser.error("--event-title and --client-id are required unless --analyze-existing-output is used.")

    request = RiskDiscoveryRequest(
        event_title=args.event_title,
        event_description=args.event_description,
        countries=args.country,
        event_date=args.event_date,
        max_risks=10,
        scope=RiskDiscoveryScope(
            client_id=args.client_id,
            scope_text=args.scope_text,
            scope_type=args.scope_type,
            scope_name=args.scope_name,
            department=args.department,
            region=args.region,
            site_id=args.site_id,
            metadata={"industry": args.industry} if args.industry else {},
        ),
    )
    result = MultiLensRiskDiscoveryExperiment(settings, embedded_mcp=args.embedded_services).discover(request)
    paths = write_experiment_outputs(settings, result, args.output)
    print("experimental_discovery_status=completed")
    print(f"agent_count={result.metadata.get('agent_count')}")
    print(f"candidate_count={result.metadata.get('candidate_count')}")
    print(f"aggregated_scenario_count={result.metadata.get('aggregated_scenario_count')}")
    print(f"web_search_count={result.metadata.get('web_search_count')}")
    print(f"web_extraction_count={result.metadata.get('web_extraction_count')}")
    print(f"execution_mode={result.metadata.get('execution_mode')}")
    aggregation = result.metadata.get("aggregation") or {}
    print(f"aggregation_generation={aggregation.get('generation')}")
    print(f"aggregation_response_format={aggregation.get('response_format')}")
    for lens in result.lens_results:
        print(
            "lens_result="
            f"{lens.discovery_lens},candidates={len(lens.candidates)},"
            f"searches={len(lens.web_searches)},extractions={len(lens.web_extractions)}"
        )
    print(f"experiment_output={paths['json']}")
    print(f"experiment_markdown={paths['markdown']}")
    if args.run_analysis:
        return _run_experiment_analysis(
            settings,
            result,
            embedded_services=args.embedded_services,
            concurrency=args.analysis_concurrency,
            reuse_completed=args.reuse_completed_analysis,
        )
    return 0


def _load_experiment_result(path: Path) -> MultiLensDiscoveryExperimentResult:
    return MultiLensDiscoveryExperimentResult.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _run_experiment_analysis(
    settings: Settings,
    result: MultiLensDiscoveryExperimentResult,
    *,
    embedded_services: bool,
    concurrency: int,
    reuse_completed: bool = False,
) -> int:
    discovery_result = _experiment_result_to_discovery_result(result)
    if not discovery_result.selected_events:
        print("analysis_status=skipped:no_aggregated_scenarios")
        return 1
    existing_records: list[dict[str, Any]] = []
    events_to_run = discovery_result.selected_events
    if reuse_completed:
        existing_records, events_to_run = _split_existing_analysis_records(settings, discovery_result.selected_events)
    new_records = _run_analysis_records(
        settings,
        events_to_run,
        embedded_services=embedded_services,
        concurrency=concurrency,
    ) if events_to_run else []
    records_by_id = {record["scenario_id"]: record for record in [*existing_records, *new_records]}
    records = [records_by_id[event.scenario_id] for event in discovery_result.selected_events if event.scenario_id in records_by_id]
    paths = _write_portfolio_summary(settings, discovery_result, records)
    completed = all(record["status"] == "completed" for record in records)
    print("experiment_analysis_status=" + ("completed" if completed else "failed"))
    print(f"experiment_analysis_count={len(records)}")
    print(f"experiment_analysis_reused_count={len(existing_records)}")
    print(f"experiment_analysis_rerun_count={len(new_records)}")
    print(f"experiment_analysis_concurrency={max(1, min(int(concurrency or 1), len(records) or 1))}")
    for idx, record in enumerate(records, start=1):
        print(f"experiment_analysis_{idx}_scenario_id={record['scenario_id']}")
        print(f"experiment_analysis_{idx}_status={record['status']}")
        print(f"experiment_analysis_{idx}_trace_id={record['trace_id']}")
        print(f"experiment_analysis_{idx}_output_dir={record['output_dir']}")
        if record.get("error"):
            error = record["error"]
            print(f"experiment_analysis_{idx}_error={error.get('code')}: {error.get('message')}")
    print(f"experiment_portfolio_summary_json={paths['json']}")
    print(f"experiment_portfolio_summary_md={paths['markdown']}")
    return 0 if completed else 1


def _split_existing_analysis_records(
    settings: Settings,
    events: list[RiskEvent],
) -> tuple[list[dict[str, Any]], list[RiskEvent]]:
    existing_records: list[dict[str, Any]] = []
    missing_events: list[RiskEvent] = []
    for event in events:
        existing = _existing_completed_analysis_record(settings, event)
        if existing:
            existing_records.append(existing)
        else:
            missing_events.append(event)
    return existing_records, missing_events


def _existing_completed_analysis_record(settings: Settings, event: RiskEvent) -> dict[str, Any] | None:
    output_dir = settings.project_root / "outputs" / event.scenario_id
    decision_path = output_dir / "decision_queue.json"
    trace_path = output_dir / "trace_metadata.json"
    if not decision_path.exists() or not trace_path.exists():
        return None
    decisions = _read_json_file(decision_path).get("decisions", [])
    evidence = _read_json_file(output_dir / "evidence_summary.json").get("evidence", [])
    trace = _read_json_file(trace_path)
    return {
        "scenario_id": event.scenario_id,
        "title": event.title,
        "risk_type": event.risk_type,
        "risk_themes": event.risk_themes,
        "urgency": event.urgency,
        "status": "completed",
        "trace_id": str(trace.get("trace_id") or ""),
        "output_dir": str(output_dir),
        "error": None,
        "decision_count": len(decisions),
        "decisions": decisions,
        "evidence_count": len(evidence),
        "evidence_domains": sorted(
            {str(item.get("source_domain")) for item in evidence if isinstance(item, dict) and item.get("source_domain")}
        ),
        "orchestrator_finding": _read_json_file(output_dir / "final_brief.json").get("finding"),
    }


def _experiment_result_to_discovery_result(result: MultiLensDiscoveryExperimentResult) -> RiskDiscoveryResult:
    events = [_aggregated_scenario_to_risk_event(result, scenario, idx) for idx, scenario in enumerate(result.aggregated_scenarios, start=1)]
    selected_candidates = [
        _aggregated_scenario_to_discovered_risk(result, scenario, event, idx)
        for idx, (scenario, event) in enumerate(zip(result.aggregated_scenarios, events, strict=False), start=1)
    ]
    return RiskDiscoveryResult(
        request=result.request,
        selected_candidates=selected_candidates,
        rejected_candidates=[],
        selected_event=events[0] if events else None,
        selected_events=events,
        metadata={
            "source": "multi_lens_experiment_aggregation",
            "experiment_metadata": result.metadata,
            "aggregated_scenario_count": len(result.aggregated_scenarios),
            "fallback_used": False,
            "discovery_confidence": "experimental_aggregated",
        },
    )


def _aggregated_scenario_to_risk_event(
    result: MultiLensDiscoveryExperimentResult,
    scenario: Any,
    index: int,
) -> RiskEvent:
    description_parts = [
        scenario.scenario_story,
        scenario.analysis,
        f"Original aggregated scenario id: {scenario.scenario_id}",
    ]
    if scenario.recommended_actions:
        description_parts.append("Recommended actions: " + "; ".join(scenario.recommended_actions))
    return RiskEvent(
        scenario_id=_analysis_scenario_id(result, index),
        client_id=result.request.scope.client_id,
        title=scenario.title,
        risk_type=scenario.risk_type,
        countries=scenario.countries or result.request.countries,
        risk_themes=list(dict.fromkeys([*scenario.risk_themes, *scenario.source_lenses])),
        affected_categories=scenario.affected_categories,
        description="\n\n".join(part for part in description_parts if part),
        event_date=result.request.event_date or date.today(),
        urgency=_urgency_from_severity(scenario.severity),
    )


def _aggregated_scenario_to_discovered_risk(
    result: MultiLensDiscoveryExperimentResult,
    scenario: Any,
    event: RiskEvent,
    index: int,
) -> DiscoveredRisk:
    return DiscoveredRisk(
        candidate_id=event.scenario_id,
        title=scenario.title,
        risk_type=scenario.risk_type,
        countries=event.countries,
        risk_themes=event.risk_themes,
        affected_categories=event.affected_categories,
        description=event.description,
        urgency=event.urgency,
        relevance_score=_relevance_from_severity(scenario.severity, scenario.likelihood),
        selected_for_analysis=True,
        scope_matches=[
            f"aggregated_scenario:{scenario.scenario_id}",
            f"source_lenses:{','.join(scenario.source_lenses)}",
        ],
        rationale=scenario.rationale or "Aggregated scenario selected for downstream analysis.",
    )


def _analysis_scenario_id(result: MultiLensDiscoveryExperimentResult, index: int) -> str:
    event_slug = re.sub(r"[^a-z0-9]+", "_", result.request.event_title.lower()).strip("_")[:36] or "event"
    return f"experiment_{event_slug}_agg_{index:03d}"


def _urgency_from_severity(severity: str) -> str:
    normalized = str(severity or "").lower()
    if normalized in {"critical", "high"}:
        return "high"
    if normalized == "low":
        return "low"
    return "medium"


def _relevance_from_severity(severity: str, likelihood: str) -> int:
    severity_score = {"critical": 95, "high": 85, "medium": 70, "low": 50}.get(str(severity or "").lower(), 65)
    likelihood_adjustment = {"high": 5, "medium": 0, "low": -10}.get(str(likelihood or "").lower(), 0)
    return max(0, min(100, severity_score + likelihood_adjustment))


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
