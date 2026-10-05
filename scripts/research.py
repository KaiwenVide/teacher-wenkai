#!/usr/bin/env python3
"""teacher Wenkai: auditable local research tools. Run --help for commands."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from wkr.common import emit,save,load,records,write,init_workspace,SKILL_ROOT
from wkr.http import Client,NetworkError
from wkr.providers import PROVIDERS,SEARCH_SOURCES,search,provider_request,doi_lookup,oa_lookup
from wkr.model import deduplicate
from wkr.bibliography import export_records,verify_records,import_references
from wkr.claims import new_claims,validate_claims,numeric_check
from wkr.reader import prepare,validate_reader,render_reader
from wkr.download import download_batch
from wkr.review import screening_flow,freeze_packet,collect_reviews
from wkr.pipeline import prioritize,archive,digest_report
from wkr.adapters import doctor,run_adapter,scansci_request

PASSTHROUGH=['citation','reader-math','jats','arxiv-parse','openalex-abstract','paginate','paperclip','publisher-download']


def parser():
    p=argparse.ArgumentParser(description=__doc__); s=p.add_subparsers(dest='cmd',required=True)
    s.add_parser('doctor',help='Detect capabilities without network/authentication checks')
    x=s.add_parser('init'); x.add_argument('workspace',type=Path); x.add_argument('--question',default=''); x.add_argument('--type',choices=['targeted','scoping','systematic','narrative'],default='targeted')
    x=s.add_parser('search'); x.add_argument('query'); x.add_argument('--sources',default='pubmed,europepmc,crossref'); x.add_argument('--limit',type=int,default=20); x.add_argument('--scope',choices=['all','nature','cns','flagship'],default='all'); x.add_argument('--from-year',type=int); x.add_argument('--to-year',type=int); x.add_argument('--workspace',type=Path); x.add_argument('--out',type=Path)
    x=s.add_parser('api',help='Read-only request to a documented provider'); x.add_argument('source',choices=PROVIDERS); x.add_argument('path'); x.add_argument('--params',default='{}'); x.add_argument('--body-file',type=Path); x.add_argument('--raw',action='store_true'); x.add_argument('--out',type=Path)
    for name in ['lookup','oa']:
        x=s.add_parser(name); x.add_argument('doi'); x.add_argument('--out',type=Path)
    for name in ['dedupe','verify','import-refs']:
        x=s.add_parser(name); x.add_argument('input',type=Path); x.add_argument('--out',type=Path)
    x=s.add_parser('export'); x.add_argument('input',type=Path); x.add_argument('--format',choices=['json','csv','ris','bib','enw','rdf'],required=True); x.add_argument('--out',type=Path,required=True)
    x=s.add_parser('download'); x.add_argument('--input',type=Path); x.add_argument('--doi'); x.add_argument('--arxiv'); x.add_argument('--url'); x.add_argument('--access',choices=['open_access','user_authorized']); x.add_argument('--kind',choices=['main','supplement'],default='main'); x.add_argument('--out',type=Path,required=True)
    x=s.add_parser('claims-init'); x.add_argument('input',type=Path); x.add_argument('--out',type=Path,required=True)
    x=s.add_parser('claims-check'); x.add_argument('input',type=Path); x.add_argument('--base',type=Path); x.add_argument('--mode',choices=['doc-only','web'],default='doc-only'); x.add_argument('--out',type=Path)
    x=s.add_parser('numeric'); x.add_argument('reported'); x.add_argument('source'); x.add_argument('--reported-unit',default='number'); x.add_argument('--source-unit',default='number'); x.add_argument('--decimal-places',type=int)
    x=s.add_parser('reader-prepare'); x.add_argument('source',type=Path); x.add_argument('--out',type=Path,required=True); x.add_argument('--render-pages',action='store_true')
    for name in ['reader-check','reader-render']:
        x=s.add_parser(name); x.add_argument('source_map',type=Path); x.add_argument('translations',type=Path)
        if name=='reader-render': x.add_argument('--out',type=Path,required=True)
    x=s.add_parser('screen-init'); x.add_argument('input',type=Path); x.add_argument('--out',type=Path,required=True)
    x=s.add_parser('flow'); x.add_argument('ledger',type=Path); x.add_argument('--out',type=Path)
    x=s.add_parser('review-packet'); x.add_argument('files',nargs='+',type=Path); x.add_argument('--reviewers',type=int,default=3); x.add_argument('--out',type=Path,required=True)
    x=s.add_parser('review-collect'); x.add_argument('packet',type=Path); x.add_argument('reports',nargs='+',type=Path); x.add_argument('--out',type=Path)
    x=s.add_parser('question-init'); x.add_argument('question'); x.add_argument('--out',type=Path,required=True)
    x=s.add_parser('rank'); x.add_argument('input',type=Path); x.add_argument('--keywords',nargs='+',required=True); x.add_argument('--year',type=int); x.add_argument('--out',type=Path)
    x=s.add_parser('archive'); x.add_argument('input',type=Path); x.add_argument('--workspace',type=Path,required=True)
    x=s.add_parser('digest'); x.add_argument('input',type=Path); x.add_argument('--out',type=Path,required=True)
    x=s.add_parser('scansci-request'); x.add_argument('identifier'); x.add_argument('--download-dir',type=Path); x.add_argument('--out',type=Path)
    x=s.add_parser('data-profile'); x.add_argument('input',type=Path); x.add_argument('--sheet'); x.add_argument('--header-row',type=int,default=1); x.add_argument('--out',type=Path)
    for name in ['analyze','data-research']:
        x=s.add_parser(name); x.add_argument('config',type=Path); x.add_argument('--out',type=Path,required=True); x.add_argument('--no-figures',action='store_true'); x.add_argument('--no-notebook',action='store_true'); x.add_argument('--offline',action='store_true')
    x=s.add_parser('research-followup'); x.add_argument('analysis',type=Path); x.add_argument('--offline',action='store_true'); x.add_argument('--retry-failed',action='store_true')
    x=s.add_parser('study-plan'); x.add_argument('question'); x.add_argument('--out',type=Path,required=True); x.add_argument('--analysis',type=Path)
    x=s.add_parser('experiment-check'); x.add_argument('plan',type=Path); x.add_argument('--out',type=Path)
    x=s.add_parser('manuscript-build'); x.add_argument('plan',type=Path); x.add_argument('--claims',type=Path,required=True); x.add_argument('--out',type=Path,required=True)
    s.add_parser('database-list')
    x=s.add_parser('database'); x.add_argument('provider'); x.add_argument('--request',type=Path,required=True); x.add_argument('--out',type=Path)
    x=s.add_parser('enrich'); x.add_argument('--selected',type=Path,required=True); x.add_argument('--universe',type=Path,required=True); x.add_argument('--gmt',type=Path,required=True); x.add_argument('--out',type=Path)
    x=s.add_parser('notebook-execute'); x.add_argument('notebook',type=Path)
    for name in PASSTHROUGH: s.add_parser(name,help='Adapter; arguments passed to its help/implementation')
    return p


def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in PASSTHROUGH: return run_adapter(argv[0],argv[1:])
    a=parser().parse_args(argv); c=a.cmd; result=None; code=0; save_result=True
    if c=='doctor': result=doctor()
    elif c=='data-profile':
        from wkr.experiment_io import profile
        result=profile(a.input,a.sheet,a.header_row)
    elif c in ['analyze','data-research']:
        from wkr.experiment import run_analysis
        result=run_analysis(a.config,a.out,not a.no_notebook,not a.no_figures); save_result=False
        if c=='data-research':
            from wkr.data_research import followup
            result['research']=followup(a.out,offline=a.offline)
        code=2 if result['status']=='qc_blocked' else 0
    elif c=='research-followup':
        from wkr.data_research import followup
        result=followup(a.analysis,a.offline,a.retry_failed)
    elif c=='study-plan':
        from wkr.academic import study_plan
        result=study_plan(a.question,a.out,a.analysis); save_result=False
    elif c=='experiment-check':
        from wkr.academic import experiment_check
        result=experiment_check(load(a.plan)); code=0 if result['complete_for_review'] else 2
    elif c=='manuscript-build':
        from wkr.academic import manuscript_build
        result=manuscript_build(load(a.plan),load(a.claims),a.out,a.claims.parent); save_result=False
    elif c=='database-list':
        from wkr.lifesciences import catalog
        result=catalog()
    elif c=='database':
        from wkr.lifesciences import request
        result=request(a.provider,load(a.request)); code=0 if result['response'].get('ok') else 2
    elif c=='enrich':
        from wkr.experiment import enrich
        result=enrich(a.selected,a.universe,a.gmt)
    elif c=='notebook-execute':
        from wkr.experiment import execute_notebook
        result=execute_notebook(a.notebook)
    elif c=='init': result=init_workspace(a.workspace,a.question,a.type)
    elif c=='search':
        if a.workspace and not (a.workspace/'project.json').is_file(): raise ValueError('Initialize the workspace first')
        result=search(a.query,[x.strip() for x in a.sources.split(',')],a.limit,a.scope,a.from_year,a.to_year,a.workspace)
        if not any(b['status'] in ['ok','partial'] for b in result['searches']): code=2
        if a.workspace: result['archive']=archive(a.workspace,result['records'])
    elif c=='api':
        client=Client(); data=provider_request(client,a.source,a.path,json.loads(a.params),load(a.body_file) if a.body_file else None,a.raw)
        if a.raw:
            if not a.out: raise ValueError('--raw requires --out')
            a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_bytes(data); save(str(a.out)+'.provenance.json',{'requests':client.requests}); result={'raw_file':str(a.out),'requests':client.requests}; save_result=False
        else: result={'data':data,'requests':client.requests}
    elif c=='lookup': result=doi_lookup(a.doi)
    elif c=='oa': result=oa_lookup(a.doi)
    elif c=='import-refs': result=import_references(a.input)
    elif c=='dedupe': result=deduplicate(records(load(a.input)))
    elif c=='verify': result=verify_records(records(load(a.input)))
    elif c=='export':
        items=records(load(a.input)); warnings=[]
        if a.format=='json': save(a.out,{'records':items})
        else:
            content,warnings=export_records(items,a.format); write(a.out,content)
        result={'output':str(a.out),'records':len(items),'warnings':warnings}; save_result=False
    elif c=='download':
        if sum(bool(x) for x in [a.input,a.doi,a.url,a.arxiv])!=1: raise ValueError('Use exactly one of --input, --doi, --arxiv, --url')
        if a.input:
            value=load(a.input); items=value if isinstance(value,list) else value.get('items',value.get('records',[]))
        elif a.arxiv:
            import re
            identifier=re.sub(r'^https?://arxiv.org/(abs|pdf)/','',a.arxiv).removesuffix('.pdf')
            if not re.fullmatch(r'(?:\d{4}\.\d{4,5}|[a-z.-]+/\d{7})(?:v\d+)?',identifier): raise ValueError('Malformed arXiv identifier')
            items=[{'url':'https://arxiv.org/pdf/'+identifier,'access':'open_access','kind':a.kind}]
        else: items=[{'doi':a.doi,'url':a.url,'access':a.access,'kind':a.kind}]
        result=download_batch(items,a.out); save_result=False
        if result['successful']<result['total']: code=2
    elif c=='claims-init': result=new_claims(a.input.read_text(encoding='utf-8'))
    elif c=='claims-check': result=validate_claims(load(a.input),a.base or a.input.parent,a.mode); code=0 if result['valid'] else 2
    elif c=='numeric': result=numeric_check(a.reported,a.source,a.reported_unit,a.source_unit,a.decimal_places)
    elif c=='reader-prepare': result=prepare(a.source,a.out,a.render_pages); save_result=False
    elif c=='reader-check': result=validate_reader(load(a.source_map),load(a.translations)); code=0 if result['complete'] else 2
    elif c=='reader-render': result=render_reader(load(a.source_map),load(a.translations),a.out); save_result=False
    elif c=='screen-init': result={'schema_version':'1.0','records':[{'record_id':r['record_id'],'duplicate_of':None,'title_abstract_decision':'pending','report_id':None,'retrieval':'pending','fulltext_decision':'pending','exclusion_reason':None,'study_id':None,'assessors':[]} for r in deduplicate(records(load(a.input)))['records']],'note':'This ledger begins after input deduplication; add original duplicates explicitly to count pre-dedup identification.'}
    elif c=='flow': result=screening_flow(load(a.ledger)); code=0 if result['valid'] else 2
    elif c=='review-packet': result=freeze_packet(a.files,a.out,a.reviewers); save_result=False
    elif c=='review-collect': result=collect_reviews(a.packet,a.reports); code=0 if result['ready_for_synthesis'] else 2
    elif c=='question-init': result=load(SKILL_ROOT/'assets/templates/question.json'); result['question']=a.question
    elif c=='rank': result=prioritize(records(load(a.input)),a.keywords,a.year)
    elif c=='archive': result=archive(a.workspace,records(load(a.input)))
    elif c=='digest': result=digest_report(records(load(a.input)),a.out); save_result=False
    elif c=='scansci-request': result=scansci_request(a.identifier,a.download_dir)
    if save_result and getattr(a,'out',None): save(a.out,result)
    emit(result); return code


if __name__=='__main__':
    try: raise SystemExit(main())
    except (ValueError,OSError,NetworkError,KeyError,json.JSONDecodeError) as e:
        emit({'status':'error','error':str(e),'error_type':type(e).__name__}); raise SystemExit(2)
