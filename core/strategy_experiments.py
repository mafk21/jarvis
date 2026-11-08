"""Opt-in, bounded strategy experiments with automatic rollback decisions."""
from __future__ import annotations
import json, os
from pathlib import Path
from typing import Any
PATH=Path(__file__).resolve().parent.parent/'config'/'strategy_experiments.json'
MIN_SAMPLE=10

def _load():
    try: data=json.loads(PATH.read_text(encoding='utf-8'))
    except (OSError,ValueError): data={'version':1,'enabled':False,'experiments':{}}
    return data if isinstance(data,dict) and data.get('version',1)==1 else {'version':1,'enabled':False,'experiments':{}}
def _save(data):
    PATH.parent.mkdir(parents=True,exist_ok=True); tmp=PATH.with_suffix('.tmp'); tmp.write_text(json.dumps(data,indent=2),encoding='utf-8'); os.replace(tmp,PATH)
def set_enabled(enabled:bool):
    data=_load(); data['enabled']=bool(enabled); _save(data)
def propose(name:str, baseline:str, candidate:str):
    key=str(name).strip()[:80]; base=str(baseline).strip()[:80]; choice=str(candidate).strip()[:80]
    if not key or not base or not choice: raise ValueError('name, baseline, and candidate are required')
    data=_load(); data.setdefault('experiments',{})[key]={'baseline':base,'candidate':choice,'baseline_ok':0,'baseline_total':0,'candidate_ok':0,'candidate_total':0,'state':'running'}; _save(data)
def remove(name:str)->bool:
    data=_load(); key=str(name).strip(); found=data.get('experiments',{}).pop(key,None) is not None
    if found: _save(data)
    return found
def assignment(name:str, subject:str)->str|None:
    data=_load(); row=data.get('experiments',{}).get(name)
    if not data.get('enabled') or not row or row.get('state')!='running': return None
    import hashlib
    return 'candidate' if int(hashlib.sha256(subject.encode()).hexdigest()[-2:],16)%2 else 'baseline'
def record(name:str, arm:str, verified:bool):
    data=_load()
    if not data.get('enabled'): return
    row=data.get('experiments',{}).get(name)
    if not row or row.get('state')!='running' or arm not in {'baseline','candidate'}: return
    row[f'{arm}_total']+=1; row[f'{arm}_ok']+=int(bool(verified))
    if row['candidate_total']>=MIN_SAMPLE and row['baseline_total']>=MIN_SAMPLE:
        br=row['baseline_ok']/row['baseline_total']; cr=row['candidate_ok']/row['candidate_total']
        if cr+0.05<br: row['state']='rolled_back'
        elif cr>br: row['state']='promoted'
    _save(data)
def snapshot()->dict[str,Any]: return _load()
