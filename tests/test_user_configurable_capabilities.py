def test_owner_auth_has_no_implicit_risk_or_permission_defaults(tmp_path, monkeypatch):
    from core import owner_auth
    monkeypatch.setattr(owner_auth, 'POLICY_PATH', tmp_path/'owner_auth.json')
    assert owner_auth.policy() == {'enabled':False,'risks':[],'permissions':[]}

def test_voice_install_requires_explicit_components(monkeypatch):
    from core import local_voice_setup
    monkeypatch.setattr(local_voice_setup, 'diagnostics', lambda: {'offline_ready':False})
    result=local_voice_setup.install([])
    assert result['ok'] is False
    assert 'Select at least one' in result['error']

def test_experiment_requires_all_user_supplied_fields(tmp_path, monkeypatch):
    import pytest
    from core import strategy_experiments
    monkeypatch.setattr(strategy_experiments, 'PATH', tmp_path/'experiments.json')
    with pytest.raises(ValueError): strategy_experiments.propose('', 'baseline', 'candidate')
    strategy_experiments.propose('tool_name','my baseline','my candidate')
    row=strategy_experiments.snapshot()['experiments']['tool_name']
    assert row['baseline']=='my baseline' and row['candidate']=='my candidate'
