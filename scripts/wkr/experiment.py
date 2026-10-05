"""Local, reproducible experimental-data analysis and scientific artifacts."""
from __future__ import annotations
import importlib.metadata
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats
from .common import load,save,write,digest,now,SKILL_ROOT,safe_name
from .experiment_io import load_experiment,prepare_units
from .experiment_stats import pairwise,associations,time_trends,reversal_patterns,finite,adjust


def code_fingerprint():
    return digest({p.name:digest(p.read_bytes()) for p in sorted((SKILL_ROOT/'scripts/wkr').glob('*.py'))})


def run_analysis(config_path,out,make_notebook=True,figures=True):
    config_path=Path(config_path).resolve(); config=load(config_path); out=Path(out).resolve()
    import jsonschema
    try: jsonschema.validate(config,load(SKILL_ROOT/'schemas/experiment-config.schema.json'))
    except jsonschema.ValidationError as e: raise ValueError('Configuration: '+e.message) from e
    if out.exists() and any(out.iterdir()): raise ValueError('Analysis output must be a new or empty directory; retain previous runs')
    raw,sources=load_experiment(config,config_path.parent); units,issues,scale=prepare_units(raw,config)
    out.mkdir(parents=True,exist_ok=True)
    save(out/'config.json',config); raw.to_csv(out/'tidy-source.csv',index=False); units.to_csv(out/'biological-units.csv',index=False)
    blocked=any(x['severity']=='blocking' for x in issues)
    result=pairwise(units,config,scale,blocked); count_model=None
    if scale=='raw_counts' and not blocked:
        from .counts import analyze_counts
        try: result,count_model=analyze_counts(units,config,result)
        except (ValueError,RuntimeError,KeyError,IndexError,np.linalg.LinAlgError) as e:
            issues.append({'severity':'blocking','code':'count_model_unavailable','detail':str(e)}); blocked=True
            for r in result: r.update(status='qc_blocked',p_value=None,q_value=None,signal_class='descriptive_or_uncertain')
    if any(x['code']=='repeated_floor' for x in issues):
        for r in result:
            r['flags'].append('possible_censoring_floor')
            if r['signal_class']=='statistical_signal': r['signal_class']='quality_limited_signal'
    corr=associations(units,config,blocked or scale=='raw_counts')
    trends=time_trends(units,config,blocked or scale=='raw_counts')
    warnings=[x for x in issues if x['severity']!='blocking']
    versions={x:importlib.metadata.version(x) for x in ['numpy','pandas','scipy','statsmodels','matplotlib','openpyxl','pydeseq2']}
    result_hash=digest({'config':config,'sources':sources,'code':code_fingerprint(),'versions':versions})
    summary={'schema_version':'2.0','analysis_id':result_hash[:20],'created_at':now(),'config_path':str(config_path),'config_sha256':digest(config),'source_files':sources,'code_sha256':code_fingerprint(),'package_versions':versions,'status':'qc_blocked' if blocked else 'completed_with_warnings' if warnings else 'completed','issues':issues,'effective_scale':scale,'raw_rows':len(raw),'biological_units':int(units.unit.nunique()),'features':int(units.feature.nunique()),'missing_observations':int(raw.value.isna().sum()),'results':result,'correlations':corr,'time_trends':trends,'reversal_patterns':reversal_patterns(result,config),'count_model':count_model,'conclusion_scope':'exploratory observational analysis; no mechanistic/causal validation; technical replicates do not increase n','normalization':config.get('qpcr',config.get('normalization',{}))}
    save(out/'analysis.json',summary); pd.DataFrame(result).to_csv(out/'contrasts.csv',index=False)
    pd.DataFrame(corr['results']).to_csv(out/'correlations.csv',index=False); pd.DataFrame(trends).to_csv(out/'time-trends.csv',index=False)
    missing=[]
    strata=['feature','group']+(['time'] if 'time' in units else [])
    for key,d in units.groupby(strata,dropna=False):
        k=key if isinstance(key,tuple) else (key,); ctx=dict(zip(strata,k)); denom=units[(units.group==ctx['group']) & (units.time==ctx['time'])] if 'time' in ctx else units[units.group==ctx['group']]
        missing.append({**ctx,'observed_units':int(d.value.notna().sum()),'expected_units_in_supplied_data':int(denom.unit.nunique()),'missing_or_absent_units':int(denom.unit.nunique()-d.value.notna().sum())})
    pd.DataFrame(missing).to_csv(out/'detection.csv',index=False)
    figures_created=draw_figures(units,summary,out/'figures',config) if figures else []
    lines=['# 实验数据分析报告','',f"状态：`{summary['status']}`；分析 ID：`{summary['analysis_id']}`。",f"原始行数 {len(raw)}；生物学单位 {summary['biological_units']}；特征 {summary['features']}。",'','原始值不改写；缺失值不填零；未自动删除离群值。每项结果可回溯到源文件、工作表、物理行和样本列。','', '## 质量检查','']
    lines += [f"- {x['severity']} / {x['code']}：{x['detail']}" for x in issues] or ['已通过本脚本实现的质量检查；不等于实验设计已经获得独立验证。']
    lines += ['', '## 结果范围','', 'contrasts.csv 包含预设比较的生物重复数、效应、置信区间、p 与 BH 校正 q。time-trends.csv 是各组内线性时间趋势；组间时间斜率差异需要交互模型。correlations.csv 只在相同组别、时间和批次内匹配生物学单位。', '', '统计结果属于探索性分析。三组反向变化不等于完全恢复；与对照无显著差异不等于等效。数据库注释和文献中的其他模型不能自动证明本实验因果机制。', '',f"自动研究候选：{sum(r['signal_class']=='statistical_signal' for r in result)} 条比较信号；同一特征会去重并受研究预算限制。",'', '## 可复现文件','', '- config.json、analysis.json：配置、来源哈希、代码哈希、依赖版本。','- tidy-source.csv、biological-units.csv：原始位置与生物学单位数据。','- detection.csv：实际检出和缺失；分母仅覆盖提供的样本，完全缺失的实验单元需要样本清单补充。','- reproduce.py：校验输入后，用当前技能版本重新分析到新目录。']
    if figures_created: lines+=['- figures/：PNG 与 SVG；单点图展示生物学单位，误差线为均值的 t 95% CI。']
    write(out/'report.md','\n'.join(lines)+'\n')
    reproduction=f'''from pathlib import Path
import json, sys
sys.path.insert(0, {str(SKILL_ROOT/'scripts')!r})
from wkr.common import load, digest
from wkr.experiment import run_analysis, code_fingerprint
run_dir=Path(__file__).resolve().parent
prior=load(run_dir/'analysis.json')
for source in prior['source_files']:
    if digest(Path(source['path']).read_bytes()) != source['sha256']: raise ValueError('Input changed: '+source['path'])
if code_fingerprint()!=prior['code_sha256']: raise ValueError('Analysis code changed; make a deliberately versioned new run')
if len(sys.argv)!=2: raise SystemExit('Usage: python reproduce.py NEW_OUTPUT_DIRECTORY')
config=load(run_dir/'config.json')
if digest(config)!=prior['config_sha256']: raise ValueError('Analysis configuration changed; create a deliberately versioned new analysis')
config['input']['data']=prior['source_files'][0]['path']
if len(prior['source_files'])>1: config['input']['samples']=prior['source_files'][1]['path']
import tempfile
with tempfile.TemporaryDirectory(prefix='wkr-config-') as t:
    p=Path(t)/'config.json'; p.write_text(json.dumps(config))
    result=run_analysis(p,sys.argv[1],make_notebook=False)
print(json.dumps({{'status':result['status'],'analysis_id':result['analysis_id']}}))
'''
    write(out/'reproduce.py',reproduction)
    if make_notebook: create_notebook(out)
    save(out/'artifact-manifest.json',{'analysis_id':summary['analysis_id'],'files':{str(p.relative_to(out)):digest(p.read_bytes()) for p in sorted(out.rglob('*')) if p.is_file() and p.name!='artifact-manifest.json'}})
    return {'status':summary['status'],'analysis_id':summary['analysis_id'],'output':str(out),'features':summary['features'],'contrasts':len(result),'statistical_signals':sum(r['signal_class']=='statistical_signal' for r in result),'issues':issues,'notebook':'generated_not_executed' if make_notebook else 'not_requested'}


def draw_figures(units,summary,out,config):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    out.mkdir(parents=True,exist_ok=True); outputs=[]
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'svg.fonttype':'none'})
    features=config.get('plots',{}).get('features') or list(units.feature.unique())[:6]
    features=[x for x in features if x in set(units.feature)][:12]
    for feature in features:
        d=units[units.feature==feature]; fig,ax=plt.subplots(figsize=(7,4.5),layout='constrained')
        if 'time' in d:
            for g,s in d.groupby('group',sort=False):
                agg=s.groupby('time').value.agg(['mean','std','count']); se=agg['std']/np.sqrt(agg['count']); ci=stats.t.ppf(.975,agg['count']-1)*se
                ax.errorbar(agg.index,agg['mean'],yerr=ci,marker='o',capsize=3,label=str(g)); ax.scatter(s.time,s.value,s=9,alpha=.25)
            ax.set_xlabel('Time ('+config['study']['time_unit']+')'); ax.legend(frameon=False)
        else:
            groups=list(d.group.unique())
            for i,g in enumerate(groups):
                values=d.loc[d.group==g,'value'].dropna().to_numpy(); jitter=np.linspace(-.14,.14,len(values))
                ax.scatter(i+jitter,values,s=28,alpha=.8,color='#326B88')
                if len(values)>1:
                    ci=stats.t.ppf(.975,len(values)-1)*stats.sem(values)
                    ax.errorbar(i,np.mean(values),yerr=ci,fmt='D',ms=5,color='#A85B32',capsize=5)
            ax.set_xticks(range(len(groups)),[g+'\nn='+str(d.loc[d.group==g,'value'].notna().sum()) for g in groups])
        ylabel='Raw counts (descriptive only)' if summary['effective_scale']=='raw_counts' else '-Delta Ct (log2 expression proxy)' if config['study']['data_scale']=='ct' else summary['effective_scale']+' measurement'
        ax.set_ylabel(ylabel); ax.set_title(str(feature)); ax.text(0,-.23,'Exploratory • points: biological units • mean and 95% CI',transform=ax.transAxes,fontsize=8,color='#555555')
        for ext in ['png','svg']:
            p=out/(safe_name(feature)+'-'+digest(feature)[:6]+'.'+ext); fig.savefig(p,dpi=180,bbox_inches='tight'); outputs.append(str(p))
        plt.close(fig)
    frame=pd.DataFrame(summary['results'])
    if not frame.empty:
        for contrast,d in frame.groupby('contrast'):
            d=d.dropna(subset=['log2_fold_change','q_value'])
            if len(d)<10: continue
            fig,ax=plt.subplots(figsize=(6,5),layout='constrained'); colors=['#AD553C' if x=='statistical_signal' else '#8D9AA3' for x in d.signal_class]
            ax.scatter(d.log2_fold_change,-np.log10(np.maximum(d.q_value,1e-300)),c=colors,s=16,alpha=.7)
            ax.set(xlabel='log2 fold change (test / reference)',ylabel='-log10 BH q',title=str(contrast)); ax.axhline(-np.log10(config.get('analysis',{}).get('alpha',.05)),color='#555555',lw=.7,ls='--')
            for ext in ['png','svg']:
                p=out/('volcano-'+safe_name(contrast)+'.'+ext); fig.savefig(p,dpi=180); outputs.append(str(p))
            plt.close(fig)
    return outputs


def create_notebook(out):
    import nbformat
    out=Path(out)
    cells=[nbformat.v4.new_markdown_cell('# Reproducible experimental analysis\nLocal source data only. Replay checks source and code hashes, uses a fresh output directory, and does not run network research. Statistical outputs are exploratory.'),nbformat.v4.new_code_cell('from pathlib import Path\nimport json, subprocess, sys, tempfile\nimport pandas as pd\nrun_dir=Path('+repr(str(out))+')\nprior=json.loads((run_dir/"analysis.json").read_text())\nprint(prior["status"], prior["analysis_id"])'),nbformat.v4.new_code_cell('replay_dir=Path(tempfile.mkdtemp(prefix="wkr-notebook-"))/"replay"\nresult=subprocess.run([sys.executable,str(run_dir/"reproduce.py"),str(replay_dir)],check=True,capture_output=True,text=True)\nprint(result.stdout)\ndisplay(pd.read_csv(replay_dir/"contrasts.csv").head(15))'),nbformat.v4.new_code_cell('display(pd.read_csv(replay_dir/"detection.csv").head(15))')]
    nb=nbformat.v4.new_notebook(cells=cells,metadata={'kernelspec':{'name':'python3','display_name':'Python 3','language':'python'},'language_info':{'name':'python'}})
    nbformat.write(nb,out/'analysis.ipynb')


def execute_notebook(path):
    import nbformat, tempfile, sys
    from nbclient import NotebookClient
    from jupyter_client import KernelManager
    from jupyter_client.kernelspec import KernelSpecManager
    path=Path(path).resolve(); nb=nbformat.read(path,as_version=4)
    with tempfile.TemporaryDirectory(prefix='wkr-kernel-') as t:
        spec=Path(t)/'wkr'; spec.mkdir(); save(spec/'kernel.json',{'argv':[sys.executable,'-m','ipykernel_launcher','-f','{connection_file}'],'display_name':'Wenkai research','language':'python'})
        km=KernelManager(kernel_name='wkr',kernel_spec_manager=KernelSpecManager(kernel_dirs=[t]))
        NotebookClient(nb,km=km,timeout=180,resources={'metadata':{'path':str(path.parent)}}).execute()
    nbformat.write(nb,path)
    manifest=path.parent/'artifact-manifest.json'
    if manifest.is_file():
        m=load(manifest); m['files'][path.name]=digest(path.read_bytes()); save(manifest,m)
    return {'status':'executed','path':str(path),'code_cells':sum(c.cell_type=='code' for c in nb.cells)}


def enrich(selected_path,universe_path,gmt_path):
    selected={x.strip() for x in Path(selected_path).read_text().splitlines() if x.strip()}; universe={x.strip() for x in Path(universe_path).read_text().splitlines() if x.strip()}
    if not universe: raise ValueError('Explicit measured/eligible universe required')
    outside=sorted(selected-universe); selected &= universe
    if not selected: raise ValueError('No selected features in measured universe')
    rows=[]; seen=set()
    for line in Path(gmt_path).read_text().splitlines():
        fields=line.split('\t')
        if len(fields)<3: raise ValueError('GMT rows require term, description, members')
        name,description,*members=fields
        if name in seen: raise ValueError('Duplicate GMT term '+name)
        seen.add(name); in_universe=set(members)&universe
        if not in_universe: continue
        overlap=selected&in_universe
        rows.append({'term':name,'description':description,'overlap':sorted(overlap),'k':len(overlap),'selected_n':len(selected),'term_n':len(in_universe),'universe_n':len(universe),'p_value':float(stats.hypergeom.sf(len(overlap)-1,len(universe),len(in_universe),len(selected)))})
    adjust(rows)
    return {'results':sorted(rows,key=lambda r:r['q_value']),'selected_outside_universe':outside,'sources':{str(p):digest(Path(p).read_bytes()) for p in [selected_path,universe_path,gmt_path]},'method':'one-sided hypergeometric over-representation; BH across every GMT term represented in measured universe','limitations':'Identifier namespace/species and gene-set version must match. Coverage and background choice affect inference; enrichment is not pathway activation or causality.'}
