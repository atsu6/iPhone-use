"""Probe the real MCP entrypoint and both install variants without phone actions."""
import json
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def catalog(root, language='', system_language='en_US.UTF-8'):
    suffix = '-ja' if language.lower().replace('_', '-').split('-')[0] == 'ja' else ''
    version = json.loads((root/'plugin.json').read_text())['version']
    uri = 'ui://iphone-use/phone-' + version + suffix + '.html'
    requests = [
        {'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'locale-test', 'version': '1'}}},
        {'method': 'tools/list', 'params': {}},
        {'method': 'resources/list', 'params': {}},
        {'method': 'resources/read', 'params': {'uri': uri}},
    ]
    wire = '\n'.join(json.dumps({'jsonrpc': '2.0', 'id': i, **r}) for i, r in enumerate(requests, 1)) + '\n'
    with tempfile.TemporaryDirectory() as state:
        env = {**os.environ, 'IPHONE_USE_ANALYTICS': '0', 'IPHONE_USE_STATE_DIR': state,
               'IPHONE_USE_LANGUAGE': language, 'LANG': system_language, 'LC_ALL': system_language}
        process = subprocess.run([sys.executable, str(root/'server/iphone_use.py')], input=wire,
                                 capture_output=True, text=True, timeout=15, check=True, env=env)
    replies = [json.loads(line) for line in process.stdout.splitlines()]
    assert len(replies) == 4 and all('error' not in item for item in replies), replies
    return [item['result'] for item in replies]


def contract(value):
    if isinstance(value, dict):
        return {key: contract(item) for key, item in value.items() if key not in ('description', 'examples')}
    if isinstance(value, list):
        return [contract(item) for item in value]
    return value


class LocalizationTests(unittest.TestCase):
    def test_installer_forwards_only_supported_language_options_before_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            python = Path(directory)/'python3'
            python.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\nexit 17\n')
            python.chmod(0o700)
            env = {**os.environ, 'PATH': directory + os.pathsep + os.environ.get('PATH', '')}
            # The fake packager stops the script before any real Codex invocation.
            for args, language in (([], 'default'), (['--language', 'ja'], 'ja'), (['--language', 'default'], 'default')):
                process = subprocess.run(['sh', str(ROOT/'scripts/install.sh'), *args], env=env, capture_output=True, text=True)
                self.assertEqual(process.returncode, 17)
                self.assertEqual(process.stdout.splitlines(), [str(ROOT/'scripts/package.py'), '--stage-only', '--language', language])
            for args in (['--help'], ['--language', 'fr'], ['--validate-only']):
                process = subprocess.run(['sh', str(ROOT/'scripts/install.sh'), *args], env=env, capture_output=True, text=True)
                self.assertEqual(process.returncode, 2)
                self.assertEqual(process.stdout, '')
                self.assertIn('Usage:', process.stderr)

    def test_system_language_does_not_override_the_existing_default(self):
        english = catalog(ROOT)
        japanese_system = catalog(ROOT, system_language='ja_JP.UTF-8')
        unsupported = catalog(ROOT, 'fr')
        self.assertEqual(english, japanese_system)
        self.assertEqual(english, unsupported)
        self.assertIn('PUA means Phone Use Agent', english[0]['instructions'])
        self.assertNotIn('ユーザーには日本語で案内する', english[0]['instructions'])
        self.assertIn('<html lang="zh-CN">', english[3]['contents'][0]['text'])

    def test_japanese_is_explicit_and_keeps_the_runtime_contract(self):
        default = catalog(ROOT)
        japanese = catalog(ROOT, 'ja')
        self.assertEqual(japanese, catalog(ROOT, 'ja-JP'))
        self.assertIn('ユーザーには日本語で案内する', japanese[0]['instructions'])
        self.assertEqual(japanese[2]['resources'][0]['title'], 'iPhoneの画面')
        self.assertIn('<html lang="ja">', japanese[3]['contents'][0]['text'])
        self.assertIn('aria-label="ホーム画面に戻る"', japanese[3]['contents'][0]['text'])
        self.assertNotEqual(default[2]['resources'][0]['uri'], japanese[2]['resources'][0]['uri'])
        for left, right in zip(default[1]['tools'], japanese[1]['tools']):
            self.assertEqual(left['name'], right['name'])
            self.assertEqual(left['annotations'], right['annotations'])
            self.assertEqual(contract(left['inputSchema']), contract(right['inputSchema']))
            self.assertLess(len(json.dumps(right['inputSchema'], ensure_ascii=False, separators=(',', ':')).encode()), 5000)

    def test_source_package_builds_japanese_without_changing_canonical_files(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            spec = importlib.util.spec_from_file_location('locale_packaging', ROOT/'scripts/package.py')
            packaging = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(packaging)
            source = target/'source'
            for path, relative in packaging.package_files(source_package=True):
                copied = source/relative
                copied.parent.mkdir(parents=True, exist_ok=True)
                copied.write_bytes(path.read_bytes())
            subprocess.run([sys.executable, str(source/'scripts/package.py')], check=True, capture_output=True)
            archive = next((source/'dist').glob('*-source.zip'))
            with zipfile.ZipFile(archive) as package:
                package.extractall(target/'extracted')
            checkout = target/'extracted/iphone-use'
            unchanged = {name: (checkout/name).read_bytes() for name in
                         ('plugin.json', '.codex-plugin/plugin.json', 'mcp.json', '.mcp.json',
                          'skills/iphone-use/SKILL.md', 'skills/iphone-use-setup/SKILL.md')}
            subprocess.run([sys.executable, str(checkout/'scripts/package.py'), '--stage-only', '--language', 'ja'],
                           check=True, capture_output=True)
            stage = checkout/'dist/iphone-use'
            manifest = json.loads((stage/'plugin.json').read_text())
            overlay = json.loads((stage/'.codex-plugin/plugin.json').read_text())
            self.assertEqual(manifest['name'], 'iphone-use')
            self.assertEqual(manifest['version'], json.loads(unchanged['plugin.json'])['version'])
            self.assertEqual(manifest['extensions']['com.openai']['interface'], overlay['interface'])
            self.assertEqual(manifest['extensions']['com.openai']['interface']['shortDescription'], 'CodexからiPhoneを操作')
            for skill in ('iphone-use', 'iphone-use-setup'):
                self.assertEqual((stage/'skills'/skill/'SKILL.md').read_bytes(), (checkout/'skills'/skill/'SKILL.ja.md').read_bytes())
            portable = json.loads((stage/'mcp.json').read_text())
            legacy = json.loads((stage/'.mcp.json').read_text())
            self.assertEqual(portable['mcpServers'], legacy['mcpServers'])
            self.assertEqual(portable['mcpServers']['iphone_use']['env']['IPHONE_USE_LANGUAGE'], 'ja')
            self.assertIn('ユーザーには日本語で案内する', catalog(stage, 'ja')[0]['instructions'])
            for name, original in unchanged.items():
                self.assertEqual((checkout/name).read_bytes(), original)
            subprocess.run([sys.executable, str(checkout/'scripts/package.py'), '--stage-only', '--language', 'default'],
                           check=True, capture_output=True)
            for name in ('plugin.json', '.codex-plugin/plugin.json', 'skills/iphone-use/SKILL.md', 'skills/iphone-use-setup/SKILL.md'):
                self.assertEqual((stage/name).read_bytes(), unchanged[name])
            default_config=json.loads((stage/'mcp.json').read_text())
            self.assertEqual(default_config['mcpServers']['iphone_use']['env']['IPHONE_USE_LANGUAGE'], 'default')
            self.assertNotIn('ユーザーには日本語で案内する', catalog(stage, 'default')[0]['instructions'])


if __name__ == '__main__':
    unittest.main()
