from core import proactive_permissions as pp
from core import session_privacy


def teardown_function():
    session_privacy.set_enabled(False)


def test_incognito_is_process_local_and_off_by_default():
    assert session_privacy.enabled() is False
    assert session_privacy.status()["temporary"] is True


def test_incognito_pauses_proactive_help():
    session_privacy.set_enabled(True)
    assert pp.allowed(pp.ProactivePolicy(enabled=True)) is False


def test_incognito_status_names_paused_capabilities():
    session_privacy.set_enabled(True)
    paused = " ".join(session_privacy.status()["pauses"])
    for expected in ("memories", "chat", "screen", "proactive"):
        assert expected in paused
