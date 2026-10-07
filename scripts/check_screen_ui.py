#!/usr/bin/env python3
"""Check bundled module syntax and run isolated widget DOM tests."""
from pathlib import Path
import re
import subprocess
import tempfile

root=Path(__file__).resolve().parents[1]
html=(root/'assets/phone-screen.html').read_text()
modules=re.findall(r'<script type="module">([\s\S]*?)</script>',html)
assert len(modules)==1,'Expected one bundled widget module'
assert 'console.debug(' not in modules[0], 'Preview SDK must not debug-log frame payloads'
assert not re.search(r'<(?:script|link)[^>]+(?:src|href)=["\']https?://',html),'Widget must be self-contained'
assert len(re.findall(r'<img\b',html))==1 and '<button' not in html
with tempfile.TemporaryDirectory() as directory:
    script=Path(directory)/'screen.mjs'
    script.write_text(modules[0])
    subprocess.run(['node','--check',str(script)],check=True)
subprocess.run(['node','--test',str(root/'ui/tests/widget.test.mjs')],check=True)
