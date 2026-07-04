from __future__ import annotations

import argparse
import json
from pathlib import Path

from risk_agent_platform.config import Settings
from risk_agent_platform.final_agents import create_embedded_a2a_apps, create_orchestrator_service, new_root_task
from risk_agent_platform.schemas import AgentTaskRequest, AgentTaskResult, RiskEvent


def execute_scenario(settings: Settings, event: RiskEvent, *, embedded_services: bool = False) -> tuple[AgentTaskResult, Path]:
    """Run the A2A/MCP/DeepAgent scenario path for a single RiskEvent, reusable by the CLI and the Platform API."""
    embedded_apps = create_embedded_a2a_apps(settings, embedded_mcp=True) if embedded_services else None
    orchestrator = create_orchestrator_service(settings, embedded_apps=embedded_apps)
    task = new_root_task(event)
    result = orchestrator.run_task(AgentTaskRequest(task=task))
    output_dir = settings.project_root / "outputs" / event.scenario_id
    return result, output_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--embedded-services", action="store_true", help="Use A2A endpoints in-process for local verification.")
    args = parser.parse_args(argv)

    settings = Settings.load(Path.cwd())
    event = RiskEvent.model_validate(json.loads(args.scenario.read_text(encoding="utf-8")))
    result, output_dir = execute_scenario(settings, event, embedded_services=args.embedded_services)
    print(f"status={result.status}")
    print(f"trace_id={result.trace_id}")
    print(f"output_dir={output_dir}")
    if result.error:
        print(f"error={result.error.code}: {result.error.message}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
