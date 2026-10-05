"""Native scientific API protocols; no plugin runtime or copied client code."""
from __future__ import annotations
import re
from urllib.parse import quote
from .http import NetworkError


def _variant_parts(text):
    match = re.fullmatch(r'(?:chr)?([0-9]{1,2}|X|Y|MT)[\s:_/\-]+([1-9][0-9]*)[\s:_/\-]+([ACGT]+)[\s:_/\-]+([ACGT]+)', str(text).strip(), re.I)
    if not match: raise ValueError('Use an explicit chromosome, 1-based position, reference and alternate allele')
    chrom, pos, ref, alt = match.groups()
    if chrom.isdigit() and not 1 <= int(chrom) <= 22: raise ValueError('Human chromosome must be 1..22, X, Y or MT')
    if ref.upper() == alt.upper(): raise ValueError('Reference and alternate alleles must differ')
    return chrom.upper(), int(pos), ref.upper(), alt.upper()


def resolve_variant(payload, assembly, client):
    keys = [k for k in ['rsid', 'grch37', 'grch38', 'variant'] if payload.get(k)]
    if len(keys) != 1: raise ValueError('Supply exactly one of rsid, grch37, grch38 or variant')
    kind = keys[0]; value = payload[kind]
    host = 'https://grch37.rest.ensembl.org' if assembly == 'GRCh37' else 'https://rest.ensembl.org'
    candidates = set()
    if kind == 'rsid':
        if not re.fullmatch(r'rs[0-9]+', str(value)): raise ValueError('Invalid rsID')
        data = client.json(host+'/variation/human/'+value, headers={'Accept': 'application/json'})
        for item in data.get('mappings', []):
            if item.get('assembly_name') != assembly or item.get('strand') != 1: continue
            chrom = str(item.get('seq_region_name', ''))
            alleles = str(item.get('allele_string', '')).split('/')
            if not alleles or any(not re.fullmatch(r'[ACGT]+', a) for a in alleles): continue
            for alt in alleles[1:]:
                try: candidates.add(_variant_parts(f"{chrom}:{item['start']}:{alleles[0]}:{alt}"))
                except ValueError: continue
        if len(candidates) != 1: raise ValueError('rsID mapping is absent or multiallelic; provide an explicit assembly and allele-specific variant')
        parts = candidates.pop()
    else:
        parts = _variant_parts(value)
        input_assembly = {'grch37': 'GRCh37', 'grch38': 'GRCh38'}.get(kind, assembly)
        if input_assembly != assembly:
            chrom, pos, ref, alt = parts
            # A coordinate-only lift cannot reliably normalize indels or strand reversals.
            if len(ref) != 1 or len(alt) != 1: raise ValueError('Cross-assembly indels require a validated allele-aware mapping; provide the target-assembly variant')
            url = 'https://rest.ensembl.org/map/human/'+input_assembly+'/'+f'{chrom}:{pos}..{pos}:1'+'/'+assembly
            data = client.json(url, headers={'Accept': 'application/json'})
            mapped = [x['mapped'] for x in data.get('mappings', []) if x.get('mapped', {}).get('start') == x.get('mapped', {}).get('end') and x.get('mapped', {}).get('strand') == 1]
            if len(mapped) != 1: raise ValueError('Coordinate lift is absent, ambiguous or strand-reversed')
            item = mapped[0]
            sequence = client.json(host+'/sequence/region/human/'+f"{item['seq_region_name']}:{item['start']}..{item['end']}:1", headers={'Accept': 'application/json'})
            if str(sequence.get('seq', '')).upper() != ref: raise ValueError('Mapped reference allele does not match the target assembly')
            parts = str(item['seq_region_name']), int(item['start']), ref, alt
    chrom, pos, ref, alt = parts
    return {'assembly': assembly, 'chr': chrom, 'pos': pos, 'ref': ref, 'alt': alt,
            'canonical': f'{chrom}:{pos}-{ref}-{alt}', 'variant_id': f'chr{chrom}_{pos}_{ref}_{alt}_b'+assembly[-2:]}


def prepare_request(provider, payload, spec, client):
    """Translate small public identifiers to a read request; preserve raw source fields."""
    p = dict(payload)
    protocol = spec.get('protocol', 'rest')
    base = p.get('base_url', spec['bases'][0]).rstrip('/')
    path = str(p.get('path', ''))
    params = dict(p.get('params') or {})
    body = p.get('json_body'); form = p.get('form_body'); headers = dict(p.get('headers') or {})
    response_format = p.get('response_format', 'json')
    selector = p.get('record_path')
    details = {}
    if protocol == 'graphql':
        query = p.get('query')
        if not isinstance(query, str) or not query.strip(): raise ValueError('A GraphQL query or query_path is required')
        stripped = re.sub(r'#[^\n]*', '', query).lstrip()
        if not (stripped.startswith('{') or re.match(r'query\b', stripped)): raise ValueError('Only GraphQL query operations are accepted')
        syntax=re.sub(r'"(?:\\.|[^"\\])*"', '""', stripped)
        if re.search(r'\b(mutation|subscription)\b', syntax): raise ValueError('Only GraphQL retrieval is accepted')
        base = spec['bases'][0]; path = spec['endpoint']; body = {'query': query, 'variables': p.get('variables', {})}; selector = selector or 'data'
    elif protocol == 'sparql':
        query = p.get('query') or params.get('query')
        if not query or not re.search(r'\b(SELECT|ASK|CONSTRUCT|DESCRIBE)\b', query, re.I): raise ValueError('A read-only SPARQL query is required')
        syntax=re.sub(r'<[^>]*>|"(?:\\.|[^"\\])*"|#[^\n]*', '', query)
        if re.search(r'\b(INSERT|DELETE|LOAD|DROP|CLEAR|CREATE|ADD|MOVE|COPY|SERVICE)\b', syntax, re.I): raise ValueError('SPARQL updates and federated service calls are not exposed')
        base = spec['bases'][0]; path = spec.get('endpoint', 'sparql'); params.update(query=query, format='json')
        headers['Accept'] = 'application/sparql-results+json'; selector = selector or ''
    elif protocol in ['phewas', 'gtex']:
        variant = resolve_variant(p, spec['assembly'], client); details['query_variant'] = variant
        if protocol == 'phewas':
            path = 'api/variant/'+quote(variant['canonical'], safe=':-'); selector = selector or ('results' if provider=='finngen-phewas' else 'phenos')
            details['variant_url'] = base+'/variant/'+quote(variant['canonical'], safe=':-')
        else:
            path = 'association/singleTissueEqtl'; params.update(variantId=variant['variant_id'], pageSize=min(1000, int(p.get('max_results', 20))))
            selector = selector or 'data'
    elif protocol == 'genebass':
        gene = p.get('ensembl_gene_id', '')
        burden = p.get('burden_set', 'pLoF')
        if not re.fullmatch(r'ENSG\d{11}', gene): raise ValueError('An unversioned human Ensembl gene ID is required')
        if burden not in ['pLoF', 'missense|LC', 'synonymous']: raise ValueError('Unknown Genebass burden set')
        path = 'phewas/'+gene; params['burdenSet'] = burden; details.update(gene=gene, burden_set=burden); selector=selector or 'phewas'
    elif protocol == 'clinicaltrials':
        action = p.get('action', 'request')
        routes = {'studies': 'studies', 'metadata': 'studies/metadata', 'search_areas': 'studies/search-areas', 'enums': 'studies/enums', 'stats_size': 'stats/size', 'field_values': 'stats/field/values', 'field_sizes': 'stats/field/sizes'}
        if action != 'request':
            if action not in routes: raise ValueError('Unknown ClinicalTrials action')
            path = routes[action]
        if path.strip('/') == 'studies': selector = selector or 'studies'
    elif protocol == 'clinvar':
        action = p.get('action')
        if action == 'search':
            base = spec['bases'][1]; path = 'search'; params['terms'] = p.get('terms', '')
            if not params['terms']: raise ValueError('Clinical Tables search requires terms')
            details['clinical_tables'] = True
        else:
            mapping = {'vcv': 'clinvar/variation/', 'rcv': 'clinvar/rcv/', 'scv': 'clinvar/scv/', 'refsnp': 'refsnp/'}
            if action not in mapping: raise ValueError('Unknown ClinVar action')
            identifier = str(p.get(action, ''))
            if not re.fullmatch(r'(?:VCV|RCV|SCV|rs)?\d+(?:\.\d+)?', identifier, re.I): raise ValueError('Invalid variant accession')
            identifier = re.sub(r'^(VCV|RCV|SCV|rs)', '', identifier, flags=re.I).split('.')[0].lstrip('0') or '0'
            path = mapping[action]+identifier
            if action=='refsnp': base=spec['bases'][2]
    elif protocol == 'clinicaltables':
        if not p.get('terms'): raise ValueError('Clinical Tables requires terms')
        path = 'search'; params['terms'] = p['terms']; details['clinical_tables'] = True
    elif protocol == 'entrez':
        endpoint = str(p.get('endpoint', '')).removesuffix('.fcgi')
        if endpoint not in ['esearch', 'esummary', 'efetch', 'elink', 'einfo', 'espell', 'egquery']:
            raise ValueError('Unsupported read-only Entrez endpoint')
        path = endpoint+'.fcgi'; params.setdefault('retmode', 'json' if endpoint != 'efetch' else 'xml')
        response_format = p.get('response_format', params['retmode'])
    return {'base': base, 'path': path, 'params': params, 'body': body, 'form': form, 'headers': headers,
            'response_format': response_format, 'selector': selector, 'details': details, 'protocol': protocol}
