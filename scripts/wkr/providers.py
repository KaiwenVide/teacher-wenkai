from __future__ import annotations
import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote
from .common import now, save, digest, SKILL_ROOT
from .http import Client, NetworkError
from .model import normalize_doi, normalize_record, deduplicate, scope_match

PROVIDERS = {
 'pubmed':('https://eutils.ncbi.nlm.nih.gov/entrez/eutils','pubmed.md'),
 'pmc':('https://eutils.ncbi.nlm.nih.gov/entrez/eutils','pmc.md'),
 'europepmc':('https://www.ebi.ac.uk/europepmc/webservices/rest','europepmc.md'),
 'biorxiv':('https://api.biorxiv.org','biorxiv.md'),
 'medrxiv':('https://api.biorxiv.org','medrxiv.md'),
 'arxiv':('https://export.arxiv.org/api','arxiv.md'),
 'openalex':('https://api.openalex.org','openalex.md'),
 'crossref':('https://api.crossref.org','crossref.md'),
 'semantic-scholar':('https://api.semanticscholar.org/graph/v1','semantic-scholar.md'),
 'core':('https://api.core.ac.uk/v3','core.md'),
 'unpaywall':('https://api.unpaywall.org/v2','unpaywall.md'),
 'opencitations':('https://api.opencitations.net/index/v2','opencitations.md'),
 'pubtator':('https://www.ncbi.nlm.nih.gov/research/pubtator3-api','pubtator.md'),
 'zenodo':('https://zenodo.org/api','zenodo.md'),
 'figshare':('https://api.figshare.com/v2','figshare.md'),
 'ror':('https://api.ror.org/v2','ror.md'),
 'biostudies':('https://www.ebi.ac.uk/biostudies/api/v1','biostudies.md'),
 'doaj':('https://doaj.org/api','doaj.md'),
}
SEARCH_SOURCES = ['pubmed','europepmc','crossref','openalex','arxiv','semantic-scholar','core']


def provider_request(client, source, path, params=None, body=None, binary=False):
    if source not in PROVIDERS: raise ValueError('Unknown provider')
    if path.startswith(('http:', 'https:', '//')) or '..' in path.split('/') or '?' in path or '#' in path:
        raise ValueError('Use a relative API path and a separate params object')
    params=dict(params or {}); headers={}
    if source in ['pubmed','pmc']:
        if os.environ.get('NCBI_API_KEY'): params['api_key']=os.environ['NCBI_API_KEY']
        if os.environ.get('NCBI_EMAIL'): params['email']=os.environ['NCBI_EMAIL']
        params.setdefault('tool','teacher-wenkai')
    if source=='openalex' and os.environ.get('OPENALEX_API_KEY'): params['api_key']=os.environ['OPENALEX_API_KEY']
    if source=='crossref' and os.environ.get('CROSSREF_MAILTO'): params['mailto']=os.environ['CROSSREF_MAILTO']
    if source=='unpaywall':
        email=os.environ.get('UNPAYWALL_EMAIL') or params.get('email')
        if not email or email.endswith('@example.com'): raise ValueError('Unpaywall needs a real email via UNPAYWALL_EMAIL')
        params['email']=email
    if source=='semantic-scholar' and (os.environ.get('S2_API_KEY') or os.environ.get('SEMANTIC_SCHOLAR_API_KEY')):
        headers['x-api-key']=os.environ.get('S2_API_KEY') or os.environ['SEMANTIC_SCHOLAR_API_KEY']
    if source=='core' and os.environ.get('CORE_API_KEY'): headers['Authorization']='Bearer '+os.environ['CORE_API_KEY']
    # Only these POST endpoints perform documented read-only searches/lookups.
    allowed_post=(source=='figshare' and path.strip('/')=='articles/search') or (source=='core' and path.strip('/') in ['search/works','search/outputs']) or (source=='semantic-scholar' and path.strip('/')=='paper/batch')
    if body is not None and not allowed_post: raise ValueError('POST allowed only for documented read-only search endpoints')
    url=PROVIDERS[source][0]+'/'+path.lstrip('/')
    if binary:
        # Europe PMC fullTextXML negotiates XML and rejects application/json with 406.
        headers['Accept']='application/xml' if source=='europepmc' and path.rstrip('/').endswith('/fullTextXML') else '*/*'
        return client.fetch(url,params=params,headers=headers,body=body)
    data=client.json(url,params=params,headers=headers,body=body)
    if isinstance(data,dict) and (data.get('errCode') or data.get('error')):
        raise NetworkError('Provider returned an error inside a successful HTTP response')
    return data


def crossref_record(x):
    parts=next((x.get(k,{}).get('date-parts',[[]])[0] for k in ['published-print','published','issued','published-online'] if x.get(k,{}).get('date-parts')),[])
    r={'title':(x.get('title') or [''])[0],'identifiers':{'doi':x.get('DOI','')},'year':parts[0] if parts else None,'journal':(x.get('container-title') or [''])[0],'authors':x.get('author',[]),'abstract':re.sub('<[^>]+>',' ',x.get('abstract','')),'volume':x.get('volume',''),'issue':x.get('issue',''),'pages':x.get('page',''),'article_number':x.get('article-number',''),'url':x.get('URL',''),'record_type':x.get('type','article'),'updates':x.get('update-to',[]),'dates':{k:x[k] for k in ['published-print','published-online','published','issued'] if k in x},'retraction_check':'metadata_updates_only'}
    return normalize_record(r)


def datacite_record(x):
    a=x.get('data',x).get('attributes',{})
    return normalize_record({'title':next((z.get('title','') for z in a.get('titles',[])),''),'identifiers':{'doi':a.get('doi','')},'year':a.get('publicationYear'),'authors':[{'given':z.get('givenName',''),'family':z.get('familyName','')} if z.get('familyName') else {'name':z.get('name','')} for z in a.get('creators',[])],'journal':a.get('container',{}).get('title','') if isinstance(a.get('container'),dict) else '', 'record_type':a.get('types',{}).get('resourceTypeGeneral','other'),'url':a.get('url',''),'publisher':a.get('publisher','')})


def epmc_record(x):
    info=x.get('journalInfo') or {}; pub=info.get('journal') or {}
    authors=[{'given':a.get('firstName',''),'family':a.get('lastName','')} if a.get('lastName') else {'name':a.get('collectiveName') or a.get('fullName','')} for a in x.get('authorList',{}).get('author',[])]
    if not authors and x.get('authorString'): authors=[{'display':x['authorString'],'unparsed':True}]
    r={'title':x.get('title',''),'identifiers':{'doi':x.get('doi','')},'year':int(x['pubYear']) if str(x.get('pubYear','')).isdigit() else None,'journal':pub.get('title') or x.get('journalTitle',''),'authors':authors,'abstract':x.get('abstractText',''),'volume':info.get('volume') or x.get('journalVolume',''),'issue':info.get('issue') or x.get('issue',''),'pages':x.get('pageInfo',''),'record_type':'preprint' if x.get('source')=='PPR' else 'article','oa_locations':[]}
    if x.get('source')=='MED': r['identifiers']['pmid']=x.get('id')
    if x.get('pmcid'): r['identifiers']['pmcid']=x['pmcid']
    r['identifiers']['europepmc']=x.get('source','')+'/'+x.get('id','')
    for u in x.get('fullTextUrlList',{}).get('fullTextUrl',[]):
        if u.get('availabilityCode')=='OA' or u.get('availability')=='Open access':
            r['oa_locations'].append({'url':u.get('url'),'format':u.get('documentStyle'),'source':'europepmc','access':'open_access'})
    return normalize_record(r)


def openalex_record(x):
    abstract=x.get('abstract_inverted_index') or {}
    positions={p:word for word,ps in abstract.items() for p in ps}
    ids={k:(str(v).split('/')[-1] if k in ['openalex','pmid','pmcid'] else v) for k,v in x.get('ids',{}).items() if v}
    ids.setdefault('openalex',x.get('id','').split('/')[-1])
    return normalize_record({'title':x.get('display_name',''),'identifiers':ids,'year':x.get('publication_year'),'authors':[{'display':a.get('author',{}).get('display_name',''),'unparsed':True,'orcid':a.get('author',{}).get('orcid')} for a in x.get('authorships',[])],'journal':((x.get('primary_location') or {}).get('source') or {}).get('display_name',''),'abstract':' '.join(positions[k] for k in sorted(positions)),'record_type':x.get('type','article'),'citation_count':x.get('cited_by_count'),'retracted':x.get('is_retracted'),'oa_locations':[{'url':p.get('pdf_url') or p.get('landing_page_url'),'source':'openalex','access':'open_access','format':'pdf' if p.get('pdf_url') else 'html','version':p.get('version')} for p in x.get('locations',[]) if p.get('is_oa') and (p.get('pdf_url') or p.get('landing_page_url'))]})


def s2_record(x):
    ids=x.get('externalIds') or {}; j=x.get('journal') or {}; pdf=x.get('openAccessPdf') or {}
    return normalize_record({'title':x.get('title',''),'identifiers':{'doi':ids.get('DOI',''),'pmid':ids.get('PubMed',''),'arxiv':ids.get('ArXiv',''),'s2':x.get('paperId','')},'authors':[{'display':a['name'],'unparsed':True} for a in x.get('authors',[])],'year':x.get('year'),'journal':j.get('name') or x.get('venue',''),'abstract':x.get('abstract') or '', 'citation_count':x.get('citationCount'),'oa_locations':[{'url':pdf['url'],'source':'semantic-scholar','access':'open_access','format':'pdf'}] if pdf.get('url') else []})


def arxiv_records(data):
    try: root=ET.fromstring(data)
    except ET.ParseError: raise NetworkError('arXiv returned invalid XML or a rate-limit body') from None
    n={'a':'http://www.w3.org/2005/Atom','o':'http://a9.com/-/spec/opensearch/1.1/'}
    total=int(root.findtext('o:totalResults','0',n)); result=[]
    for e in root.findall('a:entry',n):
        title=e.findtext('a:title','',n).strip()
        if title.casefold()=='error': raise NetworkError('arXiv returned an Error entry with HTTP 200')
        identifier=e.findtext('a:id','',n).rsplit('/abs/',1)[-1]
        date=e.findtext('a:published','',n)
        result.append(normalize_record({'title':re.sub(r'\s+',' ',title),'identifiers':{'arxiv':identifier},'year':int(date[:4]) if date[:4].isdigit() else None,'authors':[{'display':a.findtext('a:name','',n),'unparsed':True} for a in e.findall('a:author',n)],'journal':'arXiv','record_type':'preprint','abstract':e.findtext('a:summary','',n),'oa_locations':[{'url':'https://arxiv.org/pdf/'+identifier,'format':'pdf','source':'arxiv','access':'open_access'}]}))
    return result,total


def pubmed_records(data):
    root=ET.fromstring(data); result=[]
    txt=lambda node: ''.join(node.itertext()).strip() if node is not None else ''
    for e in root.findall('.//PubmedArticle'):
        a=e.find('./MedlineCitation/Article')
        if a is None: continue
        ids={'pmid':e.findtext('./MedlineCitation/PMID','')}
        for i in e.findall('./PubmedData/ArticleIdList/ArticleId'):
            if i.get('IdType') in ['doi','pmc']: ids['pmcid' if i.get('IdType')=='pmc' else 'doi']=i.text
        year=a.findtext('./Journal/JournalIssue/PubDate/Year') or (re.search(r'\d{4}',a.findtext('./Journal/JournalIssue/PubDate/MedlineDate','')) or [''])[0]
        result.append(normalize_record({'title':txt(a.find('ArticleTitle')),'identifiers':ids,'year':int(year) if str(year).isdigit() else None,'authors':[{'name':z.findtext('CollectiveName')} if z.find('CollectiveName') is not None else {'family':z.findtext('LastName',''),'given':z.findtext('ForeName') or z.findtext('Initials','')} for z in a.findall('./AuthorList/Author')],'journal':a.findtext('./Journal/Title',''),'abstract':'\n'.join(txt(z) for z in a.findall('./Abstract/AbstractText')),'volume':a.findtext('./Journal/JournalIssue/Volume',''),'issue':a.findtext('./Journal/JournalIssue/Issue',''),'pages':a.findtext('./Pagination/MedlinePgn',''),'publication_types':[z.text for z in a.findall('./PublicationTypeList/PublicationType')]}))
    return result


def search_one(client,source,query,limit=20):
    if source not in SEARCH_SOURCES: raise ValueError('Use api for this provider; normalized search supports '+', '.join(SEARCH_SOURCES))
    if not 1<=limit<=1000: raise ValueError('Search limit must be 1..1000; for bulk use the documented snapshots/paginator')
    out=[]; offset=0; cursor='*'; total=None; pages=0; raw=[]; failure=None
    while len(out)<limit and pages<20:
        try:
            size=min(100,limit-len(out)); pages+=1
            if source=='crossref':
                data=provider_request(client,source,'works',{'query.bibliographic':query,'rows':size,'offset':offset})
                m=data['message']; total=m['total-results']; batch=[crossref_record(x) for x in m['items']]
            elif source=='europepmc':
                data=provider_request(client,source,'search',{'query':query,'format':'json','resultType':'core','pageSize':size,'cursorMark':cursor})
                total=data.get('hitCount'); batch=[epmc_record(x) for x in data.get('resultList',{}).get('result',[])]
                next_cursor=data.get('nextCursorMark')
            elif source=='openalex':
                data=provider_request(client,source,'works',{'search':query,'per-page':size,'cursor':cursor})
                total=data.get('meta',{}).get('count'); batch=[openalex_record(x) for x in data.get('results',[])]
                next_cursor=data.get('meta',{}).get('next_cursor')
            elif source=='semantic-scholar':
                data=provider_request(client,source,'paper/search',{'query':query,'limit':size,'offset':offset,'fields':'title,authors,year,venue,journal,abstract,externalIds,citationCount,openAccessPdf'})
                total=data.get('total'); batch=[s2_record(x) for x in data.get('data',[])]
            elif source=='arxiv':
                q=query if re.search(r'\b(?:ti|au|abs|all|cat|id|submittedDate):',query) else 'all:'+query
                xml=provider_request(client,source,'query',{'search_query':q,'start':offset,'max_results':size},binary=True)
                batch,total=arxiv_records(xml); data={'xml':xml.decode('utf-8')}
            elif source=='pubmed':
                data=provider_request(client,source,'esearch.fcgi',{'db':'pubmed','term':query,'retmode':'json','retstart':offset,'retmax':size})
                m=data['esearchresult']; total=int(m['count']); ids=m.get('idlist',[])
                if ids:
                    xml=provider_request(client,source,'efetch.fcgi',{'db':'pubmed','id':','.join(ids),'retmode':'xml'},binary=True)
                    batch=pubmed_records(xml); data={'search':data,'fetch_xml':xml.decode()}
                else: batch=[]
            else:
                data=provider_request(client,source,'search/works/',{'q':query,'limit':min(size,100),'offset':offset})
                total=data.get('totalHits'); batch=[normalize_record({'title':x.get('title',''),'identifiers':{'doi':x.get('doi',''),'core':x.get('id')},'authors':[a.get('name','') for a in x.get('authors',[])],'year':x.get('yearPublished'),'abstract':x.get('abstract',''),'oa_locations':[{'url':x['downloadUrl'],'format':'pdf','access':'open_access','source':'core'}] if x.get('downloadUrl') else []}) for x in data.get('results',[])]
            raw.append(data); out.extend(batch); offset+=len(batch)
            if not batch or (total is not None and len(out)>=total): break
            if source in ['europepmc','openalex']:
                if not next_cursor or next_cursor==cursor: break
                cursor=next_cursor
            if source=='pubmed' and offset>=9999: break
        except (NetworkError,ValueError,KeyError,ET.ParseError) as e:
            failure=str(e); break
    for r in out:
        r['provenance'].append({'source':source,'query':query,'accessed_at':now(),'level':'abstract' if r.get('abstract') else 'metadata'})
    complete=total is not None and len(out)>=total and failure is None
    return {'records':out,'source':source,'query':query,'expected_total':total,'retrieved':len(out),'pages':pages,'complete_for_query':complete,'failure':failure,'stop_reason':'provider_failure' if failure else 'exhausted' if complete else 'requested_limit' if len(out)>=limit else 'provider_or_page_limit','raw_pages':raw}


def search(query,sources,limit=20,scope='all',from_year=None,to_year=None,workspace=None,client=None):
    client=client or Client(); batches=[]; all_records=[]
    for source in sources:
        start=len(client.requests)
        try:
            b=search_one(client,source,query,limit)
            if workspace:
                name=source+'-'+digest([query,now()])[:14]
                path=workspace/'sources'/(name+'.json')
                save(path,b.pop('raw_pages')); b['raw_file']=str(path)
            else: b.pop('raw_pages')
            b['status']='partial' if b.get('failure') and b['retrieved'] else 'failed' if b.get('failure') else 'ok'
            if b.get('failure'): b['error']=b['failure']
            all_records.extend(b.pop('records'))
        except (NetworkError,ValueError,KeyError,ET.ParseError) as e:
            b={'source':source,'query':query,'status':'failed','error':str(e),'complete_for_query':False,'retrieved':0}
        b['requests']=client.requests[start:]; batches.append(b)
    merged=deduplicate(all_records)
    selected=[r for r in merged['records'] if scope_match(r.get('journal',''),scope) and (from_year is None or (r.get('year') is not None and r['year']>=from_year)) and (to_year is None or (r.get('year') is not None and r['year']<=to_year))]
    result={**merged,'records':selected,'selected_count':len(selected),'filters':{'scope':scope,'from_year':from_year,'to_year':to_year,'applied':'locally after bounded retrieval'},'searches':batches,'searched_at':now(),'coverage':'bounded retrieval; not an exhaustive review','claim_support':'not_assessed'}
    if workspace:
        save(workspace/'searches'/('search-'+digest([query,now()])[:16]+'.json'),result)
    return result


def doi_lookup(doi,client=None):
    client=client or Client(); doi=normalize_doi(doi)
    if not doi: raise ValueError('Invalid DOI syntax')
    errors=[]; encoded=quote(doi,safe='')
    try:
        data=provider_request(client,'crossref','works/'+encoded)
        r=crossref_record(data['message'])
        if normalize_doi(r['identifiers'].get('doi'))!=doi: raise ValueError('Crossref DOI does not match requested identifier')
        return {'status':'metadata_found','agency':'crossref','record':r,'requests':client.requests,'claim_support':'not_assessed'}
    except (NetworkError,KeyError,ValueError) as e: errors.append({'source':'crossref','error':str(e)})
    try:
        data=client.json('https://api.datacite.org/dois/'+encoded)
        r=datacite_record(data)
        if normalize_doi(r['identifiers'].get('doi'))!=doi: raise ValueError('DataCite DOI does not match requested identifier')
        return {'status':'metadata_found','agency':'datacite','record':r,'requests':client.requests,'fallback_errors':errors,'claim_support':'not_assessed'}
    except (NetworkError,KeyError,ValueError) as e: errors.append({'source':'datacite','error':str(e)})
    try:
        handle=client.json('https://doi.org/api/handles/'+encoded)
        status='registered_metadata_unavailable' if handle.get('responseCode')==1 else 'not_found_in_handle_lookup' if handle.get('responseCode')==100 else 'inconclusive'
    except NetworkError as e:
        status='inconclusive'; errors.append({'source':'handle','error':str(e)})
    return {'status':status,'doi':doi,'errors':errors,'requests':client.requests,'claim_support':'not_assessed'}


def oa_lookup(doi,client=None):
    client=client or Client(); doi=normalize_doi(doi)
    if not doi: raise ValueError('Invalid DOI syntax')
    locations=[]; errors=[]
    for source in ['openalex','unpaywall']:
        try:
            if source=='openalex':
                d=provider_request(client,source,'works/https://doi.org/'+quote(doi,safe=''))
                locations.extend(openalex_record(d)['oa_locations'])
            else:
                d=provider_request(client,source,quote(doi,safe=''))
                for x in d.get('oa_locations') or []:
                    if x.get('url_for_pdf') or x.get('url'):
                        locations.append({'url':x.get('url_for_pdf') or x['url'],'format':'pdf' if x.get('url_for_pdf') else 'html','source':source,'access':'open_access','license':x.get('license'),'version':x.get('version')})
        except (NetworkError,ValueError,KeyError) as e: errors.append({'source':source,'error':str(e)})
    return {'doi':doi,'locations':list({x['url']:x for x in locations}.values()),'status':'oa_found' if locations else 'oa_resolution_inconclusive' if errors else 'oa_not_found','errors':errors,'requests':client.requests}
