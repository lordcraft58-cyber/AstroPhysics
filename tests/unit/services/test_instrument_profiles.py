from __future__ import annotations

from services.instrument_profiles import InstrumentProfile, InstrumentProfileStore


def test_store_starts_empty_when_no_file_exists(tmp_path):
    store = InstrumentProfileStore(tmp_path / "profiles.json")
    assert store.load_all() == {}


def test_save_and_load_roundtrips_profile(tmp_path):
    store = InstrumentProfileStore(tmp_path / "profiles.json")
    profile = InstrumentProfile(
        name="ZWO ASI2600MM",
        gain_e_per_adu=0.8,
        read_noise_e=3.5,
        overscan_row_start=0,
        overscan_row_end=10,
        overscan_col_start=None,
        overscan_col_end=None,
    )

    store.save(profile)
    loaded = store.load_all()

    assert loaded == {"ZWO ASI2600MM": profile}


def test_save_persists_across_new_store_instance_same_path(tmp_path):
    path = tmp_path / "profiles.json"
    InstrumentProfileStore(path).save(InstrumentProfile(name="Cam1", gain_e_per_adu=1.0, read_noise_e=5.0))

    reloaded = InstrumentProfileStore(path).load_all()

    assert "Cam1" in reloaded
    assert reloaded["Cam1"].gain_e_per_adu == 1.0


def test_save_multiple_profiles_keeps_all():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        store = InstrumentProfileStore(Path(tmp) / "profiles.json")
        store.save(InstrumentProfile(name="A", gain_e_per_adu=1.0, read_noise_e=5.0))
        store.save(InstrumentProfile(name="B", gain_e_per_adu=2.0, read_noise_e=6.0))

        profiles = store.load_all()
        assert set(profiles) == {"A", "B"}


def test_delete_removes_profile(tmp_path):
    store = InstrumentProfileStore(tmp_path / "profiles.json")
    store.save(InstrumentProfile(name="ToDelete", gain_e_per_adu=1.0, read_noise_e=5.0))
    assert "ToDelete" in store.load_all()

    store.delete("ToDelete")

    assert "ToDelete" not in store.load_all()


def test_delete_missing_profile_is_a_no_op(tmp_path):
    store = InstrumentProfileStore(tmp_path / "profiles.json")
    store.delete("DoesNotExist")  # no debe lanzar
    assert store.load_all() == {}


def test_save_overwrites_profile_with_same_name(tmp_path):
    store = InstrumentProfileStore(tmp_path / "profiles.json")
    store.save(InstrumentProfile(name="Cam", gain_e_per_adu=1.0, read_noise_e=5.0))
    store.save(InstrumentProfile(name="Cam", gain_e_per_adu=2.0, read_noise_e=7.0))

    loaded = store.load_all()

    assert len(loaded) == 1
    assert loaded["Cam"].gain_e_per_adu == 2.0
    assert loaded["Cam"].read_noise_e == 7.0
