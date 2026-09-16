"""Prueba end-to-end (no simulada) de io/fits_loader.py: escribe un FITS
real y lo carga a través del wrapper nuevo, apoyado en `load_fits`/
`sha256_file` heredados."""
from __future__ import annotations

import hashlib
from pathlib import Path

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
    # `loaded` se indexa por `ImageRef.path` (la ruta ya resuelta), que es
    # exactamente como la busca `run_generic_discovery` -- nunca por la
    # ruta cruda que recibió esta función, que puede ser un texto distinto
    # aunque señale al mismo archivo (ver test de la ruta relativa abajo).
    for image_ref in observation.images:
        assert loaded[image_ref.path].image_ref == image_ref
    oiii_loaded = next(li for li in loaded.values() if li.image_ref.band == "OIII")
    assert oiii_loaded.legacy_image.data.shape == (16, 16)

    # Roundtrip real: lo que se serializa se puede reconstruir idéntico.
    from astrophysics_suite.models.observation import Observation

    restored = Observation.from_dict(observation.to_dict())
    assert restored == observation


def test_build_observation_indexes_loaded_images_by_resolved_path_not_raw_input(tmp_path, monkeypatch):
    """Regresión de un bug real reportado en uso: si el llamador pasa una
    ruta cuyo texto difiere de `Path(ruta).resolve()` (una ruta relativa,
    o en Windows una ruta con '/' devuelta por `QFileDialog` mientras
    `Path.resolve()` normaliza a '\\'), `loaded_images[image_ref.path]`
    (la búsqueda real que hace `run_generic_discovery`) debía funcionar
    siempre -- antes del fix lanzaba `KeyError` porque el diccionario se
    indexaba por la ruta cruda, no por la resuelta."""
    data = np.full((16, 16), 50.0, dtype=np.float32)
    path = tmp_path / "target_OIII.fits"
    _write_minimal_fits_2d(path, data, pixel_scale_arcsec=0.9)

    monkeypatch.chdir(tmp_path)
    relative_path = path.name
    assert relative_path != str(Path(relative_path).resolve()), "la ruta relativa debe diferir de su forma resuelta para que el test reproduzca el bug real"

    observation, loaded = build_observation(
        [(relative_path, "OIII")],
        observation_id="OBS-TEST-0002",
        target_name="Campo con ruta relativa",
    )

    assert len(observation.images) == 1
    image_ref = observation.images[0]
    assert image_ref.path in loaded  # la búsqueda que hace run_generic_discovery
    assert loaded[image_ref.path].legacy_image.data.shape == (16, 16)


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
