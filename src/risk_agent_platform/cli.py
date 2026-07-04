from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from risk_agent_platform.api.app import create_app
from risk_agent_platform.config import Settings
from risk_agent_platform.run_discovery import main as run_discovery_main
from risk_agent_platform.run_discovery_evaluation import main as run_discovery_evaluation_main
from risk_agent_platform.run_scenario import main as run_scenario_main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="risk-agent-platform")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run-scenario", help="Run the A2A/MCP/DeepAgent scenario path.")
    run.add_argument("--scenario", required=True)
    run.add_argument("--embedded-services", action="store_true")

    discover = sub.add_parser("discover-risks", help="Discover scope-relevant risks from an event before scenario analysis.")
    discover.add_argument("--event-title", required=True)
    discover.add_argument("--event-description", default="")
    discover.add_argument("--client-id", required=True)
    discover.add_argument("--scope-text")
    discover.add_argument("--scope-type", default="company")
    discover.add_argument("--scope-name")
    discover.add_argument("--department")
    discover.add_argument("--industry")
    discover.add_argument("--region")
    discover.add_argument("--site-id")
    discover.add_argument("--country", action="append", default=[])
    discover.add_argument("--event-date")
    discover.add_argument(
        "--max-risks",
        type=int,
        default=3,
        help="Guidance for discovery candidate generation; threshold-selected candidates are not capped by this value.",
    )
    discover.add_argument("--scenario-output")
    discover.add_argument("--run-analysis", action="store_true")
    discover.add_argument(
        "--allow-fallback-analysis",
        action="store_true",
        help="Allow scenario analysis when Risk Discovery used template fallback candidates.",
    )
    discover.add_argument(
        "--analysis-mode",
        choices=["auto", "all-selected", "top", "top-n"],
        default="auto",
        help="Choose which selected RiskEvents are passed to scenario analysis; auto uses natural-language scope primary risks when present.",
    )
    discover.add_argument(
        "--top-n",
        type=int,
        default=3,
        help="Number of selected RiskEvents to analyze when --analysis-mode top-n is used.",
    )
    discover.add_argument("--embedded-services", action="store_true")

    evaluate = sub.add_parser("evaluate-discovery", help="Evaluate Risk Discovery quality against JSONL cases.")
    evaluate.add_argument("--cases", default="data/evaluation/risk_discovery_cases.jsonl")
    evaluate.add_argument("--output")
    evaluate.add_argument("--embedded-services", action="store_true")
    evaluate.add_argument("--top-n", type=int, default=3)
    evaluate.add_argument("--min-recall", type=float, default=0.75)
    evaluate.add_argument("--min-question-match", type=float, default=0.25)
    evaluate.add_argument("--min-missing-data-match", type=float, default=0.5)
    evaluate.add_argument("--min-reason-quality", type=float, default=0.75)
    evaluate.add_argument("--min-rubric-coverage", type=float, default=0.5)

    sub.add_parser("preflight", help="Check required final architecture configuration.")

    serve_api = sub.add_parser("serve-api", help="Start the external Platform API (FastAPI) service.")
    serve_api.add_argument("--host", default="127.0.0.1")
    serve_api.add_argument("--port", type=int, default=8080)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings.load(Path.cwd())

    if args.command == "run-scenario":
        argv = ["--scenario", args.scenario]
        if args.embedded_services:
            argv.append("--embedded-services")
        return run_scenario_main(argv)

    if args.command == "discover-risks":
        argv = [
            "--event-title",
            args.event_title,
            "--client-id",
            args.client_id,
            "--scope-type",
            args.scope_type,
            "--max-risks",
            str(args.max_risks),
            "--analysis-mode",
            args.analysis_mode,
            "--top-n",
            str(args.top_n),
        ]
        if args.event_description:
            argv.extend(["--event-description", args.event_description])
        for name in ("scope_text", "scope_name", "department", "industry", "region", "site_id", "event_date", "scenario_output"):
            value = getattr(args, name)
            if value:
                argv.extend([f"--{name.replace('_', '-')}", str(value)])
        for country in args.country:
            argv.extend(["--country", country])
        if args.run_analysis:
            argv.append("--run-analysis")
        if args.allow_fallback_analysis:
            argv.append("--allow-fallback-analysis")
        if args.embedded_services:
            argv.append("--embedded-services")
        return run_discovery_main(argv)

    if args.command == "evaluate-discovery":
        argv = [
            "--cases",
            args.cases,
            "--top-n",
            str(args.top_n),
            "--min-recall",
            str(args.min_recall),
            "--min-question-match",
            str(args.min_question_match),
            "--min-missing-data-match",
            str(args.min_missing_data_match),
            "--min-reason-quality",
            str(args.min_reason_quality),
            "--min-rubric-coverage",
            str(args.min_rubric_coverage),
        ]
        if args.output:
            argv.extend(["--output", args.output])
        if args.embedded_services:
            argv.append("--embedded-services")
        return run_discovery_evaluation_main(argv)

    if args.command == "preflight":
        checks = {
            "OPENROUTER_API_KEY": bool(settings.openrouter.api_key),
            "TAVILY_API_KEY": bool(settings.external_apis.tavily_api_key),
            "QDRANT_URL": bool(settings.stores.qdrant_url),
            "NEO4J_URI": bool(settings.stores.neo4j_uri),
            "LANGFUSE_HOST": bool(settings.langfuse.host),
            "LANGFUSE_PUBLIC_KEY": bool(settings.langfuse.public_key),
            "LANGFUSE_SECRET_KEY": bool(settings.langfuse.secret_key),
        }
        for name, ok in checks.items():
            print(f"{name}={'ok' if ok else 'missing'}")
        return 0 if all(checks.values()) else 1

    if args.command == "serve-api":
        app = create_app(settings)
        uvicorn.run(app, host=args.host, port=args.port)
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
