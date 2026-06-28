from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from risk_agent_platform.config import Settings
from risk_agent_platform.final_agents import create_embedded_a2a_apps, create_orchestrator_service, new_root_task
from risk_agent_platform.risk_discovery import RiskDiscoveryDeepAgent
from risk_agent_platform.schemas import AgentTaskRequest, RiskDiscoveryRequest, RiskDiscoveryResult, RiskDiscoveryScope, RiskEvent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-title", required=True)
    parser.add_argument("--event-description", default="")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--scope-text", help="Free-form natural-language scope, e.g. company, function, assets, routes, or concerns.")
    parser.add_argument("--scope-type", default="company")
    parser.add_argument("--scope-name")
    parser.add_argument("--department")
    parser.add_argument("--industry")
    parser.add_argument("--region")
    parser.add_argument("--site-id")
    parser.add_argument("--country", action="append", default=[])
    parser.add_argument("--event-date", type=date.fromisoformat)
    parser.add_argument(
        "--max-risks",
        type=int,
        default=5,
        help="Guidance for discovery candidate generation; threshold-selected candidates are not capped by this value.",
    )
    parser.add_argument("--scenario-output", type=Path)
    parser.add_argument("--run-analysis", action="store_true")
    parser.add_argument(
        "--allow-fallback-analysis",
        action="store_true",
        help="Allow scenario analysis when Risk Discovery used template fallback candidates.",
    )
    parser.add_argument(
        "--analysis-mode",
        choices=["auto", "all-selected", "top", "top-n"],
        default="auto",
        help="Choose which selected RiskEvents are passed to scenario analysis; auto uses natural-language scope primary risks when present.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=3,
        help="Number of selected RiskEvents to analyze when --analysis-mode top-n is used.",
    )
    parser.add_argument("--embedded-services", action="store_true", help="Use A2A/MCP endpoints in-process for local verification.")
    args = parser.parse_args(argv)

    settings = Settings.load(Path.cwd())
    request = RiskDiscoveryRequest(
        event_title=args.event_title,
        event_description=args.event_description,
        countries=args.country,
        event_date=args.event_date,
        max_risks=args.max_risks,
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
    discovery = RiskDiscoveryDeepAgent(settings, embedded_mcp=args.embedded_services)
    result = discovery.discover(request)
    output_path = _write_discovery_output(settings, result.model_dump(mode="json"), args.scenario_output)
    print(f"discovery_status=completed")
    print(f"selected_candidate_count={len(result.selected_candidates)}")
    print(f"rejected_candidate_count={len(result.rejected_candidates)}")
    print(f"fallback_used={str(bool(result.metadata.get('fallback_used'))).lower()}")
    print(f"discovery_confidence={result.metadata.get('discovery_confidence', '')}")
    print(f"selected_scenario_id={result.selected_event.scenario_id if result.selected_event else ''}")
    print(f"selected_scenario_ids={','.join(event.scenario_id for event in result.selected_events)}")
    print(f"discovery_output={output_path}")

    if not result.selected_event:
        print("analysis_status=skipped:no_selected_event")
        return 1

    if args.scenario_output:
        args.scenario_output.parent.mkdir(parents=True, exist_ok=True)
        args.scenario_output.write_text(json.dumps(result.selected_event.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"selected_scenario={args.scenario_output}")

    if not args.run_analysis:
        print("analysis_status=skipped")
        return 0

    if result.metadata.get("fallback_used") and not args.allow_fallback_analysis:
        print("discovery_warning=template_fallback_requires_explicit_allow_fallback_analysis")
        print("analysis_status=blocked:fallback_used")
        return 2

    events_to_analyze = _events_for_analysis(result, args.analysis_mode, args.top_n)
    if not events_to_analyze:
        print("analysis_status=skipped:no_events_to_analyze")
        return 1

    embedded_apps = create_embedded_a2a_apps(settings, embedded_mcp=True) if args.embedded_services else None
    orchestrator = create_orchestrator_service(settings, embedded_apps=embedded_apps)
    records: list[dict[str, Any]] = []
    for idx, event in enumerate(events_to_analyze, start=1):
        task = new_root_task(event)
        analysis_result = orchestrator.run_task(AgentTaskRequest(task=task))
        record = _analysis_record(settings, event, analysis_result)
        records.append(record)
        print(f"analysis_{idx}_scenario_id={event.scenario_id}")
        print(f"analysis_{idx}_status={analysis_result.status}")
        print(f"analysis_{idx}_trace_id={analysis_result.trace_id}")
        print(f"analysis_{idx}_output_dir={record['output_dir']}")
        if analysis_result.error:
            print(f"analysis_{idx}_error={analysis_result.error.code}: {analysis_result.error.message}")
    portfolio_paths = _write_portfolio_summary(settings, result, records)
    print(f"analysis_status={'completed' if all(record['status'] == 'completed' for record in records) else 'failed'}")
    print(f"analysis_count={len(records)}")
    print(f"portfolio_summary_json={portfolio_paths['json']}")
    print(f"portfolio_summary_md={portfolio_paths['markdown']}")
    return 0 if all(record["status"] == "completed" for record in records) else 1


def _write_discovery_output(settings: Settings, data: dict[str, object], scenario_output: Path | None) -> Path:
    selected_event = data.get("selected_event") if isinstance(data.get("selected_event"), dict) else {}
    scenario_id = selected_event.get("scenario_id") if isinstance(selected_event, dict) else None
    output_dir = settings.project_root / "outputs" / "risk_discovery"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{scenario_id or 'discovery'}.json"
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def _events_for_analysis(result: RiskDiscoveryResult, mode: str, top_n: int) -> list[RiskEvent]:
    events = result.selected_events or ([result.selected_event] if result.selected_event else [])
    events = [event for event in events if event is not None]
    if mode == "auto":
        raw_interpretation = result.metadata.get("scope_interpretation") if isinstance(result.metadata, dict) else None
        interpretation = raw_interpretation if isinstance(raw_interpretation, dict) else {}
        primary_types = {
            str(item)
            for item in interpretation.get("primary_risk_types") or []
        }
        if interpretation.get("source") == "scope_text" and primary_types:
            primary_events = [event for event in events if event.risk_type in primary_types]
            return primary_events or events[:1]
        return events
    if mode == "top":
        return events[:1]
    if mode == "top-n":
        return events[: max(1, top_n)]
    return events


def _analysis_record(settings: Settings, event: RiskEvent, analysis_result: Any) -> dict[str, Any]:
    output_dir = settings.project_root / "outputs" / event.scenario_id
    decisions = _read_json_file(output_dir / "decision_queue.json").get("decisions", [])
    evidence = _read_json_file(output_dir / "evidence_summary.json").get("evidence", [])
    finding = analysis_result.finding.model_dump(mode="json") if analysis_result.finding else None
    return {
        "scenario_id": event.scenario_id,
        "title": event.title,
        "risk_type": event.risk_type,
        "risk_themes": event.risk_themes,
        "urgency": event.urgency,
        "status": analysis_result.status,
        "trace_id": analysis_result.trace_id,
        "output_dir": str(output_dir),
        "error": analysis_result.error.model_dump(mode="json") if analysis_result.error else None,
        "decision_count": len(decisions),
        "decisions": decisions,
        "evidence_count": len(evidence),
        "evidence_domains": sorted(
            {str(item.get("source_domain")) for item in evidence if item.get("source_domain")}
        ),
        "orchestrator_finding": finding,
    }


def _write_portfolio_summary(
    settings: Settings,
    result: RiskDiscoveryResult,
    records: list[dict[str, Any]],
) -> dict[str, str]:
    portfolio_id = result.selected_event.scenario_id if result.selected_event else "discovery"
    output_dir = settings.project_root / "outputs" / "risk_discovery"
    output_dir.mkdir(parents=True, exist_ok=True)
    decision_rules = _load_decision_consolidation_rules(settings)
    data = {
        "request": result.request.model_dump(mode="json"),
        "discovery_metadata": result.metadata,
        "selected_candidates": [candidate.model_dump(mode="json") for candidate in result.selected_candidates],
        "rejected_candidates": [candidate.model_dump(mode="json") for candidate in result.rejected_candidates],
        "selected_events": [event.model_dump(mode="json") for event in result.selected_events],
        "decision_consolidation_rules": decision_rules,
        "portfolio_overview": _portfolio_overview(records, decision_rules),
        "analyses": records,
    }
    json_path = output_dir / f"{portfolio_id}_portfolio_summary.json"
    md_path = output_dir / f"{portfolio_id}_portfolio_summary.md"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_portfolio_markdown(data), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def _portfolio_overview(records: list[dict[str, Any]], decision_rules: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    risk_types: set[str] = set()
    evidence_domains: set[str] = set()
    review_required_scenarios: list[str] = []
    priority_decisions: list[dict[str, Any]] = []
    decision_rows = _decision_rows(records)
    consolidated_decisions = _consolidated_decisions(decision_rows, decision_rules or [])
    total_evidence = 0

    for record in records:
        status = str(record.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        if record.get("risk_type"):
            risk_types.add(str(record["risk_type"]))
        total_evidence += int(record.get("evidence_count") or 0)
        evidence_domains.update(str(domain) for domain in record.get("evidence_domains", []) if domain)

        decisions = record.get("decisions") or []
        finding = record.get("orchestrator_finding") or {}
        decision_review_required = any(
            bool(decision.get("review_required"))
            for decision in decisions
            if isinstance(decision, dict)
        )
        finding_review_required = bool(finding.get("review_required")) if isinstance(finding, dict) else False
        if decision_review_required or finding_review_required:
            review_required_scenarios.append(str(record.get("scenario_id") or ""))

        for decision in decisions:
            if not isinstance(decision, dict):
                continue
            priority = decision.get("priority")
            priority_value = priority if isinstance(priority, int) else 999
            if priority_value <= 3 or bool(decision.get("review_required")):
                priority_decisions.append(
                    {
                        "scenario_id": record.get("scenario_id"),
                        "risk_type": record.get("risk_type"),
                        "decision": decision.get("decision"),
                        "owner": decision.get("owner"),
                        "priority": priority,
                        "review_required": bool(decision.get("review_required")),
                    }
                )

    priority_decisions = sorted(
        priority_decisions,
        key=lambda item: item.get("priority") if isinstance(item.get("priority"), int) else 999,
    )
    return {
        "analysis_count": len(records),
        "completed_count": status_counts.get("completed", 0),
        "failed_count": sum(count for status, count in status_counts.items() if status not in {"completed"}),
        "status_counts": status_counts,
        "risk_types": sorted(risk_types),
        "total_decisions": len(decision_rows),
        "total_evidence": total_evidence,
        "evidence_domains": sorted(evidence_domains),
        "review_required_scenarios": [scenario_id for scenario_id in review_required_scenarios if scenario_id],
        "priority_decisions": priority_decisions[:20],
        "consolidated_decisions": consolidated_decisions,
        "decisions_by_owner": _group_decisions(decision_rows, "owner"),
        "decisions_by_deadline": _group_decisions(decision_rows, "deadline"),
        "decision_conflicts": _decision_conflicts(consolidated_decisions),
    }


def _decision_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        for decision in record.get("decisions", []):
            if not isinstance(decision, dict):
                continue
            rows.append(
                {
                    "scenario_id": record.get("scenario_id"),
                    "risk_type": record.get("risk_type"),
                    "decision": decision.get("decision"),
                    "owner": decision.get("owner") or "Unassigned",
                    "deadline": decision.get("deadline") or "Unspecified",
                    "priority": decision.get("priority") if isinstance(decision.get("priority"), int) else 999,
                    "review_required": bool(decision.get("review_required")),
                }
            )
    return rows


def _load_decision_consolidation_rules(settings: Settings) -> list[dict[str, Any]]:
    path = settings.data_dir / "expert_knowledge" / "decision_consolidation_rules.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _consolidated_decisions(rows: list[dict[str, Any]], decision_rules: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    decision_rules = decision_rules or []
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(_decision_group_key(str(row.get("decision") or ""), decision_rules), []).append(row)
    consolidated = []
    for group_key, items in groups.items():
        rule = _decision_rule_by_group(group_key, decision_rules)
        owners = sorted({owner for item in items for owner in _owner_tokens(item.get("owner"))})
        deadlines = sorted({str(item.get("deadline") or "Unspecified") for item in items})
        priorities = [int(item.get("priority") or 999) for item in items]
        representative = min((str(item.get("decision") or "") for item in items), key=len, default=group_key)
        required_owners = [str(item) for item in (rule or {}).get("required_owners", [])]
        owners_lower = {owner.lower() for owner in owners}
        owner_gap = [owner for owner in required_owners if owner.lower() not in owners_lower]
        consolidated.append(
            {
                "group_id": group_key,
                "rule_id": (rule or {}).get("rule_id"),
                "decision": representative,
                "owners": owners,
                "required_owners": required_owners,
                "primary_owner": (rule or {}).get("primary_owner"),
                "secondary_owners": [str(item) for item in (rule or {}).get("secondary_owners", [])],
                "owner_gap": owner_gap,
                "deadlines": deadlines,
                "scenario_ids": sorted({str(item.get("scenario_id") or "") for item in items if item.get("scenario_id")}),
                "risk_types": sorted({str(item.get("risk_type") or "") for item in items if item.get("risk_type")}),
                "source_count": len(items),
                "priority": min(priorities) if priorities else 999,
                "review_required": any(bool(item.get("review_required")) for item in items),
                "rationale": (rule or {}).get("rationale"),
            }
        )
    return sorted(consolidated, key=lambda item: (item["priority"], -item["source_count"], item["group_id"]))


def _owner_tokens(owner: Any) -> list[str]:
    raw = str(owner or "Unassigned")
    tokens = [token.strip() for token in re.split(r"\s*(?:/|,|;|&|\band\b)\s*", raw) if token.strip()]
    return tokens or ["Unassigned"]


def _decision_group_key(text: str, decision_rules: list[dict[str, Any]] | None = None) -> str:
    lowered = text.lower()
    for rule in decision_rules or []:
        terms = [str(term).lower() for term in rule.get("match_terms") or []]
        if terms and any(term in lowered for term in terms):
            return str(rule.get("group_id") or rule.get("rule_id") or "decision_review")
    if "sanction" in lowered or "restricted" in lowered:
        return "sanctions_review"
    if "payment" in lowered or "cash" in lowered or "bank" in lowered:
        return "payment_execution"
    if "supplier" in lowered or "procurement" in lowered:
        return "supplier_continuity"
    if "contract" in lowered or "notice" in lowered or "force majeure" in lowered:
        return "contract_review"
    tokens = [
        token
        for token in re.sub(r"[^a-z0-9]+", " ", lowered).split()
        if len(token) >= 4 and token not in {"confirm", "review", "check", "required", "owner"}
    ]
    return "_".join(tokens[:5]) if tokens else "decision_review"


def _decision_rule_by_group(group_id: str, decision_rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    for rule in decision_rules:
        if str(rule.get("group_id") or "") == group_id:
            return rule
    return None


def _group_decisions(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field) or "Unspecified")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _decision_conflicts(consolidated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conflicts = []
    for item in consolidated:
        owners = item.get("owners") or []
        deadlines = item.get("deadlines") or []
        owner_gap = item.get("owner_gap") or []
        if owner_gap:
            conflicts.append(
                {
                    "group_id": item["group_id"],
                    "issue": "Required owner is missing from consolidated decision.",
                    "missing_owners": owner_gap,
                    "required_owners": item.get("required_owners", []),
                    "owners": owners,
                    "deadlines": deadlines,
                    "scenario_ids": item.get("scenario_ids", []),
                    "rule_id": item.get("rule_id"),
                }
            )
        if int(item.get("source_count") or 0) > 1 and (len(owners) > 1 or len(deadlines) > 1):
            conflicts.append(
                {
                    "group_id": item["group_id"],
                    "issue": "Potential duplicate decision with different owner or deadline.",
                    "owners": owners,
                    "deadlines": deadlines,
                    "scenario_ids": item.get("scenario_ids", []),
                    "rule_id": item.get("rule_id"),
                }
            )
    return conflicts


def _portfolio_markdown(data: dict[str, Any]) -> str:
    request = data["request"]
    overview = data.get("portfolio_overview") or {}
    lines = [
        f"# Risk Discovery Portfolio Summary: {request['event_title']}",
        "",
        f"- Client: `{request['scope']['client_id']}`",
        f"- Scope: `{request['scope']['scope_type']}` `{request['scope'].get('scope_name') or request['scope'].get('scope_text') or ''}`",
        f"- Discovery confidence: `{(data.get('discovery_metadata') or {}).get('discovery_confidence', '')}`",
        f"- Fallback used: `{(data.get('discovery_metadata') or {}).get('fallback_used', False)}`",
        f"- Selected candidates: {len(data['selected_candidates'])}",
        f"- Rejected candidates: {len(data['rejected_candidates'])}",
        f"- Analyses executed: {len(data['analyses'])}",
        "",
        "## Portfolio Overview",
        f"- Completed analyses: {overview.get('completed_count', 0)} / {overview.get('analysis_count', 0)}",
        f"- Failed analyses: {overview.get('failed_count', 0)}",
        f"- Total decisions: {overview.get('total_decisions', 0)}",
        f"- Total evidence records: {overview.get('total_evidence', 0)}",
        f"- Risk types: {', '.join(overview.get('risk_types') or []) or 'None'}",
        f"- Evidence domains: {', '.join(overview.get('evidence_domains') or []) or 'None'}",
        f"- Review-required scenarios: {len(overview.get('review_required_scenarios') or [])}",
        "",
        "## Priority Decisions",
    ]
    priority_decisions = overview.get("priority_decisions") or []
    if priority_decisions:
        for decision in priority_decisions:
            lines.append(
                f"- `{decision.get('scenario_id')}` {decision.get('decision')} "
                f"(owner={decision.get('owner')}, priority={decision.get('priority')}, review_required={decision.get('review_required')})"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Consolidated Decisions"])
    consolidated_decisions = overview.get("consolidated_decisions") or []
    if consolidated_decisions:
        for decision in consolidated_decisions:
            lines.append(
                f"- `{decision.get('group_id')}` {decision.get('decision')} "
                f"(owners={', '.join(decision.get('owners') or [])}, "
                f"required={', '.join(decision.get('required_owners') or []) or 'None'}, "
                f"owner_gap={', '.join(decision.get('owner_gap') or []) or 'None'}, "
                f"deadlines={', '.join(decision.get('deadlines') or [])}, "
                f"sources={decision.get('source_count')})"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Decision Conflicts"])
    conflicts = overview.get("decision_conflicts") or []
    if conflicts:
        for conflict in conflicts:
            lines.append(
                f"- `{conflict.get('group_id')}` {conflict.get('issue')} "
                f"(owners={', '.join(conflict.get('owners') or [])}, "
                f"missing={', '.join(conflict.get('missing_owners') or []) or 'None'}, "
                f"deadlines={', '.join(conflict.get('deadlines') or [])})"
            )
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Selected Candidates",
        ]
    )
    for candidate in data["selected_candidates"]:
        lines.append(
            f"- `{candidate['candidate_id']}` {candidate['title']} "
            f"(score={candidate['relevance_score']}, type={candidate['risk_type']})"
        )
    lines.extend(["", "## Rejected Candidates"])
    if data["rejected_candidates"]:
        for candidate in data["rejected_candidates"]:
            lines.append(
                f"- `{candidate['candidate_id']}` {candidate['title']} "
                f"(score={candidate['relevance_score']}): {candidate['reason']}"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Scenario Analyses"])
    for record in data["analyses"]:
        lines.append(f"### {record['title']}")
        lines.append(f"- Scenario ID: `{record['scenario_id']}`")
        lines.append(f"- Status: `{record['status']}`")
        lines.append(f"- Trace ID: `{record['trace_id']}`")
        lines.append(f"- Output: `{record['output_dir']}`")
        lines.append(f"- Decisions: {record['decision_count']}")
        lines.append(f"- Evidence: {record['evidence_count']}")
        for decision in record.get("decisions", []):
            lines.append(f"- Decision: {decision.get('decision')}")
    return "\n".join(lines) + "\n"


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
