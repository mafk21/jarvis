"""Optional owner authorization using operating-system authentication only."""
from __future__ import annotations
import platform, subprocess, json, os
from pathlib import Path
POLICY_PATH=Path(__file__).resolve().parent.parent/'config'/'owner_auth.json'
def policy()->dict:
    try: data=json.loads(POLICY_PATH.read_text(encoding='utf-8'))
    except (OSError,ValueError): data={'enabled':False,'risks':[],'permissions':[]}
    return {'enabled':bool(data.get('enabled',False)),'risks':[v for v in data.get('risks',[]) if v in {'medium','high','critical'}],'permissions':[str(v)[:80] for v in data.get('permissions',[])][:50]}
def save_policy(enabled:bool, risks:list, permissions:list)->dict:
    data={'enabled':bool(enabled),'risks':[v for v in risks if v in {'medium','high','critical'}],'permissions':[str(v)[:80] for v in permissions][:50]}
    POLICY_PATH.parent.mkdir(parents=True,exist_ok=True); tmp=POLICY_PATH.with_suffix('.tmp'); tmp.write_text(json.dumps(data,indent=2),encoding='utf-8'); os.replace(tmp,POLICY_PATH); return data
def required(risk:str, permission:str)->bool:
    data=policy(); return data['enabled'] and (risk in data['risks'] or permission in data['permissions'])

def available(system:str|None=None)->bool:
    name=(system or platform.system()).lower()
    if name=='darwin': return bool(_which('osascript'))
    if name=='windows':
        try:
            from winrt.windows.security.credentials.ui import UserConsentVerifier  # type: ignore
            return UserConsentVerifier is not None
        except Exception: return False
    if name=='linux': return bool(_which('pkcheck'))
    return False

def _which(name):
    import shutil
    return shutil.which(name)
def authenticate(reason:str='Authorize JARVIS action', system:str|None=None)->bool:
    name=(system or platform.system()).lower()
    if name=='darwin':
        # Keep the AppleScript constant; never interpolate model/user text into code.
        script='do shell script "/usr/bin/true" with administrator privileges with prompt "Authorize this JARVIS action."'
        return subprocess.run(['osascript','-e',script],capture_output=True,timeout=60).returncode==0
    if name=='linux' and _which('pkcheck'):
        return subprocess.run(['pkcheck','--action-id','org.freedesktop.policykit.exec','--process',str(__import__('os').getpid()),'--allow-user-interaction'],capture_output=True,timeout=60).returncode==0
    if name=='windows':
        try:
            import asyncio
            from winrt.windows.security.credentials.ui import UserConsentVerifier, UserConsentVerificationResult  # type: ignore
            result=asyncio.run(UserConsentVerifier.request_verification_async('Authorize this JARVIS action.'))
            return result==UserConsentVerificationResult.VERIFIED
        except Exception:
            return False
    return False
