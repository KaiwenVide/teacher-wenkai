from __future__ import annotations
import datetime as dt
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SKILL_ROOT = Path(__file__).resolve().parents[2]
SECRET_KEYS = {'api_key','apikey','key','token','access_token','authorization','x-api-key','email','mailto','tool'}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(value).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    fd, temp = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(data)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return path


def write(path, text):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def records(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and isinstance(value.get('records'), list):
        return value['records']
    raise ValueError('Expected a JSON array or an object with a records array')


def redact_url(url):
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode([(k, '[redacted]' if k.lower() in SECRET_KEYS else v) for k,v in parse_qsl(p.query,keep_blank_values=True)]), ''))


def safe_name(value, limit=96):
    s = re.sub(r'[^\w.\-]+', '_', str(value), flags=re.UNICODE).strip('._')[:limit]
    return s or 'artifact'


def within(root, relative):
    root = Path(root).resolve(); target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ValueError('Artifact path escapes its workspace')
    return target


def init_workspace(path, question='', review_type='targeted'):
    root = Path(path)
    marker = root/'project.json'
    if marker.exists():
        return {'status':'existing','workspace':str(root.resolve()),'project':load(marker)}
    if root.exists() and any(root.iterdir()):
        raise ValueError('Nonempty directory has no project.json; choose a dedicated research workspace')
    for name in ['sources','searches','library','claims','readers','review','notes','downloads','outputs']:
        (root/name).mkdir(parents=True,exist_ok=True)
    project = {'schema_version':'1.0','created_at':now(),'question':question,'review_type':review_type,'language':'zh-CN','evidence_policy':'primary-source; separate facts, inference and unknown','external_backends':{},'status':'active'}
    save(marker,project)
    save(root/'library/records.json',{'records':[]})
    save(root/'claims/claims.json',{'schema_version':'1.0','claims':[]})
    return {'status':'created','workspace':str(root.resolve()),'project':project}
