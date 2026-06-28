from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from risk_agent_platform.config import Settings
from risk_agent_platform.final_agents import create_embedded_a2a_apps, create_orchestrator_service, new_root_task
from risk_agent_platform.risk_discovery import RiskDiscoveryDeepAgent
from risk_agent_platform.schemas import AgentTaskRequest, RiskDiscoveryRequest, RiskDiscoveryScope


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-title", required=True)
    parser.add_argument("--event-description", default="")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--scope-type", default="company")
    parser.add_argument("--scope-name")
    parser.add_argument("--department")
    parser.add_argument("--region")
    parser.add_argument("--site-id")
    parser.add_argument("--country", action="append", default=[])
    parser.add_argument("--event-date", type=date.fromisoformat)
    parser.add_argument("--max-risks", type=int, default=3)
    parser.add_argument("--scenario-output", type=Path)
    parser.add_argument("--run-analysis", action="store_true")
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
            scope_type=args.scope_type,
            scope_name=args.scope_name,
            department=args.department,
            region=args.region,
            site_id=args.site_id,
        ),
    )
    discovery = RiskDiscoveryDeepAgent(settings, embedded_mcp=args.embedded_services)
    result = discovery.discover(request)
    output_path = _write_discovery_output(settings, result.model_dump(mode="json"), args.scenario_output)
    print(f"discovery_status=completed")
    print(f"candidate_count={len(result.candidates)}")
    print(f"selected_scenario_id={result.selected_event.scenario_id if result.selected_event else ''}")
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

    embedded_apps = create_embedded_a2a_apps(settings, embedded_mcp=True) if args.embedded_services else None
    orchestrator = create_orchestrator_service(settings, embedded_apps=embedded_apps)
    task = new_root_task(result.selected_event)
    analysis_result = orchestrator.run_task(AgentTaskRequest(task=task))
    output_dir = settings.project_root / "outputs" / result.selected_event.scenario_id
    print(f"analysis_status={analysis_result.status}")
    print(f"analysis_trace_id={analysis_result.trace_id}")
    print(f"analysis_output_dir={output_dir}")
    if analysis_result.error:
        print(f"analysis_error={analysis_result.error.code}: {analysis_result.error.message}")
        return 1
    return 0


def _write_discovery_output(settings: Settings, data: dict[str, object], scenario_output: Path | None) -> Path:
    selected_event = data.get("selected_event") if isinstance(data.get("selected_event"), dict) else {}
    scenario_id = selected_event.get("scenario_id") if isinstance(selected_event, dict) else None
    output_dir = settings.project_root / "outputs" / "risk_discovery"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{scenario_id or 'discovery'}.json"
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


if __name__ == "__main__":
    raise SystemExit(main())
