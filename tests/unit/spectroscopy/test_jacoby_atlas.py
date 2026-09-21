"""`jacoby_atlas.py`: lee el atlas real Jacoby, Hunter & Christian (1984)
incluido en `spectroscopy/data/jacoby_atlas/` -- formato de columnas
fijas heredado del propio `.INX`, y los espectros reales de dos columnas
que ya lee `import_ascii_spectrum`."""
from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.jacoby_atlas import (
    JacobyAtlasEntry,
    bundled_atlas_paths,
    load_jacoby_atlas_index,
    load_jacoby_atlas_spectrum,
)


def _write_index(path, lines):
    path.write_text("\r\n".join(lines) + "\r\n\x1a")
    return path


def test_parses_a_simple_line_with_a_space_separated_luminosity_class(tmp_path):
    index_path = _write_index(tmp_path / "TEST.INX", ["   1 HD 242908  O5    V -.30 -1.11     1"])
    entries = load_jacoby_atlas_index(index_path)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.index == 1
    assert entry.name == "HD 242908"
    assert entry.spectral_type == "O5"
    assert entry.luminosity_class == "V"
    assert entry.color1 == pytest.approx(-0.30)
    assert entry.color2 == pytest.approx(-1.11)


def test_parses_a_line_with_luminosity_class_fused_to_the_spectral_type(tmp_path):
    # Hallazgo real: sin separador entre tipo y luminosidad ("O6.5III"),
    # un split() ingenuo rompe el nombre y el tipo espectral -- esto fija
    # el comportamiento correcto por columna fija.
    index_path = _write_index(tmp_path / "TEST.INX", ["  62 HD 227018  O6.5III -.35 -1.14 21473"])
    entry = load_jacoby_atlas_index(index_path)[0]
    assert entry.name == "HD 227018"
    assert entry.spectral_type == "O6.5"
    assert entry.luminosity_class == "III"


def test_parses_a_name_with_a_plus_sign_and_internal_space(tmp_path):
    index_path = _write_index(tmp_path / "TEST.INX", [" 161 BD+51 710  B5    I -.06 -0.74 56321"])
    entry = load_jacoby_atlas_index(index_path)[0]
    assert entry.name == "BD+51 710"
    assert entry.spectral_type == "B5"
    assert entry.luminosity_class == "I"


def test_label_combines_spectral_type_luminosity_and_name():
    entry = JacobyAtlasEntry(index=1, name="HD 242908", spectral_type="O5", luminosity_class="V", color1=-0.3, color2=-1.11)
    assert entry.label == "O5 V -- HD 242908"


def test_load_jacoby_atlas_index_skips_blank_lines_and_the_dos_eof_marker(tmp_path):
    index_path = tmp_path / "TEST.INX"
    index_path.write_text("   1 HD 242908  O5    V -.30 -1.11     1\r\n\r\n\x1a")
    entries = load_jacoby_atlas_index(index_path)
    assert len(entries) == 1


def test_load_jacoby_atlas_index_rejects_a_file_with_no_real_entries(tmp_path):
    index_path = tmp_path / "empty.INX"
    index_path.write_text("\x1a")
    with pytest.raises(ValueError, match="ninguna entrada real"):
        load_jacoby_atlas_index(index_path)


def test_load_jacoby_atlas_spectrum_reads_the_real_two_column_file(tmp_path):
    spectra_dir = tmp_path
    (spectra_dir / "A0000001.SP").write_text("3510.00 0.5\n3511.40 0.6\n3512.80 0.7\n")
    entry = JacobyAtlasEntry(index=1, name="TEST", spectral_type="O5", luminosity_class="V", color1=0.0, color2=0.0)
    wavelength, flux = load_jacoby_atlas_spectrum(entry, spectra_dir)
    np.testing.assert_allclose(wavelength, [3510.00, 3511.40, 3512.80])
    np.testing.assert_allclose(flux, [0.5, 0.6, 0.7])


def test_load_jacoby_atlas_spectrum_raises_honestly_when_the_file_is_missing(tmp_path):
    entry = JacobyAtlasEntry(index=999, name="TEST", spectral_type="O5", luminosity_class="V", color1=0.0, color2=0.0)
    with pytest.raises(ValueError, match="falta el espectro real"):
        load_jacoby_atlas_spectrum(entry, tmp_path)


# ---------------------------------------------------------------- atlas real incluido

def test_bundled_atlas_has_all_161_real_entries_with_a_matching_spectrum_file():
    inx_path, spectra_dir = bundled_atlas_paths()
    entries = load_jacoby_atlas_index(inx_path)
    assert len(entries) == 161
    assert len(set(e.index for e in entries)) == 161  # todos los índices distintos

    # muestreo real: primera (O5 V) y última (B5 I) entrada del atlas real
    assert entries[0].spectral_type == "O5"
    assert entries[0].luminosity_class == "V"
    assert entries[-1].spectral_type == "B5"
    assert entries[-1].luminosity_class == "I"

    for entry in entries:
        wavelength, flux = load_jacoby_atlas_spectrum(entry, spectra_dir)
        assert wavelength.size > 100
        assert np.all(np.diff(wavelength) > 0)
        assert flux.size == wavelength.size


def test_bundled_atlas_covers_the_real_mk_sequence_from_o_to_m():
    inx_path, _spectra_dir = bundled_atlas_paths()
    entries = load_jacoby_atlas_index(inx_path)
    first_letters = {e.spectral_type[0] for e in entries}
    assert first_letters >= {"O", "B", "A", "F", "G", "K", "M"}


def test_bundled_atlas_g6_v_entry_matches_the_expected_real_range():
    inx_path, spectra_dir = bundled_atlas_paths()
    entries = load_jacoby_atlas_index(inx_path)
    g6v = [e for e in entries if e.spectral_type == "G6" and e.luminosity_class == "V"]
    assert len(g6v) == 1
    wavelength, _flux = load_jacoby_atlas_spectrum(g6v[0], spectra_dir)
    assert wavelength.min() == pytest.approx(3510.0, abs=1.0)
    assert wavelength.max() == pytest.approx(7427.0, abs=5.0)
