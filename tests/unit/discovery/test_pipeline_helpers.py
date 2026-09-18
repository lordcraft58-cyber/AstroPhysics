"""Pruebas unitarias de los ayudantes puros del cierre de calibración
fotométrica en `discovery/pipeline.py`: `_instrumental_magnitude` (la
misma convención de magnitud instrumental que ya usa el proceso manual
de punto cero de la GUI, punto cero arbitrario 0)."""
from __future__ import annotations

import math

import pytest

from astrophysics_suite.discovery.pipeline import _instrumental_magnitude


def test_instrumental_magnitude_matches_the_minus_2_5_log10_convention():
    # Misma fórmula que `aperture_photometry(..., zeropoint_mag=0.0)`
    # usa internamente (`_magnitude_from_flux`) -- comparabilidad real
    # con el proceso manual de punto cero, no una convención paralela.
    assert _instrumental_magnitude(100.0) == pytest.approx(-2.5 * math.log10(100.0))
    assert _instrumental_magnitude(1.0) == pytest.approx(0.0)


def test_instrumental_magnitude_brighter_flux_gives_a_more_negative_magnitude():
    faint = _instrumental_magnitude(100.0)
    bright = _instrumental_magnitude(10000.0)
    assert bright < faint


def test_instrumental_magnitude_is_none_for_non_positive_flux():
    assert _instrumental_magnitude(0.0) is None
    assert _instrumental_magnitude(-5.0) is None
