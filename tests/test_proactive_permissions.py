from datetime import datetime
from core import proactive_permissions as pp


def isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(pp, "PATH", tmp_path / "policy.json")
    monkeypatch.setattr(pp, "USAGE_PATH", tmp_path / "usage.json")


def test_private_context_requires_explicit_scopes(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    memory, monitors, recent = pp.filter_context({"identity": {"name": "Private"}}, ["stocks"], ["hello"])
    assert memory == {} and monitors is None and recent == ["hello"]
    policy = pp.ProactivePolicy(use_memory=True, use_monitors=True)
    assert pp.filter_context({"x": 1}, ["topic"], [], policy)[:2] == ({"x": 1}, ["topic"])


def test_quiet_hours_and_disable_fail_closed(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    assert not pp.allowed(pp.ProactivePolicy(enabled=True), datetime(2026, 1, 1, 2))
    assert not pp.allowed(pp.ProactivePolicy(enabled=False), datetime(2026, 1, 1, 12))
    assert pp.allowed(pp.ProactivePolicy(enabled=True), datetime(2026, 1, 1, 12))


def test_legacy_policy_migrates_and_corrupt_or_future_policy_fails_closed(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    pp.PATH.write_text('{"use_memory": true}', encoding="utf-8")
    assert pp.load().use_memory is True
    pp.PATH.write_text('{broken', encoding="utf-8")
    assert pp.load().enabled is False
    pp.PATH.write_text('{"version": 99, "enabled": true}', encoding="utf-8")
    assert pp.load().enabled is False


def test_minimum_urgency_is_enforced(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    policy = pp.ProactivePolicy(enabled=True, minimum_urgency="high")
    now = datetime(2026, 1, 1, 12)
    assert not pp.allowed(policy, now, urgency="normal")
    assert pp.allowed(policy, now, urgency="high")


def test_daily_budget_is_durable(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    now = datetime(2026, 1, 1, 12)
    policy = pp.ProactivePolicy(enabled=True, daily_limit=2)
    assert pp.allowed(policy, now)
    pp.record(now); assert pp.allowed(policy, now)
    pp.record(now); assert not pp.allowed(policy, now)
