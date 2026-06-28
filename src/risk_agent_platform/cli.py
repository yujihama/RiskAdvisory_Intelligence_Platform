from __future__ import annotations

import argparse
from pathlib import Path

from risk_agent_platform.config import Settings
from risk_agent_platform.run_scenario import main as run_scenario_main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="risk-agent-platform")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run-scenario", help="Run the A2A/MCP/DeepAgent scenario path.")
    run.add_argument("--scenario", required=True)
    run.add_argument("--embedded-services", action="store_true")

    sub.add_parser("preflight", help="Check required final architecture configuration.")

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

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
