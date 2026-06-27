from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from risk_agent_platform.a2a_http import create_a2a_app
from risk_agent_platform.config import Settings
from risk_agent_platform.final_agents import create_domain_services, create_orchestrator_service


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", required=True)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args(argv)
    settings = Settings.load(Path.cwd())
    if args.agent == "orchestrator-agent":
        service = create_orchestrator_service(settings)
    else:
        services = create_domain_services(settings, embedded_mcp=False)
        service = services[args.agent]
    app = create_a2a_app(service)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
