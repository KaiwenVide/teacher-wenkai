from __future__ import annotations
import html
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from .common import digest,save,load,write,now


def extract(path,out,render_pages=False):
    path=Path(path); out=Path(out); blocks=[]; pages=[]; suffix=path.suffix.lower()
    def add(text,locator,kind='text'):
        text=text.strip()
        if text: blocks.append({'block_id':f'B{len(blocks)+1:05d}','locator':locator,'kind':kind,'original':text})
    if suffix=='.pdf':
        try: from pypdf import PdfReader
        except ImportError: raise ValueError('PDF reading requires the separately installed pypdf package') from None
        doc=PdfReader(path)
        for n,page in enumerate(doc.pages,1):
            text=page.extract_text() or ''
            for i,block in enumerate(re.split(r'\n\s*\n',text),1): add(block,f'page {n}, text block {i}')
        if render_pages:
            try: import pypdfium2 as pdfium
            except ImportError: raise ValueError('Page rendering requires the separately installed pypdfium2 package') from None
            with pdfium.PdfDocument(str(path)) as rendered:
                for n in range(len(rendered)):
                    image=out/'assets'/f'page-{n+1:04d}.png'; image.parent.mkdir(parents=True,exist_ok=True)
                    page=rendered[n]
                    bitmap=page.render(scale=1.5)
                    bitmap.to_pil().save(image)
                    bitmap.close(); page.close()
                    pages.append({'page':n+1,'path':str(image.relative_to(out)),'role':'source page; figures and tables require visual reading'})
    elif suffix in ['.docx','.pptx']:
        with zipfile.ZipFile(path) as z:
            if suffix=='.docx':
                roots=[('document',ET.fromstring(z.read('word/document.xml')))]
                for name,root in roots:
                    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                    for n,p in enumerate(root.findall('.//w:p',ns),1): add(''.join(x.text or '' for x in p.findall('.//w:t',ns)),f'paragraph {n}')
            else:
                names=sorted((x for x in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml',x)),key=lambda x:int(re.search(r'slide(\d+)',x).group(1)))
                for n,name in enumerate(names,1):
                    root=ET.fromstring(z.read(name)); ns={'a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
                    for i,p in enumerate(root.findall('.//a:p',ns),1): add(''.join(x.text or '' for x in p.findall('.//a:t',ns)),f'slide {n}, paragraph {i}')
    elif suffix in ['.md','.txt']:
        text=path.read_text(encoding='utf-8'); line=1
        for chunk in re.split(r'(\n\s*\n)',text):
            if chunk.strip(): add(chunk,f'line {line}')
            line+=chunk.count('\n')
    elif suffix in ['.xml','.nxml']:
        root=ET.fromstring(path.read_bytes()); body=root.find('.//body')
        if body is None: raise ValueError('JATS has no body; abstract-only XML cannot be labeled full text')
        for i,node in enumerate(body.iter(),1):
            if node.tag in ['p','title','table','fig','disp-formula']:
                # Skip duplicated p children inside figures/tables by an explicit source label; a reader must reconcile.
                add(''.join(node.itertext()),f'JATS body node {i} ({node.tag})',node.tag)
    else: raise ValueError('Prepare accepts PDF, DOCX, PPTX, TXT, MD or JATS XML. Convert HTML through a source-aware parser first.')
    return blocks,pages


def prepare(source,out,render_pages=False):
    source=Path(source).resolve(); out=Path(out)
    if not source.is_file(): raise ValueError('Source file missing')
    if out.exists() and any(out.iterdir()): raise ValueError('Reader output must be a new or empty directory; existing annotations are never overwritten')
    out.mkdir(parents=True,exist_ok=True)
    blocks,pages=extract(source,out,render_pages)
    doc={'schema_version':'1.0','source':{'path':str(source),'sha256':digest(source.read_bytes()),'filename':source.name},'prepared_at':now(),'status':'draft' if blocks else 'needs_ocr','extraction_limits':'Extraction order, equations, figures, tables and scanned regions require visual QA; textual coverage is not whole-document fidelity.','blocks':blocks,'pages':pages}
    save(out/'source_map.json',doc)
    save(out/'translations.json',{'source_sha256':doc['source']['sha256'],'status':'draft','scope':'provided_source','missing_materials':[],'blocks':[{'block_id':b['block_id'],'translation':'','explanation':'','visual_checked':False} for b in blocks]})
    write(out/'reading_notes.md','# 精读记录\n\n状态：待精读\n\n研究问题：\n\n关键论断与直接证据：\n\n研究设计、模型与外推边界：\n\n逐图逐表（来源定位、结果、作者解释、我的判断）：\n\n竞争解释与反证：\n\n最小决定性实验：\n\n公式、图表、翻译及提取质量复核：\n')
    return {'status':doc['status'],'blocks':len(blocks),'pages_rendered':len(pages),'source_map':str(out/'source_map.json'),'translations':str(out/'translations.json')}


def validate_reader(source_map,translations):
    issues=[]; original=source_map.get('blocks',[]); translated=translations.get('blocks',[])
    ids=[b.get('block_id') for b in original]; tids=[b.get('block_id') for b in translated]
    if not ids: issues.append('No extracted text; OCR or manual source extraction is required')
    if len(set(tids))!=len(tids): issues.append('Duplicate translation block IDs')
    if set(ids)!=set(tids): issues.append('Translation IDs do not exactly cover source blocks')
    if translations.get('source_sha256')!=source_map.get('source',{}).get('sha256'): issues.append('Translation/source hashes do not match')
    p=Path(source_map.get('source',{}).get('path',''))
    if not p.is_file(): issues.append('Original source missing')
    elif digest(p.read_bytes())!=source_map['source']['sha256']: issues.append('Original source changed')
    missing=[b.get('block_id') for b in translated if not str(b.get('translation','')).strip() or str(b.get('translation','')).strip().casefold() in ['todo','待翻译','待补充','tbd']]
    if missing: issues.append(f'{len(missing)} untranslated blocks')
    qa=translations.get('qa',{})
    missing_materials=list(dict.fromkeys([*translations.get('missing_materials',[]),*qa.get('missing_materials',[])]))
    if missing_materials: issues.append('Declared missing materials prevent full reading completion: '+', '.join(missing_materials))
    complete=not issues and translations.get('status')=='reviewed' and bool(translations.get('qa',{}).get('assessor')) and translations.get('qa',{}).get('source_fidelity_checked') is True
    if not issues and not complete:
        qa=translations.get('qa',{})
        if not qa.get('assessor') or qa.get('source_fidelity_checked') is not True:
            issues.append('All blocks populated but source-fidelity QA has not been recorded')
        elif translations.get('status')!='reviewed':
            issues.append('Reader remains in draft status; review the declared scope and missing-materials limits')
    return {'complete':complete,'issues':issues,'missing_blocks':missing,'text_blocks':len(ids),'declared_status':translations.get('status'),'scope':translations.get('scope') or qa.get('scope') or 'provided_source','missing_materials':missing_materials,'limits':'Validation checks declarations and coverage. A human/agent must actually inspect translations, equations and visuals.'}


def render_reader(source_map,translations,output):
    assessment=validate_reader(source_map,translations); mapped={b['block_id']:b for b in translations.get('blocks',[])}
    title=source_map['source']['filename']; state='已记录逐块与原文复核' if assessment['complete'] else '草稿：尚未标记完成；请查看翻译覆盖、复核记录及材料范围'
    lines=['# '+title+'｜中英对照精读','',state,'','源文件：'+source_map['source']['path'],'','SHA-256：'+source_map['source']['sha256'],'']
    for b in source_map['blocks']:
        t=mapped.get(b['block_id'],{}); lines += [f"## {b['block_id']} · {b['locator']}",'','**原文**','',b['original'],'','**中文对照**','',t.get('translation') or '【待翻译】','']
        if t.get('explanation'): lines+=['**解释与证据判断**','',t['explanation'],'']
    write(output,'\n'.join(lines))
    # Local self-contained text view; original text is escaped to avoid executing source HTML.
    parts=['<!doctype html><meta charset="utf-8"><title>'+html.escape(title)+'</title><style>body{max-width:1200px;margin:auto;padding:28px;font:16px/1.65 system-ui;color:#17212b}.pair{display:grid;grid-template-columns:1fr 1fr;gap:24px;border-top:1px solid #ddd;padding:18px 0}pre{white-space:pre-wrap;font:inherit}aside{background:#f4f6fa;padding:16px}@media(max-width:700px){.pair{grid-template-columns:1fr}}</style><h1>'+html.escape(title)+'</h1><aside>'+html.escape(state)+'</aside>']
    for b in source_map['blocks']:
        t=mapped.get(b['block_id'],{})
        parts += ['<h3>'+html.escape(b['block_id']+' · '+b['locator'])+'</h3><div class="pair"><pre>'+html.escape(b['original'])+'</pre><pre>'+html.escape(t.get('translation') or '【待翻译】')+'</pre></div>']
        if t.get('explanation'): parts+=['<aside>'+html.escape(t['explanation'])+'</aside>']
    htmlpath=Path(output).with_suffix('.html'); write(htmlpath,'\n'.join(parts))
    return {'markdown':str(output),'html':str(htmlpath),'validation':assessment}
