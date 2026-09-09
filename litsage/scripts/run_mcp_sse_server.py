from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run LitSage MCP server with SSE transport.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default="9010")
    args = parser.parse_args()

    os.environ.setdefault("MCP_TRANSPORT", "sse")
    os.environ["MCP_HOST"] = args.host
    os.environ["MCP_PORT"] = str(args.port)

    from app.mcp.server import main

    main()
