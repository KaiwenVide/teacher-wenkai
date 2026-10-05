from __future__ import annotations
import datetime as dt
import math
from pathlib import Path
from .model import normalize_record,deduplicate
from .common import save,load,write,digest,now


def prioritize(items,keywords,year=None):
    if not keywords: raise ValueError('Specify at least one topic keyword; ranking has a relevance gate')
    year=year or dt.date.today().year; rows=[]
    for raw in items:
        r=normalize_record(raw); text=(r['title']+' '+r['abstract']).casefold(); matches=[k for k in keywords if k.casefold() in text]
        relevance=len(matches)/len(keywords); recency=max(0,min(1,1-(year-r['year'])/10)) if isinstance(r.get('year'),int) else 0
        citations=max(0,r.get('citation_count') or 0); influence=min(1,math.log1p(citations)/math.log1p(1000))
        score=round(70*relevance+20*recency+10*influence,2) if matches else 0
        rows.append({**r,'reading_priority':{'score':score,'matched_keywords':matches,'relevance_gate_passed':bool(matches),'components':{'topic':round(70*relevance,2),'recency':round(20*recency,2),'citation_count':round(10*influence,2)},'prestige_weight':0,'author_network_weight':0,'evidence_certainty':'not_assessed'}})
    return {'records':sorted(rows,key=lambda r:r['reading_priority']['score'],reverse=True),'keywords':keywords,'year':year,'limitations':'Lexical heuristic; synonyms and conceptual relevance require review. Priority is not study quality or certainty.'}


def archive(workspace,items):
    root=Path(workspace)
    if not (root/'project.json').is_file(): raise ValueError('Initialize a research workspace before archiving')
    path=root/'library/records.json'; previous=load(path)['records'] if path.exists() else []
    result=deduplicate(previous+items); save(path,result)
    snap=root/'library/snapshots'/('records-'+digest(result)[:16]+'.json'); save(snap,result)
    return {'library':str(path),'snapshot':str(snap),'records':result['unique_count'],'duplicates_removed':result['duplicates_removed'],'conflicts':result['conflicts']}


def digest_report(items,output):
    rows=['# 文献阅读简报','','生成时间：'+now(),'','本文件仅汇总元数据与阅读优先级；未核验的全文结论不在此自动生成。','']
    for i,r in enumerate(items,1):
        r=normalize_record(r); ids=r['identifiers']; url='https://doi.org/'+ids['doi'] if ids.get('doi') else r.get('url','')
        rows += [f"## {i}. {r['title']}",'',f"{r.get('year') or '年份待核'} · {r.get('journal') or '期刊待核'}",'',url,'']
        if r.get('reading_priority'): rows += ['阅读优先级：'+str(r['reading_priority']['score'])+' / 100（不代表证据强度）','']
        rows += ['已访问层级：'+r.get('access_level','metadata'),'','关键问题、直接证据、反证、外推限制：待原文精读。','']
    write(output,'\n'.join(rows)); return {'output':str(output),'records':len(items),'status':'metadata_digest'}
