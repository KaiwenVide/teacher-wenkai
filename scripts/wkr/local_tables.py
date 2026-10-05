"""Local summary-statistics access when the remote eQTL Catalogue API is retired."""
from __future__ import annotations
import csv
import gzip
from pathlib import Path
from .common import now,save,digest


def catalogue_query(payload,out=None):
    if not payload.get('local_file'):
        result={'provider':'eqtl-catalogue','backend':'native','checked_at':now(),'response':{
            'ok':False,'status_code':410,'error':{'code':'remote_api_retired','message':'The official REST API is deprecated. Obtain a specific dataset under its terms, then supply local_file and explicit filters.'},
            'records':[],'sources':[],'checked_sources':[{'url':'https://www.ebi.ac.uk/eqtl/Data_access/','supports_claim':False}],
            'status_origin':'documented retirement; no network request in this call'},'evidence_status':'checked_only_not_support'}
    else:
        path=Path(payload['local_file']).expanduser().resolve();filters=payload.get('filters')
        if not path.is_file(): raise ValueError('Local eQTL table is missing')
        if not isinstance(filters,dict) or not filters or any(not isinstance(v,(str,int)) for v in filters.values()): raise ValueError('Use explicit column-to-value filters')
        limit=int(payload.get('max_items',20));scan_limit=int(payload.get('max_scan_rows',100000))
        if not 1<=limit<=1000 or not 1<=scan_limit<=1000000: raise ValueError('Use max_items 1..1000 and max_scan_rows 1..1000000')
        opener=gzip.open if path.suffix=='.gz' else open;rows=[];scanned=0;exhausted=True
        with opener(path,'rt',encoding='utf-8-sig',newline='') as stream:
            reader=csv.DictReader(stream,delimiter='\t')
            if not reader.fieldnames or not set(filters)<=set(reader.fieldnames): raise ValueError('A filter column is absent from the TSV header')
            for row in reader:
                scanned+=1
                if all(str(row.get(k,''))==str(v) for k,v in filters.items()): rows.append(row)
                if scanned>=scan_limit or len(rows)>=limit: exhausted=False;break
        stat=path.stat()
        result={'provider':'eqtl-catalogue','backend':'native_local_table','checked_at':now(),
                'response':{'ok':True,'records':rows,'scanned_rows':scanned,'truncated':not exhausted,
                            'sources':[{'path':str(path),'bytes':stat.st_size,'mtime_ns':stat.st_mtime_ns,'supports_claim':False}] if rows else [],
                            'checked_sources':[{'path':str(path),'supports_claim':False}],
                            'scope':'Exact supplied-column filters over a bounded local scan; metadata identity, assembly, allele and full-file integrity require separate verification.'},
                'request_sha256':digest(payload),'evidence_status':'annotation_requires_context' if rows else 'checked_only_not_support'}
    if out:save(out,result)
    return result
