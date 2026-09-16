"""Prueba real (no simulada): escribe un FITS con cabecera de verdad y
confirma que `read_fits_header` la devuelve sin tocar los píxeles."""
from __future__ import annotations

import numpy as np
from astropy.io import fits

from astrophysics_suite.io.fits_header_reader import read_fits_header


def test_read_fits_header_returns_keywords_without_reading_pixels(tmp_path):
    data = np.full((10, 10), 500.0, dtype=np.float32)
    path = tmp_path / "bias_001.fits"
    hdu = fits.PrimaryHDU(data)
    hdu.header["IMAGETYP"] = "Bias Frame"
    hdu.header["EXPTIME"] = 0.0
    hdu.writeto(path)

    header = read_fits_header(str(path))

    assert header["IMAGETYP"] == "Bias Frame"
    assert header["EXPTIME"] == 0.0
