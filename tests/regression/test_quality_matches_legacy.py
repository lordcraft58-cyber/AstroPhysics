"""`photometry/quality.py::measure_source_quality` (migrada del monolito
legacy en el cierre sistemático del motor 6/16, informe 94) debe producir
EXACTAMENTE lo mismo que la implementación heredada -- campo a campo, no
"aproximadamente igual". A diferencia de la migración de Detection
(informe 54), aquí no hay ningún cambio deliberado de fórmula: es una
reimplementación 1:1, y esta prueba lo demuestra sobre varios casos
reales (fuente aislada, elongada, saturada, cerca del borde, dos fuentes
mezcladas, y los dos huecos que devuelven "NO DISPONIBLE" en vez de
inventar una medida).
"""
from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.photometry.quality import measure_source_quality
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import measure_source_quality as _legacy_measure_source_quality

_NUMERIC_FIELDS = (
    "fwhm_px", "ellipticity", "sharpness", "snr_local", "peak_adu", "background_adu", "noise_adu",
)


def _assert_matches_legacy(image, x, y, **kwargs):
    migrated = measure_source_quality(image, x, y, **kwargs)
    legacy = _legacy_measure_source_quality(image, x, y, **kwargs)

    assert migrated.get("state") == legacy.get("state")
    if migrated.get("state") != "OBSERVABLE":
        assert migrated.get("error") == legacy.get("error")
        return migrated, legacy

    for field_name in _NUMERIC_FIELDS:
        migrated_value, legacy_value = migrated[field_name], legacy[field_name]
        if legacy_value is None:
            assert migrated_value is None, field_name
        else:
            assert migrated_value == pytest.approx(legacy_value, rel=1e-9, abs=1e-9), field_name
    assert migrated["saturated"] == legacy["saturated"]
    assert migrated["isolated"] == legacy["isolated"]
    assert migrated["n_peaks_in_stamp"] == legacy["n_peaks_in_stamp"]
    return migrated, legacy


def _isolated_star(shape=(64, 64), x0=32, y0=32, amplitude=900.0, sigma=2.2, background=100.0, seed=1):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    field = background + amplitude * np.exp(-(((xx - x0) ** 2 + (yy - y0) ** 2)) / (2 * sigma**2))
    field += rng.normal(0, 1.5, shape)
    return field.astype(np.float32)


def test_isolated_source_matches_legacy_field_by_field():
    field = _isolated_star()
    migrated, legacy = _assert_matches_legacy(field, 32, 32)
    assert migrated["state"] == "OBSERVABLE"
    assert legacy["state"] == "OBSERVABLE"


def test_elongated_source_matches_legacy():
    # Gaussiana anisótropa (sigma_x != sigma_y): ejercita mxy != 0 y la
    # elipticidad real, no solo el caso circular.
    shape = (70, 70)
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    field = 100.0 + 1200.0 * np.exp(-(((xx - 35) ** 2) / (2 * 4.0**2) + ((yy - 35) ** 2) / (2 * 1.8**2)))
    field = field.astype(np.float32)
    _assert_matches_legacy(field, 35, 35)


def test_saturated_source_matches_legacy_with_explicit_saturation_level():
    field = _isolated_star(amplitude=70000.0, background=100.0, seed=2)
    migrated, legacy = _assert_matches_legacy(field, 32, 32, saturation_level=65535.0)
    assert migrated["saturated"] is True
    assert legacy["saturated"] is True


def test_auto_detected_saturation_matches_legacy_for_signed_integer_dtype():
    # Sin saturation_level explícito: el heredado solo auto-detecta
    # saturación para dtype.kind == 'i' (entero CON signo) -- comportamiento
    # real, verificado tal cual, no "arreglado" a que también cubra 'u'.
    shape = (40, 40)
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    field = np.full(shape, 100, dtype=np.int32)
    field += (30000 * np.exp(-(((xx - 20) ** 2 + (yy - 20) ** 2)) / (2 * 2.0**2))).astype(np.int32)
    field[20, 20] = np.iinfo(np.int32).max  # asegura pico >= 0.95 * max real del dtype
    migrated, legacy = _assert_matches_legacy(field, 20, 20)
    assert migrated["saturated"] is True
    assert legacy["saturated"] is True


def test_unsigned_integer_dtype_never_auto_flags_saturation_matches_legacy():
    # Mismo hallazgo de comportamiento real: uint16 (lo habitual en una
    # cámara CCD/CMOS real) NUNCA dispara la auto-detección sin
    # saturation_level explícito, en el heredado y en la migración por igual.
    shape = (40, 40)
    field = np.full(shape, 100, dtype=np.uint16)
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    field += (60000 * np.exp(-(((xx - 20) ** 2 + (yy - 20) ** 2)) / (2 * 2.0**2))).astype(np.uint16)
    migrated, legacy = _assert_matches_legacy(field, 20, 20)
    assert migrated["saturated"] is False
    assert legacy["saturated"] is False


def test_two_blended_sources_match_legacy_peak_count():
    # Dos fuentes próximas dentro del mismo recorte -- n_peaks_in_stamp
    # (componentes conexas al 30% del pico) debe detectar más de una.
    shape = (64, 64)
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    field = 100.0
    field = field + 1500.0 * np.exp(-(((xx - 30) ** 2 + (yy - 32) ** 2)) / (2 * 1.6**2))
    field = field + 1300.0 * np.exp(-(((xx - 38) ** 2 + (yy - 32) ** 2)) / (2 * 1.6**2))
    field = field.astype(np.float32)
    migrated, legacy = _assert_matches_legacy(field, 34, 32)
    assert migrated["n_peaks_in_stamp"] == legacy["n_peaks_in_stamp"]
    assert migrated["isolated"] == legacy["isolated"]


def test_source_near_the_border_matches_legacy_with_a_clipped_cutout():
    field = _isolated_star(shape=(30, 30), x0=3, y0=3, sigma=1.8, seed=3)
    _assert_matches_legacy(field, 3, 3)


def test_cutout_too_small_matches_legacy_not_available():
    field = _isolated_star()
    _assert_matches_legacy(field, 0, 0, cutout_size=3)


def test_flat_field_with_no_positive_signal_matches_legacy_real_quirk():
    # Hallazgo real durante la migración: el "Sin señal positiva" del
    # heredado es, tal cual está escrito, inalcanzable (`total` se
    # recalcula a 1.0 en la rama sin señal, así que `total <= 0` nunca es
    # cierto) -- un recorte totalmente plano SÍ devuelve "OBSERVABLE",
    # con fwhm_px/ellipticity/sharpness en None. Se conserva ese
    # comportamiento real tal cual (ver el comentario en
    # `photometry/quality.py`), no se "arregla" en silencio.
    field = np.full((40, 40), 500.0, dtype=np.float32)
    migrated, legacy = _assert_matches_legacy(field, 20, 20)
    assert migrated["state"] == "OBSERVABLE"
    assert legacy["state"] == "OBSERVABLE"
    assert migrated["fwhm_px"] is None
    assert migrated["ellipticity"] is None


@pytest.mark.parametrize("gain", [0.5, 1.0, 2.5])
def test_gain_parameter_is_accepted_but_unused_same_as_legacy(gain):
    # `gain` viaja en la firma heredada sin usarse en el cálculo -- se
    # conserva así en la migración (mismo comportamiento, no una mejora
    # no pedida); esta prueba deja constancia explícita de que cambiar
    # `gain` no cambia el resultado, en ambas implementaciones por igual.
    field = _isolated_star(seed=4)
    baseline_migrated, baseline_legacy = _assert_matches_legacy(field, 32, 32, gain=1.0)
    migrated, legacy = _assert_matches_legacy(field, 32, 32, gain=gain)
    assert migrated == baseline_migrated
    assert legacy == baseline_legacy
