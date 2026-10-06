#!/usr/bin/env python3
"""Vision WDA fallback CLI, with a persistent JSON-lines mode for screenshot IDs."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from iphone_wda import Runtime, SCHEMAS, TOOL_PREFIX
from wda_client import WDAError


def parse_json(value):
    return json.loads(value, parse_constant=lambda token: (_ for _ in ()).throw(ValueError("Non-finite JSON number")))


def call(runtime, tool, arguments):
    try:
        return runtime.call(tool, arguments)
    except WDAError as exc:
        return {"error": exc.as_dict()}
    except (ValueError, TypeError) as exc:
        return {"error": {"code": "invalid_argument", "message": str(exc), "uncertain": False}}


def output(value):
    print(json.dumps(value, ensure_ascii=False, allow_nan=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", nargs="?", choices=[TOOL_PREFIX + name for name in SCHEMAS])
    parser.add_argument("arguments", nargs="?", default="{}", help="JSON object matching the MCP tool schema")
    parser.add_argument("--interactive", action="store_true", help='Keep one Runtime alive; stdin lines are {"tool":"wda_vision_observe","arguments":{}}. EOF closes the stream.')
    parser.add_argument("--state-dir")
    parser.add_argument("--url")
    args = parser.parse_args()
    if args.interactive and args.tool:
        parser.error("Choose --interactive or a standalone tool.")
    if not args.interactive and not args.tool:
        parser.error("A tool or --interactive is required.")
    runtime = None
    try:
        runtime = Runtime(args.state_dir, args.url)
        if args.interactive:
            output({"cli_stream_ready": True, "mode": "persistent_json_lines", "phone_ready": "Run wda_vision_ready and inspect its screenshot first."})
            for line in sys.stdin:
                try:
                    if len(line) > 1024 * 1024:
                        raise ValueError("Request exceeds 1 MiB")
                    request = parse_json(line)
                    if not isinstance(request, dict) or set(request) != {"tool", "arguments"}:
                        raise ValueError("Each request must contain tool and arguments only.")
                    result = call(runtime, request["tool"], request["arguments"])
                except (ValueError, TypeError) as exc:
                    result = {"error": {"code": "invalid_argument", "message": str(exc), "uncertain": False}}
                output(result)
            return 0
        result = call(runtime, args.tool, parse_json(args.arguments))
    except WDAError as exc:
        result = {"error": exc.as_dict()}
    except (ValueError, TypeError) as exc:
        result = {"error": {"code": "invalid_argument", "message": str(exc), "uncertain": False}}
    finally:
        if runtime:
            runtime.close()
    output(result)
    return 1 if "error" in result or (args.tool == TOOL_PREFIX + "ready" and result.get("ready") is not True) else 0


if __name__ == "__main__":
    sys.exit(main())
