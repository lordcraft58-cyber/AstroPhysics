"""El lector FITS migrado debe producir EXACTAMENTE lo mismo que el del
monolito legacy sobre archivos reales.

Esta es la prueba que autoriza a quitar la dependencia del legacy: no
basta con que el lector nuevo funcione, tiene que coincidir campo a
campo con el que lleva usándose todo el proyecto -- píxeles incluidos,
byte a byte.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from astrophysics_suite.io.fits_reader import AmbiguousCubeError, load_fits, sha256_file
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import load_fits as legacy_load_fits
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import sha256_file as legacy_sha256_file

_COMPARED_FIELDS = (
    "pixel_scale_arcsec", "bunit", "exptime", "filter_name", "hdu_index",
    "wcs_source", "original_ndim", "original_shape", "selected_plane", "cube_plane_is_explicit",
)


@pytest.fixture
def real_fits_dir() -> Path:
    """Carpeta con FITS reales del usuario, indicada por la variable de
    entorno `ASTROPHYSICS_REAL_FITS_DIR`. Sin ella la prueba se salta: los
    archivos reales pesan demasiado para versionarlos, pero cuando están
    son el contraste que de verdad vale."""
    raw = os.environ.get("ASTROPHYSICS_REAL_FITS_DIR")
    if not raw:
        pytest.skip("ASTROPHYSICS_REAL_FITS_DIR no está definida (FITS reales no disponibles en este entorno)")
    directory = Path(raw)
    if not directory.is_dir():
        pytest.skip(f"ASTROPHYSICS_REAL_FITS_DIR no apunta a una carpeta real: {directory}")
    return directory


def _write_fits(path, data, header_cards: dict | None = None):
    header = fits.Header()
    for key, value in (header_cards or {}).items():
        header[key] = value
    fits.PrimaryHDU(data=data, header=header).writeto(path, overwrite=True)
    return str(path)


def _assert_same_image(new, legacy):
    np.testing.assert_array_equal(np.asarray(new.data), np.asarray(legacy.data))
    assert new.data.dtype == legacy.data.dtype
    for name in _COMPARED_FIELDS:
        assert getattr(new, name) == getattr(legacy, name), f"campo distinto: {name}"
    assert (new.wcs is None) == (legacy.wcs is None)
    assert set(new.header) == set(legacy.header)


def test_matches_legacy_on_a_plain_2d_image(tmp_path):
    path = _write_fits(tmp_path / "plain.fits", np.arange(48, dtype=np.float32).reshape(6, 8), {"EXPTIME": 300.0, "FILTER": "Ha", "BUNIT": "adu"})
    _assert_same_image(load_fits(path), legacy_load_fits(path))


def test_matches_legacy_on_a_real_wcs_image(tmp_path):
    header = {
        "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
        "CRVAL1": 10.684708, "CRVAL2": 41.26875,
        "CRPIX1": 16.0, "CRPIX2": 16.0,
        "CD1_1": -0.000287, "CD1_2": 0.0, "CD2_1": 0.0, "CD2_2": 0.000287,
    }
    path = _write_fits(tmp_path / "wcs.fits", np.random.default_rng(3).normal(100, 5, (32, 32)).astype(np.float32), header)
    new, legacy = load_fits(path), legacy_load_fits(path)
    _assert_same_image(new, legacy)
    assert new.wcs_source == "WCS del propio FITS"
    assert new.pixel_scale_arcsec == pytest.approx(legacy.pixel_scale_arcsec, rel=1e-12)

    # y la conversión píxel -> cielo coincide de verdad, no solo el campo
    for x, y in ((0.0, 0.0), (16.0, 16.0), (31.0, 5.0)):
        np.testing.assert_allclose(new.pixel_to_world(x, y), legacy.pixel_to_world(x, y), rtol=0, atol=1e-12)


def test_matches_legacy_on_uint16_with_bzero_disabling_memmap(tmp_path):
    # el caso real de una cámara CMOS de 16 bits sin signo (la del usuario)
    data = (np.arange(400, dtype=np.uint16).reshape(20, 20))
    path = _write_fits(tmp_path / "u16.fits", data)
    with fits.open(path, mode="update") as hdul:
        hdul[0].header["BZERO"] = 32768
    _assert_same_image(load_fits(path), legacy_load_fits(path))


def test_matches_legacy_on_cube_plane_selection(tmp_path):
    cube = np.arange(3 * 5 * 4, dtype=np.float32).reshape(3, 5, 4)
    path = _write_fits(tmp_path / "cube.fits", cube)
    for plane in (0, 1, 2):
        _assert_same_image(load_fits(path, plane=plane), legacy_load_fits(path, plane=plane))


def test_matches_legacy_raising_on_an_ambiguous_cube(tmp_path):
    from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import AmbiguousCubeError as LegacyAmbiguousCubeError

    path = _write_fits(tmp_path / "ambiguous.fits", np.zeros((3, 5, 4), dtype=np.float32))
    with pytest.raises(AmbiguousCubeError):
        load_fits(path)
    with pytest.raises(LegacyAmbiguousCubeError):
        legacy_load_fits(path)

    # Son dos clases distintas a propósito (la nueva no hereda del
    # monolito: ese es justo el punto de la migración), pero AMBAS siguen
    # siendo ValueError, así que cualquier `except ValueError` que ya
    # existiera en el proyecto sigue atrapándolas igual.
    assert AmbiguousCubeError is not LegacyAmbiguousCubeError
    assert issubclass(AmbiguousCubeError, ValueError)
    assert issubclass(LegacyAmbiguousCubeError, ValueError)


def test_matches_legacy_marking_a_non_explicit_quicklook_plane(tmp_path):
    path = _write_fits(tmp_path / "quicklook.fits", np.zeros((2, 5, 4), dtype=np.float32))
    new, legacy = load_fits(path, allow_first_plane=True), legacy_load_fits(path, allow_first_plane=True)
    _assert_same_image(new, legacy)
    assert new.cube_plane_is_explicit is False


def test_sha256_matches_legacy(tmp_path):
    path = _write_fits(tmp_path / "hash.fits", np.ones((4, 4), dtype=np.float32))
    assert sha256_file(path) == legacy_sha256_file(path)


@pytest.mark.parametrize(
    "name", ["Light_M31_300s_0001.fit", "dbxtract_HA_registered.fit", "dbxtract_OIII.fit"]
)
def test_matches_legacy_on_the_users_real_m31_files(real_fits_dir, name):
    """Los archivos reales del usuario -- el contraste que de verdad
    importa: 3008x3008 uint16 de una ASI533MC Pro con BZERO."""
    path = str(real_fits_dir / name)
    _assert_same_image(load_fits(path), legacy_load_fits(path))
