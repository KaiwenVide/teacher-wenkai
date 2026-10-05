from __future__ import annotations
import re
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from pathlib import Path
from .common import digest, now

STATUSES=['pending','supported','partially_supported','contradicted','not_found','insufficient_access','not_assessable']
UNITS={'number':('number',Decimal(1)),'fraction':('ratio',Decimal(1)),'%':('ratio',Decimal('.01')),'percent':('ratio',Decimal('.01')),'percentage_point':('percentage_point',Decimal(1)),'mg':('mass',Decimal('.001')),'g':('mass',Decimal(1)),'ug':('mass',Decimal('.000001')),'μg':('mass',Decimal('.000001')),'µg':('mass',Decimal('.000001')),'ng':('mass',Decimal('.000000001')),'mL':('volume',Decimal('.001')),'L':('volume',Decimal(1)),'uL':('volume',Decimal('.000001')),'μL':('volume',Decimal('.000001')),'s':('time',Decimal(1)),'min':('time',Decimal(60)),'h':('time',Decimal(3600))}


def numeric_check(reported,source,reported_unit='number',source_unit='number',decimal_places=None):
    if reported_unit not in UNITS or source_unit not in UNITS: raise ValueError('Unsupported unit; use an explicitly documented conversion before comparing')
    a,fa=UNITS[reported_unit]; b,fb=UNITS[source_unit]
    if a!=b: return {'status':'incompatible_units','reported_unit':reported_unit,'source_unit':source_unit,'semantic_support':'not_assessed'}
    try: actual=Decimal(str(reported)); expected=Decimal(str(source))*fb/fa
    except InvalidOperation: raise ValueError('Values must be decimal numbers') from None
    if not actual.is_finite() or not expected.is_finite(): raise ValueError('Values must be finite')
    if decimal_places is not None and not 0<=decimal_places<=12: raise ValueError('Decimal places must be 0..12')
    exact=actual==expected
    rounded=decimal_places is not None and actual==expected.quantize(Decimal(1).scaleb(-decimal_places),rounding=ROUND_HALF_UP)
    return {'status':'exact_or_unit_equivalent' if exact else 'compatible_with_declared_rounding' if rounded else 'numeric_mismatch','reported':str(actual),'source_in_reported_unit':str(expected),'decimal_places':decimal_places,'rounding':'half_up' if decimal_places is not None else None,'semantic_support':'not_assessed; check population, endpoint, denominator, timepoint, CI and adjustment'}


def new_claims(text):
    # Deliberately split paragraphs only; do not invent atomic claim boundaries.
    paragraphs=[x.strip() for x in re.split(r'\n\s*\n',text) if x.strip()]
    return {'schema_version':'1.0','created_at':now(),'segmentation':'paragraph drafts; agent must split atomic claims and preserve parent_id','claims':[{'claim_id':'C'+str(i).zfill(4),'text':p,'status':'pending','evidence_type':'unassessed','sources':[],'semantic_review':None,'numeric_checks':[],'limitations':[]} for i,p in enumerate(paragraphs,1)]}


def validate_claims(doc,base=None,mode='doc-only'):
    issues=[]; ids=set(); base=Path(base or '.')
    for c in doc.get('claims',[]):
        cid=c.get('claim_id'); status=c.get('status'); sources=c.get('sources',[])
        def issue(code,msg): issues.append({'claim_id':cid,'code':code,'message':msg})
        if not cid or cid in ids: issue('id','Missing or duplicate claim ID')
        ids.add(cid)
        if status not in STATUSES: issue('status','Status outside shared vocabulary')
        if not c.get('text'): issue('text','Claim text is empty')
        if status in ['supported','partially_supported','contradicted']:
            if not sources: issue('source','Evidence judgment needs at least one source')
            review=c.get('semantic_review') or {}
            if not review.get('assessor') or not review.get('rationale'): issue('semantic_review','Numeric and metadata checks cannot establish support; record assessor and rationale')
            if not c.get('evidence_type') or c['evidence_type']=='unassessed': issue('evidence_type','Label direct evidence, extrapolation, counterevidence or mixed')
        for s in sources:
            if not s.get('locator'): issue('locator','Missing page/figure/table/paragraph/line anchor')
            if status in ['supported','partially_supported','contradicted'] and not s.get('excerpt'): issue('excerpt','Evidence judgment needs an anchored excerpt or visual transcription')
            if mode=='doc-only' and not s.get('path'): issue('mode','doc-only requires a local source, not a URL alone')
            if s.get('path'):
                p=base/s['path']
                if not p.is_file(): issue('path','Local source does not exist'); continue
                if not s.get('source_sha256'): issue('source_hash','Missing source hash')
                elif digest(p.read_bytes())!=s['source_sha256']: issue('source_hash','Source changed since it was assessed')
                if p.suffix.lower() in ['.txt','.md'] and s.get('excerpt'):
                    norm=lambda t: re.sub(r'\s+',' ',t).strip()
                    if norm(s['excerpt']) not in norm(p.read_text(encoding='utf-8')): issue('excerpt','Excerpt is absent from source text')
            elif not s.get('url'): issue('source','Source needs a file path or URL')
    return {'valid':not issues,'claims':len(doc.get('claims',[])),'issues':issues,'checked':'structure, text excerpts and hashes only; not semantic truth or visual accuracy'}
