"""Prespecified contrasts, time trends and within-stratum associations."""
from __future__ import annotations
from itertools import combinations
import math
import warnings
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests
import statsmodels.api as sm


def finite(x):
    try: return float(x) if np.isfinite(float(x)) else None
    except (TypeError,ValueError): return None


def adjust(rows,key='p_value',family=None):
    families={}
    for i,r in enumerate(rows):
        r['q_value']=None
        if r.get(key) is not None and np.isfinite(r[key]): families.setdefault(r.get(family,'all') if family else 'all',[]).append(i)
    for label,indices in families.items():
        qs=multipletests([rows[i][key] for i in indices],method='fdr_bh')[1]
        for i,q in zip(indices,qs): rows[i].update(q_value=float(q),multiplicity_family=str(label),tests_in_family=len(indices))
    return rows


def pairwise(units,config,scale,blocked=False):
    out=[]; design=config['study']['design']; opts=config.get('analysis',{}); minimum=max(2,int(opts.get('min_n',3)))
    contrasts=config.get('comparisons',[])
    if not contrasts: raise ValueError('Prespecify comparisons with name/test/reference; a control group is not guessed')
    groups=set(units['group'])
    if len({c['name'] for c in contrasts})!=len(contrasts): raise ValueError('Contrast names must be unique')
    for c in contrasts:
        if c['test'] not in groups or c['reference'] not in groups or c['test']==c['reference']: raise ValueError('Invalid comparison '+str(c))
    strata=['feature']+(['time'] if 'time' in units else [])
    for key,d in units.groupby(strata,dropna=False,sort=False):
        values=key if isinstance(key,tuple) else (key,); extra=dict(zip(strata,values)); feature=extra['feature']
        for c in contrasts:
            a=d[d.group==c['test']]; b=d[d.group==c['reference']]; av=a.value.dropna().to_numpy(); bv=b.value.dropna().to_numpy()
            denom=units[units.time==extra['time']] if 'time' in extra else units
            total_a=denom.loc[denom.group==c['test'],'unit'].nunique(); total_b=denom.loc[denom.group==c['reference'],'unit'].nunique()
            row={**extra,'contrast':c['name'],'test_group':c['test'],'reference_group':c['reference'],'method':None,'analysis_scale':scale,'n_test':len(av),'n_reference':len(bv),'detection_test':len(av)/total_a if total_a else 0,'detection_reference':len(bv)/total_b if total_b else 0,'mean_test':finite(np.mean(av)) if len(av) else None,'mean_reference':finite(np.mean(bv)) if len(bv) else None,'effect':None,'log2_fold_change':None,'ci_low':None,'ci_high':None,'p_value':None,'status':'not_tested','flags':[],'source_rows':sorted(set(x for rs in d['__source_row'] for x in rs))}
            for col in ['symbol','accession']:
                if col in d: row[col]=str(d[col].dropna().iloc[0]) if not d[col].dropna().empty else None
            if len(av) and len(bv):
                row['effect']=float(np.mean(av)-np.mean(bv))
                if scale=='log2': row['log2_fold_change']=row['effect']
                elif scale=='linear' and np.mean(av)>0 and np.mean(bv)>0: row['log2_fold_change']=float(np.log2(np.mean(av)/np.mean(bv)))
            if blocked: row['status']='qc_blocked'; out.append(row); continue
            if scale=='raw_counts': row['status']='requires_count_model'; out.append(row); continue
            if min(len(av),len(bv))<minimum: row['status']='descriptive_small_n'; out.append(row); continue
            paired=design=='paired'; selected=opts.get('test','paired_t' if paired else 'welch')
            if paired:
                paircol='pair' if 'pair' in d else 'unit'; sub=d[d.group.isin([c['test'],c['reference']])]
                if sub.duplicated([paircol,'group']).any(): row['status']='ambiguous_pairing'; out.append(row); continue
                joined=sub.pivot(index=paircol,columns='group',values='value')[[c['test'],c['reference']]].dropna()
                row.update(n_matched_pairs=len(joined),unmatched_units=int(sub[paircol].nunique()-len(joined)))
                av=joined[c['test']].to_numpy(); bv=joined[c['reference']].to_numpy()
                row.update(n_test=len(av),n_reference=len(bv),mean_test=finite(np.mean(av)) if len(av) else None,mean_reference=finite(np.mean(bv)) if len(bv) else None,effect=finite(np.mean(av-bv)) if len(av) else None)
                row['log2_fold_change']=row['effect'] if scale=='log2' else finite(np.log2(np.mean(av)/np.mean(bv))) if len(av) and np.mean(av)>0 and np.mean(bv)>0 else None
                if len(av)<minimum: row['status']='descriptive_small_n'; out.append(row); continue
                if selected not in ['paired_t','wilcoxon']: raise ValueError('Paired design requires paired_t or wilcoxon')
            elif selected not in ['welch','mannwhitney','ols']: raise ValueError('Independent contrast requires welch, mannwhitney or ols')
            if opts.get('adjust_batch') and 'batch' in d and d['batch'].nunique()>1:
                if paired: row['status']='requires_custom_paired_batch_model'; out.append(row); continue
                selected='ols'
            row['method']=selected
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore',RuntimeWarning)
                    if selected=='ols':
                        sub=d[d.group.isin([c['test'],c['reference']])].dropna(subset=['value']).copy(); sub['contrast_code']=(sub.group==c['test']).astype(float)
                        design_matrix=pd.DataFrame({'intercept':1.,'contrast_code':sub.contrast_code},index=sub.index)
                        if opts.get('adjust_batch') and 'batch' in sub: design_matrix=pd.concat([design_matrix,pd.get_dummies(sub.batch,prefix='batch',drop_first=True,dtype=float)],axis=1)
                        if np.linalg.matrix_rank(design_matrix)<design_matrix.shape[1] or len(sub)<=design_matrix.shape[1]+1: raise ValueError('Confounded or insufficient-residual-df design')
                        fit=sm.OLS(sub.value,design_matrix).fit(cov_type='HC3'); ci=fit.conf_int().loc['contrast_code']
                        row.update(effect=finite(fit.params['contrast_code']),p_value=finite(fit.pvalues['contrast_code']),ci_low=finite(ci.iloc[0]),ci_high=finite(ci.iloc[1]),ci_method='OLS HC3 95% CI')
                        row['log2_fold_change']=row['effect'] if scale=='log2' else None
                    elif selected in ['welch','paired_t']:
                        if (paired and np.var(av-bv,ddof=1)==0) or (not paired and np.var(av,ddof=1)==0 and np.var(bv,ddof=1)==0): raise ValueError('Zero estimated variance; inspect rounding or repeated constants')
                        result=stats.ttest_rel(av,bv) if paired else stats.ttest_ind(av,bv,equal_var=False)
                        ci=result.confidence_interval(.95); row.update(p_value=finite(result.pvalue),ci_low=finite(ci.low),ci_high=finite(ci.high),ci_method='two-sided t 95% CI on mean difference')
                    elif selected=='mannwhitney':
                        result=stats.mannwhitneyu(av,bv,alternative='two-sided',method='auto'); row.update(p_value=finite(result.pvalue),rank_biserial=finite(2*result.statistic/(len(av)*len(bv))-1),ci_method='not_computed; p tests rank distribution, effect column is descriptive mean difference')
                    else:
                        result=stats.wilcoxon(av,bv,alternative='two-sided',zero_method='wilcox',method='auto'); row.update(p_value=finite(result.pvalue),ci_method='not_computed; signed-rank test')
                row['status']='tested' if row['p_value'] is not None else 'not_estimable'
                if selected!='ols' and row['effect'] is not None:
                    effects=[np.mean(np.delete(av,i))-np.mean(np.delete(bv,i)) for i in range(len(av))] if paired else [np.mean(np.delete(av,i))-np.mean(bv) for i in range(len(av))]+[np.mean(av)-np.mean(np.delete(bv,i)) for i in range(len(bv))]
                    row['leave_one_unit_out_direction_stable']=bool(all(np.sign(e)==np.sign(row['effect']) for e in effects))
                    if not row['leave_one_unit_out_direction_stable']: row['flags'].append('single_unit_direction_sensitivity')
            except (ValueError,ZeroDivisionError,np.linalg.LinAlgError) as e: row.update(status='not_estimable',reason=str(e))
            if min(row['detection_test'],row['detection_reference'])<float(opts.get('min_detection',.7)): row['flags'].append('low_detection')
            out.append(row)
    adjust(out,family='contrast' if opts.get('fdr_family')=='per_contrast' else None)
    for row in out:
        row['signal_class']='statistical_signal' if row['status']=='tested' and row.get('q_value') is not None and row['q_value']<=float(opts.get('alpha',.05)) and abs(row['effect'] or 0)>=float(opts.get('minimum_effect',0)) else 'descriptive_or_uncertain'
        if row['flags']: row['signal_class']='quality_limited_signal' if row['signal_class']=='statistical_signal' else row['signal_class']
    return out


def associations(units,config,blocked=False):
    opts=config.get('correlations',{}); selected=opts.get('features'); names=list(units.feature.unique())
    if opts.get('enabled',True) is False: return {'status':'not_requested','results':[]}
    if blocked: return {'status':'qc_blocked','results':[]}
    if selected is None:
        if len(names)>30: return {'status':'requires_bounded_feature_set','results':[],'reason':'No automatic all-pairs testing across an omics-wide matrix'}
        selected=names
    if len(selected)>50 or len(set(selected))!=len(selected): raise ValueError('Correlation feature list must be unique and at most 50')
    if any(x not in names for x in selected): raise ValueError('Unknown correlation feature')
    out=[]; strata=['group']+(['time'] if 'time' in units else [])+(['batch'] if 'batch' in units and units.batch.nunique()>1 else [])
    for key,d in units[units.feature.isin(selected)].groupby(strata,dropna=False):
        values=key if isinstance(key,tuple) else (key,); context=dict(zip(strata,values))
        pivot=d.pivot(index='unit',columns='feature',values='value')
        for a,b in combinations(selected,2):
            if a not in pivot or b not in pivot: continue
            paired=pivot[[a,b]].dropna(); r={**context,'feature_a':a,'feature_b':b,'n_units':len(paired),'rho':None,'p_value':None,'status':'descriptive_small_n','method':'within-stratum Spearman','causality':'not_established'}
            if len(paired)>=max(4,int(opts.get('min_n',4))) and paired[a].nunique()>1 and paired[b].nunique()>1:
                result=stats.spearmanr(paired[a],paired[b]); r.update(rho=finite(result.statistic),p_value=finite(result.pvalue),status='tested',p_method='asymptotic; small-sample exploratory')
            out.append(r)
    adjust(out)
    return {'status':'completed','results':out,'selection': 'user_specified' if opts.get('features') else 'all_features_when_at_most_30','limitations':'Associations are within group/time/batch strata; no causal interpretation. Small-sample Spearman p-values are approximate; validate with permutation/independent data before promotion.'}


def time_trends(units,config,blocked=False):
    if 'time' not in units: return []
    rows=[]
    for (feature,group),d in units.groupby(['feature','group']):
        d=d.dropna(subset=['value']); row={'feature':feature,'group':group,'n_units':int(d.unit.nunique()),'timepoints':int(d.time.nunique()),'slope':None,'p_value':None,'status':'not_estimable'}
        if blocked: row['status']='qc_blocked'; rows.append(row); continue
        if d.unit.nunique()<4 or d.time.nunique()<3: row['status']='descriptive_small_n'; rows.append(row); continue
        try:
            repeated=d.unit.duplicated().any()
            if repeated:
                import statsmodels.formula.api as smf
                formula='value ~ time'+(' + C(batch)' if 'batch' in d and d.batch.nunique()>1 else '')
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore'); fit=smf.mixedlm(formula,d,groups=d['unit']).fit(reml=True,method='lbfgs')
                if not fit.converged: raise ValueError('Mixed model did not converge')
                row['method']='random-intercept mixed model; common linear time slope'
            else:
                x=pd.DataFrame({'intercept':1.,'time':d.time},index=d.index)
                if 'batch' in d and d.batch.nunique()>1: x=pd.concat([x,pd.get_dummies(d.batch,prefix='batch',drop_first=True,dtype=float)],axis=1)
                if np.linalg.matrix_rank(x)<x.shape[1] or len(d)<=x.shape[1]+1: raise ValueError('Time and batch not identifiable')
                fit=sm.OLS(d.value,x).fit(cov_type='HC3'); row['method']='OLS HC3 time slope'
            ci=fit.conf_int().loc['time']; row.update(slope=finite(fit.params['time']),ci_low=finite(ci.iloc[0]),ci_high=finite(ci.iloc[1]),p_value=finite(fit.pvalues['time']),status='tested')
        except Exception as e: row['reason']=type(e).__name__+': '+str(e)[:180]
        rows.append(row)
    return adjust(rows)


def reversal_patterns(results,config):
    roles=config.get('reversal')
    if not roles: return []
    lookup={(r['feature'],r.get('time'),r['contrast']):r for r in results}; output=[]
    for feature,time in dict.fromkeys((f,t) for f,t,_ in lookup):
        a=lookup.get((feature,time,roles['model_vs_control'])); b=lookup.get((feature,time,roles['treatment_vs_model'])); c=lookup.get((feature,time,roles['treatment_vs_control']))
        if not all([a,b,c]) or any(x.get('effect') is None for x in [a,b,c]): continue
        opposite=a['effect']*b['effect']<0; closer=abs(c['effect'])<abs(a['effect'])
        output.append({'feature':feature,'time':time,'opposite_directions':opposite,'closer_to_control_descriptively':closer,'model_q':a.get('q_value'),'treatment_q':b.get('q_value'),'residual_difference_q':c.get('q_value'),'pattern':'opposing_change_and_smaller_residual' if opposite and closer else 'not_a_consistent_reversal_pattern','evidence':'descriptive three-contrast pattern; non-significance versus control is not equivalence, rescue or target dependence'})
    return output
