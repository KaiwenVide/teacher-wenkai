from __future__ import annotations
import datetime as dt
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from wkr.common import load, save, digest
from wkr.paper_reverse import prepare_reverse, check_reverse, render_reverse
from wkr.cns_monthly import collect_month, check_month, render_month, month_window, JOURNALS
from wkr.http import NetworkError

class Fake:
    def __init__(self, *responses):
        self.responses = iter(responses); self.requests = []; self.calls = []
    def json(self, url, **kwargs):
        self.calls.append((url, kwargs)); self.requests.append({'url': url})
        response = next(self.responses)
        if isinstance(response, Exception): raise response
        return response

def cross(items, total=None, cursor='next'):
    return {'message': {'items': items, 'total-results': len(items) if total is None else total, 'next-cursor': cursor}}

def epmc(items, total=None, cursor='next'):
    return {'resultList': {'result': items}, 'hitCount': len(items) if total is None else total, 'nextCursorMark': cursor}

def article(n=1, month='2026-09', journal='Nature', issn='0028-0836'):
    return {'DOI': f'10.1234/synthetic{n}', 'title': [f'Synthetic experiment {n}'],
            'container-title': [journal], 'ISSN': [issn], 'type': 'journal-article',
            'published-online': {'date-parts': [[int(month[:4]), int(month[5:]), 12]]},
            'abstract': '<p>Synthetic culture experiment with a treatment and control.</p>'}

def reviewed_month(root, month='2026-09', observations=2):
    items = [article(i+1, month) for i in range(observations)]
    client = Fake(cross(items), epmc([]), cross([]), epmc([]), cross([]), epmc([]))
    collect_month(month, root, client=client, today=dt.date(2026, 10, 19))
    screening = load(root/'screening.json'); screening['assessor'] = 'synthetic-test'
    for i, p in enumerate(screening['papers']):
        p.update(include=True, life_sciences=True, article_type='primary_research',
                 reason='Synthetic biology fixture', study_key=f'independent-{i}',
                 reading_level='abstract', finding='A reported endpoint differs.',
                 methods='Culture comparison.', limitations='Synthetic abstract only.',
                 source_locator='Crossref abstract')
    save(root/'screening.json', screening)
    synthesis = load(root/'synthesis.json')
    synthesis.update(assessor='synthetic-test', taxonomy_id='synthetic-v1', summary='Synthetic monthly signal.',
                     coverage_notes='Only synthetic API fixtures were read.',
                     publisher_checks=[{'journal': j, 'url': 'https://example.org/'+j,
                                        'status': 'unavailable', 'note': 'Offline synthetic test.'} for j in JOURNALS])
    if observations >= 2:
        synthesis['trends'] = [{'title': 'Synthetic convergence', 'kind': 'monthly_signal',
                                'finding': 'Two separate studies address an endpoint.',
                                'paper_ids': [p['record_id'] for p in screening['papers']],
                                'limitations': 'Synthetic sources, abstract level.',
                                'next_experiment': 'An independent, randomized pilot.'}]
    else:
        synthesis['single_paper_signals'] = [{'paper_id': screening['papers'][0]['record_id'],
                                              'finding': 'One synthetic finding.', 'limitation': 'One abstract.'}]
    save(root/'synthesis.json', synthesis)
    return screening, synthesis

class ReverseTests(unittest.TestCase):
    def prepared(self, temp):
        root = Path(temp); source = root/'synthetic.md'
        source.write_text('Synthetic paper, not a real biological result.\n\nTreatment A reduced endpoint Y in six independent cultures per group. Control cultures received vehicle. Allocation was randomized.\n')
        out = root/'reverse'; prepare_reverse([source], out, 'Does A alter Y?')
        doc = load(out/'reconstruction.json')
        doc['paper'].update(title='Synthetic paper')
        doc['evidence'] = [{'evidence_id': 'E1', 'kind': 'observation', 'statement': 'Reported reduction.',
                            'anchors': [{'source_id': 'S1', 'block_id': 'B00002',
                                         'quote': 'Treatment A reduced endpoint Y'}]}]
        doc['experiments'] = [{'experiment_id': 'X1', 'question': 'Effect of A?', 'model': 'Cultures',
                               'groups': ['A', 'vehicle'], 'biological_unit': 'independent culture',
                               'sample_size': 'six per group', 'intervention': 'A', 'readout': 'Y',
                               'outcome': 'Y reduced', 'evidence_ids': ['E1'], 'not_reported': ['statistics']}]
        doc['claims'] = [{'claim_id': 'C1', 'text': 'A reduced measured Y in this synthetic experiment.',
                          'status': 'supported', 'evidence_ids': ['E1'], 'rationale': 'The reported comparison.',
                          'boundary': 'Only synthetic culture results.',
                          'alternative_explanations': ['Measurement interference.'],
                          'decisive_test': 'An orthogonal assay.'}]
        doc['reproduction'] = {'requirements': ['Cultures and A'], 'steps': ['Confirm assay conditions.'],
                               'minimum_discriminating_experiment': 'Vehicle-controlled orthogonal assay.',
                               'success_criterion': 'Concordant endpoint change.',
                               'alternative_outcomes': ['Assay-specific interference.'],
                               'feasibility': 'Actual protocol and statistics are not available.'}
        doc['missing_materials'] = ['Full protocol.']
        doc['review'] = {'assessor': 'synthetic-test', 'source_fidelity_checked': True,
                         'limitations': ['Synthetic material; no actual replication.']}
        save(out/'reconstruction.json', doc)
        return source, out, doc

    def test_anchored_reconstruction_with_explicit_gaps(self):
        with tempfile.TemporaryDirectory() as t:
            source, out, doc = self.prepared(t)
            result = render_reverse(out, Path(t)/'report.md')
            self.assertTrue(result['valid']); self.assertEqual(result['status'], 'reviewed_with_gaps')
            self.assertTrue((Path(t)/'report.md').is_file())
    def test_preparation_is_not_completed_reading(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t)/'x.md'; p.write_text('Synthetic source.')
            out = Path(t)/'out'; prepare_reverse([p], out)
            self.assertFalse(check_reverse(out)['valid'])
    def test_changed_original_invalidates_reconstruction(self):
        with tempfile.TemporaryDirectory() as t:
            source, out, doc = self.prepared(t); source.write_text('Changed.')
            self.assertFalse(check_reverse(out)['valid'])
    def test_wrong_block_cannot_support_excerpt(self):
        with tempfile.TemporaryDirectory() as t:
            _, out, doc = self.prepared(t); doc['evidence'][0]['anchors'][0]['block_id'] = 'B00001'
            save(out/'reconstruction.json', doc); self.assertFalse(check_reverse(out)['valid'])
    def test_inference_is_not_direct_observation(self):
        with tempfile.TemporaryDirectory() as t:
            _, out, doc = self.prepared(t); doc['evidence'][0]['kind'] = 'inference'
            save(out/'reconstruction.json', doc); self.assertFalse(check_reverse(out)['valid'])
    def test_unknown_evidence_reference_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            _, out, doc = self.prepared(t); doc['claims'][0]['evidence_ids'] = ['absent']
            save(out/'reconstruction.json', doc); self.assertFalse(check_reverse(out)['valid'])
    def test_visual_claim_needs_rendered_page(self):
        with tempfile.TemporaryDirectory() as t:
            _, out, doc = self.prepared(t)
            doc['evidence'][0]['anchors'] = [{'source_id': 'S1', 'page': 1, 'visual_description': 'A graph.', 'visual_checked': True}]
            save(out/'reconstruction.json', doc); self.assertFalse(check_reverse(out)['valid'])

class MonthlyTests(unittest.TestCase):
    def test_previous_month_handles_year_boundary(self):
        self.assertEqual(str(month_window(today=dt.date(2026, 1, 5))[0]), '2025-12-01')
        self.assertEqual(str(month_window('2024-02', dt.date(2026, 1, 5))[1]), '2024-02-29')
        with self.assertRaises(ValueError): month_window('2026-10', dt.date(2026, 10, 19))
    def test_full_pagination_and_family_journal_exclusion(self):
        with tempfile.TemporaryDirectory() as t:
            client = Fake(cross([article(1)], 3, 'a'), cross([article(2)], 3, 'b'),
                          cross([article(3, journal='Nature Genetics', issn='1061-4036')], 3),
                          epmc([]), cross([]), epmc([]), cross([]), epmc([]))
            r = collect_month('2026-09', Path(t)/'out', page_size=1, client=client, today=dt.date(2026, 10, 19))
            self.assertEqual(r['candidates'], 2); self.assertEqual(r['coverage'], 'complete_for_queries')
    def test_month_boundaries_prefer_online_over_issue_date(self):
        with tempfile.TemporaryDirectory() as t:
            item = article(1, '2026-08'); item['published-print'] = {'date-parts': [[2026, 9, 5]]}
            client = Fake(cross([item]), epmc([]), cross([]), epmc([]), cross([]), epmc([]))
            r = collect_month('2026-09', Path(t)/'out', client=client, today=dt.date(2026, 10, 19))
            self.assertEqual(r['candidates'], 0)
    def test_failure_preserves_other_sources_and_reports_partial(self):
        with tempfile.TemporaryDirectory() as t:
            client = Fake(NetworkError('synthetic unavailable'), epmc([]), cross([article(1, journal='Science', issn='0036-8075')]),
                          epmc([]), cross([]), epmc([]))
            r = collect_month('2026-09', Path(t)/'out', client=client, today=dt.date(2026, 10, 19))
            self.assertEqual(r['coverage'], 'partial'); self.assertEqual(r['candidates'], 1)
    def test_page_budget_and_repeated_cursor_not_exhaustive(self):
        for cap in [1, 3]:
            with tempfile.TemporaryDirectory() as t:
                responses = [cross([article(1)], 10, '*'), epmc([]), cross([]), epmc([]), cross([]), epmc([])]
                r = collect_month('2026-09', Path(t)/'out', max_pages=cap, client=Fake(*responses), today=dt.date(2026, 10, 19))
                self.assertEqual(r['coverage'], 'partial')
    def test_reviewed_abstract_report_remains_abstract_level(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)/'run'; reviewed_month(root)
            result = render_month(root, Path(t)/'monthly.md')
            self.assertTrue(result['valid'], result)
            self.assertIn('abstract', (Path(t)/'monthly.md').read_text())
    def test_unread_or_missing_fulltext_cannot_complete(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)/'run'; screening, _ = reviewed_month(root)
            for level in ['unread', 'fulltext']:
                screening['papers'][0]['reading_level'] = level
                save(root/'screening.json', screening)
                self.assertFalse(check_month(root)['valid'])
    def test_single_study_or_review_is_not_independent_trend_support(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)/'run'; screening, _ = reviewed_month(root)
            screening['papers'][1]['study_key'] = screening['papers'][0]['study_key']
            save(root/'screening.json', screening); self.assertFalse(check_month(root)['valid'])
            screening['papers'][1].update(study_key='second', article_type='review')
            save(root/'screening.json', screening); self.assertFalse(check_month(root)['valid'])
    def test_growth_needs_comparable_reviewed_baseline(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)/'run'; _, synthesis = reviewed_month(root)
            synthesis['trends'][0].update(kind='change_over_baseline', comparison_basis='Synthetic comparison.')
            save(root/'synthesis.json', synthesis); self.assertFalse(check_month(root)['valid'])
            prior = Path(t)/'prior'; reviewed_month(prior, '2026-08')
            render_month(prior, Path(t)/'prior.md')
            self.assertTrue(check_month(root, prior)['valid'])
            changed = load(prior/'synthesis.json'); changed['summary'] = 'Changed after review.'
            save(prior/'synthesis.json', changed); self.assertFalse(check_month(root, prior)['valid'])
    def test_changed_corpus_or_raw_page_invalidates_review(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)/'run'; reviewed_month(root)
            next((root/'raw').glob('*.json')).write_text('{}')
            self.assertFalse(check_month(root)['valid'])
    def test_collection_does_not_mark_screening_complete(self):
        with tempfile.TemporaryDirectory() as t:
            client = Fake(cross([article()]), epmc([]), cross([]), epmc([]), cross([]), epmc([]))
            root = Path(t)/'out'; collect_month('2026-09', root, client=client, today=dt.date(2026, 10, 19))
            self.assertFalse(check_month(root)['valid'])

    def test_invalid_calendar_days_never_verify_publication_month(self):
        with tempfile.TemporaryDirectory() as t:
            invalid = article(); invalid['published-online'] = {'date-parts': [[2026, 9, 99]]}
            pub = {'id': '999999991', 'source': 'MED', 'doi': '10.1234/synthetic2',
                   'title': 'Synthetic invalid date', 'firstPublicationDate': '2026-09-99',
                   'journalInfo': {'journal': {'title': 'Nature', 'issn': '0028-0836'}}}
            root = Path(t)/'run'
            collect_month('2026-09', root, client=Fake(cross([invalid]), epmc([pub]), cross([]), epmc([]), cross([]), epmc([])),
                          today=dt.date(2026, 10, 19))
            self.assertTrue(all(r['month_status'] == 'unresolved' for r in load(root/'corpus.json')['records']))
            self.assertTrue(all(not p['month_verified'] for p in load(root/'screening.json')['papers']))
    def test_empty_dates_are_unresolved_but_month_precision_is_valid(self):
        with tempfile.TemporaryDirectory() as t:
            a = article(1); a['published-online'] = {'date-parts': []}
            b = article(2); b['published-online'] = {'date-parts': [[2026, 9]]}
            root = Path(t)/'run'
            collect_month('2026-09', root, client=Fake(cross([a,b]), epmc([]), cross([]), epmc([]), cross([]), epmc([])),
                          today=dt.date(2026, 10, 19))
            states = {r['identifiers']['doi']:r['month_status'] for r in load(root/'corpus.json')['records']}
            self.assertEqual(states['10.1234/synthetic1'], 'unresolved')
            self.assertEqual(states['10.1234/synthetic2'], 'in_month')
    def test_baseline_raw_and_fulltext_changes_are_rechecked(self):
        for artifact in ['raw', 'fulltext']:
            with self.subTest(artifact=artifact), tempfile.TemporaryDirectory() as t:
                root = Path(t)/'run'; _, synthesis = reviewed_month(root)
                synthesis['trends'][0].update(kind='change_over_baseline', comparison_basis='Synthetic comparison.')
                save(root/'synthesis.json', synthesis)
                prior = Path(t)/'prior'; screening, _ = reviewed_month(prior, '2026-08')
                text = prior/'source.md'; text.write_text('Synthetic source with actual local text.')
                screening['papers'][0].update(reading_level='fulltext', fulltext_sources=[
                    {'path':'source.md','sha256':digest(text.read_bytes()),'locator':'paragraph 1'}])
                save(prior/'screening.json', screening)
                self.assertTrue(render_month(prior, Path(t)/'prior.md')['valid'])
                changed = next((prior/'raw').glob('*.json')) if artifact == 'raw' else text
                changed.write_bytes(changed.read_bytes()+b'\n')
                self.assertFalse(check_month(root, prior)['valid'])
    def test_retracted_publication_type_is_preserved_as_warning(self):
        with tempfile.TemporaryDirectory() as t:
            pub = {'id':'999999992','source':'MED','doi':'10.1234/synthetic2','title':'Synthetic withdrawn study',
                   'firstPublicationDate':'2026-09-03','pubTypeList':{'pubType':['Retracted Publication']},
                   'journalInfo':{'journal':{'title':'Nature','issn':'0028-0836'}}}
            root=Path(t)/'run'
            collect_month('2026-09', root, client=Fake(cross([]),epmc([pub]),cross([]),epmc([]),cross([]),epmc([])),
                          today=dt.date(2026,10,19))
            self.assertTrue(load(root/'corpus.json')['records'][0]['retraction_notice_flag'])

if __name__ == '__main__': unittest.main()
