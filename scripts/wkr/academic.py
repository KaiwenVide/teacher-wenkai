"""Traceable study planning and evidence-linked manuscript assembly."""
from __future__ import annotations
from pathlib import Path
from .common import load, save, write, digest, now
from .claims import validate_claims


def validated_analysis(directory):
    root = Path(directory).resolve()
    result = load(root/'analysis.json')
    config = load(root/'config.json')
    manifest = load(root/'artifact-manifest.json')
    if manifest.get('files', {}).get('analysis.json') != digest((root/'analysis.json').read_bytes()):
        raise ValueError('Analysis integrity check failed')
    if result.get('config_sha256') != digest(config): raise ValueError('Analysis configuration changed')
    for source in result.get('source_files', []):
        path = Path(source['path'])
        if not path.is_file() or digest(path.read_bytes()) != source['sha256']:
            raise ValueError('Analysis input changed or is unavailable')
    return result, config


def study_plan(question, out, analysis_dir=None):
    if not question.strip(): raise ValueError('A research question is required')
    out = Path(out)
    if out.exists() and any(out.iterdir()): raise ValueError('Choose a new planning directory')
    prior = None
    candidates = []
    if analysis_dir:
        from .data_research import signals
        analysis, config = validated_analysis(analysis_dir)
        prior = {'analysis_id': analysis['analysis_id'], 'path': str(Path(analysis_dir).resolve()),
                 'sha256': digest((Path(analysis_dir)/'analysis.json').read_bytes()), 'status': analysis['status']}
        candidates = signals(analysis, config)
    plan = {'schema_version': '1.0', 'created_at': now(), 'question': question, 'status': 'draft',
            'analysis_origin': prior, 'exploratory_candidates': candidates,
            'search_protocol': {'concepts': [], 'sources': [], 'inclusion': [], 'exclusion': [], 'date_range': None},
            'evidence_matrix': [], 'competing_explanations': [],
            'stages': [{'stage': k, 'status': 'pending', 'artifacts': [], 'open_questions': []}
                       for k in ['scope', 'corpus', 'appraisal', 'design', 'analysis', 'writing', 'review']],
            'next_action': 'Read primary evidence and define a falsifiable claim before filling the experimental design.'}
    experiment = {'schema_version': '1.0', 'question': question, 'hypothesis': '', 'model': '',
                  'biological_unit': '', 'primary_outcome': '', 'measurement_time': '',
                  'intervention': '', 'comparators': [], 'randomization': '', 'blinding': '',
                  'exclusion_rule': '', 'sample_size': {'n_per_group': None, 'rationale': '', 'assumptions': []},
                  'analysis_plan': '', 'missing_data_rule': '', 'multiplicity_rule': '',
                  'success_criterion': '', 'falsifying_result': '', 'alternative_explanations': [],
                  'minimal_pilot': '', 'stop_rule': '', 'design_review': {'assessor': '', 'status': 'pending'},
                  'boundary': 'A filled template is a proposed design; no experiment or causal validation has occurred.'}
    manuscript = {'schema_version': '1.0', 'title': question, 'genre': 'research_article', 'target_venue': None,
                  'sections': [{'name': k, 'text': '', 'claim_ids': []} for k in ['Abstract', 'Introduction', 'Methods', 'Results', 'Discussion']],
                  'limitations': [], 'analysis_origin': prior,
                  'boundary': 'Write only from verified sources and actual results. Do not promote exploratory candidates to mechanisms.'}
    save(out/'research-plan.json', plan)
    save(out/'experiment-plan.json', experiment)
    save(out/'manuscript-plan.json', manuscript)
    save(out/'claims.json', {'schema_version': '1.0', 'claims': []})
    write(out/'planning-notes.md', '# 研究规划\n\n问题：'+question+'\n\n状态：草稿。\n\n'
          '先完成论断—证据矩阵，再填实验设计和论文提纲。数据候选只代表探索性趋势或关联。\n'
          '记录直接证据、模型外推、竞争解释和反证；优先设计能区分这些解释的最小实验。\n'
          '协议冻结后发生的更改需保留日期与理由。样本量必须写明假设与依据，不用固定经验数冒充功效分析。\n')
    return {'status': 'draft', 'output': str(out), 'analysis_linked': prior is not None, 'candidate_count': len(candidates),
            'files': ['research-plan.json', 'experiment-plan.json', 'manuscript-plan.json', 'claims.json', 'planning-notes.md']}


def experiment_check(plan):
    issues = []
    required = ['question', 'hypothesis', 'model', 'biological_unit', 'primary_outcome', 'measurement_time',
                'intervention', 'randomization', 'blinding', 'exclusion_rule', 'analysis_plan',
                'missing_data_rule', 'multiplicity_rule', 'success_criterion', 'falsifying_result', 'minimal_pilot', 'stop_rule']
    for field in required:
        if not isinstance(plan.get(field), str) or not plan[field].strip() or plan[field].strip().lower() in ['todo', 'tbd', '待补充']:
            issues.append({'field': field, 'issue': 'A concrete decision or explicit justified non-applicability is needed'})
    for field in ['comparators', 'alternative_explanations']:
        if not isinstance(plan.get(field), list) or not plan[field] or not all(isinstance(x, str) and x.strip() for x in plan[field]):
            issues.append({'field': field, 'issue': 'At least one explicit entry is needed'})
    sample = plan.get('sample_size', {})
    n = sample.get('n_per_group')
    if not isinstance(n, int) or isinstance(n, bool) or n < 2 or not sample.get('rationale') or not sample.get('assumptions'):
        issues.append({'field': 'sample_size', 'issue': 'Record independent n, rationale and assumptions; this check does not compute power'})
    review = plan.get('design_review', {})
    if review.get('status') != 'reviewed' or not review.get('assessor'):
        issues.append({'field': 'design_review', 'issue': 'Design review not recorded'})
    return {'complete_for_review': not issues, 'issues': issues,
            'boundary': 'Completeness and declared review only; suitability, feasibility, power and ethics are not certified.'}


def manuscript_build(plan, claims, out, base=None):
    validation = validate_claims(claims, base, 'doc-only')
    problems = list(validation['issues'])
    indexed = {c['claim_id']: c for c in claims.get('claims', []) if c.get('claim_id')}
    sections = plan.get('sections', [])
    if not indexed: problems.append('No source-linked claims have been provided')
    if not sections: problems.append('No manuscript sections have been provided')
    if not plan.get('limitations'): problems.append('Limitations have not been recorded')
    lines = ['# '+str(plan.get('title') or 'Untitled manuscript'), '', '**Evidence-linked draft; requires editorial and source review.**', '']
    used = set()
    mapping = []
    for section in sections:
        lines += ['## '+str(section.get('name') or 'Unnamed section'), '', section.get('text') or '[DRAFT: section text missing]', '']
        if not str(section.get('text', '')).strip(): problems.append('Section text missing: '+str(section.get('name')))
        refs = section.get('claim_ids', [])
        if not refs: problems.append('Section has no declared claim mapping: '+str(section.get('name')))
        for cid in refs:
            used.add(cid)
            claim = indexed.get(cid)
            if claim is None:
                problems.append('Unknown claim reference: '+cid)
                lines += ['[VERIFY: unknown claim '+cid+']', '']
                continue
            status = claim.get('status', 'pending')
            if status != 'supported': problems.append('Claim '+cid+' remains '+status)
            lines += [f"- {cid} [{status}]: {claim.get('text', '')}"]
            sources = []
            for source in claim.get('sources', []):
                sources.append({k: source.get(k) for k in ['source_id', 'path', 'url', 'locator', 'source_sha256'] if source.get(k)})
            mapping.append({'section': section.get('name'), 'claim_id': cid, 'status': status, 'sources': sources})
        lines.append('')
    lines += ['## Limitations', '']+[str(x) for x in plan.get('limitations', [])]
    result = {'status': 'draft_requires_review', 'structural_evidence_checks_passed': not problems,
              'issues': problems, 'claim_mapping': mapping, 'unused_claims': sorted(set(indexed)-used),
              'scope': 'Checks declared source links and coverage, not whether section prose is entailed by those claims.'}
    out = Path(out)
    if out.exists() or Path(str(out)+'.evidence.json').exists(): raise ValueError('Manuscript outputs already exist; use a new revision path')
    write(out, '\n'.join(lines)+'\n')
    save(str(out)+'.evidence.json', result)
    return {**result, 'output': str(out)}
