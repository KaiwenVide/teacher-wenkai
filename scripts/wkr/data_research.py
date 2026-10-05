"""Execute bounded, resumable public research from traceable local data signals."""
from __future__ import annotations
from pathlib import Path
import re
from .common import load,save,write,digest,now
from .providers import search
from .lifesciences import request,gene_request,resolve_accession,annotation_request


def feature_identity(feature,row,config):
    research=config.get('research',{}); mapping=research.get('feature_terms',{})
    if feature in mapping:
        item=mapping[feature]
        if isinstance(item,str): return {'term':item,'symbol':None}
        return {'term':item['public_term'],'symbol':item.get('gene_symbol')}
    ns=config['study'].get('feature_namespace')
    symbol=row.get('symbol') or (feature if ns=='gene_symbol' else None)
    if symbol and re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',str(symbol)): return {'term':str(symbol),'symbol':str(symbol)}
    if ns in ['uniprot','ensembl_gene'] and re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',str(feature)): return {'term':feature,'symbol':None}
    return None


def signals(analysis,config):
    if analysis['status']=='qc_blocked': return []
    opts=config.get('research',{}); alpha=float(config.get('analysis',{}).get('alpha',.05)); candidates=[]
    for row in analysis['results']:
        if row.get('signal_class')!='statistical_signal': continue
        identity=feature_identity(row['feature'],row,config)
        if identity: candidates.append({'kind':'differential','feature':row['feature'],'identity':identity,'data_result':row,'evidence_level':'exploratory differential association','priority':row['q_value']})
    # These are distinct analyses, not pooled post-hoc confirmatory tests.
    if not any(x['severity']=='warning' for x in analysis['issues']):
        for row in analysis['time_trends']:
            identity=feature_identity(row['feature'],row,config)
            if identity and row['status']=='tested' and row.get('q_value') is not None and row['q_value']<=alpha:
                candidates.append({'kind':'time_trend','feature':row['feature'],'identity':identity,'data_result':row,'evidence_level':'exploratory within-group linear time association','priority':row['q_value']})
        for row in analysis['correlations']['results']:
            if row['status']!='tested' or row['n_units']<8 or row.get('q_value') is None or row['q_value']>alpha or abs(row.get('rho') or 0)<float(opts.get('min_abs_rho',.6)): continue
            a=feature_identity(row['feature_a'],{},config); b=feature_identity(row['feature_b'],{},config)
            if a and b: candidates.append({'kind':'correlation','feature':row['feature_a']+' | '+row['feature_b'],'identity':{'term':a['term']+' '+b['term'],'symbol':None},'data_result':row,'evidence_level':'exploratory within-stratum correlation; small-sample approximation','priority':row['q_value']})
    chosen=[]; seen=set()
    for c in sorted(candidates,key=lambda c:(c['priority'],c['kind'],c['feature'])):
        # Keep data result IDs and avoid treating repeated contrasts as independent discoveries.
        key=c['feature']
        if key in seen: continue
        seen.add(key); c['signal_id']='sig-'+digest([analysis['analysis_id'],c['kind'],c['data_result']])[:12]; chosen.append(c)
        if len(chosen)>=max(1,min(10,int(opts.get('max_signals',3)))): break
    return chosen


def followup(analysis_dir,offline=False,retry_failed=False,search_fn=None,database_fn=None):
    from .academic import validated_analysis
    root=Path(analysis_dir).resolve(); analysis,config=validated_analysis(root)
    opts=config.get('research',{}); search_fn=search_fn or search; database_fn=database_fn or request
    out=root/'research'; out.mkdir(exist_ok=True); selected=signals(analysis,config); save(out/'signals.json',selected)
    budget=max(1,min(50,int(opts.get('max_queries',12)))); limit=max(1,min(20,int(opts.get('papers_per_query',6))))
    sources=opts.get('sources',['pubmed','europepmc'])
    if not sources or any(x not in ['pubmed','europepmc','crossref','openalex'] for x in sources): raise ValueError('Use documented public literature providers')
    context=str(opts.get('public_context','')).strip(); organism=config['study'].get('organism',''); taxon=config['study'].get('taxon_id')
    state_path=out/'state.json'; previous=load(state_path) if state_path.exists() else None
    identity=digest([analysis['analysis_id'],opts,sources])
    if previous and previous.get('run_key')!=identity: raise ValueError('Research configuration changed; create a new analysis run')
    state=previous or {'run_key':identity,'analysis_id':analysis['analysis_id'],'created_at':now(),'queries':{},'attempts':0}
    def perform(kind,payload,callback):
        key=digest([kind,payload]); old=state['queries'].get(key)
        if old and (not retry_failed or old['status'] not in ['failed','partial']): return load(out/old['file'])
        if offline: return {'status':'pending_offline','query_kind':kind,'request':payload}
        if state['attempts']>=budget: return {'status':'budget_exhausted','query_kind':kind}
        state['attempts']+=1
        # Persist before execution so crashes do not reset the budget.
        save(state_path,state)
        try:
            response=callback()
            if kind=='literature':
                batches=response.get('searches',[]); status='completed' if batches and all(x['status']=='ok' for x in batches) else 'partial' if response.get('records') else 'failed'
            else: status='completed' if response.get('response',{}).get('ok') else 'failed'
            response={**response,'execution_status':status}
        except Exception as e: status='failed'; response={'execution_status':'failed','error_type':type(e).__name__,'error':str(e)[:500]}
        file='queries/'+key+'.json'; save(out/file,response); state['queries'][key]={'kind':kind,'status':status,'file':file,'checked_at':now(),'request':payload}; save(state_path,state)
        return response
    cards=[]
    for sig in selected:
        ident=sig['identity']; term=ident['term']; card={**sig,'database':[],'literature':[],'claim_support':'not_assessed','next_decisive_check':'Confirm direction in independent biological units; then perturb candidate and measure target dependence before expanding mechanisms.'}
        if ident.get('symbol') and taxon:
            payload=gene_request(ident['symbol'],taxon)
            result=perform('database',{'provider':'uniprot','request':payload},lambda p=payload:database_fn('uniprot',p)); card['database'].append(result)
            resolution=resolve_accession(result,ident['symbol'],taxon); card['identifier_resolution']=resolution
            if resolution['status']=='resolved':
                p=annotation_request(resolution['accession'],'reactome',taxon)
                card['database'].append(perform('database',{'provider':'reactome','request':p},lambda p=p:database_fn('reactome',p)))
        else: card['identifier_resolution']={'status':'requires_explicit_species_or_gene_mapping; literature_only'}
        base=' '.join(x for x in [term,organism,context] if x)
        for purpose,query in [('context',base),('causal_and_competing_evidence',base+' (knockout OR knockdown OR rescue OR inhibition OR "no effect" OR "not associated")')]:
            payload={'query':query,'sources':sources,'limit':limit}
            result=perform('literature',payload,lambda query=query:search_fn(query,sources,limit=limit))
            card['literature'].append({'purpose':purpose,'query':query,'response':result})
        cards.append(card)
    state.update(updated_at=now(),status='qc_blocked' if analysis['status']=='qc_blocked' else 'no_eligible_signal' if not selected else 'pending_offline' if offline else 'budget_exhausted' if any(x.get('status')=='budget_exhausted' for c in cards for x in c['database']+[a['response'] for a in c['literature']]) else 'retrieval_completed_requires_evidence_reading')
    if state['status']=='retrieval_completed_requires_evidence_reading':
        statuses=[x['status'] for x in state['queries'].values()]
        if statuses and all(x=='failed' for x in statuses): state['status']='retrieval_failed'
        elif any(x in ['failed','partial'] for x in statuses): state['status']='retrieval_partial_requires_evidence_reading'
    save(state_path,state); save(out/'evidence-cards.json',{'analysis_id':analysis['analysis_id'],'cards':cards,'boundary':'Database annotation is not causal validation; article retrieval is not claim support. Read original figures/results and mark direct evidence, extrapolation, counterevidence or unresolved.'})
    lines=['# 数据驱动的后续研究','',f"状态：`{state['status']}`；候选信号 {len(selected)}；已尝试逻辑查询 {state['attempts']}/{budget}。",'', '每次逻辑文献查询可能调用多个数据库并取详情，实际 HTTP 请求以查询记录为准。断点续跑复用已存结果；失败重试也消耗预算。', '', '原始值、样本 ID 和未公开实验条件保留本地。远程查询仅使用配置明确允许的公开特征、物种和 public_context。', '']
    for c in cards:
        lines += [f"## {c['feature']} · {c['signal_id']}",'',f"数据层级：{c['evidence_level']}。论断支持：未评估。",'']
        for lit in c['literature']:
            response=lit['response']; records=response.get('records',[])
            lines += [f"查询 `{lit['purpose']}`：{lit['query']}",f"实际返回 {len(records)} 条；状态 `{response.get('execution_status',response.get('status','unknown'))}`。"]
            for r in records[:5]:
                ids=r.get('identifiers',{}); url='https://doi.org/'+ids['doi'] if ids.get('doi') else 'https://pubmed.ncbi.nlm.nih.gov/'+str(ids['pmid'])+'/' if ids.get('pmid') else r.get('url','')
                lines.append('- '+(f"[{r.get('title','Untitled')}]({url})" if url else r.get('title','Untitled'))+' — 待读原文，不能据此标记支持。')
            lines.append('')
    lines += ['## Codex 继续执行','', '读取 evidence-cards.json 的实际摘要与数据库 sources；优先精读最有区分力的原始研究和反证。记录模型、物种、剂量、时间、结果/图表定位、匹配程度；填入可证伪机制假设及最小判别实验。首次限定这些信号，出现明确缺口时再执行一轮有理由的定向检索；达到预算、证据饱和或关键元数据缺失就交付现有结论和未解问题。', '', '如果没有合格信号，输出缺失/设计/效应量报告与下一次测量方案，不凭最大倍数强行生成机制。网络失败与未检出分别保留，不得当作反证。']
    write(out/'research-brief.md','\n'.join(lines)+'\n')
    return {'status':state['status'],'output':str(out),'signals':len(selected),'logical_queries_attempted':state['attempts'],'query_budget':budget,'failed_queries':sum(x['status']=='failed' for x in state['queries'].values()),'evidence_synthesis':'requires_source_reading_by_Codex'}
