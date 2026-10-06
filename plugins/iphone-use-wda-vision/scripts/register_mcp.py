#!/usr/bin/env python3
"""Register the installed Vision server through Codex's standard MCP path."""
import json
from pathlib import Path
import subprocess
import sys


def main():
    installation = json.load(sys.stdin)
    if installation.get("pluginId") != "iphone-use-wda-vision@iphone-wda-vision-local":
        raise SystemExit("Expected the WDA Vision plugin installation result.")
    root = Path(installation["installedPath"]).resolve(strict=True)
    server = root / "server" / "iphone_wda.py"
    if not server.is_file():
        raise SystemExit("Installed WDA Vision MCP entrypoint is missing.")
    print(json.dumps(installation, ensure_ascii=False), flush=True)
    subprocess.run(["codex", "mcp", "add", "iphone_wda_vision", "--",
                    "python3", str(server)], check=True)


if __name__ == "__main__":
    main()
