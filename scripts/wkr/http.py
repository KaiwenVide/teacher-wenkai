from __future__ import annotations
import json
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode
from .common import redact_url, now, digest


class NetworkError(RuntimeError):
    def __init__(self,message,status=None):
        super().__init__(message); self.status=status


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from urllib.parse import urlsplit
        old, new = urlsplit(req.full_url), urlsplit(newurl)
        if new.scheme != 'https': raise NetworkError('Refused non-HTTPS redirect')
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and old.netloc != new.netloc:
            for key in list(redirected.headers):
                if key.lower() not in ['accept', 'user-agent', 'content-type']:
                    redirected.remove_header(key)
        return redirected


class Client:
    def __init__(self,timeout=25,max_bytes=16*1024*1024,delay=0.36,opener=None):
        self.timeout=timeout; self.max_bytes=max_bytes; self.delay=delay
        self.opener=opener or urllib.request.build_opener(SafeRedirect()).open
        self.last={}; self.requests=[]

    def fetch(self,url,params=None,headers=None,body=None,form=None):
        from urllib.parse import urlsplit
        if params:
            url += ('&' if '?' in url else '?')+urlencode({k:v for k,v in params.items() if v is not None})
        p=urlsplit(url)
        if p.scheme!='https': raise ValueError('Only HTTPS endpoints are accepted')
        delay=max(self.delay,3.05 if 'arxiv.org' in p.netloc else 1.02 if 'crossref.org' in p.netloc else 0)
        elapsed=time.monotonic()-self.last.get(p.netloc,0)
        if elapsed<delay: time.sleep(delay-elapsed)
        if body is not None and form is not None: raise ValueError('Use either JSON or form body')
        payload=urlencode(form,doseq=True).encode() if form is not None else json.dumps(body).encode() if body is not None else None
        req=urllib.request.Request(url,data=payload,headers={'User-Agent':'teacher-wenkai/3.0 (auditable academic retrieval)','Accept':'application/json',**({'Content-Type':'application/json'} if body is not None else {'Content-Type':'application/x-www-form-urlencoded'} if form is not None else {}),**(headers or {})})
        event={'url':redact_url(url),'method':'POST' if payload is not None else 'GET','accessed_at':now()}
        if payload is not None: event['request_body_sha256']=digest(payload)
        try:
            for attempt in range(2):
                self.last[p.netloc]=time.monotonic()
                try:
                    with self.opener(req,timeout=self.timeout) as response:
                        data=response.read(self.max_bytes+1)
                        if len(data)>self.max_bytes: raise NetworkError('Response exceeds configured byte limit')
                        encoding=response.headers.get('Content-Encoding','').lower() if hasattr(response,'headers') else ''
                        if encoding:
                            import gzip, io, zlib
                            event['encoded_bytes']=len(data); event['content_encoding']=encoding
                            try:
                                if encoding in ['gzip','x-gzip']:
                                    with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed: data=compressed.read(self.max_bytes+1)
                                elif encoding=='deflate':
                                    stream=zlib.decompressobj(); data=stream.decompress(data,self.max_bytes+1)
                                    if stream.unconsumed_tail: raise NetworkError('Decompressed response exceeds byte limit')
                                elif encoding!='identity': raise NetworkError('Unsupported response content encoding: '+encoding)
                            except (OSError,EOFError,zlib.error): raise NetworkError('Invalid compressed response') from None
                            if len(data)>self.max_bytes: raise NetworkError('Decompressed response exceeds byte limit')
                        event.update(status=getattr(response,'status',200),bytes=len(data),sha256=digest(data),content_type=response.headers.get('Content-Type','') if hasattr(response,'headers') else '',final_url=redact_url(response.geturl()) if hasattr(response,'geturl') else redact_url(url))
                        return data
                except urllib.error.HTTPError as e:
                    if e.code in (429,503) and attempt==0:
                        retry=e.headers.get('Retry-After','1') if e.headers else '1'
                        if retry.isdigit() and int(retry)<=10:
                            time.sleep(max(delay,float(retry))); continue
                    event['status']=e.code
                    raise NetworkError(f'HTTP {e.code} from {p.netloc}',e.code) from None
                except (urllib.error.URLError,TimeoutError,OSError) as e:
                    event['status']='network_error'
                    raise NetworkError(f'Network request failed for {p.netloc}: {type(e).__name__}') from None
        finally:
            self.requests.append(event)

    def json(self,*args,**kwargs):
        try: return json.loads(self.fetch(*args,**kwargs))
        except (ValueError,UnicodeError): raise NetworkError('Endpoint returned non-JSON content') from None
