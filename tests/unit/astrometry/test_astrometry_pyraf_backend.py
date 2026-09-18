"""Pruebas del backend real de IRAF/PyRAF para astrometría
(`astrometry.pyraf_backend`). Mismo patrón que
`tests/unit/reduction/test_pyraf_backend.py`: las pruebas que necesitan
IRAF real se saltan explícitamente (`HAS_PYRAF is False` en este
sandbox, confirmado); las que verifican el comportamiento honesto SIN
pyraf corren de verdad aquí, sin saltarse nada."""
from __future__ import annotations

import pytest

from astrophysics_suite.astrometry.pyraf_backend import HAS_PYRAF, PyrafUnavailableError, check_pyraf_environment

requires_real_pyraf = pytest.mark.skipif(not HAS_PYRAF, reason="pyraf/IRAF real no disponible en este entorno (ver docstring del módulo)")


def test_check_pyraf_environment_reports_real_status():
    ok, detail = check_pyraf_environment()
    assert isinstance(ok, bool)
    assert detail
    if not HAS_PYRAF:
        assert ok is False


def test_functions_raise_explicit_error_when_pyraf_unavailable(monkeypatch):
    import astrophysics_suite.astrometry.pyraf_backend as backend

    monkeypatch.setattr(backend, "HAS_PYRAF", False)
    with pytest.raises(PyrafUnavailableError, match="PyRAF/IRAF no están disponibles"):
        backend.fit_wcs_pyraf("matches.txt", "db.dat")
    with pytest.raises(PyrafUnavailableError):
        backend.register_images_pyraf("ref.fits", ["a.fits"], "out_dir")


def test_register_images_pyraf_requires_at_least_one_input():
    from astrophysics_suite.astrometry.pyraf_backend import register_images_pyraf

    if not HAS_PYRAF:
        with pytest.raises(PyrafUnavailableError):
            register_images_pyraf("ref.fits", [], "out_dir")
    else:
        with pytest.raises(ValueError):
            register_images_pyraf("ref.fits", [], "out_dir")


@requires_real_pyraf
def test_fit_wcs_pyraf_writes_a_real_database(tmp_path):
    from astrophysics_suite.astrometry.pyraf_backend import fit_wcs_pyraf

    matches = tmp_path / "matches.txt"
    matches.write_text("10.0 10.0 180.0 30.0\n20.0 20.0 180.01 30.01\n30.0 15.0 180.02 29.99\n")
    database = fit_wcs_pyraf(str(matches), str(tmp_path / "solution.db"))
    from pathlib import Path

    assert Path(database).exists()


@requires_real_pyraf
def test_register_images_pyraf_writes_real_outputs(tmp_path):
    from astrophysics_suite.astrometry.pyraf_backend import register_images_pyraf

    outputs = register_images_pyraf(str(tmp_path / "ref.fits"), [str(tmp_path / "a.fits")], str(tmp_path / "registered"))
    from pathlib import Path

    assert len(outputs) == 1
    assert Path(outputs[0]).exists()


@requires_real_pyraf
def test_fit_wcs_pyraf_refuses_to_overwrite_silently(tmp_path):
    from astrophysics_suite.astrometry.pyraf_backend import fit_wcs_pyraf

    matches = tmp_path / "matches.txt"
    matches.write_text("10.0 10.0 180.0 30.0\n")
    existing = tmp_path / "already_there.db"
    existing.write_text("x")
    with pytest.raises(FileExistsError):
        fit_wcs_pyraf(str(matches), str(existing))
