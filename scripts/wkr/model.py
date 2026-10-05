from __future__ import annotations
import html
import re
from urllib.parse import unquote
from .common import digest, now


def normalize_doi(value):
    value = unquote(str(value or '').strip())
    value = re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi\s*:\s*)','',value,flags=re.I)
    value = value.strip().rstrip('.,;')
    if not re.fullmatch(r'10\.\d{4,9}/\S+',value,flags=re.I):
        return ''
    # DOI parentheses may be significant. Never strip them unconditionally.
    return value.lower()


def normalize_title(value):
    return re.sub(r'[^\w]+',' ',html.unescape(re.sub('<[^>]+>',' ',str(value))),flags=re.UNICODE).casefold().strip()


def author(value):
    if isinstance(value,dict):
        if value.get('name') and not value.get('family'):
            return {'literal':value['name']}
        if value.get('literal'):
            return {'literal':value['literal']}
        return {k:value[k] for k in ['given','family','display','unparsed','orcid'] if value.get(k)}
    value=str(value).strip()
    if ',' in value:
        family,given=value.split(',',1)
        return {'family':family.strip(),'given':given.strip()}
    return {'display':value,'unparsed':True}


def author_display(a):
    if isinstance(a,str): return a
    return a.get('literal') or a.get('display') or ' '.join(x for x in [a.get('given'),a.get('family')] if x)


def record_id(r):
    ids=r.get('identifiers',{})
    doi=normalize_doi(ids.get('doi') or r.get('doi'))
    if ids.get('arxiv') and re.search(r'v[0-9]+$',str(ids['arxiv'])): return 'arxiv:'+str(ids['arxiv'])
    if doi: return 'doi:'+doi
    for key in ['pmid','pmcid','arxiv','openalex','s2']:
        if ids.get(key): return key+':'+str(ids[key])
    return 'rec:'+digest([normalize_title(r.get('title','')),r.get('year'),r.get('authors')])[:20]


def normalize_record(r):
    r=dict(r)
    ids={k:v for k,v in (r.get('identifiers') or {}).items() if v is not None and v!=''}
    doi=normalize_doi(ids.get('doi') or r.get('doi'))
    if doi: ids['doi']=doi
    elif ids.get('doi'):
        r.setdefault('unparsed_identifiers',{})['doi']=ids.pop('doi')
    r['identifiers']=ids
    r['authors']=[author(a) for a in r.get('authors',[])]
    r.setdefault('title',''); r.setdefault('year',None)
    r.setdefault('journal',''); r.setdefault('abstract','')
    r.setdefault('record_type','article'); r.setdefault('access_level','abstract' if r.get('abstract') else 'metadata')
    r.setdefault('provenance',[]); r.setdefault('oa_locations',[])
    r['record_id']=record_id(r)
    return r


def doi_set(r):
    d=normalize_doi(r.get('identifiers',{}).get('doi'))
    return {d} if d else set()


def can_merge(a,b):
    if doi_set(a) and doi_set(b) and doi_set(a)!=doi_set(b): return False
    ai,bi=a.get('identifiers',{}),b.get('identifiers',{})
    if ai.get('arxiv') and bi.get('arxiv') and str(ai['arxiv'])!=str(bi['arxiv']): return False
    # A versioned arXiv record is a report version, not the same search record.
    for key in ['doi','pmid','pmcid','arxiv','openalex','s2']:
        if ai.get(key) and bi.get(key) and str(ai[key]).casefold()==str(bi[key]).casefold(): return True
    if ai or bi: return False
    title=normalize_title(a.get('title',''))
    aa=[author_display(x).casefold() for x in a.get('authors',[])]; ba=[author_display(x).casefold() for x in b.get('authors',[])]
    return bool(len(title)>24 and title==normalize_title(b.get('title','')) and a.get('year') and a['year']==b.get('year') and aa and ba and aa[0]==ba[0])


def deduplicate(items):
    result=[]; merged=[]; conflicts=[]
    for raw in items:
        r=normalize_record(raw)
        target=next((x for x in result if can_merge(x,r)),None)
        if target is None:
            result.append(r); continue
        merged.append({'kept':target['record_id'],'merged':r['record_id']})
        for k,v in r.items():
            if k in ['provenance','oa_locations']:
                for item in v:
                    if item not in target[k]: target[k].append(item)
            elif k=='identifiers': target[k].update({ik:iv for ik,iv in v.items() if ik not in target[k]})
            elif not target.get(k) and v: target[k]=v
            elif k in ['title','year','authors'] and v and target.get(k)!=v:
                conflicts.append({'record_id':target['record_id'],'field':k,'kept':target[k],'alternative':v})
        target['record_id']=record_id(target)
    return {'records':result,'input_count':len(items),'unique_count':len(result),'duplicates_removed':len(merged),'merge_log':merged,'conflicts':conflicts,'study_linking':'not_performed; link reports separately'}


def scope_match(journal,scope):
    j=re.sub(r'\s+',' ',journal.strip()).casefold()
    if scope=='all': return True
    if scope=='flagship': return j in {'nature','science','cell'}
    nature = j=='nature' or j.startswith(('nature ','npj ','communications ')) or j in {'nature communications','scientific reports'}
    if scope=='nature': return nature
    science=j in {'science','science advances','science immunology','science robotics','science signaling','science translational medicine'}
    cell=j in {'cell','cancer cell','cell stem cell','cell metabolism','cell host & microbe','cell reports','cell reports medicine','cell systems','cell chemical biology','molecular cell','developmental cell','immunity','neuron','current biology','structure','joule','chem','matter','one earth','iscience','med','device','cell genomics'} or j.startswith('trends in ')
    return nature or science or cell
