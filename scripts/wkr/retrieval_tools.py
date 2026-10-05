"""Original bounded pagination and entitlement-aware publisher downloads."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
from urllib.parse import quote, urlsplit
from .common import emit, load, save, digest
from .http import Client
from .providers import provider_request, PROVIDERS
from .download import download_batch
from .model import normalize_doi
from .lifesciences import _select


def paginate(source, path, params, record_path, limit=100, pages=3, mode='offset', page_key='offset', size_key='limit', cursor_path=None, client=None):
    if not 1 <= limit <= 1000 or not 1 <= pages <= 10: raise ValueError('Use 1..1000 records and 1..10 pages')
    if mode == 'cursor' and not cursor_path: raise ValueError('Cursor pagination requires cursor_path')
    client = client or Client(); query = dict(params); rows = []; seen = set(); requests = []; seen_pages = set()
    query.setdefault(size_key, min(100, limit))
    token = query.get(page_key, '*' if mode == 'cursor' else 0)
    exhausted = False; repeated = False
    for page in range(pages):
        query[page_key] = token
        key = digest(query)
        if key in seen_pages: repeated = True; break
        seen_pages.add(key)
        response = provider_request(client, source, path, query)
        items = _select(response, record_path)
        if not isinstance(items, list): raise ValueError('record_path must select an array')
        requests.append({'page': page+1, 'received': len(items), 'parameters': {k:v for k,v in query.items() if k not in ['api_key','key','token','email']}})
        for row in items:
            identity = digest(row)
            if identity not in seen: seen.add(identity); rows.append(row)
        if not items: exhausted = True; break
        if len(rows) >= limit: break
        if mode == 'offset': token = int(token)+len(items)
        else:
            new = _select(response, cursor_path)
            if not new: exhausted = True; break
            if new == token: repeated = True; break
            token = new
    return {'records': rows[:limit], 'pages': requests, 'requests': client.requests, 'exhausted': exhausted,
            'repeated_cursor': repeated, 'truncated': len(rows)>limit or not exhausted,
            'scope': 'Deduplicated raw provider records; no exhaustive-search claim unless exhaustion is observed.'}


class EntitledClient(Client):
    def __init__(self, origin, credentials):
        super().__init__(max_bytes=128*1024*1024)
        self.origin = origin; self.credentials = credentials
    def fetch(self, url, **kwargs):
        if urlsplit(url).netloc == self.origin:
            kwargs['headers'] = {**kwargs.get('headers',{}), **self.credentials}
        return super().fetch(url, **kwargs)


def publisher_download(dois, route, out, supplement_queue=None):
    normalized = [normalize_doi(x) for x in dois]
    if not normalized or not all(normalized): raise ValueError('Supply valid DOI identifiers')
    client = None
    if route == 'elsevier':
        key = os.environ.get('ELSEVIER_API_KEY') or os.environ.get('ELS_API_KEY')
        if not key: raise ValueError('Configure ELSEVIER_API_KEY for an entitled Elsevier API request')
        headers = {'X-ELS-APIKey':key}
        token = os.environ.get('ELSEVIER_INST_TOKEN') or os.environ.get('ELS_INST_TOKEN')
        if token: headers['X-ELS-Insttoken'] = token
        client = EntitledClient('api.elsevier.com', headers)
        items = [{'doi':doi,'url':'https://api.elsevier.com/content/article/doi/'+quote(doi,safe='/')+'?httpAccept=application%2Fpdf','access':'user_authorized'} for doi in normalized]
    elif route == 'wiley':
        token = os.environ.get('WILEY_TDM_TOKEN')
        if not token: raise ValueError('Configure a legitimately issued WILEY_TDM_TOKEN')
        client = EntitledClient('api.wiley.com', {'Wiley-TDM-Client-Token':token})
        items = [{'doi':doi,'url':'https://api.wiley.com/onlinelibrary/tdm/v1/articles/'+quote(doi,safe=''),'access':'user_authorized'} for doi in normalized]
    else:
        # Metadata/OA resolvers retain the actual PDF/XML landing location and access classification.
        items = [{'doi':doi} for doi in normalized]
    result = download_batch(items, out, client)
    if supplement_queue:
        supplements = load(supplement_queue)
        supplements = supplements if isinstance(supplements,list) else supplements.get('items',[])
        if any(x.get('kind') != 'supplement' for x in supplements): raise ValueError('Each supplement item must declare kind=supplement and its authorized URL')
        result['supplements'] = download_batch(supplements, out, client)
    result['publisher_route'] = route
    result['institution_browser'] = 'Use the authorized host browser when entitlement requires an interactive session; no cookies or tokens are copied.'
    return result


def run(name, argv):
    p = argparse.ArgumentParser(prog=name)
    if name == 'paginate':
        p.add_argument('source',choices=PROVIDERS); p.add_argument('path'); p.add_argument('--params',default='{}')
        p.add_argument('--record-path',required=True); p.add_argument('--limit',type=int,default=100); p.add_argument('--pages',type=int,default=3)
        p.add_argument('--mode',choices=['offset','cursor'],default='offset'); p.add_argument('--page-key',default='offset'); p.add_argument('--size-key',default='limit'); p.add_argument('--cursor-path')
        p.add_argument('--out',type=Path,required=True); a=p.parse_args(argv)
        import json
        result=paginate(a.source,a.path,json.loads(a.params),a.record_path,a.limit,a.pages,a.mode,a.page_key,a.size_key,a.cursor_path)
        save(a.out,result); emit(result); return 0
    p.add_argument('--dois',nargs='+',required=True); p.add_argument('--route',choices=['oa','springer_nature','elsevier','wiley'],default='oa')
    p.add_argument('--out',type=Path,required=True); p.add_argument('--supplements',type=Path)
    p.add_argument('--no-si',action='store_true'); p.add_argument('--si',action='store_true')
    a=p.parse_args(argv)
    if a.si and not a.supplements: raise ValueError('--si requires --supplements with actual authorized supplement URLs')
    dois=[x for value in a.dois for x in value.split(',') if x]
    result=publisher_download(dois,a.route,a.out,a.supplements); emit(result)
    failed=result['successful']<result['total'] or result.get('supplements',{}).get('successful',0)<result.get('supplements',{}).get('total',0)
    return 2 if failed else 0
