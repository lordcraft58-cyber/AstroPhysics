"""`object_line_identification.py`: detección + emparejamiento por
posición real (§21/§22) -- siempre sugerencia, nunca inventa a qué
corresponde una detección sin evidencia de catálogo, avisa (sin
descartar) cuando el signo detectado no encaja con el tipo catalogado,
y marca (sin corregir) el solape con bandas telúricas conocidas."""
from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.line_catalog import LineType, SpectralLine
from astrophysics_suite.spectroscopy.object_line_identification import (
    detect_object_lines,
    identify_object_lines_in_spectrum,
)


def _synthetic_spectrum(features, *, n_points=3000, noise=0.2, seed=21):
    """`features`: lista de `(wavelength, amplitude, sigma)` -- amplitud
    negativa = absorción, positiva = emisión, sumadas sobre un continuo
    real conocido."""
    rng = np.random.default_rng(seed)
    wavelength = np.linspace(3800.0, 7200.0, n_points)
    continuum = 100.0 + 0.001 * (wavelength - 5500.0)
    flux = continuum.copy()
    for wl, amp, sigma in features:
        flux += amp * np.exp(-((wavelength - wl) ** 2) / (2 * sigma**2))
    flux_noisy = flux + rng.normal(0, noise, n_points)
    return wavelength, flux_noisy, continuum


_H_ALPHA = 6562.8
_O_III = 5006.8


def test_detect_object_lines_finds_both_absorption_and_emission():
    wavelength, flux, continuum = _synthetic_spectrum([(_H_ALPHA, -15.0, 1.3), (_O_III, 8.0, 1.0)])
    detections = detect_object_lines(wavelength, flux, continuum)

    detected_wavelengths = [w for w, _amp in detections]
    assert any(abs(w - _H_ALPHA) < 1.0 for w in detected_wavelengths)
    assert any(abs(w - _O_III) < 1.0 for w in detected_wavelengths)
    amplitudes = {round(w): amp for w, amp in detections}
    assert amplitudes[round(_H_ALPHA)] < 0
    assert amplitudes[round(_O_III)] > 0


def test_detect_object_lines_returns_empty_for_a_flat_continuum():
    rng = np.random.default_rng(22)
    wavelength = np.linspace(3800.0, 7200.0, 3000)
    continuum = np.full_like(wavelength, 100.0)
    flux = continuum + rng.normal(0, 0.2, wavelength.size)
    assert detect_object_lines(wavelength, flux, continuum) == []


def test_detect_object_lines_rejects_mismatched_shapes():
    wavelength = np.linspace(3800.0, 7200.0, 100)
    with pytest.raises(ValueError):
        detect_object_lines(wavelength, wavelength[:-1], wavelength)


_HALPHA_ABSORPTION = SpectralLine(_H_ALPHA, "H-alpha (test)", "H", line_type=LineType.ABSORPTION)
_HALPHA_EMISSION = SpectralLine(_H_ALPHA, "H-alpha (test)", "H", line_type=LineType.EMISSION)
_OIII_EMISSION = SpectralLine(_O_III, "[O III] (test)", "O", "III", line_type=LineType.EMISSION)


def test_identify_matches_a_real_absorption_line_against_the_correct_catalog_entry():
    wavelength, flux, continuum = _synthetic_spectrum([(_H_ALPHA, -15.0, 1.3)])
    matches = identify_object_lines_in_spectrum(wavelength, flux, continuum, (_HALPHA_ABSORPTION,), tolerance_angstrom=2.0)

    assert len(matches) == 1
    match = matches[0]
    assert match.detected_wavelength == pytest.approx(_H_ALPHA, abs=0.5)
    assert match.catalog_line is _HALPHA_ABSORPTION
    assert match.confidence > 0.8
    assert match.line_type_agrees
    assert match.telluric_overlap is None


def test_identify_flags_a_type_mismatch_without_discarding_the_match():
    """La misma detección de absorción real, contra un catálogo que la
    etiqueta como emisión -- debe seguir devolviendo la coincidencia por
    POSICIÓN (el llamador decide qué hacer), con el aviso puesto."""
    wavelength, flux, continuum = _synthetic_spectrum([(_H_ALPHA, -15.0, 1.3)])
    matches = identify_object_lines_in_spectrum(wavelength, flux, continuum, (_HALPHA_EMISSION,), tolerance_angstrom=2.0)

    assert len(matches) == 1
    assert not matches[0].line_type_agrees


def test_identify_never_invents_a_match_without_a_nearby_catalog_line():
    wavelength, flux, continuum = _synthetic_spectrum([(_H_ALPHA, -15.0, 1.3)])
    far_away_line = SpectralLine(4000.0, "lejos", "X")
    matches = identify_object_lines_in_spectrum(wavelength, flux, continuum, (far_away_line,), tolerance_angstrom=2.0)
    assert matches == ()


def test_identify_flags_telluric_overlap_on_a_matched_line():
    telluric_wavelength = 6870.0  # dentro de la banda O2 B real (6867-6884)
    fake_catalog_line = SpectralLine(telluric_wavelength, "prueba telúrica", "X", line_type=LineType.ABSORPTION)
    wavelength, flux, continuum = _synthetic_spectrum([(telluric_wavelength, -6.0, 1.0)])

    matches = identify_object_lines_in_spectrum(wavelength, flux, continuum, (fake_catalog_line,), tolerance_angstrom=2.0)

    assert len(matches) == 1
    assert matches[0].telluric_overlap is not None
    assert matches[0].telluric_overlap.name == "O2 B"


def test_identify_can_disable_telluric_flagging():
    telluric_wavelength = 6870.0
    fake_catalog_line = SpectralLine(telluric_wavelength, "prueba telúrica", "X", line_type=LineType.ABSORPTION)
    wavelength, flux, continuum = _synthetic_spectrum([(telluric_wavelength, -6.0, 1.0)])

    matches = identify_object_lines_in_spectrum(
        wavelength, flux, continuum, (fake_catalog_line,), tolerance_angstrom=2.0, flag_telluric=False
    )
    assert matches[0].telluric_overlap is None


def test_identify_rejects_an_empty_catalog():
    wavelength, flux, continuum = _synthetic_spectrum([(_H_ALPHA, -15.0, 1.3)])
    with pytest.raises(ValueError):
        identify_object_lines_in_spectrum(wavelength, flux, continuum, (), tolerance_angstrom=2.0)


def test_identify_rejects_nonpositive_tolerance():
    wavelength, flux, continuum = _synthetic_spectrum([(_H_ALPHA, -15.0, 1.3)])
    with pytest.raises(ValueError):
        identify_object_lines_in_spectrum(wavelength, flux, continuum, (_HALPHA_ABSORPTION,), tolerance_angstrom=0.0)


def test_identify_confidence_decreases_with_residual_distance():
    wavelength, flux, continuum = _synthetic_spectrum([(_H_ALPHA, -15.0, 1.3)])
    close_line = SpectralLine(_H_ALPHA + 0.3, "cerca", "H", line_type=LineType.ABSORPTION)
    far_line = SpectralLine(_H_ALPHA + 1.8, "lejos", "H", line_type=LineType.ABSORPTION)

    close_match = identify_object_lines_in_spectrum(wavelength, flux, continuum, (close_line,), tolerance_angstrom=2.0)[0]
    far_match = identify_object_lines_in_spectrum(wavelength, flux, continuum, (far_line,), tolerance_angstrom=2.0)[0]

    assert close_match.confidence > far_match.confidence


def test_identify_picks_the_closest_catalog_line_when_several_are_in_tolerance():
    wavelength, flux, continuum = _synthetic_spectrum([(_H_ALPHA, -15.0, 1.3)])
    near = SpectralLine(_H_ALPHA + 0.2, "cerca", "H", line_type=LineType.ABSORPTION)
    farther = SpectralLine(_H_ALPHA - 1.5, "más lejos", "H", line_type=LineType.ABSORPTION)

    matches = identify_object_lines_in_spectrum(wavelength, flux, continuum, (near, farther), tolerance_angstrom=2.0)
    assert len(matches) == 1
    assert matches[0].catalog_line is near
