"""Reconstruct a paper's evidence chain from anchored local source material."""
from __future__ import annotations
import re
from pathlib import Path
from .common import digest, load, now, save, within, write
from .model import normalize_doi
from .reader import extract
from .claims import STATUSES

def prepare_reverse(sources, out, question='', doi='', render_pages=False):
    paths = [Path(p).resolve() for p in sources]
    if not paths or any(not p.is_file() for p in paths):
        raise ValueError('Provide the paper and any available supplements as local files')
    if len(set(paths)) != len(paths):
        raise ValueError('The same source was supplied more than once')
    if doi and not normalize_doi(doi):
        raise ValueError('Invalid DOI')
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise ValueError('Use a new reconstruction directory')
    out.mkdir(parents=True, exist_ok=True)
    documents = []
    for i, path in enumerate(paths, 1):
        sid = f'S{i}'
        blocks, pages = extract(path, out/sid, render_pages)
        for page in pages:
            local = out/sid/page['path']
            page['path'] = str(local.relative_to(out))
            page['sha256'] = digest(local.read_bytes())
        documents.append({'source_id': sid, 'path': str(path), 'sha256': digest(path.read_bytes()),
                          'blocks': blocks, 'pages': pages})
    mapping = {'schema_version': '1.0', 'created_at': now(), 'documents': documents}
    save(out/'source-map.json', mapping)
    reconstruction = {
        'schema_version': '1.0', 'created_at': now(), 'source_map_sha256': digest(mapping),
        'paper': {'doi': normalize_doi(doi), 'title': '', 'question': question},
        'scope': 'provided_sources', 'missing_materials': [], 'evidence': [],
        'experiments': [], 'claims': [],
        'reproduction': {'requirements': [], 'steps': [], 'minimum_discriminating_experiment': '',
                         'success_criterion': '', 'alternative_outcomes': [], 'feasibility': ''},
        'review': {'assessor': '', 'source_fidelity_checked': False, 'limitations': []},
        'boundary': 'A reconstruction of reported evidence, not recovered raw data or a completed replication.'
    }
    save(out/'reconstruction.json', reconstruction)
    return {'status': 'draft_requires_reading', 'output': str(out),
            'sources': len(documents), 'blocks': sum(len(d['blocks']) for d in documents),
            'next_action': 'Read the original text and rendered figures, then fill reconstruction.json and run paper-reverse-report.'}

def check_reverse(directory):
    root = Path(directory)
    mapping = load(root/'source-map.json')
    doc = load(root/'reconstruction.json')
    issues = []
    if doc.get('source_map_sha256') != digest(mapping):
        issues.append('Source map changed since preparation')
    sources = {}
    for source in mapping.get('documents', []):
        sid = source.get('source_id')
        if not sid or sid in sources: issues.append('Missing or duplicate source ID')
        sources[sid] = source
        path = Path(source.get('path', ''))
        if not path.is_file() or digest(path.read_bytes()) != source.get('sha256'):
            issues.append(f'{sid}: original source missing or changed')
        for page in source.get('pages', []):
            path = within(root, page['path'])
            if not path.is_file() or digest(path.read_bytes()) != page.get('sha256'):
                issues.append(f'{sid}: rendered page missing or changed')
    if not sources: issues.append('No source documents')
    evidence = {}
    norm = lambda s: re.sub(r'\s+', ' ', str(s)).strip()
    for item in doc.get('evidence', []):
        eid = item.get('evidence_id')
        if not eid or eid in evidence: issues.append('Missing or duplicate evidence ID')
        evidence[eid] = item
        if not item.get('statement') or item.get('kind') not in ['observation', 'author_interpretation', 'inference']:
            issues.append(f'{eid}: describe the evidence and distinguish observation from interpretation')
        if not item.get('anchors'): issues.append(f'{eid}: evidence has no source anchor')
        for anchor in item.get('anchors', []):
            source = sources.get(anchor.get('source_id'))
            if not source:
                issues.append(f'{eid}: unknown source'); continue
            if anchor.get('block_id'):
                block = next((b for b in source['blocks'] if b['block_id'] == anchor['block_id']), None)
                if not block or not norm(anchor.get('quote', '')) or norm(anchor['quote']) not in norm(block['original']):
                    issues.append(f'{eid}: excerpt absent from the referenced source block')
            elif anchor.get('page'):
                page = next((p for p in source['pages'] if p['page'] == anchor['page']), None)
                if not page or not anchor.get('visual_description') or anchor.get('visual_checked') is not True:
                    issues.append(f'{eid}: visual evidence requires a rendered page and explicit inspection')
            else:
                issues.append(f'{eid}: a text block or rendered page is required')
    if not evidence: issues.append('No reconstructed evidence')
    def references(item, label):
        ids = item.get('evidence_ids', [])
        if not ids or any(eid not in evidence for eid in ids):
            issues.append(f'{label}: missing or unknown evidence reference')
        return ids
    claims = doc.get('claims', [])
    seen = set()
    for claim in claims:
        cid = claim.get('claim_id')
        if not cid or cid in seen: issues.append('Missing or duplicate claim ID')
        seen.add(cid)
        ids = references(claim, str(cid))
        if not claim.get('text') or claim.get('status') not in STATUSES:
            issues.append(f'{cid}: text or evidence judgment missing')
        if claim.get('status') == 'pending': issues.append(f'{cid}: judgment is pending')
        for key in ['rationale', 'boundary', 'decisive_test']:
            if not claim.get(key): issues.append(f'{cid}: {key} missing')
        if not claim.get('alternative_explanations'): issues.append(f'{cid}: competing explanations missing')
        if claim.get('status') == 'supported' and not any(evidence.get(e, {}).get('kind') == 'observation' for e in ids):
            issues.append(f'{cid}: interpretation alone cannot establish direct support')
    if not claims: issues.append('No reconstructed claims')
    experiments = doc.get('experiments', [])
    seen = set()
    for experiment in experiments:
        xid = experiment.get('experiment_id')
        if not xid or xid in seen: issues.append('Missing or duplicate experiment ID')
        seen.add(xid)
        references(experiment, str(xid))
        missing = experiment.get('not_reported', [])
        for key in ['question', 'model', 'groups', 'biological_unit', 'sample_size', 'intervention', 'readout', 'statistics', 'outcome']:
            if not experiment.get(key) and key not in missing:
                issues.append(f'{xid}: {key} must be sourced or explicitly not_reported')
    if not experiments: issues.append('No experiment reconstruction')
    paper = doc.get('paper', {})
    if not paper.get('title') or not paper.get('question'): issues.append('Paper title or research question missing')
    reproduction = doc.get('reproduction', {})
    for key in ['requirements', 'steps', 'minimum_discriminating_experiment', 'success_criterion', 'alternative_outcomes', 'feasibility']:
        if not reproduction.get(key): issues.append('Reproduction proposal missing: '+key)
    review = doc.get('review', {})
    if not review.get('assessor') or review.get('source_fidelity_checked') is not True or not review.get('limitations'):
        issues.append('Source review and limitations have not been recorded')
    gaps = doc.get('missing_materials', []) or any(e.get('not_reported') for e in experiments)
    return {'valid': not issues, 'status': 'draft' if issues else 'reviewed_with_gaps' if gaps else 'reviewed_reconstruction',
            'issues': issues, 'scope': 'provided_sources',
            'checked': 'Source hashes, exact text anchors, declared visual review and evidence links; not scientific truth or successful replication.'}

def render_reverse(directory, out):
    root = Path(directory); out = Path(out)
    if out.exists() or Path(str(out)+'.checks.json').exists():
        raise ValueError('Use a new report path')
    check = check_reverse(root); doc = load(root/'reconstruction.json'); mapping = load(root/'source-map.json')
    sources = {s['source_id']: s for s in mapping['documents']}
    lines = ['# '+(doc['paper'].get('title') or 'Paper reconstruction'), '',
             '状态：'+check['status'], '', '研究问题：'+doc['paper'].get('question', ''),
             '', '本报告反推已报告的研究逻辑；不是恢复缺失原始数据，也不代表已完成复现。', '',
             '## 实验与证据', '']
    for experiment in doc.get('experiments', []):
        lines += ['### '+str(experiment.get('experiment_id')), '']
        for key, value in experiment.items(): lines.append(f'- {key}: {value}')
        lines.append('')
    lines += ['## 论断与竞争解释', '']
    for claim in doc.get('claims', []):
        lines += ['### '+str(claim.get('claim_id'))+' · '+claim.get('text', ''), '']
        for key in ['status', 'evidence_ids', 'rationale', 'boundary', 'alternative_explanations', 'decisive_test']:
            lines.append(f'- {key}: {claim.get(key, "")}')
        lines.append('')
    lines += ['## 来源定位', '']
    for sid, source in sources.items():
        path = Path(source['path'])
        lines += [f"- {sid}: [{path.name}](<{path}>) · SHA-256: {source['sha256']}"]
    lines.append('')
    for item in doc.get('evidence', []):
        lines += ['- '+str(item.get('evidence_id'))+' ['+item.get('kind', '')+'] '+item.get('statement', '')]
        for anchor in item.get('anchors', []):
            source = sources.get(anchor.get('source_id'), {})
            block = next((b for b in source.get('blocks', []) if b['block_id'] == anchor.get('block_id')), {})
            lines += ['  - '+str(anchor.get('source_id'))+' · '+str(block.get('locator') or 'page '+str(anchor.get('page')))]
    lines += ['', '## 复现与最小判别实验', '']
    lines += [f'- {key}: {value}' for key, value in doc.get('reproduction', {}).items()]
    lines += ['', '## 材料缺口与局限', '']+[str(x) for x in doc.get('missing_materials', [])+doc.get('review', {}).get('limitations', [])]
    if check['issues']: lines += ['', '## 尚待解决', '']+['- '+x for x in check['issues']]
    write(out, '\n'.join(lines)+'\n'); save(str(out)+'.checks.json', check)
    return {**check, 'output': str(out)}
