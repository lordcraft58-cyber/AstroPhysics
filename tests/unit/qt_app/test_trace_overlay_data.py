"""`trace_overlay_data.py`: `recalculate_extraction` reutiliza la MISMA
traza ya calculada con un semiancho de apertura distinto -- nunca
retraza ni recalcula el cielo desde cero (§2)."""
from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.trace import extract_optimal, extract_sum, trace_spectrum
from qt_app.spectroscopy.trace_overlay_data import TraceEditContext, recalculate_extraction


def _synthetic_2d_spectrum(shape=(41, 150), *, center=20.0, sigma=2.0, flux_per_col=3000.0, background=50.0, seed=1):
    rng = np.random.default_rng(seed)
    height, width = shape
    rows = np.arange(height)[:, np.newaxis]
    profile = np.exp(-((rows - center) ** 2) / (2 * sigma**2))
    profile /= profile.sum(axis=0, keepdims=True)
    data = background + flux_per_col * profile
    data = data + rng.normal(0, 3.0, shape)
    return data


def _context(extractor=extract_sum, aperture_half_width=4.0) -> tuple[TraceEditContext, float]:
    data = _synthetic_2d_spectrum()
    uncertainty = np.sqrt(np.clip(data, 1.0, None))
    trace = trace_spectrum(data, initial_center_px=20.0, fit_degree=1)
    context = TraceEditContext(
        trace=trace, data=data, uncertainty=uncertainty, mask=None,
        extractor=extractor, extraction_method_label="suma simple",
    )
    return context, aperture_half_width


def test_recalculate_extraction_reuses_the_same_trace_with_a_different_aperture():
    context, half_width = _context()
    original = context.extractor(context.data, context.uncertainty, context.trace, aperture_half_width=half_width)
    recalculated = recalculate_extraction(context, half_width * 2.0)

    # misma traza real, apertura mas ancha -> mas senal capturada (mismo perfil positivo)
    assert np.nanmedian(recalculated.flux) > np.nanmedian(original.flux)


def test_recalculate_extraction_matches_calling_the_original_extractor_directly():
    context, _ = _context(extractor=extract_optimal)
    new_half_width = 6.0
    recalculated = recalculate_extraction(context, new_half_width)
    direct = extract_optimal(context.data, context.uncertainty, context.trace, aperture_half_width=new_half_width)
    np.testing.assert_allclose(recalculated.flux, direct.flux, equal_nan=True)


def test_recalculate_extraction_rejects_a_non_positive_aperture():
    context, _ = _context()
    with pytest.raises(ValueError, match="positivo"):
        recalculate_extraction(context, 0.0)
    with pytest.raises(ValueError, match="positivo"):
        recalculate_extraction(context, -2.0)
