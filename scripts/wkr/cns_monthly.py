"""Monthly flagship CNS discovery and evidence-linked, reviewed trend reports."""
from __future__ import annotations
import datetime as dt
import re
from pathlib import Path
from zoneinfo import ZoneInfo
from .common import digest, load, now, save, write
from .http import Client, NetworkError
from .model import normalize_doi
from .providers import crossref_record, epmc_record, provider_request

JOURNALS = {'Nature': ['0028-0836', '1476-4687'], 'Science': ['0036-8075', '1095-9203'],
            'Cell': ['0092-8674', '1097-4172']}
SCOPE = {'journals': list(JOURNALS), 'field': 'life_sciences', 'screening': 'manual_title_abstract_fulltext_v1'}

def month_window(month=None, today=None):
    today = today or dt.datetime.now(ZoneInfo('Asia/Shanghai')).date()
    previous = today.replace(day=1)-dt.timedelta(days=1)
    month = month or previous.strftime('%Y-%m')
    if not re.fullmatch(r'\d{4}-(?:0[1-9]|1[0-2])', month):
        raise ValueError('Month must be YYYY-MM')
    first = dt.date.fromisoformat(month+'-01')
    if first >= today.replace(day=1): raise ValueError('Use a completed calendar month')
    next_month = (first.replace(day=28)+dt.timedelta(days=4)).replace(day=1)
    return first, next_month-dt.timedelta(days=1)

def _crossref_month(item):
    for key in ['published-online', 'published', 'issued', 'published-print']:
        date_parts = (item.get(key) or {}).get('date-parts') or [[]]
        parts = date_parts[0]
        if parts:
            if len(parts) < 2: return None, key+'_year_only'
            try: return dt.date(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 1).strftime('%Y-%m'), key
            except (ValueError, TypeError): return None, key+'_invalid'
    return None, 'missing'

def _record(raw, source, journal, month):
    if source == 'crossref':
        issns = raw.get('ISSN', []); name = (raw.get('container-title') or [''])[0]
        rec = crossref_record(raw); published, basis = _crossref_month(raw)
    else:
        ji = raw.get('journalInfo', {}).get('journal', {})
        issns = [ji.get('issn'), ji.get('essn')]; name = ji.get('title', '')
        rec = epmc_record(raw); date = raw.get('firstPublicationDate', '')
        try: published = dt.date.fromisoformat(date).strftime('%Y-%m') if isinstance(date, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', date) else None
        except ValueError: published = None
        basis = 'firstPublicationDate'
        rec['publication_types'] = raw.get('pubTypeList', {}).get('pubType', [])
        rec['retraction_notice_flag'] = raw.get('isRetracted') == 'Y' or any(
            str(t).casefold() in ['retracted publication', 'retraction of publication'] for t in rec['publication_types'])
    issns = [s for s in issns if s]
    aliases = {journal.casefold()}
    if journal == 'Science': aliases.add('science (new york, n.y.)')
    if (issns and not set(issns).intersection(JOURNALS[journal])) or (not issns and name.casefold().strip() not in aliases):
        return None, 'different_journal'
    rec['journal'] = journal
    rec['date_evidence'] = [{'provider': source, 'month': published, 'basis': basis}]
    rec['provenance'] = [{'source': source, 'accessed_at': now(),
                          'level': 'abstract' if rec.get('abstract') else 'metadata'}]
    rec['access_level'] = 'abstract' if rec.get('abstract') else 'metadata'
    rec['month_status'] = 'in_month' if published == month else 'unresolved' if not published else 'outside_month'
    return rec, None

def collect_month(month, out, max_pages=20, page_size=100, client=None, today=None):
    first, last = month_window(month, today); month = first.strftime('%Y-%m')
    if not 1 <= max_pages <= 100 or not 1 <= page_size <= 1000:
        raise ValueError('max_pages must be 1..100 and page_size 1..1000')
    out = Path(out)
    if out.exists() and any(out.iterdir()): raise ValueError('Use a new monthly retrieval directory')
    out.mkdir(parents=True, exist_ok=True)
    client = client or Client()
    merged = {}; searches = []; exclusions = []
    for journal, issns in JOURNALS.items():
        for source in ['crossref', 'europepmc']:
            query = f'ISSN:{issns[0]} AND FIRST_PDATE:[{first} TO {last}]'
            cursor = '*'; seen_cursors = set(); count = 0; total = None; failure = None; pages = []
            for number in range(1, max_pages+1):
                try:
                    if cursor in seen_cursors: raise ValueError('Repeated pagination cursor')
                    seen_cursors.add(cursor)
                    if source == 'crossref':
                        params = {'filter': f'from-pub-date:{first},until-pub-date:{last},type:journal-article',
                                  'rows': page_size, 'cursor': cursor}
                        data = provider_request(client, source, 'journals/'+issns[0]+'/works', params)
                        body = data['message']; batch = body['items']; current_total = int(body['total-results'])
                        next_cursor = body.get('next-cursor')
                    else:
                        params = {'query': query, 'format': 'json', 'resultType': 'core', 'pageSize': page_size, 'cursorMark': cursor}
                        data = provider_request(client, source, 'search', params)
                        batch = data['resultList']['result']; current_total = int(data['hitCount'])
                        next_cursor = data.get('nextCursorMark')
                    if total is not None and current_total != total:
                        raise ValueError('Result count changed during retrieval; rerun in a new directory')
                    total = current_total
                    path = out/'raw'/f'{journal.lower()}-{source}-{number:03d}.json'
                    save(path, data); pages.append({'path': str(path.relative_to(out)), 'sha256': digest(path.read_bytes())})
                    count += len(batch)
                    for raw in batch:
                        rec, reason = _record(raw, source, journal, month)
                        if rec is None:
                            exclusions.append({'provider': source, 'journal': journal, 'reason': reason,
                                               'doi': normalize_doi(raw.get('DOI') or raw.get('doi'))}); continue
                        key = rec['record_id']
                        old = merged.get(key)
                        if old:
                            old['date_evidence'].extend(rec['date_evidence']); old['provenance'].extend(rec['provenance'])
                            for k in ['abstract', 'publication_types']:
                                if not old.get(k) and rec.get(k): old[k] = rec[k]
                            old['identifiers'].update(rec['identifiers'])
                            for loc in rec.get('oa_locations', []):
                                if loc not in old['oa_locations']: old['oa_locations'].append(loc)
                            old['retraction_notice_flag'] = old.get('retraction_notice_flag', False) or rec.get('retraction_notice_flag', False)
                        else: merged[key] = rec
                    if count >= total: break
                    if not batch or not next_cursor: raise ValueError('Pagination ended before the advertised total')
                    cursor = next_cursor
                except (NetworkError, ValueError, TypeError, KeyError) as error:
                    failure = str(error); break
            searches.append({'journal': journal, 'provider': source, 'query': query if source == 'europepmc' else params,
                             'expected_total': total, 'retrieved_before_filtering': count, 'pages': pages,
                             'complete_for_query': failure is None and total is not None and count >= total,
                             'failure': failure, 'page_budget': max_pages})
    records = []
    for rec in merged.values():
        dates = {d['month'] for d in rec['date_evidence'] if d['month']}
        if dates and month not in dates:
            exclusions.append({'record_id': rec['record_id'], 'reason': 'first_publication_outside_month', 'date_evidence': rec['date_evidence']})
            continue
        rec['month_status'] = 'in_month' if dates == {month} else 'conflicting_dates' if len(dates) > 1 else 'unresolved'
        rec['access_level'] = 'abstract' if rec.get('abstract') else 'metadata'
        records.append(rec)
    records.sort(key=lambda r: (r['journal'], r['record_id']))
    corpus = {'schema_version': '1.0', 'month': month, 'window': [str(first), str(last)], 'scope': SCOPE,
              'collected_at': now(), 'records': records, 'searches': searches, 'exclusions': exclusions,
              'coverage': 'complete_for_queries' if all(s['complete_for_query'] for s in searches) else 'partial',
              'limits': 'Database coverage and indexing lag remain; publisher contents and publication types require review. Life-science screening and full-text reading have not occurred.',
              'requests': client.requests}
    save(out/'corpus.json', corpus)
    save(out/'screening.json', {'corpus_sha256': digest(corpus), 'assessor': '', 'papers': [
        {'record_id': r['record_id'], 'include': None, 'life_sciences': None, 'article_type': 'pending', 'reason': '',
         'month_verified': r['month_status'] == 'in_month', 'study_key': '', 'reading_level': 'unread',
         'finding': '', 'methods': '', 'limitations': '', 'source_locator': '', 'fulltext_sources': []} for r in records]})
    save(out/'synthesis.json', {'corpus_sha256': digest(corpus), 'assessor': '', 'taxonomy_id': '',
                              'summary': '', 'trends': [], 'single_paper_signals': [], 'coverage_notes': '',
                              'publisher_checks': []})
    write(out/'reading-brief.md', '# CNS 月度研读任务\n\n'+month+'\n\n'
          '候选记录不是生命科学纳入结果。先逐篇填写 screening.json；新闻、社论、更正和综述不得混作独立原始研究。\n'
          '核对三刊当月目录与在线发表日期，补查索引延迟。阅读纳入文章的摘要，关键论断尽量精读全文与补充材料。\n'
          '把已读证据、可迁移方法、限制与下一步实验写入 synthesis.json，再运行 cns-report。\n'
          '首次报告描述当月信号；没有可比基线不能声称升温。无法获取全文时明确标注摘要层级。\n')
    return {'status': 'awaiting_screening_and_reading', 'month': month, 'candidates': len(records),
            'coverage': corpus['coverage'], 'output': str(out), 'failures': [s for s in searches if s['failure']]}

def _artifact_issues(root, corpus, screening):
    from .common import within
    issues = []
    for search in corpus['searches']:
        for raw in search['pages']:
            path = within(root, raw['path'])
            if not path.is_file() or digest(path.read_bytes()) != raw['sha256']:
                issues.append('Raw retrieval evidence changed or missing')
    for paper in screening.get('papers', []):
        if paper.get('include') and paper.get('reading_level') == 'fulltext':
            for source in paper.get('fulltext_sources', []):
                path = Path(source.get('path', '')).expanduser()
                if not path.is_absolute(): path = root/path
                if not source.get('locator') or not path.is_file() or digest(path.read_bytes()) != source.get('sha256'):
                    issues.append(str(paper.get('record_id'))+': full-text source missing, changed, or unanchored')
    return issues

def _describe(value):
    if isinstance(value, dict): return '; '.join(str(k)+': '+_describe(v) for k, v in value.items())
    if isinstance(value, list): return '; '.join(_describe(v) for v in value)
    return str(value)

def check_month(directory, baseline=None):
    root = Path(directory); corpus = load(root/'corpus.json')
    screening = load(root/'screening.json'); synthesis = load(root/'synthesis.json')
    issues = []; notes = []
    for value in [screening, synthesis]:
        if value.get('corpus_sha256') != digest(corpus): issues.append('Corpus changed after screening or synthesis')
        if not value.get('assessor'): issues.append('Assessor missing')
    issues.extend(_artifact_issues(root, corpus, screening))
    if corpus['coverage'] != 'complete_for_queries': notes.append('Partial retrieval; do not claim comprehensive monthly coverage')
    indexed = {r['record_id']: r for r in corpus['records']}
    papers = screening.get('papers', [])
    pids = [p.get('record_id') for p in papers]
    if len(set(pids)) != len(pids) or set(pids) != set(indexed): issues.append('Screening does not exactly cover retrieved candidates')
    included = {}
    for p in papers:
        pid = p.get('record_id'); rec = indexed.get(pid, {})
        if type(p.get('include')) is not bool or not p.get('reason'): issues.append(str(pid)+': screening decision/reason missing')
        if not p.get('include'): continue
        included[pid] = p
        if p.get('life_sciences') is not True or p.get('month_verified') is not True:
            issues.append(str(pid)+': field or month unverified')
        if p.get('article_type') not in ['primary_research', 'review']:
            issues.append(str(pid)+': only research and separately labeled reviews enter the synthesis')
        level = p.get('reading_level')
        if level not in ['abstract', 'fulltext']: issues.append(str(pid)+': article not read')
        if level == 'abstract' and not rec.get('abstract'): issues.append(str(pid)+': no abstract in retrieved material')
        for field in ['finding', 'methods', 'limitations', 'source_locator', 'study_key']:
            if not p.get(field): issues.append(str(pid)+': missing '+field)
        if rec.get('retraction_notice_flag'): issues.append(str(pid)+': retraction notice requires exclusion from positive evidence')
        if level == 'fulltext':
            if not p.get('fulltext_sources'): issues.append(str(pid)+': full text needs saved source evidence')
    baseline_data = None
    if baseline:
        b = Path(baseline); baseline_data = load(b/'corpus.json'); prior = load(b/'synthesis.json')
        issues.extend('Baseline: '+issue for issue in _artifact_issues(b, baseline_data, load(b/'screening.json')))
        approval = load(b/'report-validation.json')
        if baseline_data['month'] >= corpus['month'] or baseline_data['scope'] != corpus['scope']:
            issues.append('Baseline period/scope is not comparable')
        expected = {'corpus_sha256': digest(baseline_data), 'screening_sha256': digest(load(b/'screening.json')), 'synthesis_sha256': digest(prior)}
        if not approval.get('valid') or any(approval.get(k) != v for k, v in expected.items()):
            issues.append('Baseline has no current reviewed report')
        if not synthesis.get('taxonomy_id') or synthesis.get('taxonomy_id') != prior.get('taxonomy_id'):
            issues.append('Baseline topic taxonomy differs or is missing')
    for trend in synthesis.get('trends', []):
        refs = trend.get('paper_ids', [])
        primary = [included[r] for r in refs if r in included and included[r].get('article_type') == 'primary_research']
        if len({p['study_key'] for p in primary}) < 2:
            issues.append('A trend requires at least two independently identified primary studies; use single_paper_signals otherwise')
        if len(set(refs)) != len(refs) or any(r not in included for r in refs):
            issues.append('Trend has duplicate or unknown included-paper references')
        if trend.get('kind') not in ['monthly_signal', 'change_over_baseline']: issues.append('Trend kind missing or invalid')
        if trend.get('kind') == 'change_over_baseline' and (baseline_data is None or not trend.get('comparison_basis')):
            issues.append('Change claims need a reviewed comparable baseline and explicit comparison basis')
        for field in ['title', 'finding', 'limitations', 'next_experiment']:
            if not trend.get(field): issues.append('Trend lacks '+field)
    for signal in synthesis.get('single_paper_signals', []):
        if signal.get('paper_id') not in included or not signal.get('finding') or not signal.get('limitation'):
            issues.append('Single-paper signal missing its read source or limitations')
    if not synthesis.get('summary') or not synthesis.get('coverage_notes'): issues.append('Summary or coverage notes missing')
    checks = {x.get('journal'): x for x in synthesis.get('publisher_checks', [])}
    for name in JOURNALS:
        entry = checks.get(name, {})
        if entry.get('status') not in ['checked', 'unavailable'] or not entry.get('url') or not entry.get('note'):
            issues.append(name+': record publisher contents check or access failure')
        if entry.get('status') == 'unavailable': notes.append(name+': publisher coverage unverified')
    if included and not synthesis.get('trends') and not synthesis.get('single_paper_signals'):
        issues.append('Included papers lack an evidence-linked synthesis')
    return {'valid': not issues, 'issues': issues, 'coverage_notes': notes, 'included': len(included),
            'month': corpus['month'], 'corpus_sha256': digest(corpus), 'screening_sha256': digest(screening),
            'synthesis_sha256': digest(synthesis), 'scope': 'Source links and declared review; semantic validity still requires reading and judgment.'}

def render_month(directory, out, baseline=None):
    root = Path(directory); out = Path(out)
    if out.exists(): raise ValueError('Use a new monthly report path')
    check = check_month(root, baseline)
    corpus = load(root/'corpus.json'); screening = load(root/'screening.json'); synthesis = load(root/'synthesis.json')
    by_id = {r['record_id']: r for r in corpus['records']}
    lines = ['# '+corpus['month']+' CNS 生命科学月报', '',
             '状态：'+('已记录阅读与来源复核' if check['valid'] else '草稿：复核未完成'), '',
             synthesis.get('summary') or '尚未归纳研究信号。', '', '## 覆盖与限制', '',
             synthesis.get('coverage_notes', ''), '检索状态：'+corpus['coverage'],
             *check['coverage_notes'], '', '## 研究信号', '', '主题分类版本：'+(synthesis.get('taxonomy_id') or '当月定性归纳'), '']
    for t in synthesis.get('trends', []):
        lines += ['### '+t.get('title', ''), '', t.get('finding', ''), '',
                  '判断类型：'+t.get('kind', ''), '支持文章：'+', '.join(t.get('paper_ids', [])),
                  '限制与竞争解释：'+_describe(t.get('limitations', '')), '下一项判别实验：'+_describe(t.get('next_experiment', '')), '']
        if t.get('comparison_basis'): lines += ['基线比较：'+_describe(t['comparison_basis']), '']
    for s in synthesis.get('single_paper_signals', []):
        lines += ['- 单篇信号：'+s.get('finding', '')+'；'+s.get('paper_id', '')+'；限制：'+s.get('limitation', '')]
    lines += ['', '## 纳入文章与实际阅读层级', '']
    for paper in screening['papers']:
        if not paper.get('include'): continue
        r = by_id[paper['record_id']]; doi = r.get('identifiers', {}).get('doi')
        url = 'https://doi.org/'+doi if doi else 'https://europepmc.org/article/MED/'+str(r.get('identifiers', {}).get('pmid', ''))
        lines += ['### ['+r['title'].replace('[','(').replace(']',')')+']('+url+')', '',
                  r['journal']+' · '+paper['article_type']+' · '+paper['reading_level'],
                  '首次发表月份：'+_describe(r.get('date_evidence', [])),
                  '独立研究标识：'+paper.get('study_key', ''), '',
                  '发现：'+paper.get('finding', ''), '方法：'+paper.get('methods', ''),
                  '限制：'+paper.get('limitations', ''), '定位：'+paper.get('source_locator', ''), '']
    if check['issues']: lines += ['## 未完成项', '']+['- '+x for x in check['issues']]
    write(out, '\n'.join(lines)+'\n'); save(root/'report-validation.json', check)
    return {**check, 'output': str(out)}
