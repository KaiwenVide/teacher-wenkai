from __future__ import annotations
import copy,json,sys,tempfile,unittest
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'scripts'))
from wkr.common import load,save
from wkr.experiment_io import load_experiment,prepare_units,read_table
from wkr.experiment_stats import pairwise,associations,time_trends,adjust,reversal_patterns
from wkr.experiment import run_analysis,enrich
from wkr.data_research import followup
from wkr.lifesciences import request,resolve_accession,catalog


class DataTests(unittest.TestCase):
    def setUp(self): self.temp=tempfile.TemporaryDirectory(prefix='wkr-data-test-'); self.root=Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def data(self,frame,**extra):
        frame.to_csv(self.root/'raw.csv',index=False)
        config={'study':{'design':'independent','data_scale':'log2','sample_is_biological_unit':True,'independent_units_confirmed':True,'feature_namespace':'gene_symbol','taxon_id':9606,'organism':'Homo sapiens'},'input':{'data':'raw.csv','layout':'long'},'comparisons':[{'name':'B_A','test':'B','reference':'A'}],'analysis':{'min_n':3,'technical_aggregation':'mean'},'research':{'max_signals':1,'max_queries':4,'sources':['pubmed']}}
        config.update(extra); save(self.root/'config.json',config); return config
    def base(self,n=5):
        return pd.DataFrame([{'feature':'GPX4','sample':g+str(i),'unit':g+str(i),'group':g,'value':float(i)*.1+(4 if g=='B' else 1)} for g in ['A','B'] for i in range(n)])
    def prepared(self,config):
        raw,_=load_experiment(config,self.root); units,issues,scale=prepare_units(raw,config); return units,issues,scale
    def test_technical_replicates_do_not_inflate_n(self):
        d=self.base(); d=pd.concat([d.assign(technical=i) for i in range(3)]); c=self.data(d); u,_,scale=self.prepared(c)
        r=pairwise(u,c,scale)[0]; self.assertEqual(r['n_test'],5); self.assertEqual(len(u),10); self.assertAlmostEqual(r['effect'],3)
    def test_undefined_technical_aggregation_blocks_inference(self):
        d=pd.concat([self.base().assign(technical=i) for i in range(2)]); c=self.data(d); c['analysis'].pop('technical_aggregation'); _,issues,_=self.prepared(c); self.assertTrue(any(x['code']=='technical_replicates' for x in issues))
    def test_paired_matching_not_row_order(self):
        d=self.base(); d['pair']=[str(i) for g in ['A','B'] for i in range(5)]; d.loc[d.group=='B','value']+=[0,.1,-.1,.2,-.2]; d=d.sample(frac=1,random_state=3); c=self.data(d); c['study']['design']='paired'; u,_,sc=self.prepared(c)
        r=pairwise(u,c,sc)[0]; self.assertEqual(r['n_matched_pairs'],5); self.assertAlmostEqual(r['effect'],3); self.assertEqual(r['method'],'paired_t')
    def test_missing_values_not_zero_filled(self):
        d=self.base(); d.loc[0,'value']=np.nan; c=self.data(d); u,_,sc=self.prepared(c); r=pairwise(u,c,sc)[0]
        self.assertEqual(r['n_reference'],4); self.assertAlmostEqual(r['detection_reference'],.8); self.assertEqual(int(u.value.isna().sum()),1)
    def test_qpcr_tests_negative_delta_ct(self):
        d=self.base(); d['value']=20-d.value; ref=d.copy(); ref['feature']='ACTB'; ref['value']=15
        c=self.data(pd.concat([d,ref])); c['study']['data_scale']='ct'; c['qpcr']={'reference_features':['ACTB'],'equal_efficiency_confirmed':True}
        u,_,sc=self.prepared(c); r=pairwise(u,c,sc)[0]; self.assertEqual(set(u.feature),{'GPX4'}); self.assertAlmostEqual(r['log2_fold_change'],3); self.assertIn('delta_ct',u)
    def test_qpcr_missing_reference_refused(self):
        c=self.data(self.base()); c['study']['data_scale']='ct'; c['qpcr']={'reference_features':['ACTB'],'equal_efficiency_confirmed':True}
        with self.assertRaises(ValueError): self.prepared(c)
    def test_batch_confounding_blocks_followup(self):
        d=self.base(); d['batch']=d.group; self.data(d); r=run_analysis(self.root/'config.json',self.root/'run',False,False)
        self.assertEqual(r['status'],'qc_blocked'); called=[]; f=followup(self.root/'run',search_fn=lambda *a,**kw:called.append(a),database_fn=lambda *a:called.append(a)); self.assertEqual(called,[]); self.assertEqual(f['signals'],0)
    def test_batch_adjusted_ols_fits(self):
        d=self.base(8); d['batch']=['one','two']*8; d.loc[d.batch=='two','value']+=5; c=self.data(d); c['analysis']['adjust_batch']=True; u,issues,sc=self.prepared(c)
        self.assertFalse(any(x['severity']=='blocking' for x in issues)); r=pairwise(u,c,sc)[0]; self.assertEqual(r['method'],'ols'); self.assertAlmostEqual(r['effect'],3)
    def test_fdr_spans_all_comparisons(self):
        rows=[{'contrast':'one','p_value':.01},{'contrast':'two','p_value':.04},{'contrast':'two','p_value':.9}]; adjust(rows); self.assertAlmostEqual(rows[0]['q_value'],.03); self.assertEqual(rows[0]['tests_in_family'],3)
    def test_correlations_separate_groups_and_batches(self):
        d=self.base(8); d['batch']=['one']*4+['two']*4+['one']*4+['two']*4; e=d.copy(); e['feature']='NQO1'; e['value']=10-e.value; c=self.data(pd.concat([d,e])); c['analysis']['adjust_batch']=True; u,_,_=self.prepared(c)
        r=associations(u,c); self.assertEqual(len(r['results']),4); self.assertTrue(all(x['n_units']==4 for x in r['results'])); self.assertTrue(all(x['rho']<0 for x in r['results']))
    def test_three_group_reversal_not_equivalence(self):
        rows=[{'feature':'X','contrast':a,'effect':b,'q_value':q} for a,b,q in [('M_C',2,.01),('T_M',-1.7,.01),('T_C',.3,.4)]]
        r=reversal_patterns(rows,{'reversal':{'model_vs_control':'M_C','treatment_vs_model':'T_M','treatment_vs_control':'T_C'}})[0]
        self.assertTrue(r['opposite_directions']); self.assertIn('not equivalence',r['evidence'])
    def test_excel_physical_row_and_sheet_preserved(self):
        import openpyxl
        book=openpyxl.Workbook(); ws=book.active; ws.title='raw'; ws.append(['title']); ws.append(['sample','feature','value']); ws.append(['s1','X',3]); path=self.root/'source.xlsx'; book.save(path)
        df,meta=read_table(path,'raw',2); self.assertEqual(df['__source_row'].iloc[0],3); self.assertEqual(meta['sheet'],'raw')
    def test_wide_matrix_excludes_annotation_columns(self):
        pd.DataFrame({'feature':['g1','g2'],'mass':[20,30],'a':[1,2],'b':[3,4]}).to_csv(self.root/'matrix.csv',index=False)
        pd.DataFrame({'sample':['a','b'],'group':['A','B'],'unit':['a','b']}).to_csv(self.root/'samples.csv',index=False)
        c=self.data(self.base()); c['input']={'data':'matrix.csv','layout':'wide','samples':'samples.csv'}; raw,_=load_experiment(c,self.root); self.assertEqual(len(raw),4); self.assertEqual(set(raw['__source_column']),{'a','b'})
    def test_bulk_counts_real_model_and_noninteger_refusal(self):
        rng=np.random.default_rng(112); data=[]
        for g in ['A','B']:
            for i in range(6):
                for f in range(80):
                    mu=(200 if f<4 and g=='B' else 45)+f
                    data.append({'sample':g+str(i),'unit':g+str(i),'group':g,'feature':'G'+str(f),'value':int(rng.negative_binomial(30,30/(30+mu)))})
        c=self.data(pd.DataFrame(data)); c['study']['data_scale']='raw_counts'; c['analysis']['technical_aggregation']='none'; save(self.root/'config.json',c)
        r=run_analysis(self.root/'config.json',self.root/'counts',False,False); self.assertNotEqual(r['status'],'qc_blocked',r)
        result=load(self.root/'counts/analysis.json'); self.assertEqual(result['count_model']['genes_retained'],80); self.assertTrue(next(x for x in result['results'] if x['feature']=='G0')['log2_fold_change']>1)
        d=pd.DataFrame(data); d.loc[0,'value']=1.5; d.to_csv(self.root/'raw.csv',index=False); r=run_analysis(self.root/'config.json',self.root/'bad-counts',False,False); self.assertEqual(r['status'],'qc_blocked')
    def test_enrichment_uses_measured_background(self):
        (self.root/'selected').write_text('A\nB\nOUTSIDE\n'); (self.root/'universe').write_text('A\nB\nC\nD\n'); (self.root/'sets.gmt').write_text('s1\tdescription\tA\tB\tUNMEASURED\ns2\tdescription\tC\tD\n')
        r=enrich(self.root/'selected',self.root/'universe',self.root/'sets.gmt'); self.assertEqual(r['selected_outside_universe'],['OUTSIDE']); self.assertEqual(r['results'][0]['universe_n'],4); self.assertAlmostEqual(r['results'][0]['p_value'],1/6)
    def test_followup_executes_and_resumes_without_duplicate_requests(self):
        self.data(self.base()); run_analysis(self.root/'config.json',self.root/'run',False,False); calls=[]
        def fake_search(query,sources,limit): calls.append(('search',query)); return {'records':[],'searches':[{'status':'ok'}]}
        def fake_db(provider,payload):
            calls.append(('db',provider)); return {'response':{'ok':True,'records':[{'primaryAccession':'P36969','genes':[{'geneName':{'value':'GPX4'}}],'organism':{'taxonId':9606}}] if provider=='uniprot' else [],'sources':[]}}
        first=followup(self.root/'run',search_fn=fake_search,database_fn=fake_db); self.assertEqual(first['logical_queries_attempted'],4); self.assertEqual(len(calls),4)
        second=followup(self.root/'run',search_fn=fake_search,database_fn=fake_db); self.assertEqual(len(calls),4); self.assertEqual(second['logical_queries_attempted'],4)
        self.assertNotIn('A0',str(calls)); self.assertNotIn('B0',str(calls))
        cards=load(self.root/'run/research/evidence-cards.json'); self.assertEqual(cards['cards'][0]['claim_support'],'not_assessed')
    def test_offline_queue_and_changed_source_guard(self):
        self.data(self.base()); run_analysis(self.root/'config.json',self.root/'run',False,False); r=followup(self.root/'run',offline=True); self.assertEqual(r['logical_queries_attempted'],0); self.assertEqual(r['status'],'pending_offline')
        with (self.root/'raw.csv').open('a') as f: f.write('\n')
        with self.assertRaises(ValueError): followup(self.root/'run',offline=True)
    def test_database_unique_species_mapping_and_mutation_guard(self):
        r=resolve_accession({'response':{'ok':True,'records':[{'primaryAccession':'X','genes':[{'geneName':{'value':'GPX4'}}],'organism':{'taxonId':10090}}]}},'GPX4',9606); self.assertEqual(r['status'],'not_resolved')
        with self.assertRaises(ValueError): request('opentargets',{'query':'mutation { something }'})
        with self.assertRaises(ValueError): request('uniprot',{'method':'DELETE'})
        self.assertEqual(len(catalog()['providers']),44)
    def test_database_rejects_unknown_origin_without_network(self):
        r=request('uniprot',{'base_url':'https://example.com','path':'private'}); self.assertFalse(r['response']['ok'])
    def test_failed_retrieval_not_reported_complete(self):
        self.data(self.base()); run_analysis(self.root/'config.json',self.root/'run',False,False)
        def fail(*args,**kwargs): raise OSError('simulated offline')
        r=followup(self.root/'run',search_fn=fail,database_fn=fail); self.assertEqual(r['status'],'retrieval_failed'); self.assertEqual(r['failed_queries'],3)
    def test_edited_analysis_cannot_seed_research(self):
        self.data(self.base()); run_analysis(self.root/'config.json',self.root/'run',False,False)
        p=self.root/'run/analysis.json'; a=load(p); a['results'][0]['effect']=900; save(p,a)
        with self.assertRaises(ValueError): followup(self.root/'run',offline=True)
    def test_database_404_retains_status_without_evidence(self):
        from wkr.http import Client, NetworkError
        from unittest.mock import patch
        client=Client(delay=0)
        client.requests=[{'url':'https://reactome.org/ContentService/data/query/missing','status':404}]
        with patch.object(client,'json',side_effect=NetworkError('HTTP 404',404)):
            r=request('reactome',{'path':'data/query/missing'},client=client)['response']
        self.assertEqual(r['status_code'],404); self.assertEqual(r['error']['code'],'http_not_found'); self.assertFalse(r['ok']); self.assertEqual(r['sources'],[]); self.assertFalse(r['checked_sources'][0]['supports_claim'])

    def test_time_trend_respects_repeated_units(self):
        data=[]
        for g in ['A','B']:
            for i in range(6):
                for time in [0,1,2]: data.append({'feature':'GPX4','sample':g+str(i),'unit':g+str(i),'group':g,'time':time,'value':i*.6+time*2+(.12 if i%2 else -.09)*time})
        c=self.data(pd.DataFrame(data)); c['study']['design']='longitudinal'; c['study']['time_unit']='day'; u,_,_=self.prepared(c); r=time_trends(u,c)
        self.assertEqual(len(r),2); self.assertTrue(all(x['n_units']==6 for x in r)); self.assertTrue(all(x['status']=='tested' for x in r),r); self.assertTrue(all('mixed' in x['method'] for x in r)); self.assertTrue(all(1.8<x['slope']<2.2 for x in r))

    def test_raw_counts_invalid_cells_block_before_technical_sum(self):
        for values in [[.5,.5],[2,None],[-1,3]]:
            d=self.base(); d=pd.concat([d.assign(technical=i,value=values[i]) for i in range(2)])
            c=self.data(d); c['study']['data_scale']='raw_counts'; c['analysis']['technical_aggregation']='sum'
            _,issues,_=self.prepared(c)
            self.assertTrue(any(x['code']=='invalid_raw_count_cells' and x['severity']=='blocking' for x in issues))
    def test_long_sample_manifest_missing_measurements_refused(self):
        d=self.base(); metadata=d[['sample','group','unit']].drop_duplicates()
        metadata=pd.concat([metadata,pd.DataFrame([{'sample':'missing','group':'A','unit':'missing'}])]);metadata.to_csv(self.root/'samples.csv',index=False)
        d=d[['sample','feature','value']];c=self.data(d);c['input']['samples']='samples.csv'
        with self.assertRaisesRegex(ValueError,'no measurement rows'): load_experiment(c,self.root)
    def test_reproduce_checks_frozen_configuration(self):
        import subprocess
        self.data(self.base());run_analysis(self.root/'config.json',self.root/'run',False,False)
        c=load(self.root/'run/config.json');c['analysis']['minimum_effect']=999;save(self.root/'run/config.json',c)
        result=subprocess.run([sys.executable,str(self.root/'run/reproduce.py'),str(self.root/'replay')],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('configuration changed',result.stderr);self.assertFalse((self.root/'replay').exists())

if __name__=='__main__': unittest.main()
