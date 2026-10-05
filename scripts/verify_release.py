#!/usr/bin/env python3
"""Verify a published file manifest without executing research workflows."""
from pathlib import Path
import hashlib
import json

root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'audit/source-manifest.json').read_text(encoding='utf-8'))
issues=[]
for item in manifest['files']:
    path=(root/item['path']).resolve()
    if not path.is_relative_to(root):
        issues.append({'path':item['path'],'issue':'path escapes release'})
    elif not path.is_file():
        issues.append({'path':item['path'],'issue':'missing'})
    elif hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
        issues.append({'path':item['path'],'issue':'hash mismatch'})
print(json.dumps({'valid':not issues,'files_checked':len(manifest['files']),'issues':issues,'scope':'File integrity relative to this manifest; not a signature or an intellectual-property certification.'},indent=2))
raise SystemExit(2 if issues else 0)
