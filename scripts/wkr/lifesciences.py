"""Bounded native database retrieval with inspectable source and failure records."""
from __future__ import annotations
import json
import os
import re
from pathlib import Path
from urllib.parse import unquote
from .common import SKILL_ROOT, load, now, digest, save, write, redact_url, SECRET_KEYS
from .http import Client, NetworkError
from .database_protocols import prepare_request


def catalog():
    result = load(SKILL_ROOT/'references/life-sciences-catalog.json')
    for spec in result['providers'].values(): spec['backend'] = 'native'
    result['availability_note'] = '44 native protocol integrations; presence is not live endpoint validation. No external plugin client is executed.'
    return result


def _redact(value):
    if isinstance(value, dict): return {k: '[redacted]' if k.lower() in SECRET_KEYS else _redact(v) for k,v in value.items()}
    if isinstance(value, list): return [_redact(v) for v in value]
    return value


def _error(code, message, status=None, checked=None):
    return {'ok': False, 'status_code': status, 'error': {'code': code, 'message': message}, 'records': [], 'sources': [], 'checked_sources': checked or []}


def _select(data, selector):
    if selector is None:
        return data.get('results', data) if isinstance(data, dict) else data
    if not isinstance(selector, str) or not re.fullmatch(r'[A-Za-z0-9_@.]*', selector): raise ValueError('record_path must contain dot-separated keys or array indices')
    value = data
    for key in selector.split('.') if selector else []:
        if isinstance(value, dict) and key in value: value = value[key]
        elif isinstance(value, list) and key.isdigit() and int(key) < len(value): value = value[int(key)]
        else: raise ValueError('Requested record_path is missing from the response')
    return value


def _compact(data, max_items, max_depth):
    cuts = []
    def visit(value, path='', depth=0):
        if isinstance(value, (dict, list)) and depth >= max_depth:
            cuts.append(path or '$'); return {'_omitted': 'maximum depth reached'}
        if isinstance(value, list):
            if len(value) > max_items: cuts.append(path or '$')
            return [visit(v, path+'.'+str(i), depth+1) for i,v in enumerate(value[:max_items])]
        if isinstance(value, dict): return {k: visit(v, path+'.'+k, depth+1) for k,v in value.items()}
        if isinstance(value, str) and len(value) > 8000: cuts.append(path); return value[:8000]+' [truncated]'
        return value
    return visit(data), cuts


def _execute(provider, payload, spec, client):
    prepared = prepare_request(provider, payload, spec, client)
    base = prepared['base']; path = prepared['path'].lstrip('/')
    decoded = unquote(path)
    if base not in spec['bases'] or '..' in decoded.split('/') or any(x in decoded for x in ['?', '#', '\\']) or re.match(r'^https?:', decoded):
        return _error('invalid_origin_or_path', 'Use an allowed provider origin and a relative path')
    if not path: raise ValueError('A relative API path is required')
    if any(k.lower() not in ['accept','content-type'] for k in prepared['headers']): raise ValueError('Keep credentials out of JSON request headers; use supported environment variables')
    body, form = prepared['body'], prepared['form']
    method = str(payload.get('method', 'POST' if body is not None or form is not None else 'GET')).upper()
    if method == 'GET' and (body is not None or form is not None): raise ValueError('GET requests cannot contain POST bodies')
    if method == 'POST':
        allowed = prepared['protocol'] == 'graphql' or (provider == 'string' and path in ['network','interaction_partners','get_string_ids','enrichment','functional_annotation','ppi_enrichment']) or (provider == 'cbioportal' and path.endswith('/fetch')) or (provider == 'rcsb-pdb' and base == spec['bases'][1] and path == 'query')
        if not allowed: raise ValueError('POST is restricted to known retrieval endpoints')
        if body is None and form is None: raise ValueError('A retrieval POST body is required')
    params = prepared['params']
    if provider == 'ncbi-entrez':
        if os.environ.get('NCBI_API_KEY'): params['api_key'] = os.environ['NCBI_API_KEY']
        if os.environ.get('NCBI_EMAIL'): params['email'] = os.environ['NCBI_EMAIL']
        params.setdefault('tool', 'teacher-wenkai')
    url = base+'/'+path
    headers = {'Accept': 'application/json', **prepared['headers']}
    limit = int(payload.get('max_results', payload.get('max_items', 20)))
    depth = int(payload.get('max_depth', 10))
    if not 1 <= limit <= 1000 or not 1 <= depth <= 20: raise ValueError('max_items/max_results must be 1..1000 and max_depth 1..20')
    max_pages = int(payload.get('max_pages', 1))
    if not 1 <= max_pages <= 5: raise ValueError('max_pages must be 1..5')
    all_records = []; raw_pages = []; next_token = None; details = dict(prepared['details'])
    for page in range(max_pages):
        if page:
            if not next_token: break
            params['pageToken'] = next_token
        if prepared['response_format'] in ['text','xml','fasta']:
            raw = client.fetch(url, params=params, headers={**headers, 'Accept': '*/*'}, body=body, form=form)
            text = raw.decode('utf-8', errors='replace')
            if payload.get('save_raw'): Path(payload['raw_output_path']).parent.mkdir(parents=True, exist_ok=True); Path(payload['raw_output_path']).write_bytes(raw)
            source = {'url': client.requests[-1]['url'], 'accessed_at': now(), 'level': 'text_excerpt', 'supports_claim': False}
            return {'ok': True, 'records': [], 'text_head': text[:8000], 'truncated': len(text)>8000, 'sources': [source], 'checked_sources': [source], 'status_code': 200}
        data = client.json(url, params=params, headers=headers, body=body, form=form)
        raw_pages.append(data)
        if isinstance(data, dict) and (data.get('error') or data.get('errors') or data.get('errCode') or data.get('Fault')):
            return _error('provider_error', 'Provider returned an error object; no biological evidence inferred', checked=client.requests)
        if prepared['details'].get('clinical_tables'):
            if not isinstance(data, list) or len(data)<4: raise ValueError('Clinical Tables response shape changed')
            all_records.extend([{'code': code, 'display': row, 'extra': {k: v[i] if isinstance(v,list) and i<len(v) else v for k,v in (data[2] or {}).items()}}
                                for i,(code,row) in enumerate(zip(data[1], data[3]))])
            details['total_count'] = data[0]
        else:
            selected = _select(data, prepared['selector'])
            all_records.extend(selected if isinstance(selected, list) else [selected])
        next_token = data.get('nextPageToken') if isinstance(data, dict) and provider == 'clinicaltrials' else None
        if isinstance(data, dict):
            for key in ['paging_info','pagingInfo','totalCount','regions']:
                if key in data: details[key] = data[key]
        if len(all_records) >= limit or not next_token: break
    if payload.get('save_raw'): save(payload['raw_output_path'], raw_pages[0] if len(raw_pages)==1 else raw_pages)
    records, cuts = _compact(all_records, limit, depth)
    details, detail_cuts = _compact(details, limit, depth)
    cuts += ['details'+p for p in detail_cuts]
    source = {'url': client.requests[-1]['url'] if client.requests else url, 'accessed_at': now(), 'level': 'database_annotation', 'supports_claim': False}
    return {'ok': True, 'status_code': 200, 'records': records, 'record_count_returned': len(records),
            'record_count_received': len(all_records), 'truncated': bool(cuts or next_token), 'truncated_paths': cuts,
            'pages_fetched': len(raw_pages), 'next_page_token': next_token,
            'pagination': 'bounded response; not an exhaustive database search', 'details': details,
            'sources': [source] if records else [], 'checked_sources': [source]}


def request(provider, payload, out=None, client=None):
    registry = catalog()['providers']
    if provider not in registry: raise ValueError('Unknown database provider: '+provider)
    if not isinstance(payload, dict): raise ValueError('Database request must be an object')
    p = dict(payload)
    if str(p.get('method', 'GET')).upper() not in ['GET','POST']: raise ValueError('Only retrieval GET/POST requests are exposed')
    if p.get('query_path'): p['query'] = Path(p.pop('query_path')).read_text(encoding='utf-8')
    if p.get('save_raw') and not p.get('raw_output_path'): raise ValueError('save_raw requires an explicit local raw_output_path')
    client = client or Client(timeout=min(60, max(1, int(p.get('timeout_sec',30)))))
    if provider=='eqtl-catalogue':
        from .local_tables import catalogue_query
        return catalogue_query(p,out)
    try: data = _execute(provider,p,registry[provider],client)
    except NetworkError as exc:
        checked = [{'url': x.get('url'), 'status_code': x.get('status'), 'supports_claim': False} for x in client.requests]
        data = _error('http_not_found' if exc.status==404 else 'request_failed',str(exc),exc.status,checked)
    data['requests'] = client.requests
    result = {'provider': provider, 'backend': 'native', 'implementation_version': '3.0.0', 'checked_at': now(),
              'request_sha256': digest(p), 'request': _redact(p), 'response': data,
              'evidence_status': 'annotation_requires_context' if data.get('ok') and data.get('sources') else 'checked_only_not_support'}
    if out: save(out,result)
    return result


def gene_request(symbol, taxon_id):
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', str(symbol)): raise ValueError('Use a gene symbol, not a protein description or group')
    if not str(taxon_id).isdigit() or int(taxon_id) <= 0: raise ValueError('Explicit NCBI taxonomy ID required')
    return {'path': 'uniprotkb/search', 'params': {'query': f'gene_exact:{symbol} AND organism_id:{taxon_id} AND reviewed:true',
            'fields': 'accession,gene_names,organism_id,protein_name', 'size': 10, 'format': 'json'}, 'record_path': 'results', 'max_items': 10}


def resolve_accession(result, symbol, taxon_id):
    response = result.get('response', {})
    if not response.get('ok'): return {'status': 'lookup_failed'}
    matches = set()
    for record in response.get('records', []):
        if not isinstance(record, dict): continue
        names = [x.get('geneName', {}).get('value') for x in record.get('genes', []) if isinstance(x, dict)]
        if symbol in names and str(record.get('organism', {}).get('taxonId')) == str(taxon_id) and record.get('primaryAccession'):
            matches.add(record['primaryAccession'])
    candidates = sorted(matches)
    return {'status': 'resolved' if len(candidates) == 1 else 'ambiguous' if candidates else 'not_resolved',
            'accession': candidates[0] if len(candidates) == 1 else None, 'candidates': candidates}


def annotation_request(accession, provider, taxon_id=None):
    if not re.fullmatch(r'[A-Z0-9]+(?:-\d+)?', accession): raise ValueError('Invalid accession')
    if provider == 'reactome':
        if not str(taxon_id).isdigit() or int(taxon_id) <= 0:
            raise ValueError('Explicit NCBI taxonomy ID required for automatic Reactome mapping')
        return {'path': 'data/mapping/UniProt/'+accession+'/pathways',
                'params': {'species': int(taxon_id)}, 'max_items': 10}
    if provider == 'quickgo': return {'path': 'annotation/search', 'params': {'geneProductId': accession, 'limit': 10}, 'record_path': 'results', 'max_items': 10}
    raise ValueError('Unsupported automatic annotation provider')
