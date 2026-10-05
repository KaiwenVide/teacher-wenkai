from __future__ import annotations
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from wkr.lifesciences import request,catalog,_select,annotation_request
from wkr.database_protocols import resolve_variant
from wkr.http import SafeRedirect,NetworkError,Client
from wkr.academic import study_plan,experiment_check,manuscript_build
from wkr.common import load,save,digest
from wkr.format_tools import math_structure
from wkr.bibliography import export_records
from wkr.retrieval_tools import paginate,EntitledClient


class Fake:
    def __init__(self,*responses): self.values=iter(responses); self.requests=[]; self.calls=[]
    def json(self,url,**kwargs):
        self.requests.append({'url':url,'status':200}); self.calls.append((url,kwargs))
        value=next(self.values)
        if isinstance(value,Exception): raise value
        return value
    def fetch(self,url,**kwargs): return self.json(url,**kwargs)


class NativeTests(unittest.TestCase):
    def test_no_plugin_execution_for_database_requests(self):
        self.assertEqual(len(catalog()['providers']),44)
        self.assertEqual({x['backend'] for x in catalog()['providers'].values()},{'native'})
        with patch('subprocess.run',side_effect=AssertionError('No plugin subprocess allowed')):
            result=request('uniprot',{'path':'uniprotkb/search'},client=Fake({'results':[{'id':'X'}]}))
        self.assertTrue(result['response']['ok'])
    def test_graphql_errors_cannot_be_evidence(self):
        result=request('civic',{'query':'query { search(query:"BRAF") { id } }'},client=Fake({'errors':[{'message':'schema changed'}]}))
        self.assertFalse(result['response']['ok']); self.assertEqual(result['response']['sources'],[])
    def test_graphql_search_may_contain_mutation_word(self):
        client=Fake({'data':{'search':[]}})
        result=request('opentargets',{'query':'query { search(queryString:"mutation") { total } }'},client=client)
        self.assertTrue(result['response']['ok']); self.assertIn('query',client.calls[0][1]['body'])
    def test_graphql_actual_mutation_refused(self):
        for q in ['mutation { deleteThing }','query { one } mutation { two }','subscription { event }']:
            with self.assertRaises(ValueError): request('civic',{'query':q},client=Fake())
    def test_sparql_updates_and_federation_refused(self):
        for q in ['INSERT DATA { <x> <y> <z> }','SELECT * WHERE { SERVICE <https://private.invalid> { ?s ?p ?o } }','SELECT * WHERE {} ; DROP ALL']:
            with self.assertRaises(ValueError): request('bgee',{'query':q},client=Fake())
    def test_sparql_bindings_preserve_datatypes(self):
        raw={'results':{'bindings':[{'x':{'type':'literal','datatype':'integer','value':'3'}}]}}
        r=request('bgee',{'query':'SELECT ?x WHERE { VALUES ?x { 3 } }','record_path':'results.bindings'},client=Fake(raw))
        self.assertEqual(r['response']['records'][0]['x']['value'],'3')
    def test_rest_form_post_and_write_endpoint_rejection(self):
        client=Fake([{'stringId':'synthetic'}]); request('string',{'path':'network','method':'POST','form_body':{'identifiers':'TP53','species':9606}},client=client)
        self.assertEqual(client.calls[0][1]['form']['species'],9606)
        with self.assertRaises(ValueError): request('cbioportal',{'path':'studies','method':'POST','json_body':{}},client=Fake())
    def test_host_path_traversal_refused_before_call(self):
        client=Fake()
        for payload in [{'base_url':'https://evil.invalid','path':'x'},{'path':'%2e%2e/secret'},{'path':'https://evil.invalid/x'}]:
            self.assertFalse(request('uniprot',payload,client=client)['response']['ok'])
        self.assertEqual(client.calls,[])
    def test_nested_compaction_declares_loss(self):
        result=request('uniprot',{'path':'uniprotkb/search','max_items':1,'max_depth':3},client=Fake({'results':[{'genes':[{'name':'X'},{'name':'Y'}]},{'id':'second'}]}))
        self.assertTrue(result['response']['truncated']); self.assertTrue(result['response']['truncated_paths'])
    def test_array_record_path_and_missing_path(self):
        self.assertEqual(_select({'response':[{'result':[1]}]},'response.0.result'),[1])
        with self.assertRaises(ValueError): _select({'response':[]},'response.0.result')
    def test_clinical_trials_bounded_pagination(self):
        client=Fake({'studies':[{'id':'a'}],'nextPageToken':'next'},{'studies':[{'id':'b'}]})
        r=request('clinicaltrials',{'action':'studies','max_pages':2,'max_items':3},client=client)['response']
        self.assertEqual(r['record_count_returned'],2); self.assertEqual(r['pages_fetched'],2)
        self.assertEqual(client.calls[1][1]['params']['pageToken'],'next')
    def test_clinical_tables_rows_keep_codes(self):
        r=request('ncbi-clinicaltables',{'terms':'TP53'},client=Fake([1,['7157'],{'field':['value']},[['TP53','tumor protein']]]))
        self.assertEqual(r['response']['records'][0]['code'],'7157')
        self.assertEqual(r['response']['records'][0]['extra'],{'field':'value'})
    def test_variant_preserves_assembly_and_alleles(self):
        v=resolve_variant({'grch38':'chr10 112998590 C T'},'GRCh38',Fake())
        self.assertEqual(v['canonical'],'10:112998590-C-T'); self.assertEqual(v['variant_id'],'chr10_112998590_C_T_b38')
    def test_multiallelic_rsid_refused(self):
        c=Fake({'mappings':[{'assembly_name':'GRCh38','strand':1,'seq_region_name':'1','start':99,'allele_string':'A/C/T'}]})
        with self.assertRaises(ValueError): resolve_variant({'rsid':'rs123'},'GRCh38',c)
    def test_wrong_assembly_and_indels_not_silently_mapped(self):
        with self.assertRaises(ValueError): resolve_variant({'grch37':'1:100:AG:A'},'GRCh38',Fake())
        c=Fake({'mappings':[{'mapped':{'seq_region_name':'1','start':101,'end':101,'strand':1}}]},{'seq':'C'})
        with self.assertRaises(ValueError): resolve_variant({'grch37':'1:100:A:T'},'GRCh38',c)
    def test_gtex_and_phewas_use_correct_target_assembly(self):
        c=Fake({'data':[{'gene':'example'}]}); request('gtex-eqtl',{'grch38':'10:112998590:C:T'},client=c)
        self.assertEqual(c.calls[0][1]['params']['variantId'],'chr10_112998590_C_T_b38')
        c=Fake({'phenos':[{'phenocode':'test'}]}); r=request('biobankjapan-phewas',{'grch37':'10:114758349:C:T'},client=c)
        self.assertEqual(r['response']['details']['query_variant']['assembly'],'GRCh37')
    def test_genebass_keeps_requested_burden_set(self):
        c=Fake({'phewas':[{'phenotype_id':'p','pvalue':.2}]}); request('genebass-gene-burden',{'ensembl_gene_id':'ENSG00000141510','burden_set':'synonymous'},client=c)
        self.assertEqual(c.calls[0][1]['params']['burdenSet'],'synonymous')
    def test_cross_origin_redirect_drops_credentials(self):
        req=Request('https://api.example.org/a',headers={'Authorization':'secret','X-ELS-APIKey':'private','Accept':'application/pdf'})
        redirect=SafeRedirect().redirect_request(req,None,302,'Found',{},'https://other.example.org/b')
        self.assertNotIn('secret',str(redirect.headers)); self.assertNotIn('private',str(redirect.headers))
        with self.assertRaises(NetworkError): SafeRedirect().redirect_request(req,None,302,'Found',{},'http://other.example.org/b')
    def test_entitlement_headers_are_origin_scoped(self):
        seen=[]
        class Response(io.BytesIO):
            status=200; headers={}
        client=EntitledClient('api.example.org',{'X-ELS-APIKey':'secret'});client.delay=0
        client.opener=lambda req,**kwargs:(seen.append(req.headers) or Response(b'{}'))
        client.fetch('https://api.example.org/file');client.fetch('https://other.example.org/file')
        self.assertIn('secret',str(seen[0]));self.assertNotIn('secret',str(seen[1]))
        self.assertNotIn('secret',json.dumps(client.requests))
    def test_cursor_loop_stops_and_deduplicates(self):
        c=Fake({'items':[{'id':1}], 'cursor':'next'},{'items':[{'id':1}], 'cursor':'next'})
        r=paginate('crossref','works',{},'items',limit=10,pages=5,mode='cursor',page_key='cursor',cursor_path='cursor',client=c)
        self.assertEqual(len(r['records']),1);self.assertTrue(r['repeated_cursor']);self.assertTrue(r['truncated'])
    def test_math_code_fences_and_environment_order(self):
        self.assertTrue(math_structure('```tex\n$ unmatched code\n```\n\\[x^2\\]')['structurally_balanced'])
        self.assertFalse(math_structure('\\[x^2')['structurally_balanced'])
        self.assertFalse(math_structure('\\begin{align} x \\end{equation}')['structurally_balanced'])
    def test_rdf_escapes_title(self):
        text,_=export_records([{'title':'A & B < C','doi':'10.1234/test'}],'rdf')
        import xml.etree.ElementTree as ET
        self.assertIn('A & B < C', ''.join(ET.fromstring(text).itertext()))
    def test_planning_and_writing_cannot_claim_validation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); r=study_plan('A falsifiable question',root/'plan')
            self.assertEqual(r['status'],'draft'); self.assertFalse(experiment_check(load(root/'plan/experiment-plan.json'))['complete_for_review'])
            doc={'title':'Draft','sections':[{'name':'Results','text':'An exploratory association.','claim_ids':['C1']}],'limitations':['Synthetic example']}
            claims={'claims':[{'claim_id':'C1','text':'Exploratory association','status':'pending','sources':[]}]}
            output=manuscript_build(doc,claims,root/'draft.md',root)
            self.assertFalse(output['structural_evidence_checks_passed']);self.assertEqual(output['status'],'draft_requires_review')
            self.assertIn('[pending]',(root/'draft.md').read_text())
            with self.assertRaises(ValueError): manuscript_build(doc,claims,root/'draft.md',root)
    def test_supported_manuscript_claim_needs_source_hash_and_locator(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'source.txt';p.write_text('Synthetic observation only.')
            claims={'claims':[{'claim_id':'C1','text':'Observation','status':'supported','evidence_type':'direct','semantic_review':{'assessor':'tester','rationale':'Exact local sentence'},'sources':[{'path':'source.txt','source_sha256':digest(p.read_bytes()),'locator':'line 1','excerpt':p.read_text()}]}]}
            plan={'title':'Test','sections':[{'name':'Results','text':'Synthetic observation only.','claim_ids':['C1']}],'limitations':['No biological conclusion']}
            self.assertTrue(manuscript_build(plan,claims,root/'draft.md',root)['structural_evidence_checks_passed'])
            p.write_text('Changed source')
            self.assertFalse(manuscript_build(plan,claims,root/'draft2.md',root)['structural_evidence_checks_passed'])


class RegressionFixTests(unittest.TestCase):
    def test_bounded_gzip_decoding(self):
        import gzip
        class Response(io.BytesIO):
            status=200;headers={'Content-Encoding':'gzip'}
        raw=gzip.compress(b'{"records":[1,2]}')
        client=Client(delay=0,opener=lambda *a,**k:Response(raw))
        self.assertEqual(client.json('https://example.org')['records'],[1,2])
        bomb=gzip.compress(b'x'*10000)
        limited=Client(delay=0,max_bytes=100,opener=lambda *a,**k:Response(bomb))
        with self.assertRaises(NetworkError):limited.fetch('https://example.org')
    def test_automatic_reactome_mapping_uses_external_accession_and_species(self):
        payload=annotation_request('P36969','reactome',9606)
        client=Fake([{'stId':'R-HSA-2142688','speciesName':'Homo sapiens'}])
        result=request('reactome',payload,client=client)
        self.assertTrue(result['response']['ok'])
        self.assertEqual(client.calls[0][0],'https://reactome.org/ContentService/data/mapping/UniProt/P36969/pathways')
        self.assertEqual(client.calls[0][1]['params']['species'],9606)
        for taxon in [None,0,-1,'human']:
            with self.assertRaises(ValueError): annotation_request('P36969','reactome',taxon)
    def test_ref_snp_uses_non_beta_endpoint(self):
        client=Fake({'refsnp_id':'1042522'})
        request('clinvar-variation',{'action':'refsnp','refsnp':'rs1042522'},client=client)
        self.assertEqual(client.calls[0][0],'https://api.ncbi.nlm.nih.gov/variation/v0/refsnp/1042522')
    def test_finngen_source_schema_keeps_results(self):
        client=Fake({'results':[{'phenocode':'T2D'}],'regions':[],'variant':{}})
        r=request('finngen-phewas',{'grch38':'10:112998590:C:T'},client=client)
        self.assertEqual(r['response']['records'][0]['phenocode'],'T2D')
    def test_retired_eqtl_endpoint_and_bounded_local_alternative(self):
        self.assertEqual(request('eqtl-catalogue',{'path':'associations'},client=Fake())['response']['error']['code'],'remote_api_retired')
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'study.tsv';p.write_text('rsid\tbeta\nrs7412\t0.5\nrs123\t-0.3\nrs7412\t0.2\n')
            r=request('eqtl-catalogue',{'local_file':str(p),'filters':{'rsid':'rs7412'},'max_items':1})
            self.assertEqual(r['response']['records'],[{'rsid':'rs7412','beta':'0.5'}]);self.assertTrue(r['response']['truncated'])
    def test_citation_html_escapes_claim_and_title(self):
        from wkr.format_tools import run
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'refs.html'
            with patch('wkr.format_tools.search',return_value={'records':[{'record_id':'synthetic-record','title':'<script>title</script>'}],'searches':[{'status':'ok'}]}),patch('builtins.print'):
                run('citation',['--claim','<script>claim</script>','--output-file',str(out)])
            self.assertNotIn('<script>',out.read_text());self.assertIn('&lt;script&gt;',out.read_text())

if __name__=='__main__': unittest.main()
