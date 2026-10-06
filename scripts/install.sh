#!/bin/sh
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python3 "$task_root/scripts/package.py" --stage-only
codex plugin marketplace add "$task_root" --json
codex plugin add iphone-use-wda@iphone-wda-local --json
printf '%s\n' 'Reconnect the Codex chat to load the WDA tools and skills.'
