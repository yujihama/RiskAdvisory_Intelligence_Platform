from __future__ import annotations

import argparse
from pathlib import Path

from risk_agent_platform.config import Settings
from risk_agent_platform.mcp_servers.factory import create_mcp_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args(argv)
    settings = Settings.load(Path.cwd())
    server = create_mcp_server(args.server, settings)
    server.run(transport="http", host=args.host, port=args.port, path="/mcp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
