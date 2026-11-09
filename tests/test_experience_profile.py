from core import experience


def test_experience_defaults_are_safe(monkeypatch):
    monkeypatch.setattr(experience, "load_api_keys", lambda: {})
    profile = experience.load_profile()
    assert profile.personality == "command"
    assert profile.language == "clean"
    prompt = experience.prompt_context(profile)
    assert "Use no profanity" in prompt
    assert "Never weaken safety" in prompt


def test_adult_language_stays_bounded():
    profile = experience.ExperienceProfile("inventor", "adult")
    prompt = experience.prompt_context(profile)
    assert "Natural adult profanity is allowed" in prompt
    assert "never use slurs" in prompt
    assert "Never put profanity into an email" in prompt


def test_save_rejects_unknown_values():
    try:
        experience.save_profile(personality="chaos", language="adult")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown personality must fail closed")
