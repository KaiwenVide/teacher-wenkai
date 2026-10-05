"""Bulk count inference. Does not treat TPM, intensity or cells as count replicates."""
from __future__ import annotations
import contextlib
import io
import warnings
import numpy as np
import pandas as pd
from .experiment_stats import finite, adjust


def analyze_counts(units,config,rows):
    from pydeseq2.dds import DeseqDataSet
    from pydeseq2.ds import DeseqStats
    from pydeseq2.default_inference import DefaultInference
    if 'time' in units: raise ValueError('Count time series require an explicit interaction/repeated-measure model; generic count adapter is for independent/paired bulk samples')
    opts=config.get('counts',{}); design=config['study']['design']
    if config.get('analysis',{}).get('technical_aggregation') not in [None,'none','sum']: raise ValueError('Count technical libraries may only be summed, never averaged')
    if units.value.isna().any() or (units.value<0).any() or not np.allclose(units.value,np.round(units.value),rtol=0,atol=0): raise ValueError('Raw counts require nonnegative integers with no missing cells; no zero filling')
    sub=units.copy(); sub['sample_key']=[str(i) for i in pd.MultiIndex.from_frame(sub[['unit','group']]).factorize()[0]]
    attrs=['group']+([ 'batch'] if 'batch' in sub else [])+(['pair'] if 'pair' in sub else [])
    if any((sub.groupby('sample_key')[col].nunique()>1).any() for col in attrs): raise ValueError('Sample metadata varies across features')
    meta=sub[['sample_key','unit']+attrs].drop_duplicates().set_index('sample_key')
    matrix=sub.pivot(index='sample_key',columns='feature',values='value').reindex(meta.index)
    if matrix.isna().any().any(): raise ValueError('Count matrix is incomplete; absence is not a measured zero')
    matrix=matrix.astype('int64')
    if (matrix.sum(axis=1)==0).any(): raise ValueError('All-zero count library')
    minimum=max(2,int(config.get('analysis',{}).get('min_n',3)))
    for c in config['comparisons']:
        if min((meta.group==c['test']).sum(),(meta.group==c['reference']).sum())<minimum: raise ValueError('Too few independent count libraries for a prespecified contrast')
    factors=[]
    if design=='paired':
        if 'pair' not in meta: meta['pair']=meta['unit']
        for c in config['comparisons']:
            pair=meta[meta.group.isin([c['test'],c['reference']])]
            if pair.duplicated(['pair','group']).any() or (pair.groupby('pair').group.nunique()!=2).any(): raise ValueError('Paired count contrasts require complete unique pairs; supply a custom model for incomplete blocks')
        factors.append('pair')
    if 'batch' in meta and meta.batch.nunique()>1: factors.append('batch')
    factors.append('group')
    from formulaic import model_matrix
    formula='~ '+' + '.join(factors); dm=np.asarray(model_matrix(formula,meta),dtype=float)
    if np.linalg.matrix_rank(dm)<dm.shape[1] or len(meta)<=dm.shape[1]+1: raise ValueError('Count model design is confounded or lacks residual degrees of freedom')
    threshold=max(1,int(opts.get('min_total_count',10))); keep=matrix.sum(axis=0)>=threshold
    filtered=[str(x) for x in matrix.columns[~keep]]; matrix=matrix.loc[:,keep]
    if matrix.shape[1]<10: raise ValueError('Too few retained genes for stable dispersion fitting; use a suitable targeted-count model')
    stream=io.StringIO(); captured=[]
    with contextlib.redirect_stdout(stream),contextlib.redirect_stderr(stream),warnings.catch_warnings(record=True) as warns:
        warnings.simplefilter('always')
        dds=DeseqDataSet(counts=matrix,metadata=meta,design=formula,refit_cooks=False,inference=DefaultInference(n_cpus=1),quiet=True)
        dds.deseq2(); results={}
        for c in config['comparisons']:
            ds=DeseqStats(dds,contrast=['group',c['test'],c['reference']],alpha=float(config.get('analysis',{}).get('alpha',.05)),cooks_filter=True,independent_filter=False,inference=DefaultInference(n_cpus=1),quiet=True)
            ds.summary(); results[c['name']]=ds.results_df
        captured=list(dict.fromkeys(str(w.message) for w in warns))
    for row in rows:
        row.update(method='PyDESeq2 Wald; negative binomial',analysis_scale='log2_fold_change',effect=None,log2_fold_change=None,p_value=None,ci_low=None,ci_high=None)
        if row['feature'] in filtered: row['status']='filtered_low_total_count'; continue
        r=results[row['contrast']].loc[row['feature']]; lfc=finite(r.log2FoldChange); se=finite(r.lfcSE)
        row.update(effect=lfc,log2_fold_change=lfc,p_value=finite(r.pvalue),deseq2_padj=finite(r.padj),base_mean=finite(r.baseMean),ci_low=lfc-1.96*se if lfc is not None and se is not None else None,ci_high=lfc+1.96*se if lfc is not None and se is not None else None,ci_method='Wald 95% CI; unshrunk log2 fold change',status='tested' if finite(r.pvalue) is not None else 'not_estimable')
    adjust(rows,family='contrast' if config.get('analysis',{}).get('fdr_family')=='per_contrast' else None)
    for row in rows:
        row['signal_class']='statistical_signal' if row['status']=='tested' and row.get('q_value') is not None and row['q_value']<=float(config.get('analysis',{}).get('alpha',.05)) and abs(row.get('effect') or 0)>=float(config.get('analysis',{}).get('minimum_effect',0)) else 'descriptive_or_uncertain'
    return rows,{'method':'PyDESeq2','formula':formula,'min_total_count':threshold,'filtered_features':filtered,'warnings':captured,'log':stream.getvalue(),'inference':'Cook filtering; no automatic outlier replacement; no independent filtering; BH family is explicit; no LFC shrinkage','genes_retained':matrix.shape[1],'libraries':matrix.shape[0]}
