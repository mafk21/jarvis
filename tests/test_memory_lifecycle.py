import json
from datetime import date
from memory import memory_manager as mm


def seed(monkeypatch, tmp_path):
    path = tmp_path / "long_term.json"
    monkeypatch.setattr(mm, "MEMORY_PATH", path)
    path.write_text(json.dumps({
        "identity": {}, "preferences": {}, "projects": {
            "apollo": {"value": "Build Apollo", "source": "conversation", "updated": date.today().isoformat()}
        }, "relationships": {}, "wishes": {}, "notes": {}
    }), encoding="utf-8")
    return path


def test_memory_lifecycle_is_visible_and_user_controlled(monkeypatch, tmp_path):
    seed(monkeypatch, tmp_path)
    assert mm.all_entries_for_ui()[0]["lifecycle"] == "recent"
    assert mm.set_memory_lifecycle("projects", "apollo", "core") == "core"
    row = mm.all_entries_for_ui()[0]
    assert row["lifecycle"] == "core" and row["pinned"] is True


def test_archived_memory_is_stored_but_not_prompted_or_recalled(monkeypatch, tmp_path):
    seed(monkeypatch, tmp_path)
    mm.set_memory_lifecycle("projects", "apollo", "archived")
    assert "Build Apollo" not in mm.format_memory_for_prompt(mm.load_memory())
    assert "Build Apollo" not in mm.search_memory("apollo")
    assert mm.all_entries_for_ui()[0]["value"] == "Build Apollo"


def test_memory_edit_records_user_source(monkeypatch, tmp_path):
    path = seed(monkeypatch, tmp_path)
    assert mm.edit_memory("projects", "apollo", "Ship Apollo") == "Ship Apollo"
    entry = json.loads(path.read_text(encoding="utf-8"))["projects"]["apollo"]
    assert entry["source"] == "user_edit"
    assert entry["confidence"] == 1.0


def test_invalid_lifecycle_fails_closed(monkeypatch, tmp_path):
    seed(monkeypatch, tmp_path)
    try:
        mm.set_memory_lifecycle("projects", "apollo", "deleted")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid lifecycle accepted")
