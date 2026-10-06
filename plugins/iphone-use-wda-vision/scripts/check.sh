#!/bin/sh
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$task_root"
python3 -m unittest discover -s tests -v
python3 scripts/package.py --validate-only
node --check tooling/forward.mjs
