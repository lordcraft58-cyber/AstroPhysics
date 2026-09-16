"""Prueba end-to-end (no simulada) de io/fits_loader.py: escribe un FITS
real y lo carga a través del wrapper nuevo, apoyado en `load_fits`/
`sha256_file` heredados."""
from __future__ import annotations

import hashlib

import numpy as np
import pytest

from astrophysics_suite.io.fits_loader import build_observation, load_image
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d


def test_load_image_builds_real_image_ref(tmp_path):
    data = np.full((32, 32), 100.0, dtype=np.float32)
    path = tmp_path / "target_OIII.fits"
    _write_minimal_fits_2d(path, data, pixel_scale_arcsec=1.2)

    loaded = load_image(str(path), band="OIII")

    assert loaded.image_ref.band == "OIII"
    assert loaded.image_ref.role == "science"
    assert loaded.image_ref.pixel_scale_arcsec == pytest.approx(1.2, rel=1e-3)
    assert loaded.image_ref.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert loaded.legacy_image.data.shape == (32, 32)


def test_build_observation_from_real_files(tmp_path):
    oiii = np.full((16, 16), 50.0, dtype=np.float32)
    ha = np.full((16, 16), 60.0, dtype=np.float32)
    oiii_path = tmp_path / "target_OIII.fits"
    ha_path = tmp_path / "target_HALPHA.fits"
    _write_minimal_fits_2d(oiii_path, oiii, pixel_scale_arcsec=0.9)
    _write_minimal_fits_2d(ha_path, ha, pixel_scale_arcsec=0.9)

    observation, loaded = build_observation(
        [(str(oiii_path), "OIII"), (str(ha_path), "HA")],
        observation_id="OBS-TEST-0001",
        target_name="NGC 6960",
    )

    assert observation.observation_id == "OBS-TEST-0001"
    assert {im.band for im in observation.images} == {"OIII", "HA"}
    assert len(loaded) == 2
    assert loaded[str(oiii_path)].legacy_image.data.shape == (16, 16)

    # Roundtrip real: lo que se serializa se puede reconstruir idéntico.
    from astrophysics_suite.models.observation import Observation

    restored = Observation.from_dict(observation.to_dict())
    assert restored == observation


def test_load_image_handles_bzero_bscale_fits_without_memmap_error(tmp_path):
    """Bug real reportado en uso: astropy no puede memory-mapear un HDU cuyo
    header declara BZERO/BSCALE/BLANK -- la convención estándar con la que
    casi cualquier cámara CCD/CMOS de 16 bits guarda datos sin signo -- y solo
    lo descubre al acceder a `.data`, no al abrir el archivo
    ("Cannot load a memory-mapped image: BZERO/BSCALE/BLANK header keywords
    present. Set memmap=False."). `load_fits` debe manejarlo de forma
    transparente en vez de propagar el ValueError."""
    from astropy.io import fits

    raw_values = (np.arange(400, dtype=np.uint16).reshape(20, 20) + 1000)
    path = tmp_path / "camera_16bit_OIII.fits"
    fits.PrimaryHDU(raw_values).writeto(path)

    loaded = load_image(str(path), band="OIII")  # no debe lanzar ValueError de memmap

    np.testing.assert_array_equal(loaded.legacy_image.data.astype(np.uint16), raw_values)
