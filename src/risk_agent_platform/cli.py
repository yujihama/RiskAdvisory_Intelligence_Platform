from __future__ import annotations

import argparse
from pathlib import Path

from risk_agent_platform.agents.orchestrator import OrchestratorDeepAgent
from risk_agent_platform.config import Settings
from risk_agent_platform.llm.openrouter_client import OpenRouterClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="risk-agent-platform")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run-scenario", help="Run the local A2A/MCP scenario pipeline.")
    run.add_argument("--input", required=True, type=Path)

    smoke = sub.add_parser("llm-smoke", help="Run a tiny OpenRouter smoke test.")
    smoke.add_argument("--max-tokens", type=int, default=16)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings.load(Path.cwd())

    if args.command == "run-scenario":
        result = OrchestratorDeepAgent(settings).run_from_file(args.input)
        print(f"scenario_id={result.scenario_id}")
        print(f"artifact_dir={result.artifact_dir}")
        print(f"decisions={len(result.decisions)}")
        print(f"final_brief={result.final_brief_path}")
        return 0

    if args.command == "llm-smoke":
        client = OpenRouterClient(settings.openrouter)
        result = client.smoke_test(max_tokens=args.max_tokens)
        print(f"model={result.model}")
        print(f"content={result.content.strip()}")
        usage = result.usage
        if usage:
            print(f"usage={usage}")
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
