"""Pruebas del backend real de IRAF/PyRAF para espectroscopía
(`spectroscopy.pyraf_backend`). Mismo patrón que
`tests/unit/reduction/test_pyraf_backend.py`: las pruebas que necesitan
IRAF real se saltan explícitamente (`HAS_PYRAF is False` en este
sandbox, confirmado); las que verifican el comportamiento honesto SIN
pyraf corren de verdad aquí, sin saltarse nada."""
from __future__ import annotations

import pytest

from astrophysics_suite.spectroscopy.pyraf_backend import HAS_PYRAF, PyrafUnavailableError, check_pyraf_environment

requires_real_pyraf = pytest.mark.skipif(not HAS_PYRAF, reason="pyraf/IRAF real no disponible en este entorno (ver docstring del módulo)")


def test_check_pyraf_environment_reports_real_status():
    ok, detail = check_pyraf_environment()
    assert isinstance(ok, bool)
    assert detail
    if not HAS_PYRAF:
        assert ok is False


def test_functions_raise_explicit_error_when_pyraf_unavailable(monkeypatch):
    import astrophysics_suite.spectroscopy.pyraf_backend as backend

    monkeypatch.setattr(backend, "HAS_PYRAF", False)
    with pytest.raises(PyrafUnavailableError, match="PyRAF/IRAF no están disponibles"):
        backend.extract_spectrum_pyraf("img.fits", "out.ms.fits")
    with pytest.raises(PyrafUnavailableError):
        backend.calibrate_wavelength_pyraf("spec.fits", "ref.fits", "out.fits")
    with pytest.raises(PyrafUnavailableError):
        backend.flux_calibrate_pyraf("std.fits", "HZ44", "sci.fits", "out.fits")
    with pytest.raises(PyrafUnavailableError):
        backend.fit_continuum_pyraf("spec.fits", "out.fits")


@requires_real_pyraf
def test_extract_spectrum_pyraf_writes_a_real_output(tmp_path):
    from astrophysics_suite.spectroscopy.pyraf_backend import extract_spectrum_pyraf

    output = extract_spectrum_pyraf(str(tmp_path / "raw2d.fits"), str(tmp_path / "extracted.ms.fits"))
    from pathlib import Path

    assert Path(output).exists()


@requires_real_pyraf
def test_calibrate_wavelength_pyraf_writes_a_real_output(tmp_path):
    from astrophysics_suite.spectroscopy.pyraf_backend import calibrate_wavelength_pyraf

    output = calibrate_wavelength_pyraf(str(tmp_path / "extracted.ms.fits"), str(tmp_path / "reference.ms.fits"), str(tmp_path / "wcal.fits"))
    from pathlib import Path

    assert Path(output).exists()


@requires_real_pyraf
def test_flux_calibrate_pyraf_writes_a_real_output(tmp_path):
    from astrophysics_suite.spectroscopy.pyraf_backend import flux_calibrate_pyraf

    output = flux_calibrate_pyraf(str(tmp_path / "std.ms.fits"), "HZ44", str(tmp_path / "sci.ms.fits"), str(tmp_path / "fcal.fits"))
    from pathlib import Path

    assert Path(output).exists()


@requires_real_pyraf
def test_fit_continuum_pyraf_writes_a_real_output(tmp_path):
    from astrophysics_suite.spectroscopy.pyraf_backend import fit_continuum_pyraf

    output = fit_continuum_pyraf(str(tmp_path / "fcal.fits"), str(tmp_path / "norm.fits"))
    from pathlib import Path

    assert Path(output).exists()


@requires_real_pyraf
def test_extract_spectrum_pyraf_refuses_to_overwrite_silently(tmp_path):
    from astrophysics_suite.spectroscopy.pyraf_backend import extract_spectrum_pyraf

    existing = tmp_path / "already_there.ms.fits"
    existing.write_text("x")
    with pytest.raises(FileExistsError):
        extract_spectrum_pyraf(str(tmp_path / "raw2d.fits"), str(existing))
