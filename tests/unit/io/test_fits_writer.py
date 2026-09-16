"""Prueba end-to-end real (no simulada): escribe un FITS con `save_fits_image`
y lo vuelve a leer con `astropy.io.fits` directamente, confirmando que los
píxeles y las claves de cabecera relevantes sobreviven el roundtrip."""
from __future__ import annotations

import numpy as np
from astropy.io import fits

from astrophysics_suite.io.fits_writer import save_fits_image


def test_save_fits_image_roundtrips_pixel_values(tmp_path):
    data = np.arange(20, dtype=np.float64).reshape(4, 5) + 100.5
    path = tmp_path / "calibrated_light_001.fits"

    save_fits_image(str(path), data)

    with fits.open(path) as hdul:
        np.testing.assert_allclose(hdul[0].data, data.astype(np.float32), rtol=1e-6)


def test_save_fits_image_copies_serializable_header_keys(tmp_path):
    data = np.full((3, 3), 42.0)
    path = tmp_path / "with_header.fits"
    header = {"OBJECT": "NGC 6960", "EXPTIME": 30.0, "FILTER": "OIII", "GAIN": 1.5}

    save_fits_image(str(path), data, header=header)

    with fits.open(path) as hdul:
        assert hdul[0].header["OBJECT"] == "NGC 6960"
        assert hdul[0].header["EXPTIME"] == 30.0
        assert hdul[0].header["FILTER"] == "OIII"
        assert hdul[0].header["GAIN"] == 1.5


def test_save_fits_image_ignores_unserializable_header_values(tmp_path):
    data = np.full((3, 3), 1.0)
    path = tmp_path / "odd_header.fits"
    header = {"OBJECT": "M31", "WEIRD": [1, 2, 3], "NONETYPE": None}

    save_fits_image(str(path), data, header=header)  # no debe lanzar

    with fits.open(path) as hdul:
        assert hdul[0].header["OBJECT"] == "M31"
        assert "WEIRD" not in hdul[0].header


def test_save_fits_image_creates_missing_parent_directories(tmp_path):
    data = np.full((2, 2), 5.0)
    path = tmp_path / "nested" / "output" / "product.fits"

    save_fits_image(str(path), data)

    assert path.exists()


def test_save_fits_image_overwrite_false_raises_on_existing_file(tmp_path):
    import pytest

    data = np.full((2, 2), 5.0)
    path = tmp_path / "existing.fits"
    save_fits_image(str(path), data)

    with pytest.raises(OSError):
        save_fits_image(str(path), data, overwrite=False)
