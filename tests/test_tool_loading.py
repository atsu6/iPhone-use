"""Guard the published catalog against Codex's lossy 5 KB schema compaction."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from iphone_wda import BATCH_OPS, Runtime, SCHEMAS, TOOLS, validate, validate_semantics
from wda_client import WDAError


def json_bytes(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def without_documentation(value):
    if isinstance(value, list):
        return [without_documentation(item) for item in value]
    if isinstance(value, dict):
        return {key: without_documentation(item) for key, item in value.items()
                if key not in ("description", "examples")}
    return value


def expand_references(schema):
    """Expand local references for contract comparison, rejecting broken/cyclic refs."""
    def expand(value, active=()):
        if isinstance(value, list):
            return [expand(item, active) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            reference = value["$ref"]
            if not reference.startswith("#/$defs/") or reference in active:
                raise AssertionError("Unsupported or cyclic schema reference: " + reference)
            target = schema
            for part in reference[2:].split("/"):
                target = target[part.replace("~1", "/").replace("~0", "~")]
            expanded = expand(target, (*active, reference))
            # This catalog uses pure references, so no sibling keyword can be lost.
            if set(value) != {"$ref"}:
                raise AssertionError("Reference has sibling constraints")
            return expanded
        return {key: expand(item, active) for key, item in value.items()
                if key != "$defs"}
    return expand(schema)


def codex_supported_schema(value):
    """Project to JsonSchema fields supported by Codex 0.160.1, without expanding refs.

    The host keeps reachable $defs and $ref; it only compacts once this serialized
    projection exceeds 5,000 bytes. This test protects the actual branch contract
    through that compatibility boundary, including const -> enum lowering.
    """
    supported = {"$ref", "type", "description", "encrypted", "enum", "items",
                 "minItems", "properties", "required", "additionalProperties",
                 "anyOf", "oneOf", "allOf", "$defs", "definitions"}
    result = {}
    for key, item in value.items():
        if key == "const":
            result["enum"] = [item]
        elif key in supported:
            if key in ("properties", "$defs", "definitions"):
                item = {name: codex_supported_schema(child) for name, child in item.items()}
            elif key in ("anyOf", "oneOf", "allOf"):
                item = [codex_supported_schema(child) for child in item]
            elif key == "items" or (key == "additionalProperties" and isinstance(item, dict)):
                item = codex_supported_schema(item)
            result[key] = item
    return result


class ToolLoadingTests(unittest.TestCase):
    def setUp(self):
        self.catalog = {tool["name"]: tool for tool in TOOLS}
        self.batch = self.catalog["wda_batch"]["inputSchema"]

    def test_every_published_schema_fits_before_host_compaction(self):
        for name, tool in self.catalog.items():
            with self.subTest(tool=name):
                self.assertLess(json_bytes(tool["inputSchema"]), 5000)
                self.assertLess(json_bytes(codex_supported_schema(tool["inputSchema"])), 5000)

    def test_batch_references_resolve_to_the_complete_runtime_contract(self):
        self.assertIn("$defs", self.batch)
        expanded = expand_references(self.batch)
        self.assertEqual(expanded, without_documentation(SCHEMAS["batch"]))
        branches = expanded["properties"]["steps"]["items"]["oneOf"]
        self.assertEqual(len(branches), len(BATCH_OPS))
        for branch in branches:
            op = branch["properties"]["op"]["const"]
            with self.subTest(op=op):
                self.assertEqual(branch["required"], ["op", "args"])
                self.assertFalse(branch["additionalProperties"])
                arguments = branch["properties"]["args"]
                self.assertFalse(arguments["additionalProperties"])
                self.assertEqual(arguments, without_documentation(SCHEMAS[op]))

    def test_codex_projection_keeps_references_and_all_operation_fields(self):
        projected = codex_supported_schema(self.batch)
        self.assertEqual(set(projected["$defs"]), set(self.batch["$defs"]))
        expanded = expand_references(projected)
        expected = codex_supported_schema(without_documentation(SCHEMAS["batch"]))
        self.assertEqual(expanded, expected)
        actual_ops = {branch["properties"]["op"]["enum"][0]
                      for branch in expanded["properties"]["steps"]["items"]["oneOf"]}
        self.assertEqual(actual_ops, set(BATCH_OPS))
        self.assertIn("$ref", json.dumps(projected))

    def test_publication_does_not_replace_the_strict_runtime_schemas(self):
        self.assertIsNot(self.batch, SCHEMAS["batch"])
        self.assertNotIn("$ref", json.dumps(SCHEMAS["batch"]))
        self.assertNotIn("$defs", SCHEMAS["batch"])
        original = copy.deepcopy(SCHEMAS["batch"])
        expand_references(self.batch)
        self.assertEqual(SCHEMAS["batch"], original)

    def test_valid_examples_accept_the_same_fields_in_both_contracts(self):
        examples = {
            "tap": {"x": 40, "y": 80, "observe": "tree"},
            "swipe": {"region": {"x": 0, "y": 100, "width": 300, "height": 400},
                      "verify": False, "observe": "both"},
            "type_text": {"selector": {"name": "message", "type": "TextField"},
                          "text": "直接输入完整文本", "replace": True, "verify": True},
            "launch_app": {"bundle_id": "com.example.app", "expect": {"label": "首页"}},
            "press_button": {"name": "home", "verify": False},
            "wait": {"selector": {"label": "完成"}, "timeout_seconds": 2},
            "observe": {"mode": "tree", "max_nodes": 50},
            "scroll_find": {"selector": {"label": "列表末项"}, "max_swipes": 3},
        }
        self.assertEqual(set(examples), set(BATCH_OPS))
        arguments = {"steps": [{"op": op, "args": args} for op, args in examples.items()]}
        for schema in (SCHEMAS["batch"], expand_references(self.batch)):
            validate(arguments, schema)
        validate_semantics("batch", arguments)

    def test_unknown_fields_in_later_batch_step_fail_before_any_execution(self):
        first = {"op": "press_button", "args": {"name": "home"}}
        invalid_cases = [
            {"steps": [first], "unknown": True},
            {"steps": [first, {"op": "tap", "args": {"x": 40, "y": 80}, "unknown": True}]},
            {"steps": [first, {"op": "type_text", "args": {
                "selector": {"name": "message"}, "text": "test", "unknown": True}}]},
            {"steps": [first, {"op": "tap", "args": {"selector": {"label": "继续", "rect": {}}}}]},
        ]
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(directory)
            self.addCleanup(runtime.close)
            with patch.object(runtime, "_call") as execute, patch.object(runtime.client, "request") as request:
                for arguments in invalid_cases:
                    with self.subTest(arguments=arguments), self.assertRaises(WDAError) as caught:
                        runtime.call("wda_batch", arguments)
                    self.assertEqual(caught.exception.code, "invalid_argument")
                    self.assertFalse(caught.exception.details["action_executed"])
                execute.assert_not_called()
                request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
