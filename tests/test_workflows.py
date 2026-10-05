from __future__ import annotations
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from wkr.common import digest,load,save,init_workspace
from wkr.model import normalize_doi,normalize_record,deduplicate
from wkr.providers import doi_lookup,search_one,search,openalex_record,provider_request
from wkr.http import Client,NetworkError
from wkr.bibliography import export_records,import_references,compare_metadata
from wkr.claims import new_claims,validate_claims,numeric_check
from wkr.reader import prepare,validate_reader,render_reader
from wkr.download import inspect_payload,download_batch
from wkr.review import screening_flow,freeze_packet,collect_reviews
from wkr.pipeline import prioritize,archive
from wkr.adapters import scansci_request


class FakeClient:
    def __init__(self,responses): self.responses=iter(responses); self.requests=[]
    def json(self,url,**kwargs):
        self.requests.append({'url':url,'params':kwargs.get('params',{})}); x=next(self.responses)
        if isinstance(x,Exception): raise x
        return x
    def fetch(self,url,**kwargs): return self.json(url,**kwargs)


class IntegrationTests(unittest.TestCase):
    def setUp(self): self.temp=tempfile.TemporaryDirectory(prefix='wkr-tests-'); self.path=Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def cli(self,*args,code=0):
        p=subprocess.run([sys.executable,str(ROOT/'scripts/research.py'),*map(str,args)],capture_output=True,text=True)
        self.assertEqual(p.returncode,code,p.stdout+p.stderr); return json.loads(p.stdout)

    def test_fulltext_xml_content_negotiation_preserves_raw_bytes(self):
        seen=[]
        class XMLClient:
            def fetch(self,url,**kwargs):
                seen.append(kwargs['headers'].get('Accept'))
                if seen[-1]!='application/xml': raise NetworkError('HTTP 406',406)
                return b'<article><body>Original XML</body></article>'
        data=provider_request(XMLClient(),'europepmc','PMC12928647/fullTextXML',binary=True)
        self.assertEqual(data,b'<article><body>Original XML</body></article>')
        self.assertEqual(seen,['application/xml'])

    def test_crossref_404_can_be_valid_datacite_doi(self):
        client=FakeClient([NetworkError('HTTP 404',404),{'data':{'attributes':{'doi':'10.5281/zenodo.123','titles':[{'title':'A dataset'}],'publicationYear':2024,'creators':[{'name':'Consortium'}]}}}])
        r=doi_lookup('https://doi.org/10.5281/zenodo.123',client)
        self.assertEqual(r['status'],'metadata_found'); self.assertEqual(r['agency'],'datacite'); self.assertEqual(r['claim_support'],'not_assessed')

    def test_registry_outage_is_inconclusive(self):
        r=doi_lookup('10.1234/example',FakeClient([NetworkError('offline')]*3))
        self.assertEqual(r['status'],'inconclusive')

    def test_dedup_keeps_versions_and_merges_exact_records(self):
        r=deduplicate(load(ROOT/'tests/fixtures/records.json')['records'])
        self.assertEqual(r['unique_count'],3); self.assertEqual(r['duplicates_removed'],1)
        a={'title':'Identical title that is deliberately long','doi':'10.1234/a','year':2025,'authors':['A Li']}
        b={**a,'doi':'10.1234/b'}; self.assertEqual(deduplicate([a,b])['unique_count'],2)

    def test_openalex_author_is_not_lost(self):
        r=openalex_record({'id':'https://openalex.org/W1','display_name':'Test','authorships':[{'author':{'display_name':'Synthetic Author'}}]})
        self.assertEqual(r['authors'][0]['display'],'Synthetic Author')

    def test_doi_parenthesis_and_year_are_not_guessed(self):
        self.assertEqual(normalize_doi('https://doi.org/10.1234/A(B)'), '10.1234/a(b)')
        canonical={'title':'X','doi':'10.1234/2021.x','year':2023,'dates':{'published-online':{'date-parts':[[2022,12,1]]}},'authors':[{'family':'Li','given':'A'}]}
        report=compare_metadata({'title':'X','year':2022,'authors':['A Li et al.']},canonical)
        self.assertEqual(next(x for x in report['checks'] if x['field']=='year')['status'],'matches_alternate_publication_date')
        self.assertEqual(next(x for x in report['checks'] if x['field']=='authors')['status'],'truncated_presentation_needs_style_check')

    def test_ris_roundtrip_multiline_and_corporate_author(self):
        p=self.path/'refs.ris'; p.write_text('TY  - JOUR\nTI  - A long title\n  spanning two lines\nAU  - Li, Anna\nAU  - Trial Consortium\nPY  - 2024\nDO  - 10.1234/test\nSP  - 12\nEP  - 18\nER  - \n')
        r=import_references(p); self.assertEqual(len(r['records']),1); self.assertEqual(r['records'][0]['pages'],'12-18')
        out,warnings=export_records(r['records'],'ris'); self.assertIn('Li, Anna',out); self.assertIn('Trial Consortium',out); self.assertIn('spanning two lines',out)

    def test_ris_preserves_arxiv_version_identity_through_roundtrip(self):
        rows=deduplicate(load(ROOT/'tests/fixtures/records.json')['records'])['records']
        content,_=export_records(rows,'ris'); target=self.path/'refs.ris'; target.write_text(content)
        imported=import_references(target)['records']; versions={r['identifiers'].get('arxiv') for r in imported if r['identifiers'].get('arxiv')}
        self.assertEqual(versions,{'2401.00001v1','2401.00001v2'})
        self.assertEqual(len({r['record_id'] for r in imported}),3)
        self.assertEqual(deduplicate(imported)['unique_count'],3)

    def test_nbib_continuation_and_full_author(self):
        p=self.path/'refs.nbib'; p.write_text('PMID- 12345\nTI  - First\n      continuation\nFAU - Li, Anna\nAU  - Li A\nDP  - 2024 Jan\nAID - 10.1234/test [doi]\n\nPMID- 23456\nTI  - Second\n')
        r=import_references(p)['records']; self.assertEqual(len(r),2); self.assertEqual(r[0]['authors'][0]['given'],'Anna'); self.assertEqual(r[0]['identifiers']['doi'],'10.1234/test')

    def test_percent_rounding_and_percentage_points(self):
        r=numeric_check('33.3','.333333','percent','fraction',1)
        self.assertEqual(r['status'],'compatible_with_declared_rounding'); self.assertIn('not_assessed',r['semantic_support'])
        self.assertEqual(numeric_check('33.3','.333333','percent','fraction')['status'],'numeric_mismatch')
        self.assertEqual(numeric_check('10','.10','percentage_point','fraction')['status'],'incompatible_units')
        self.assertEqual(numeric_check('1','1000','mg','ug')['status'],'exact_or_unit_equivalent')

    def test_search_cursor_and_bounded_coverage(self):
        page=lambda ids,cursor:{'hitCount':3,'nextCursorMark':cursor,'resultList':{'result':[{'id':str(i),'source':'MED','title':'paper '+str(i),'pubYear':'2024'} for i in ids]}}
        client=FakeClient([page([1,2],'next'),page([3],'last')]); r=search_one(client,'europepmc','query',3)
        self.assertEqual(r['retrieved'],3); self.assertTrue(r['complete_for_query']); self.assertEqual(client.requests[1]['params']['cursorMark'],'next')
        client=FakeClient([page([1],'next')]); r=search_one(client,'europepmc','query',1); self.assertFalse(r['complete_for_query'])

    def test_late_page_failure_preserves_first_page(self):
        page={'hitCount':3,'nextCursorMark':'next','resultList':{'result':[{'id':'1','source':'MED','title':'First page','pubYear':'2024'}]}}
        result=search('q',['europepmc'],3,client=FakeClient([page,NetworkError('page two unavailable')]))
        self.assertEqual(len(result['records']),1)
        self.assertEqual(result['searches'][0]['status'],'partial')
        self.assertFalse(result['searches'][0]['complete_for_query'])

    def test_provider_failure_preserves_other_database_results(self):
        client=FakeClient([NetworkError('blocked'),{'message':{'total-results':1,'items':[{'DOI':'10.1234/a','title':['Found'],'author':[]}]}}])
        r=search('q',['openalex','crossref'],1,client=client)
        self.assertEqual(len(r['records']),1); self.assertEqual(r['searches'][0]['status'],'failed')

    def test_http_error_body_and_secret_redaction(self):
        with self.assertRaises(NetworkError): provider_request(FakeClient([{'errCode':'E1'}]),'core','search/works')
        class Response(io.BytesIO):
            status=200; headers={}
            def geturl(self): return 'https://example.org/?api_key=SECRET&email=a@b.org&q=public'
        client=Client(delay=0,opener=lambda *a,**k:Response(b'{"ok":true}'))
        client.json('https://example.org/',params={'api_key':'SECRET','q':'public'})
        encoded=json.dumps(client.requests); self.assertNotIn('SECRET',encoded); self.assertNotIn('a@b.org',encoded); self.assertIn('public',encoded)

    def test_reader_cannot_pass_with_empty_or_stale_translation(self):
        source=self.path/'source.md'; source.write_text('First paragraph.\n\nSecond paragraph.')
        result=prepare(source,self.path/'reader'); sm=load(result['source_map']); tr=load(result['translations'])
        self.assertFalse(validate_reader(sm,tr)['complete'])
        for b in tr['blocks']: b['translation']='译文'
        self.assertFalse(validate_reader(sm,tr)['complete'])
        tr.update(status='reviewed',qa={'assessor':'test-assessor','source_fidelity_checked':True})
        self.assertTrue(validate_reader(sm,tr)['complete'])
        source.write_text('Changed source'); self.assertFalse(validate_reader(sm,tr)['complete'])

    def test_reader_distinguishes_missing_qa_from_declared_draft(self):
        source=self.path/'source.md'; source.write_text('Text')
        r=prepare(source,self.path/'reader'); sm=load(r['source_map']); tr=load(r['translations'])
        tr['blocks'][0]['translation']='译文'; tr['qa']={'assessor':'tester','source_fidelity_checked':True}; tr['missing_materials']=['Figure 2']
        result=validate_reader(sm,tr); self.assertFalse(result['complete'])
        self.assertNotIn('QA has not been recorded',' '.join(result['issues'])); self.assertEqual(result['missing_materials'],['Figure 2'])
        tr['qa']['missing_materials']=['Supplementary methods']; tr['status']='reviewed'
        result=validate_reader(sm,tr); self.assertFalse(result['complete']); self.assertEqual(result['missing_materials'],['Figure 2','Supplementary methods'])

    def test_reader_html_escapes_source_and_marks_draft(self):
        source=self.path/'source.md'; source.write_text('<script>alert(1)</script>')
        result=prepare(source,self.path/'reader'); sm=load(result['source_map']); tr=load(result['translations']); output=self.path/'reader.md'
        render_reader(sm,tr,output); html=output.with_suffix('.html').read_text()
        self.assertNotIn('<script>',html); self.assertIn('草稿',html)

    def test_pdf_extraction_pages_and_corrupt_pdf(self):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        path=self.path/'source.pdf'
        writer=PdfWriter(); page=writer.add_blank_page(width=300,height=200)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        stream=DecodedStreamObject(); stream.set_data(b'BT /F1 12 Tf 20 150 Td (Synthetic evidence: n = 3 cultures per group.) Tj ET')
        page[NameObject('/Contents')]=writer._add_object(stream)
        with path.open('wb') as output: writer.write(output)
        inspection=inspect_payload(path.read_bytes()); self.assertTrue(inspection['valid']); self.assertEqual(inspection['validation'],'opened_with_pypdf')
        r=prepare(path,self.path/'reader',True); self.assertEqual(r['pages_rendered'],1); self.assertGreater(r['blocks'],0)
        self.assertFalse(inspect_payload(b'%PDF-1.7 corrupted body')['valid'])

    def test_bibtex_arxiv_and_author_roundtrip(self):
        try: import bibtexparser
        except ImportError: self.skipTest('bibtexparser not installed')
        rows=deduplicate(load(ROOT/'tests/fixtures/records.json')['records'])['records']; content,_=export_records(rows,'bib')
        path=self.path/'refs.bib'; path.write_text(content); got=import_references(path)['records']
        self.assertEqual({r['identifiers'].get('arxiv') for r in got if r['identifiers'].get('arxiv')},{'2401.00001v1','2401.00001v2'})

    def test_metadata_jats_and_html_are_not_fulltext(self):
        self.assertFalse(inspect_payload(b'<html>Login</html>')['valid'])
        self.assertFalse(inspect_payload(b'<article><front><article-title>T</article-title></front></article>')['valid'])
        self.assertTrue(inspect_payload(b'<article><body><p>Full text</p></body></article>')['valid'])
        p=self.path/'meta.xml'; p.write_text('<article><front/></article>')
        with self.assertRaises(ValueError): prepare(p,self.path/'reader')

    def test_download_resumes_only_when_file_hash_matches(self):
        payload=b'<article><body><p>Full text</p></body></article>'; item={'url':'https://publisher.example/article.xml','access':'open_access'}
        r=download_batch([item],self.path/'downloads',FakeClient([payload])); self.assertEqual(r['successful'],1)
        r=download_batch([item],self.path/'downloads',FakeClient([])); self.assertTrue(r['results'][0]['reused'])
        (self.path/'downloads'/r['results'][0]['file']).write_bytes(b'corrupt')
        r=download_batch([item],self.path/'downloads',FakeClient([b'<html>paywall</html>'])); self.assertEqual(r['successful'],0)

    def test_claim_support_needs_semantics_and_source(self):
        doc=new_claims('A claim'); doc['claims'][0]['status']='supported'
        result=validate_claims(doc,self.path); self.assertFalse(result['valid'])
        source=self.path/'source.md'; source.write_text('Observed outcome.')
        c=doc['claims'][0]; c.update(evidence_type='direct',semantic_review={'assessor':'test','rationale':'Context checked'},sources=[{'path':'source.md','locator':'line 1','excerpt':'Observed outcome.','source_sha256':digest(source.read_bytes())}])
        self.assertTrue(validate_claims(doc,self.path)['valid'])
        c['sources'][0]['excerpt']='Not present'; self.assertFalse(validate_claims(doc,self.path)['valid'])

    def test_prisma_counts_reports_separately_from_studies(self):
        rows=[{'record_id':'a','title_abstract_decision':'include','report_id':'paper1','retrieval':'retrieved','fulltext_decision':'include','study_id':'study1'}, {'record_id':'b','duplicate_of':'a'}, {'record_id':'c','title_abstract_decision':'include','report_id':'paper2','retrieval':'retrieved','fulltext_decision':'include','study_id':'study1'}, {'record_id':'d','title_abstract_decision':'include','report_id':'paper3','retrieval':'not_retrieved'}]
        r=screening_flow({'records':rows}); self.assertTrue(r['complete']); self.assertEqual(r['counts']['reports_included'],2); self.assertEqual(r['counts']['studies_included'],1); self.assertEqual(r['counts']['reports_not_retrieved'],1)

    def test_pending_and_unreasoned_exclusion_are_not_complete(self):
        r=screening_flow({'records':[{'record_id':'r1','title_abstract_decision':'pending'}]}); self.assertFalse(r['complete'])
        r=screening_flow({'records':[{'record_id':'r1','title_abstract_decision':'include','report_id':'p1','retrieval':'retrieved','fulltext_decision':'exclude'}]}); self.assertFalse(r['valid'])

    def test_review_rejects_shared_context_and_modified_packet(self):
        source=self.path/'paper.md'; source.write_text('Manuscript'); packet=freeze_packet([source],self.path/'packet',2); files=[]
        for i in [1,2]:
            f=self.path/f'reviewer{i}.json'; save(f,{'packet_sha256':packet['packet_sha256'],'reviewer_id':str(i),'isolated_context_id':'same-context','status':'complete','findings':[]}); files.append(f)
        self.assertFalse(collect_reviews(packet['packet'],files)['ready_for_synthesis'])
        obj=load(files[1]); obj['isolated_context_id']='second-context'; save(files[1],obj)
        self.assertTrue(collect_reviews(packet['packet'],files)['ready_for_synthesis'])
        (self.path/'packet/sources/01-paper.md').write_text('changed'); self.assertFalse(collect_reviews(packet['packet'],files)['ready_for_synthesis'])

    def test_ranking_is_bounded_and_relevance_gated(self):
        r=prioritize([{'title':'Unrelated topic','year':2026,'citation_count':999999},{'title':'Senescence','year':2030,'citation_count':999999}],['senescence'],2026)
        self.assertLessEqual(r['records'][0]['reading_priority']['score'],100); self.assertEqual(r['records'][1]['reading_priority']['score'],0); self.assertEqual(r['records'][0]['reading_priority']['evidence_certainty'],'not_assessed')

    def test_scansci_payload_cannot_use_upstream_gray_default(self):
        r=scansci_request('10.1234/a'); self.assertEqual(r['arguments']['strategy'],'legal_only'); self.assertIs(r['arguments']['scihub_enabled'],False)

    def test_end_to_end_local_library_and_exports(self):
        workspace=self.path/'project'; self.cli('init',workspace,'--question','Example')
        unique=self.path/'unique.json'; r=self.cli('dedupe',ROOT/'tests/fixtures/records.json','--out',unique); self.assertEqual(r['unique_count'],3)
        self.cli('archive',unique,'--workspace',workspace); self.cli('archive',unique,'--workspace',workspace)
        self.assertEqual(len(load(workspace/'library/records.json')['records']),3)
        output=self.path/'refs.ris'; self.cli('export',unique,'--format','ris','--out',output); self.assertEqual(output.read_text().count('ER  -'),3)
        self.cli('screen-init',unique,'--out',self.path/'screen.json'); flow=self.cli('flow',self.path/'screen.json'); self.assertFalse(flow['complete'])
        self.cli('question-init','A testable question?','--out',self.path/'question.json'); self.assertEqual(load(self.path/'question.json')['status'],'draft')

    def test_schema_accepts_actual_generated_artifacts(self):
        try: import jsonschema
        except ImportError: self.skipTest('jsonschema not installed')
        jsonschema.validate(new_claims('Claim'),load(ROOT/'schemas/claim.schema.json'))
        jsonschema.validate(normalize_record({'title':'Title'}),load(ROOT/'schemas/record.schema.json'))



if __name__=='__main__': unittest.main()
