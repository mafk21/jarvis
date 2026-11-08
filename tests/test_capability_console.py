from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
STATIC=ROOT/'apex_ui'/'static_hud'

def test_proven_hud_loads_additive_capability_overlay():
    index=(STATIC/'index.html').read_text(encoding='utf-8')
    assert '<script src="/capability-overlay.js"></script>' in index
    assert (STATIC/'capability-overlay.js').is_file()

def test_capability_console_covers_secure_backend_controls():
    html=(STATIC/'capabilities.html').read_text(encoding='utf-8')
    js=(STATIC/'capability-console.js').read_text(encoding='utf-8')
    for action in ('browser_companion_pair','browser_companion_revoke','smart_home_configure','smart_home_discover','smart_home_undo','local_voice_diagnostics','local_voice_install','owner_auth_save','provider_routing_save','strategy_experiments_enable','strategy_experiment_propose','strategy_experiment_remove','workflow_review_status','phone_device_revoke','phone_devices_revoke_all'):
        assert action in html or action in js
    assert 'type="password"' in html
    assert 'confirm(b.dataset.confirm)' in js

def test_console_starts_without_implicit_user_choices():
    html=(STATIC/'capabilities.html').read_text(encoding='utf-8')
    js=(STATIC/'capability-console.js').read_text(encoding='utf-8')
    assert ' checked' not in html
    assert "risks:['critical']" not in js
    assert "permissions:['smart_home'" not in js
    assert "components:selected('[data-voice]')" not in js  # selection is validated before request
    assert "if(!components.length)" in js

def test_console_does_not_embed_secrets_or_external_origins():
    combined=''.join((STATIC/name).read_text(encoding='utf-8') for name in ('capabilities.html','capability-console.js','capability-overlay.js'))
    assert 'https://' not in combined
    assert 'http://' not in combined
    assert "fetch('/api/hud/action'" in combined
