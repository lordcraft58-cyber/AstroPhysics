"""Prueba end-to-end (no simulada) de que `io/fits_loader.py` reconoce y
carga un XISF real (formato nativo de PixInsight) exactamente igual que
un FITS -- vía `io/xisf_reader.py` (lector propio, ver su docstring).

El archivo de prueba se construye aquí mismo, byte a byte, con el mismo
formato real ya verificado en `test_xisf_reader.py` contra una
herramienta de desarrollo independiente (nunca una dependencia del
proyecto) -- este archivo se centra en la integración con
`fits_loader.load_image`/`probe_fits_shape`/`build_observation`, no en
recubrir de nuevo la cobertura de códecs de compresión."""
from __future__ import annotations

import struct

import numpy as np
import pytest

from astrophysics_suite.io.fits_loader import build_observation, load_image, probe_fits_shape

XISF_SIGNATURE = b"XISF0100"


def _write_minimal_xisf(path, data: np.ndarray, *, fits_keywords: dict[str, str] | None = None) -> None:
    height, width = data.shape
    sample_format = {np.dtype("uint16"): "UInt16", np.dtype("float32"): "Float32"}[data.dtype]
    raw = data.tobytes()

    # Marcador de ancho FIJO (12 dígitos) para el offset: si se sustituyera
    # por un texto de longitud distinta, cambiaría el tamaño de la propia
    # cabecera XML, y con ello el offset real -- un problema autorreferente
    # que un solo reemplazo no resuelve en general. Con ancho fijo, la
    # sustitución nunca cambia la longitud, así que es exacta de una vez.
    placeholder = "0" * 12
    kw_xml = "".join(f'<FITSKeyword name="{k}" value="{v}" comment="" />' for k, v in (fits_keywords or {}).items())
    xml = (
        f'<?xml version="1.0" encoding="utf8"?>'
        f'<xisf xmlns="http://www.pixinsight.com/xisf" version="1.0">'
        f'<Image id="image" geometry="{width}:{height}:1" colorSpace="Gray" sampleFormat="{sample_format}" '
        f'location="attachment:{placeholder}:{len(raw)}">{kw_xml}</Image></xisf>'
    )
    xml_bytes = xml.encode("utf-8")
    data_offset = 16 + len(xml_bytes)
    real_offset_str = str(data_offset).zfill(len(placeholder))
    assert len(real_offset_str) == len(placeholder), "el offset real necesita más dígitos que el ancho fijo reservado -- amplía el marcador"
    xml_bytes = xml_bytes.replace(placeholder.encode("ascii"), real_offset_str.encode("ascii"), 1)

    with open(path, "wb") as f:
        f.write(XISF_SIGNATURE)
        f.write(struct.pack("<I", len(xml_bytes)))
        f.write(b"\x00\x00\x00\x00")
        f.write(xml_bytes)
        f.write(raw)


def test_load_image_reads_a_real_xisf_file(tmp_path):
    rng = np.random.default_rng(7)
    data = rng.integers(2800, 5000, size=(40, 50), dtype=np.uint16)  # rango ADU realista, como los lights reales
    path = tmp_path / "field.xisf"
    _write_minimal_xisf(path, data, fits_keywords={"OBJECT": "'M 31'", "EXPTIME": "300.0"})

    loaded = load_image(str(path), band="L")

    assert loaded.legacy_image.data.shape == (40, 50)
    assert np.array_equal(np.asarray(loaded.legacy_image.data), data)
    assert loaded.legacy_image.header.get("OBJECT") == "M 31"
    assert loaded.legacy_image.header.get("EXPTIME") == 300.0
    assert loaded.image_ref.sha256 == __import__("hashlib").sha256(path.read_bytes()).hexdigest()


def test_load_image_reads_a_real_xisf_file_with_full_wcs_and_sip(tmp_path):
    """Bug real encontrado probando con un XISF real generado a partir de
    los lights de M 31 reales: sin convertir los valores de FITSKeyword
    al tipo numérico real (en vez de dejarlos como texto), astropy
    escribía tarjetas de TEXTO para CRVAL/CRPIX/CD, y el WCS resultante
    era numéricamente incorrecto (RA/Dec desviadas decenas de grados) en
    vez de simplemente ausente -- peor que no tener WCS en absoluto."""
    rng = np.random.default_rng(8)
    data = rng.integers(2800, 5000, size=(60, 60), dtype=np.uint16)
    path = tmp_path / "field_wcs.xisf"
    # Mismo vocabulario real que un light real de M 31 (ver
    # docs/audit/34-PRUEBAS-CON-FITS-REALES.md) -- valores SIN comillas,
    # como los escribe PixInsight para una tarjeta FITS numérica real.
    _write_minimal_xisf(path, data, fits_keywords={
        "CTYPE1": "'RA---TAN'", "CTYPE2": "'DEC--TAN'",
        "CRVAL1": "10.9131301993", "CRVAL2": "41.2120838282",
        "CRPIX1": "30.0", "CRPIX2": "30.0",
        "CD1_1": "0.000245450853875", "CD1_2": "0.000149121982691",
        "CD2_1": "-0.00014909406634", "CD2_2": "0.000245457021999",
    })

    loaded = load_image(str(path), band="L")

    assert loaded.image_ref.has_wcs is True
    assert loaded.image_ref.pixel_scale_arcsec == pytest.approx(1.0339, rel=1e-2)
    # CRPIX es 1-indexado (convención FITS); pixel_to_world usa el origen
    # 0-indexado de astropy.wcs (`all_pix2world(..., 0)`) -- el píxel que
    # corresponde exactamente a CRVAL es CRPIX - 1 en esa convención.
    ra, dec = loaded.legacy_image.pixel_to_world(29.0, 29.0)
    assert float(ra) == pytest.approx(10.9131301993, abs=1e-4)
    assert float(dec) == pytest.approx(41.2120838282, abs=1e-4)


def test_probe_fits_shape_reads_a_real_xisf_without_decompressing(tmp_path):
    data = np.zeros((22, 33), dtype=np.uint16)
    path = tmp_path / "shape_only.xisf"
    _write_minimal_xisf(path, data)
    assert probe_fits_shape(str(path)) == (22, 33)


def test_build_observation_mixes_fits_and_xisf_in_the_same_observation(tmp_path):
    from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d

    fits_data = np.full((16, 16), 50.0, dtype=np.float32)
    fits_path = tmp_path / "target_OIII.fits"
    _write_minimal_fits_2d(fits_path, fits_data, pixel_scale_arcsec=0.9)

    xisf_data = np.full((16, 16), 4000, dtype=np.uint16)
    xisf_path = tmp_path / "target_HA.xisf"
    _write_minimal_xisf(xisf_path, xisf_data)

    observation, loaded = build_observation(
        [(str(fits_path), "OIII"), (str(xisf_path), "HA")],
        observation_id="OBS-XISF-MIX-0001", target_name="Campo mixto FITS+XISF",
    )

    assert len(observation.images) == 2
    assert len(loaded) == 2
    bands = {ref.band for ref in observation.images}
    assert bands == {"OIII", "HA"}
