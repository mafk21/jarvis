from core import session_privacy, vision_policy


def isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(vision_policy, "POLICY_PATH", tmp_path / "policy.json")
    monkeypatch.setattr(vision_policy, "AUDIT_PATH", tmp_path / "history.jsonl")


def teardown_function():
    session_privacy.set_enabled(False)


def test_sensitive_apps_are_blocked_by_default(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(vision_policy, "active_application", lambda: "Bitwarden.exe | Vault")
    allowed, reason = vision_policy.authorize("screen")
    assert not allowed
    assert "protected rule" in reason
    row = vision_policy.history()[0]
    assert row["allowed"] is False
    assert row["content_stored"] is False


def test_custom_exclusion_is_case_insensitive(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    vision_policy.save_policy(
        deny_all=False, block_sensitive_defaults=False, blocked_apps=["Medical Portal"]
    )
    monkeypatch.setattr(vision_policy, "active_application", lambda: "Browser | MEDICAL PORTAL")
    assert vision_policy.authorize("screen_region")[0] is False


def test_allowed_capture_audits_provider_disclosure(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(vision_policy, "active_application", lambda: "notepad.exe | Notes")
    assert vision_policy.authorize("screen")[0] is True
    row = vision_policy.history()[0]
    assert row["cloud_possible"] is True
    assert row["content_stored"] is False


def test_corrupt_policy_fails_closed(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    vision_policy.POLICY_PATH.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(vision_policy, "active_application", lambda: "notepad.exe")
    assert vision_policy.authorize("screen")[0] is False


def test_incognito_always_wins(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(vision_policy, "active_application", lambda: "notepad.exe")
    session_privacy.set_enabled(True)
    allowed, reason = vision_policy.authorize("camera")
    assert not allowed and "Incognito" in reason
