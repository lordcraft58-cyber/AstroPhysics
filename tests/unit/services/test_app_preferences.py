from __future__ import annotations

from services.app_preferences import AppPreferencesStore


def test_get_returns_default_when_no_file_exists(tmp_path):
    store = AppPreferencesStore(tmp_path / "prefs.json")
    assert store.get("last_master_frame_dir") is None
    assert store.get("last_master_frame_dir", "/fallback") == "/fallback"


def test_set_and_get_roundtrips(tmp_path):
    store = AppPreferencesStore(tmp_path / "prefs.json")
    store.set("last_master_frame_dir", "/data/masters")
    assert store.get("last_master_frame_dir") == "/data/masters"


def test_set_persists_across_new_store_instance_same_path(tmp_path):
    path = tmp_path / "prefs.json"
    AppPreferencesStore(path).set("last_master_frame_dir", "/data/masters")
    assert AppPreferencesStore(path).get("last_master_frame_dir") == "/data/masters"


def test_set_preserves_other_keys(tmp_path):
    path = tmp_path / "prefs.json"
    store = AppPreferencesStore(path)
    store.set("a", "1")
    store.set("b", "2")
    assert store.get("a") == "1"
    assert store.get("b") == "2"
