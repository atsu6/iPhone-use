#!/usr/bin/env python3
"""Register the installed WDA server through Codex's standard MCP path."""
import json
from pathlib import Path
import subprocess
import sys


def main():
    installation=json.load(sys.stdin)
    if installation.get("pluginId")!="iphone-use-wda@iphone-wda-local":
        raise SystemExit("Expected the ordinary WDA plugin installation result.")
    root=Path(installation["installedPath"]).resolve(strict=True)
    server=root/"server"/"iphone_wda.py"
    if not server.is_file():
        raise SystemExit("Installed WDA MCP entrypoint is missing.")
    print(json.dumps(installation,ensure_ascii=False),flush=True)
    # Same name as the plugin registration: Config wins over Plugin in Codex,
    # so there is one namespace, without the shared agent-plugin tool budget.
    subprocess.run(["codex","mcp","add","iphone_wda","--","python3",str(server)],check=True)


if __name__=="__main__":main()
