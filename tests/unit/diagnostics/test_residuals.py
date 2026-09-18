from __future__ import annotations

import math

import pytest

from astrophysics_suite.diagnostics.residuals import build_residual_diagnostic


def test_build_residual_diagnostic_rejects_empty_input():
    with pytest.raises(ValueError):
        build_residual_diagnostic((), unit="arcsec")


def test_build_residual_diagnostic_computes_real_statistics():
    residuals = (0.1, -0.2, 0.15, -0.05, 0.3)
    diagnostic = build_residual_diagnostic(residuals, unit="arcsec")

    assert diagnostic.unit == "arcsec"
    assert diagnostic.residuals == residuals
    expected_rms = math.sqrt(sum(r * r for r in residuals) / len(residuals))
    assert diagnostic.rms == pytest.approx(expected_rms)
    assert diagnostic.mean == pytest.approx(sum(residuals) / len(residuals))
    assert diagnostic.max_abs == pytest.approx(0.3)


def test_build_residual_diagnostic_flags_a_real_outlier():
    residuals = (0.1, 0.12, 0.09, 0.11, 5.0)
    diagnostic = build_residual_diagnostic(residuals, unit="mag")
    assert diagnostic.outlier_indices == (4,)


def test_build_residual_diagnostic_with_no_outliers_has_empty_indices():
    residuals = (0.1, 0.11, 0.09, 0.1, 0.12)
    diagnostic = build_residual_diagnostic(residuals, unit="mag")
    assert diagnostic.outlier_indices == ()
