"""Pruebas del backend real de IRAF/PyRAF para fotometría
(`photometry.pyraf_backend`). Mismo patrón que
`tests/unit/reduction/test_pyraf_backend.py`: las pruebas que necesitan
IRAF real se saltan explícitamente (`HAS_PYRAF is False` en este
sandbox, confirmado); las que verifican el comportamiento honesto SIN
pyraf corren de verdad aquí, sin saltarse nada."""
from __future__ import annotations

import pytest

from astrophysics_suite.photometry.pyraf_backend import HAS_PYRAF, PyrafUnavailableError, check_pyraf_environment

requires_real_pyraf = pytest.mark.skipif(not HAS_PYRAF, reason="pyraf/IRAF real no disponible en este entorno (ver docstring del módulo)")


def test_check_pyraf_environment_reports_real_status():
    ok, detail = check_pyraf_environment()
    assert isinstance(ok, bool)
    assert detail
    if not HAS_PYRAF:
        assert ok is False


def test_functions_raise_explicit_error_when_pyraf_unavailable(monkeypatch):
    import astrophysics_suite.photometry.pyraf_backend as backend

    monkeypatch.setattr(backend, "HAS_PYRAF", False)
    with pytest.raises(PyrafUnavailableError, match="PyRAF/IRAF no están disponibles"):
        backend.run_aperture_photometry_pyraf("img.fits", "coords.txt", "out.mag", apertures=[5.0])
    with pytest.raises(PyrafUnavailableError):
        backend.run_daofind_pyraf("img.fits", "out.coo", sigma=5.0)
    with pytest.raises(PyrafUnavailableError):
        backend.run_psf_photometry_pyraf("img.fits", "coords.txt", "out_dir", sigma=5.0)


@requires_real_pyraf
def test_run_aperture_photometry_pyraf_writes_a_real_output(tmp_path):
    from astrophysics_suite.photometry.pyraf_backend import run_aperture_photometry_pyraf

    output = run_aperture_photometry_pyraf(
        str(tmp_path / "science.fits"), str(tmp_path / "coords.txt"), str(tmp_path / "phot.mag"),
        apertures=[5.0, 8.0],
    )
    from pathlib import Path

    assert Path(output).exists()


@requires_real_pyraf
def test_run_daofind_pyraf_writes_a_real_output(tmp_path):
    from astrophysics_suite.photometry.pyraf_backend import run_daofind_pyraf

    output = run_daofind_pyraf(str(tmp_path / "science.fits"), str(tmp_path / "found.coo"), sigma=5.0)
    from pathlib import Path

    assert Path(output).exists()


@requires_real_pyraf
def test_run_psf_photometry_pyraf_produces_the_three_real_products(tmp_path):
    from astrophysics_suite.photometry.pyraf_backend import run_psf_photometry_pyraf

    products = run_psf_photometry_pyraf(str(tmp_path / "science.fits"), str(tmp_path / "coords.txt"), str(tmp_path / "psf_out"), sigma=5.0)
    from pathlib import Path

    assert set(products) == {"pst", "psf", "allstar"}
    for path in products.values():
        assert Path(path).exists()


@requires_real_pyraf
def test_run_aperture_photometry_pyraf_refuses_to_overwrite_silently(tmp_path):
    from astrophysics_suite.photometry.pyraf_backend import run_aperture_photometry_pyraf

    existing = tmp_path / "already_there.mag"
    existing.write_text("x")
    with pytest.raises(FileExistsError):
        run_aperture_photometry_pyraf(str(tmp_path / "science.fits"), str(tmp_path / "coords.txt"), str(existing), apertures=[5.0])
