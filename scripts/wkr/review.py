from __future__ import annotations
import shutil
from collections import Counter,defaultdict
from pathlib import Path
from .common import save,load,write,digest,now,safe_name


def screening_flow(ledger):
    rows=ledger.get('records',[]); errors=[]; seen=set(); unique=[]; duplicates=[]
    for r in rows:
        rid=r.get('record_id')
        if not rid or rid in seen: errors.append('Missing or repeated record_id: '+str(rid))
        seen.add(rid)
        (duplicates if r.get('duplicate_of') else unique).append(r)
    for r in duplicates:
        if r['duplicate_of'] not in seen or r['duplicate_of']==r.get('record_id'): errors.append('Invalid duplicate target: '+str(r.get('record_id')))
        elif next((x for x in rows if x.get('record_id')==r['duplicate_of']),{}).get('duplicate_of'): errors.append('Duplicate chains must point directly to retained record')
    screened=[r for r in unique if r.get('title_abstract_decision') in ['include','exclude']]
    excluded=[r for r in screened if r['title_abstract_decision']=='exclude']
    seeking=[r for r in screened if r['title_abstract_decision']=='include']; reports=defaultdict(list)
    for r in seeking:
        if not r.get('report_id'): errors.append('Included screening record needs report_id: '+r['record_id'])
        else: reports[r['report_id']].append(r)
    retrieved=[]; unavailable=[]; unresolved=[]; full_excluded=[]; included=[]; reasons=Counter(); studies=set()
    for report_id,group in reports.items():
        signatures={(r.get('retrieval'),r.get('fulltext_decision'),r.get('exclusion_reason'),r.get('study_id')) for r in group}
        if len(signatures)>1: errors.append('Conflicting report-level decisions: '+report_id)
        r=group[0]; state=r.get('retrieval')
        if state=='not_retrieved': unavailable.append(report_id); continue
        if state!='retrieved': unresolved.append(report_id); continue
        retrieved.append(report_id); decision=r.get('fulltext_decision')
        if decision=='exclude':
            full_excluded.append(report_id)
            if not r.get('exclusion_reason'): errors.append('Full-text exclusion needs primary reason: '+report_id)
            else: reasons[r['exclusion_reason']]+=1
        elif decision=='include':
            included.append(report_id)
            if not r.get('study_id'): errors.append('Included report needs study_id: '+report_id)
            else: studies.add(r['study_id'])
        else: unresolved.append(report_id)
    complete=len(screened)==len(unique) and not unresolved and not errors
    return {'valid':not errors,'complete':complete,'counts':{'records_identified':len(rows),'duplicate_records_removed':len(duplicates),'records_screened':len(screened),'records_pending_screening':len(unique)-len(screened),'records_excluded_title_abstract':len(excluded),'reports_sought':len(reports),'reports_not_retrieved':len(unavailable),'reports_retrieved':len(retrieved),'reports_excluded_fulltext':len(full_excluded),'reports_included':len(included),'studies_included':len(studies)},'fulltext_exclusion_reasons':dict(reasons),'unresolved_report_ids':unresolved,'errors':errors,'coverage':'Counts reflect the supplied ledger only; search completeness, dual screening and PRISMA compliance are not established by this calculation.'}


def freeze_packet(files,out,reviewers=3):
    if not 1<=reviewers<=5: raise ValueError('Reviewer count must be 1..5')
    out=Path(out)
    if out.exists() and any(out.iterdir()): raise ValueError('Use a fresh review packet directory; frozen packets are immutable')
    entries=[]
    for i,f in enumerate(files,1):
        p=Path(f)
        if not p.is_file(): raise ValueError('Missing source '+str(p))
        name=f'{i:02d}-'+safe_name(p.name,140); target=out/'sources'/name; target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p,target)
        entries.append({'path':'sources/'+name,'sha256':digest(target.read_bytes()),'original_path':str(p.resolve())})
    packet_hash=digest([{'path':x['path'],'sha256':x['sha256']} for x in entries])
    packet={'schema_version':'1.0','packet_sha256':packet_hash,'created_at':now(),'sources':entries,'requested_reviewers':reviewers,'status':'frozen','independence':'not_yet_executed'}
    save(out/'packet.json',packet)
    rubric=Path(__file__).resolve().parents[2]/'assets/templates/reviewer_prompt.md'
    for i in range(1,reviewers+1):
        write(out/f'reviewer-{i}/task.md',rubric.read_text(encoding='utf-8')+f'\n\nYour reviewer ID: reviewer-{i}. Packet SHA-256: {packet_hash}.\n')
        save(out/f'reviewer-{i}/report-template.json',{'schema_version':'1.0','packet_sha256':packet_hash,'reviewer_id':f'reviewer-{i}','isolated_context_id':None,'status':'pending','summary':'','findings':[],'limits':[]})
    return {'packet':str(out/'packet.json'),'reviewers':reviewers,'packet_sha256':packet_hash,'status':'prepared; reviews have not run'}


def collect_reviews(packet_path,reports):
    path=Path(packet_path); packet=load(path); problems=[]; ids=set(); contexts=set(); findings=[]; summaries=[]
    for src in packet['sources']:
        p=path.parent/src['path']
        if not p.is_file() or digest(p.read_bytes())!=src['sha256']: problems.append('Frozen source changed: '+src['path'])
    for name in reports:
        r=load(name); rid=r.get('reviewer_id'); context=r.get('isolated_context_id')
        if not rid or rid in ids: problems.append('Duplicate/missing reviewer ID')
        ids.add(rid)
        if r.get('status')!='complete': problems.append('Incomplete reviewer report: '+str(rid))
        if r.get('packet_sha256')!=packet['packet_sha256']: problems.append('Reviewer used a different packet: '+str(rid))
        if not context or context in contexts: problems.append('Independent context not declared or reused: '+str(rid))
        contexts.add(context)
        summaries.append({'reviewer_id':rid,'summary':r.get('summary'),'limits':r.get('limits',[])})
        for f in r.get('findings',[]):
            if not all(f.get(k) for k in ['issue','source_locator','severity','resolution_test']): problems.append('Finding missing issue/location/severity/resolution_test: '+str(rid))
            findings.append({**f,'reviewer_id':rid})
    if len(reports)!=packet['requested_reviewers']: problems.append('Report count differs from requested reviewers')
    return {'ready_for_synthesis':not problems,'problems':problems,'packet_sha256':packet['packet_sha256'],'reviewer_summaries':summaries,'findings':findings,'independence':'context declarations checked; host execution logs must substantiate isolation','synthesis_rule':'Retain disagreements, verify locations and weigh evidence. Do not turn reviewer voting into scientific truth or an editorial prediction.'}
