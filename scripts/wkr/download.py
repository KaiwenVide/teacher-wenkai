from __future__ import annotations
import io
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit
from .common import load,save,digest,safe_name,now,redact_url
from .http import Client,NetworkError
from .providers import oa_lookup
from .model import normalize_doi


def inspect_payload(data,kind='main'):
    stripped=data.lstrip(); result={'valid':False,'format':None,'validation':None}
    if stripped[:1024].lower().startswith((b'<!doctype html',b'<html')) or b'<html' in stripped[:1024].lower(): return {**result,'reason':'HTML landing page or access challenge, not a downloaded paper'}
    if b'%PDF-' in data[:1024]:
        try:
            from pypdf import PdfReader
        except ImportError:
            return {'valid':True,'format':'pdf','validation':'magic_only; install pypdf for structural validation','identity':'not_verified'}
        try:
            doc=PdfReader(io.BytesIO(data), strict=True)
            if len(doc.pages)<1: return {**result,'reason':'PDF has no pages'}
            return {'valid':True,'format':'pdf','validation':'opened_with_pypdf','pages':len(doc.pages),'identity':'not_verified'}
        except Exception: return {**result,'reason':'PDF signature present but parser could not open it'}
    if stripped.startswith(b'<'):
        try:
            root=ET.fromstring(data)
            if root.tag.split('}')[-1]=='article' and root.find('.//body') is not None:
                return {'valid':True,'format':'xml','validation':'JATS article with body','identity':'not_verified'}
        except ET.ParseError: pass
    if kind=='supplement':
        import zipfile
        if data.startswith(b'PK'):
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    # Inspect the central directory without decompressing untrusted archives.
                    if z.infolist(): return {'valid':True,'format':'zip','validation':'zip_directory_readable; content and archive members not validated','identity':'not_verified'}
            except zipfile.BadZipFile: pass
        if data.startswith((b'\x89PNG\r\n\x1a\n',b'\xff\xd8\xff')):
            return {'valid':True,'format':'png' if data.startswith(b'\x89PNG') else 'jpg','validation':'magic_only','identity':'not_verified'}
    return {**result,'reason':'Unsupported or unverifiable file content; obtain the file through the authorized publisher page and inspect it'}


def download_batch(items,out,client=None):
    out=Path(out); out.mkdir(parents=True,exist_ok=True); manifest=out/'download-manifest.json'
    state=load(manifest) if manifest.exists() else {'schema_version':'1.0','policy':'open_access_or_user_authorized','items':{}}
    client=client or Client(max_bytes=128*1024*1024); results=[]
    for item in items:
        item={'doi':item} if isinstance(item,str) else dict(item)
        kind=item.get('kind','main')
        if kind not in ['main','supplement']: raise ValueError('kind must be main or supplement')
        doi=normalize_doi(item.get('doi') or (item.get('identifiers') or {}).get('doi'))
        url=item.get('url'); identifier=doi or url
        if not identifier: results.append({'status':'invalid_input','error':'Provide DOI or authorized URL'}); continue
        key=digest([identifier,kind])[:20]; previous=state['items'].get(key)
        if previous and previous.get('status')=='downloaded':
            p=out/previous['file']
            if p.is_file() and digest(p.read_bytes())==previous.get('sha256'):
                results.append({**previous,'reused':True}); continue
        entry={'item_id':key,'doi':doi or None,'kind':kind,'status':'pending','attempts':[],'checked_at':now()}
        if url:
            if item.get('access') not in ['open_access','user_authorized']:
                entry.update(status='authorization_not_recorded',next_action='Record open_access or user_authorized access for the URL')
                results.append(entry); state['items'][key]=entry; save(manifest,state); continue
            locations=[{'url':url,'access':item['access'],'source':'provided_url'}]
        elif kind=='supplement':
            locations=[]; entry.update(status='supplement_url_required',next_action='Locate the actual supplement link on the authorized article page; DOI alone identifies the main article')
        else:
            lookup=oa_lookup(doi,client); locations=sorted(lookup['locations'],key=lambda x:x.get('format')!='pdf'); entry['oa_lookup']=lookup
        for location in locations:
            u=location['url']; start=len(client.requests)
            try:
                data=client.fetch(u,headers={'Accept':'application/pdf,application/xml;q=0.9,*/*;q=0.5'})
                checked=inspect_payload(data,kind)
                entry['attempts'].append({'url':redact_url(u),'inspection':checked,'requests':client.requests[start:]})
                if not checked['valid']: continue
                name=safe_name(doi or urlsplit(u).path.split('/')[-1] or 'paper',70)+'-'+key[:8]+'.'+checked['format']
                path=out/name; temp=path.with_suffix(path.suffix+'.part'); temp.write_bytes(data); temp.replace(path)
                entry.update(status='downloaded',file=name,bytes=len(data),sha256=digest(data),source_url=redact_url(u),access=location['access'],inspection=checked)
                break
            except (NetworkError,ValueError) as e: entry['attempts'].append({'url':redact_url(u),'error':str(e),'requests':client.requests[start:]})
        if entry['status']=='pending': entry.update(status='fulltext_unavailable',next_action='Use an authorized publisher/institution browser session, or request a local source; do not treat metadata or HTML as full text')
        state['items'][key]=entry; save(manifest,state); results.append(entry)
    return {'results':results,'manifest':str(manifest),'successful':sum(x.get('status')=='downloaded' for x in results),'total':len(results),'identity_policy':'File validation is separate from article identity; verify first-page title/DOI and supplement association.'}
