"""Permission-scoped Home Assistant connector; Matter devices flow through HA."""
from __future__ import annotations
from urllib.parse import urlparse
from pathlib import Path
import json, os, time, urllib.request
from core.security_vault import encrypt_secret, decrypt_secret

ALLOWED_SERVICES={'light.turn_on','light.turn_off','light.toggle','scene.turn_on','climate.set_temperature','lock.lock','lock.unlock','cover.open_cover','cover.close_cover'}
PATH=Path(__file__).resolve().parent.parent/'config'/'smart_home.json'
_LAST_ACTION={}

def _url(value:str)->str:
    parsed=urlparse(value)
    if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password: raise ValueError('invalid Home Assistant URL')
    return value.rstrip('/')
def _load()->dict:
    try: data=json.loads(PATH.read_text(encoding='utf-8'))
    except (OSError,ValueError): return {'url':'','token':'','entities':[]}
    if data.get('token'):
        try: data['token']=decrypt_secret(data['token'])
        except ValueError: data['token']=''
    return data
def configure(base_url:str, token:str, entities:list[str]|None=None)->dict:
    url=_url(base_url); clean=sorted({str(v).strip() for v in (entities or []) if '.' in str(v) and '\n' not in str(v)})[:500]
    current=_load(); raw=token.strip() or current.get('token','')
    if not raw: raise ValueError('Home Assistant token is required')
    data={'url':url,'token':encrypt_secret(raw),'entities':clean,'updated_at':int(time.time())}
    PATH.parent.mkdir(parents=True,exist_ok=True); tmp=PATH.with_suffix('.tmp'); tmp.write_text(json.dumps(data,indent=2),encoding='utf-8'); os.chmod(tmp,0o600); os.replace(tmp,PATH)
    return status()
def disconnect()->None: PATH.unlink(missing_ok=True)
def status()->dict:
    data=_load(); return {'configured':bool(data.get('url') and data.get('token')),'url':data.get('url',''),'allowed_entities':data.get('entities',[]),'token_stored':bool(data.get('token'))}
def _request(path:str, method='GET', payload=None):
    data=_load()
    if not data.get('url') or not data.get('token'): raise ValueError('Home Assistant is not configured')
    req=urllib.request.Request(data['url']+path,data=json.dumps(payload).encode() if payload is not None else None,headers={'Authorization':f"Bearer {data['token']}",'Content-Type':'application/json'},method=method)
    with urllib.request.urlopen(req,timeout=10) as response: return response.status,json.loads(response.read().decode() or 'null')
def discover()->list[dict]:
    _, rows=_request('/api/states'); allowed=set(_load().get('entities',[])); result=[]
    for row in rows if isinstance(rows,list) else []:
        entity=str(row.get('entity_id',''))
        if entity.split('.',1)[0] in {'light','scene','climate','lock','cover','switch'}:
            result.append({'entity_id':entity,'name':str(row.get('attributes',{}).get('friendly_name') or entity)[:120],'state':str(row.get('state',''))[:80],'allowed':entity in allowed})
    return result[:500]
def state(entity_id:str)->dict:
    _, row=_request('/api/states/'+entity_id); return {'entity_id':entity_id,'state':row.get('state'),'attributes':row.get('attributes',{})}
def call(base_url:str, token:str, service:str, entity_id:str, data:dict|None=None)->dict:
    _url(base_url)
    if service not in ALLOWED_SERVICES: raise ValueError('service is not allowlisted')
    if not entity_id or any(ch in entity_id for ch in '\r\n\0'): raise ValueError('invalid entity id')
    config=_load(); allowed=config.get('entities',[])
    configured_call=(config.get('url')==base_url.rstrip('/') and config.get('token')==token)
    if configured_call and entity_id not in allowed: raise PermissionError('entity is not allowed')
    before=state(entity_id) if config.get('url')==base_url.rstrip('/') and config.get('token')==token else {}
    domain,action=service.split('.',1); payload={'entity_id':entity_id,**(data or {})}
    req=urllib.request.Request(f"{base_url.rstrip('/')}/api/services/{domain}/{action}",data=json.dumps(payload).encode(),headers={'Authorization':f'Bearer {token}','Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(req,timeout=10) as response:
        body=json.loads(response.read().decode() or '[]'); acknowledged=200<=response.status<300 and isinstance(body,list)
    after=state(entity_id) if before else {}
    expected={'turn_on':'on','turn_off':'off','lock':'locked','unlock':'unlocked','open_cover':'open','close_cover':'closed'}.get(action)
    verified=acknowledged and (not expected or after.get('state')==expected)
    undo=None
    if before.get('state') in {'on','off'}: undo=f"{domain}.turn_{before['state']}"
    elif before.get('state') in {'locked','unlocked'}: undo=f"{domain}.{'lock' if before['state']=='locked' else 'unlock'}"
    elif before.get('state') in {'open','closed'}: undo=f"{domain}.{'open_cover' if before['state']=='open' else 'close_cover'}"
    result={'ok':acknowledged,'status':response.status,'acknowledged':acknowledged,'verified':verified,'before':before.get('state'),'after':after.get('state'),'undo_service':undo}
    if acknowledged and undo: _LAST_ACTION.clear(); _LAST_ACTION.update({'service':undo,'entity_id':entity_id,'created_at':time.time()})
    return result
def undo_status()->dict:
    row=dict(_LAST_ACTION); row['available']=bool(row and time.time()-row.get('created_at',0)<300); return row
def undo_last()->dict:
    row=undo_status()
    if not row.get('available'): raise ValueError('No recent reversible smart-home action')
    config=_load(); _LAST_ACTION.clear(); return call(config['url'],config['token'],row['service'],row['entity_id'],{})
