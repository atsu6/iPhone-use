#!/bin/sh
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python3 "$task_root/scripts/package.py" --stage-only
codex plugin marketplace add "$task_root" --json
codex plugin add iphone-use-wda-vision@iphone-wda-vision-local --json
printf '%s\n' 'Reconnect the Codex chat to load the WDA Vision tools and skills.'
