"""Small original converters and structural checks, independent of upstream helpers."""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
from .common import emit, load, save, write
from .providers import search, arxiv_records, openalex_record, doi_lookup
from .bibliography import export_records
from .reader import extract


def math_structure(text):
    # Preserve line positions but ignore fenced code; this is syntax lint, not math verification.
    source = re.sub(r'(?ms)^```[^\n]*\n.*?^```[^\n]*$', lambda m: '\n'*m.group().count('\n'), text)
    source = re.sub(r'(?<!\\)%[^\n]*', '', source)
    tokens = list(re.finditer(r'(?<!\\)(?:\$\$|\$)|\\[()[\]]|\\(?:begin|end)\{([^}]+)\}', source))
    stack = []
    issues = []
    close = {'\\)': '\\(', '\\]': '\\['}
    for match in tokens:
        token = match.group(); line = source.count('\n', 0, match.start())+1
        if token in ['$', '$$']:
            if stack and stack[-1][0] == token: stack.pop()
            else: stack.append((token, line))
        elif token in ['\\(', '\\['] or token.startswith('\\begin{'): stack.append((token, line))
        else:
            expected = close.get(token, token.replace('\\end{', '\\begin{', 1))
            if stack and stack[-1][0] == expected: stack.pop()
            else: issues.append({'line': line, 'issue': 'Unmatched closing delimiter', 'token': token})
    issues += [{'line': line, 'issue': 'Unclosed delimiter', 'token': token} for token, line in stack]
    return {'structurally_balanced': not issues, 'issues': issues,
            'scope': 'Dollar/display delimiters and LaTeX environments only. Not a TeX compiler or mathematical proof.'}


def run(name, argv):
    p = argparse.ArgumentParser(prog=name)
    if name == 'citation':
        group=p.add_mutually_exclusive_group(required=True)
        group.add_argument('--claim'); group.add_argument('--text-file',type=Path); group.add_argument('--doi')
        p.add_argument('--max-claims',type=int,default=5)
        p.add_argument('--scope', choices=['all', 'nature', 'cns', 'flagship'], default='cns')
        p.add_argument('--sources', default='pubmed,europepmc,crossref'); p.add_argument('--limit', type=int, default=20)
        p.add_argument('--output-file', type=Path, required=True); p.add_argument('--with-artifacts', action='store_true')
        a = p.parse_args(argv)
        if not 1<=a.max_claims<=20: raise ValueError('max-claims must be 1..20')
        paragraphs=[a.claim] if a.claim else [x.strip() for x in re.split(r'\n\s*\n',a.text_file.read_text()) if x.strip()] if a.text_file else []
        mappings=[]; batches=[]; candidates=[]
        if a.doi:
            lookup=doi_lookup(a.doi)
            if lookup.get('record'): candidates=[lookup['record']]
            batches=[{'status':'ok' if candidates else 'failed','source':'doi_lookup','details':lookup}]
        else:
            for i,claim in enumerate(paragraphs[:a.max_claims],1):
                found=search(claim,a.sources.split(','),limit=a.limit,scope=a.scope)
                candidates.extend(found['records']);batches.extend(found['searches'])
                mappings.append({'claim_id':'C'+str(i).zfill(4),'text':claim,'candidate_ids':[r['record_id'] for r in found['records']],'claim_support':'not_assessed'})
        from .model import deduplicate
        result={'records':deduplicate(candidates)['records'],'searches':batches,'claims':mappings,
                'claim_support':'not_assessed; candidates require source reading','claims_truncated':len(paragraphs)>a.max_claims}
        fmt=a.output_file.suffix.lstrip('.')
        if fmt=='json': save(a.output_file,result)
        elif fmt!='html':
            content,warnings=export_records(result['records'],fmt);write(a.output_file,content);result['export_warnings']=warnings
        if a.with_artifacts or fmt=='html':
            import html
            pieces=['<!doctype html><meta charset="utf-8"><title>Reference candidates</title><h1>Reference candidates</h1><p>Candidate retrieval only; semantic support has not been assessed.</p>']
            for row in mappings: pieces.append('<h2>'+html.escape(row['claim_id'])+'</h2><p>'+html.escape(row['text'])+'</p>')
            pieces.append('<ol>')
            for row in result['records']:
                pieces.append('<li>'+html.escape(row['record_id']+' | '+row['title']+' | '+str(row.get('year') or '')+' | '+str(row.get('identifiers',{})))+'</li>')
            pieces.append('</ol>');write(a.output_file if fmt=='html' else a.output_file.with_suffix('.html'),'\n'.join(pieces))
        # Always retain search provenance and candidate-only status.
        save(str(a.output_file)+'.search.json', result)
        emit({'output': str(a.output_file), 'candidates': len(result['records']), 'claim_support': result['claim_support']})
        return 0 if any(x['status'] in ['ok', 'partial'] for x in result['searches']) else 2
    p.add_argument('input', type=Path)
    p.add_argument('--out', type=Path)
    if name == 'reader-math': p.add_argument('--json', action='store_true')
    if name == 'jats': p.add_argument('--text-only', action='store_true')
    a = p.parse_args(argv)
    if name == 'reader-math': result = math_structure(a.input.read_text(encoding='utf-8'))
    elif name == 'arxiv-parse': result = {'records': arxiv_records(a.input.read_bytes())}
    elif name == 'openalex-abstract':
        record = openalex_record(load(a.input)); result = {'text': record['abstract'], 'level': 'abstract_only'}
    elif name == 'jats':
        blocks, _ = extract(a.input, a.input.parent)
        result = {'blocks': blocks, 'text': '\n\n'.join(b['original'] for b in blocks), 'level': 'extracted_body_requires_reading'}
        if a.text_only:
            if a.out: write(a.out, result['text'])
            else: print(result['text'])
            return 0
    else: raise ValueError('Unknown format tool')
    if a.out: save(a.out, result)
    emit(result)
    return 2 if name == 'reader-math' and not result['structurally_balanced'] else 0
