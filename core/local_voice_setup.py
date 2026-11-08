"""Bounded installer and hardware diagnostics for the optional offline voice stack."""
from __future__ import annotations
import importlib, platform, subprocess, sys, time
PACKAGE_BY_COMPONENT={'openwakeword':'openwakeword','faster_whisper':'faster-whisper','kokoro':'kokoro','piper':'piper-tts'}
def diagnostics()->dict:
    from core.local_voice_profile import snapshot
    profile=snapshot(); audio={'input':False,'output':False,'error':''}
    try:
        sd=importlib.import_module('sounddevice'); devices=sd.query_devices(); audio['input']=any(int(d.get('max_input_channels',0))>0 for d in devices); audio['output']=any(int(d.get('max_output_channels',0))>0 for d in devices)
    except Exception as exc: audio['error']=type(exc).__name__
    cuda=False
    try: cuda=bool(importlib.import_module('ctranslate2').get_cuda_device_count())
    except Exception: pass
    return {**profile,'audio':audio,'hardware':{'platform':platform.system(),'machine':platform.machine(),'cuda':cuda,'recommended_stt':'faster_whisper' if cuda else 'moonshine_or_small_whisper'}}
def install(components:list[str])->dict:
    chosen=[]
    for component in components:
        key=str(component).strip().lower()
        if key in PACKAGE_BY_COMPONENT and key not in chosen: chosen.append(key)
    if not chosen: return {'ok':False,'elapsed_s':0,'diagnostics':diagnostics(),'error':'Select at least one offline voice component.'}
    packages=[PACKAGE_BY_COMPONENT[key] for key in chosen]
    started=time.monotonic(); command=[sys.executable,'-m','pip','install','--disable-pip-version-check',*packages]
    completed=subprocess.run(command,capture_output=True,text=True,timeout=900)
    return {'ok':completed.returncode==0,'elapsed_s':round(time.monotonic()-started,1),'diagnostics':diagnostics(),'error':'' if completed.returncode==0 else 'Package installer failed; inspect local pip logs.'}
