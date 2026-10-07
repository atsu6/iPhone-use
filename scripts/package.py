#!/usr/bin/env python3
"""Validate and allowlist a portable source package, excluding all device data."""
import argparse
import json
from pathlib import Path
import re
import shutil
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
FILES=('plugin.json','mcp.json','.mcp.json','.codex-plugin/plugin.json','.agents/plugins/marketplace.json','README.md','CHANGELOG.md','LICENSE','THIRD_PARTY_NOTICES.md','.gitignore','ui/package.json','ui/package-lock.json','ui/build.mjs','ui/src/app.ts','ui/index.html','ui/style.css','ui/tsconfig.json','ui/tests/widget.test.mjs')
DIRS=('assets','server','skills','scripts','docs','evals','tests','.github')


def validate():
    manifest=json.loads((ROOT/'plugin.json').read_text());overlay=json.loads((ROOT/'.codex-plugin/plugin.json').read_text())
    ui=manifest['extensions']['com.openai']['interface']
    assert manifest['name']=='iphone-use-wda' and re.fullmatch(r'\d+\.\d+\.\d+',manifest['version'])
    assert len(ui['shortDescription'])<=30
    assert ui==overlay['interface']
    assert all(manifest[k]==overlay[k] for k in ('name','version','description'))
    assert overlay['mcpServers']=='./.mcp.json' and overlay['skills']=='./skills/'
    portable=json.loads((ROOT/'mcp.json').read_text());legacy=json.loads((ROOT/'.mcp.json').read_text())
    assert portable['mcpServers']==legacy['mcpServers']
    for config in portable['mcpServers'].values():
        assert config['type']=='stdio' and config['args']==['${PLUGIN_ROOT}/server/iphone_wda.py']
    for skill in ('iphone-wda-use','iphone-wda-setup'):
        path=ROOT/'skills'/skill/'SKILL.md';body=path.read_text()
        assert body.startswith('---\n') and re.search(r'^name: '+skill+r'$',body,re.M) and re.search(r'^description: .+',body,re.M)
    assert (ROOT/'tooling/package-lock.json').is_file()
    sys.path.insert(0,str(ROOT/'server'))
    from iphone_wda import TOOLS,SCHEMAS,VERSION,SCREEN_URI
    assert VERSION==manifest['version'] and len(TOOLS)==18
    assert sum(t.get('_meta',{}).get('ui',{}).get('visibility')!=['app'] for t in TOOLS)==17
    assert (ROOT/'assets/phone-screen.html').is_file()
    assert next(t for t in TOOLS if t['name']=='wda_ready')['_meta']['ui']['resourceUri']==SCREEN_URI
    assert len(set(t['name'] for t in TOOLS))==len(TOOLS)
    for t in TOOLS:assert t['inputSchema']['additionalProperties'] is False
    return manifest


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--validate-only',action='store_true');parser.add_argument('--stage-only',action='store_true');args=parser.parse_args()
    manifest=validate()
    if args.validate_only:
        print('Plugin manifests, 2 skills, 17 model tools and 1 app-only preview validated.');return
    stage=ROOT/'dist'/manifest['name']
    if stage.exists():shutil.rmtree(stage)
    stage.mkdir(parents=True)
    sources=[ROOT/name for name in FILES]
    for dirname in DIRS:sources.extend((ROOT/dirname).rglob('*'))
    sources.extend(ROOT/'tooling'/name for name in ('package.json','package-lock.json','forward.mjs','screen-stream.mjs'))
    for source in sources:
        if source.is_symlink():raise SystemExit('Refusing package symlink: '+str(source))
        if not source.is_file():continue
        rel=source.relative_to(ROOT)
        if '__pycache__' in rel.parts or source.suffix in ('.pyc','.jsonl') or source.name=='.DS_Store':continue
        target=stage/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    if args.stage_only:print(stage);return
    archive=ROOT/'dist'/f"{manifest['name']}-{manifest['version']}-source.zip"
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for path in sorted(stage.rglob('*')):
            if path.is_file():z.write(path,str(Path(manifest['name'])/path.relative_to(stage)))
    print(archive)


if __name__=='__main__':main()
