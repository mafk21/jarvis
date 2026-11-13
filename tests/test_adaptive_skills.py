from pathlib import Path

from core.skill_loader import discover_skills


def test_every_default_skill_uses_same_safe_adaptation_lifecycle():
    registry = discover_skills(Path("skills"), logger=lambda _line: None)
    assert len(registry) == 12
    for name in registry.names():
        body = registry.read(name)
        assert f'`skill="{name}"`' in body
        assert '`adaptation_inspect`' in body
        assert '`adaptation_outcome`' in body
        assert '`adaptation_feedback`' in body
        assert "silence is never feedback" in body
        assert "learned behavior is never permission" in body
        assert "continue with this playbook unchanged" in body
