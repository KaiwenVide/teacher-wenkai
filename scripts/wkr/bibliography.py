from __future__ import annotations
import csv
import io
import re
from .model import normalize_record, normalize_doi, normalize_title, author_display
from .providers import doi_lookup
from .common import now


def export_records(items, fmt):
    rows=[normalize_record(r) for r in items]; warnings=[]
    for r in rows:
        ids=r['identifiers']
        if not r.get('url'):
            r['url']='https://arxiv.org/abs/'+str(ids['arxiv']) if ids.get('arxiv') else 'https://doi.org/'+ids['doi'] if ids.get('doi') else 'https://pubmed.ncbi.nlm.nih.gov/'+str(ids['pmid'])+'/' if ids.get('pmid') else ''
    def names(r):
        for a in r['authors']:
            if a.get('unparsed'): warnings.append({'record_id':r['record_id'],'field':'authors','issue':'display name retained; family/given not inferred'})
            yield a.get('literal') or (a['family']+', '+a.get('given','')).rstrip(', ') if a.get('family') else author_display(a)
    if fmt=='csv':
        out=io.StringIO(); w=csv.DictWriter(out,fieldnames=['record_id','title','authors','year','journal','doi','volume','issue','pages','article_number','url']); w.writeheader()
        for r in rows: w.writerow({k:(('; '.join(names(r))) if k=='authors' else r['identifiers'].get('doi','') if k=='doi' else r.get(k,'')) for k in w.fieldnames})
        return out.getvalue(),warnings
    if fmt=='bib':
        def esc(x): return str(x).replace('\\',r'\textbackslash{}').replace('{',r'\{').replace('}',r'\}').replace('%',r'\%').replace('&',r'\&').replace('_',r'\_')
        blocks=[]
        for i,r in enumerate(rows,1):
            vals={k:r.get(k) for k in ['title','year','journal','volume','pages','url']}; vals['number']=r.get('issue'); vals['doi']=r['identifiers'].get('doi')
            authors=[]
            for a,n in zip(r['authors'],names(r)): authors.append('{'+esc(n)+'}' if a.get('literal') or a.get('unparsed') else esc(n))
            if authors: vals['author']=' and '.join(authors)
            if r.get('article_number'): vals['eid']=r['article_number']
            if r['identifiers'].get('arxiv'): vals.update(eprint=r['identifiers']['arxiv'],archivePrefix='arXiv')
            if r['identifiers'].get('pmid'): vals['pmid']=r['identifiers']['pmid']
            fields=[f'  {k} = {{{v if k=="author" else esc(v)}}}' for k,v in vals.items() if v is not None and v!='']
            kind='article' if r.get('journal') else 'misc'
            blocks.append('@'+kind+'{wkr'+str(i)+',\n'+',\n'.join(fields)+'\n}')
        return '\n\n'.join(blocks)+'\n',warnings
    if fmt=='rdf':
        import xml.etree.ElementTree as ET
        rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'; dc='http://purl.org/dc/elements/1.1/'
        ET.register_namespace('rdf',rdf); ET.register_namespace('dc',dc)
        root=ET.Element('{'+rdf+'}RDF')
        for r in rows:
            item=ET.SubElement(root,'{'+rdf+'}Description',{'{'+rdf+'}about':r.get('url') or 'urn:record:'+r['record_id']})
            for field,key in [('title','title'),('date','year'),('source','journal')]:
                if r.get(key): ET.SubElement(item,'{'+dc+'}'+field).text=str(r[key])
            for author in names(r): ET.SubElement(item,'{'+dc+'}creator').text=author
            for key,value in r['identifiers'].items():
                if value: ET.SubElement(item,'{'+dc+'}identifier').text=key+':'+str(value)
        return ET.tostring(root,encoding='unicode')+'\n',warnings
    tags={'ris':{'title':'TI','year':'PY','journal':'JO','volume':'VL','issue':'IS','pages':'SP','article_number':'C7','url':'UR'},'enw':{'title':'%T','year':'%D','journal':'%J','volume':'%V','issue':'%N','pages':'%P','article_number':'%7','url':'%U'}}
    if fmt not in tags: raise ValueError('Supported formats: json, csv, ris, enw, bib, rdf')
    blocks=[]
    for r in rows:
        lines=['TY  - JOUR' if r.get('journal') else 'TY  - GEN'] if fmt=='ris' else ['%0 Journal Article' if r.get('journal') else '%0 Generic']
        add=lambda tag,value: lines.append(tag+('  - ' if fmt=='ris' else ' ')+re.sub(r'\s+',' ',str(value)))
        for n in names(r): add('AU' if fmt=='ris' else '%A',n)
        for field,tag in tags[fmt].items():
            if r.get(field) is not None and r.get(field)!='': add(tag,r[field])
        if r['identifiers'].get('doi'): add('DO' if fmt=='ris' else '%R',r['identifiers']['doi'])
        if fmt=='ris': add('ID',r['record_id'])
        for key in ['arxiv','pmid','pmcid']:
            if r['identifiers'].get(key): add('N1' if fmt=='ris' else '%Z',key+':'+str(r['identifiers'][key]))
        if fmt=='ris': lines.append('ER  - ')
        blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks)+'\n',warnings


def compare_metadata(supplied, canonical):
    a=normalize_record(supplied); b=normalize_record(canonical); checks=[]
    for key in ['title','year','journal','volume','issue','pages','article_number']:
        av,bv=a.get(key),b.get(key)
        if av is None or av=='': status='not_supplied'
        elif bv is None or bv=='': status='source_missing'
        elif normalize_title(av)==normalize_title(bv): status='match'
        elif key=='year' and any(str(av)==str(v.get('date-parts',[['']])[0][0]) for v in b.get('dates',{}).values() if v.get('date-parts')): status='matches_alternate_publication_date'
        else: status='needs_review'
        checks.append({'field':key,'supplied':av,'canonical':bv,'status':status})
    aa=[author_display(x) for x in a['authors']]; ba=[author_display(x) for x in b['authors']]
    truncated=any(re.search(r'et\s*al|等',x,re.I) for x in aa)
    checks.append({'field':'authors','supplied':aa,'canonical':ba,'status':'not_supplied' if not aa else 'source_missing' if not ba else 'truncated_presentation_needs_style_check' if truncated else 'match' if [normalize_title(x) for x in aa]==[normalize_title(x) for x in ba] else 'needs_review'})
    return {'checks':checks,'discrepancies':[x for x in checks if x['status']=='needs_review'],'claim_support':'not_assessed','note':'Metadata differences are review items, not proof of fabrication. DOI suffix years and page-gap thresholds are not used.'}


def verify_records(items,lookup=doi_lookup):
    results=[]
    for r in items:
        doi=normalize_doi((r.get('identifiers') or {}).get('doi') or r.get('doi'))
        if not doi: results.append({'input':r,'status':'identifier_missing_or_malformed','claim_support':'not_assessed'}); continue
        found=lookup(doi)
        results.append({'input':r,'lookup':found,**(compare_metadata(r,found['record']) if found.get('record') else {'claim_support':'not_assessed'})})
    return {'checked_at':now(),'results':results,'coverage':'registration lookup with fallback; discrepancies require publisher/second-source review'}


def import_references(path):
    from pathlib import Path
    from .common import load,records,digest
    p=Path(path); text=p.read_text(encoding='utf-8-sig'); suffix=p.suffix.lower(); result=[]; warnings=[]
    if suffix=='.json': return {'records':[normalize_record(r) for r in records(load(p))],'warnings':[]}
    if suffix=='.bib':
        try: import bibtexparser
        except ImportError: raise ValueError('BibTeX import requires bibtexparser v1.x; RIS/NBIB/JSON import has no third-party dependency') from None
        if not hasattr(bibtexparser,'loads'): raise ValueError('Installed bibtexparser lacks the v1 loads API; use RIS or a compatible isolated runtime')
        for x in bibtexparser.loads(text).entries:
            result.append(normalize_record({'title':x.get('title',''),'authors':[z.strip().strip('{}') for z in re.split(r'\s+and\s+',x.get('author','')) if z.strip()],'identifiers':{'doi':x.get('doi',''),'arxiv':x.get('eprint','') if x.get('archiveprefix',x.get('archivePrefix','')).casefold()=='arxiv' else '', 'pmid':x.get('pmid','')},'year':int(x['year']) if str(x.get('year','')).isdigit() else None,'journal':x.get('journal',''),'volume':x.get('volume',''),'issue':x.get('number',''),'pages':x.get('pages',''),'url':x.get('url',''),'bibtex_key':x.get('ID')}))
        warnings.append('Brace-protected corporate/ambiguous author names need export review; original BibTeX is retained as provenance')
    elif suffix in ['.ris','.nbib','.enw']:
        current={}; last=None; entries=[]
        for line in text.splitlines()+['']:
            match=re.match(r'^([A-Z0-9]{2,4})\s*-\s?(.*)$',line) if suffix!='.enw' else re.match(r'^(%\S)\s+(.*)$',line)
            if match:
                tag,value=match.groups()
                if (tag in ['TY','PMID','%0'] and current) or tag=='ER':
                    entries.append(current); current={}
                    if tag=='ER': last=None; continue
                current.setdefault(tag,[]).append(value); last=tag
            elif line.strip() and last: current[last][-1]+=' '+line.strip()
            elif not line.strip() and current and suffix in ['.enw','.nbib']:
                entries.append(current); current={}; last=None
        if current: entries.append(current)
        maps={'ris':{'title':['TI','T1'],'authors':['AU','A1'],'journal':['JO','JF','T2'],'year':['PY','Y1'],'doi':['DO'],'volume':['VL'],'issue':['IS'],'pages':['SP'],'url':['UR']},'nbib':{'title':['TI'],'authors':['FAU','AU'],'journal':['JT','TA'],'year':['DP'],'volume':['VI'],'issue':['IP'],'pages':['PG'],'url':['URL']},'enw':{'title':['%T'],'authors':['%A'],'journal':['%J'],'year':['%D'],'doi':['%R'],'volume':['%V'],'issue':['%N'],'pages':['%P'],'url':['%U']}}
        mapping=maps[suffix[1:]]
        for e in entries:
            r={}; ids={}
            for field,tags in mapping.items():
                vals=next((e[t] for t in tags if e.get(t)),[])
                if field=='authors': r[field]=vals
                elif field=='doi': ids['doi']=vals[0] if vals else ''
                elif field=='year':
                    match=re.search(r'\b(?:18|19|20|21)\d{2}\b',' '.join(vals)); r[field]=int(match.group()) if match else None
                else: r[field]=vals[0] if vals else ''
            if suffix=='.nbib':
                ids['pmid']=(e.get('PMID') or [''])[0]
                for val in e.get('AID',[])+e.get('LID',[]):
                    if '[doi]' in val: ids['doi']=val.replace('[doi]','').strip()
            if suffix=='.ris' and e.get('EP') and r.get('pages'): r['pages']+='-'+e['EP'][0]
            for note in e.get('N1',[])+e.get('%Z',[]):
                match=re.fullmatch(r'(arxiv|pmid|pmcid):(.+)',note,re.I)
                if match: ids[match.group(1).lower()]=match.group(2).strip()
            match=re.search(r'arxiv.org/(?:abs|pdf)/([^?#]+)',r.get('url',''))
            if match: ids.setdefault('arxiv',match.group(1).removesuffix('.pdf'))
            r['identifiers']=ids; result.append(normalize_record(r))
    else: raise ValueError('Import accepts .ris, .nbib, .enw, .bib or normalized .json')
    for r in result: r['provenance'].append({'source':'local_reference_file','path':str(p.resolve()),'sha256':digest(p.read_bytes()),'level':'metadata'})
    if not result and text.strip(): raise ValueError('No recognizable reference entries; source was not imported')
    return {'records':result,'warnings':warnings,'imported_count':len(result),'verification':'not_performed'}
