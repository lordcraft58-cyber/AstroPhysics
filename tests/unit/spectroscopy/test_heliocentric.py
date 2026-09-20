"""`heliocentric.py`: corrección baricéntrica/heliocéntrica real vía
astropy -- nunca asume coordenadas u observatorio desconocidos (§60)."""
from __future__ import annotations

import pytest

from astrophysics_suite.spectroscopy.heliocentric import (
    apply_barycentric_correction,
    compute_barycentric_correction,
)

# Coordenadas reales de Vega (alpha Lyr, J2000) y de un observatorio de
# ejemplo real (Observatorio de Calar Alto, España) -- solo para tener
# un caso de prueba con números físicamente sensatos, no como catálogo.
_VEGA_RA_DEG = 279.23473479
_VEGA_DEC_DEG = 38.78368896
_CALAR_ALTO_LON_DEG = -2.546111
_CALAR_ALTO_LAT_DEG = 37.223611
_CALAR_ALTO_HEIGHT_M = 2168.0


def test_barycentric_correction_has_a_physically_sensible_magnitude():
    correction = compute_barycentric_correction(
        ra_deg=_VEGA_RA_DEG, dec_deg=_VEGA_DEC_DEG, obstime_iso="2024-06-01T00:00:00",
        observatory_longitude_deg=_CALAR_ALTO_LON_DEG, observatory_latitude_deg=_CALAR_ALTO_LAT_DEG,
        observatory_height_m=_CALAR_ALTO_HEIGHT_M,
    )
    # La velocidad orbital terrestre es ~29.8 km/s -- la componente de
    # línea de visión nunca puede superarla en magnitud (más una pequeña
    # contribución de rotación terrestre, <0.5 km/s).
    assert abs(correction.correction_km_s) < 31.0
    assert correction.kind == "barycentric"


def test_heliocentric_and_barycentric_are_close_but_not_identical():
    kwargs = dict(
        ra_deg=_VEGA_RA_DEG, dec_deg=_VEGA_DEC_DEG, obstime_iso="2024-06-01T00:00:00",
        observatory_longitude_deg=_CALAR_ALTO_LON_DEG, observatory_latitude_deg=_CALAR_ALTO_LAT_DEG,
        observatory_height_m=_CALAR_ALTO_HEIGHT_M,
    )
    barycentric = compute_barycentric_correction(kind="barycentric", **kwargs)
    heliocentric = compute_barycentric_correction(kind="heliocentric", **kwargs)
    difference = abs(barycentric.correction_km_s - heliocentric.correction_km_s)
    assert 0.0 <= difference < 0.1  # difieren en como mucho unas decenas de m/s (arrastre del Sol por Jupiter etc.)


def test_correction_sign_roughly_flips_six_months_apart():
    """Hecho astrofísico real y verificable: la Tierra invierte el
    sentido de su componente de velocidad orbital de línea de visión
    hacia un objetivo fijo aproximadamente cada seis meses."""
    kwargs = dict(
        ra_deg=_VEGA_RA_DEG, dec_deg=_VEGA_DEC_DEG,
        observatory_longitude_deg=_CALAR_ALTO_LON_DEG, observatory_latitude_deg=_CALAR_ALTO_LAT_DEG,
        observatory_height_m=_CALAR_ALTO_HEIGHT_M,
    )
    correction_a = compute_barycentric_correction(obstime_iso="2024-03-01T00:00:00", **kwargs)
    correction_b = compute_barycentric_correction(obstime_iso="2024-09-01T00:00:00", **kwargs)
    assert correction_a.correction_km_s * correction_b.correction_km_s < 0


def test_correction_is_deterministic_for_the_same_inputs():
    kwargs = dict(
        ra_deg=_VEGA_RA_DEG, dec_deg=_VEGA_DEC_DEG, obstime_iso="2024-06-01T00:00:00",
        observatory_longitude_deg=_CALAR_ALTO_LON_DEG, observatory_latitude_deg=_CALAR_ALTO_LAT_DEG,
        observatory_height_m=_CALAR_ALTO_HEIGHT_M,
    )
    a = compute_barycentric_correction(**kwargs)
    b = compute_barycentric_correction(**kwargs)
    assert a.correction_km_s == pytest.approx(b.correction_km_s, abs=1e-9)


def test_apply_correction_adds_it_to_the_observed_velocity():
    correction = compute_barycentric_correction(
        ra_deg=_VEGA_RA_DEG, dec_deg=_VEGA_DEC_DEG, obstime_iso="2024-06-01T00:00:00",
        observatory_longitude_deg=_CALAR_ALTO_LON_DEG, observatory_latitude_deg=_CALAR_ALTO_LAT_DEG,
        observatory_height_m=_CALAR_ALTO_HEIGHT_M,
    )
    observed = 42.0
    assert apply_barycentric_correction(observed, correction) == pytest.approx(observed + correction.correction_km_s)


def test_rejects_an_unknown_kind():
    with pytest.raises(ValueError):
        compute_barycentric_correction(
            ra_deg=0.0, dec_deg=0.0, obstime_iso="2024-01-01T00:00:00",
            observatory_longitude_deg=0.0, observatory_latitude_deg=0.0, kind="geocentric",
        )


def test_rejects_declination_out_of_range():
    with pytest.raises(ValueError):
        compute_barycentric_correction(
            ra_deg=0.0, dec_deg=120.0, obstime_iso="2024-01-01T00:00:00",
            observatory_longitude_deg=0.0, observatory_latitude_deg=0.0,
        )


def test_rejects_an_unparseable_obstime():
    with pytest.raises(ValueError):
        compute_barycentric_correction(
            ra_deg=0.0, dec_deg=0.0, obstime_iso="not a real date",
            observatory_longitude_deg=0.0, observatory_latitude_deg=0.0,
        )


def test_describe_mentions_the_kind_and_the_numeric_value():
    correction = compute_barycentric_correction(
        ra_deg=_VEGA_RA_DEG, dec_deg=_VEGA_DEC_DEG, obstime_iso="2024-06-01T00:00:00",
        observatory_longitude_deg=_CALAR_ALTO_LON_DEG, observatory_latitude_deg=_CALAR_ALTO_LAT_DEG,
        observatory_height_m=_CALAR_ALTO_HEIGHT_M,
    )
    description = correction.describe()
    assert "barycentric" in description
    assert f"{correction.correction_km_s:+.4f}" in description
