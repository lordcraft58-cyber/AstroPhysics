"""Pruebas del backend real de IRAF/PyRAF (`reduction.pyraf_backend`).

Las pruebas que necesitan un IRAF real se saltan explícitamente cuando
`HAS_PYRAF is False` -- que es SIEMPRE el caso en este sandbox de
desarrollo (confirmado: sin salida de red hacia el canal astroconda que
distribuye los binarios reales de IRAF). No es una razón para fallar la
suite; es una limitación real y documentada del entorno (mismo patrón
ya establecido para las pruebas de red de Gaia/SIMBAD:
`test_gaia_network.py`, `test_simbad_network.py`). Las pruebas que
verifican el comportamiento honesto SIN pyraf (que es justo el caso
real aquí) sí corren de verdad en este entorno, sin saltarse nada.

**Las pruebas marcadas para saltarse nunca se han ejecutado de verdad
contra IRAF real en esta sesión** -- están escritas para correr en
cuanto exista esa instalación (p. ej. la del usuario, vía WSL2 +
astroconda), no como una validación ya completada."""
from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.reduction.pyraf_backend import HAS_PYRAF, PyrafUnavailableError, check_pyraf_environment

requires_real_pyraf = pytest.mark.skipif(not HAS_PYRAF, reason="pyraf/IRAF real no disponible en este entorno (ver docstring del módulo)")


def _write_frame(path, shape=(20, 20), level=500.0, seed=0):
    from astropy.io import fits

    rng = np.random.default_rng(seed)
    data = (np.full(shape, level) + rng.normal(0, 2.0, shape)).astype(np.float32)
    fits.PrimaryHDU(data).writeto(path)
    return path


def test_check_pyraf_environment_reports_real_status():
    """Corre siempre, con o sin IRAF real -- el propio contrato de
    `check_pyraf_environment` es devolver un diagnóstico honesto en
    ambos casos, no solo cuando IRAF está disponible."""
    ok, detail = check_pyraf_environment()
    assert isinstance(ok, bool)
    assert detail
    if not HAS_PYRAF:
        assert ok is False


def test_functions_raise_explicit_error_when_pyraf_unavailable(monkeypatch):
    """Corre siempre -- en este sandbox, `HAS_PYRAF` ya es `False` de
    verdad; en un entorno con IRAF real, se fuerza igualmente con
    monkeypatch para confirmar el mensaje accionable en ambos casos."""
    import astrophysics_suite.reduction.pyraf_backend as backend

    monkeypatch.setattr(backend, "HAS_PYRAF", False)
    with pytest.raises(PyrafUnavailableError, match="PyRAF/IRAF no están disponibles"):
        backend.combine_bias_frames_pyraf(["a.fits", "b.fits", "c.fits"], "out.fits")
    with pytest.raises(PyrafUnavailableError):
        backend.apply_calibration_pyraf(["a.fits"], "out_dir")


@requires_real_pyraf
def test_combine_bias_frames_pyraf_writes_a_real_master(tmp_path):
    from astrophysics_suite.reduction.pyraf_backend import combine_bias_frames_pyraf

    paths = [str(_write_frame(tmp_path / f"bias_{i}.fits", level=500.0, seed=i)) for i in range(5)]
    output = tmp_path / "master_bias.fits"

    combine_bias_frames_pyraf(paths, str(output))

    assert output.exists()
    from astropy.io import fits

    with fits.open(output) as hdul:
        assert abs(float(np.median(hdul[0].data)) - 500.0) < 10.0


@requires_real_pyraf
def test_combine_dark_frames_pyraf_records_exposure(tmp_path):
    from astrophysics_suite.reduction.pyraf_backend import combine_dark_frames_pyraf

    paths = [str(_write_frame(tmp_path / f"dark_{i}.fits", level=520.0, seed=i)) for i in range(5)]
    output = tmp_path / "master_dark.fits"

    combine_dark_frames_pyraf(paths, str(output), exposure_s=120.0)

    from astropy.io import fits

    with fits.open(output) as hdul:
        assert float(hdul[0].header["EXPTIME"]) == pytest.approx(120.0)


@requires_real_pyraf
def test_combine_frames_pyraf_requires_at_least_three():
    from astrophysics_suite.reduction.pyraf_backend import combine_bias_frames_pyraf

    with pytest.raises(ValueError):
        combine_bias_frames_pyraf(["a.fits", "b.fits"], "out.fits")


@requires_real_pyraf
def test_combine_frames_pyraf_refuses_to_overwrite_silently(tmp_path):
    from astrophysics_suite.reduction.pyraf_backend import combine_bias_frames_pyraf

    paths = [str(_write_frame(tmp_path / f"bias_{i}.fits", seed=i)) for i in range(3)]
    existing = tmp_path / "already_there.fits"
    _write_frame(existing)

    with pytest.raises(FileExistsError):
        combine_bias_frames_pyraf(paths, str(existing))


@requires_real_pyraf
def test_apply_calibration_pyraf_writes_real_calibrated_copies(tmp_path):
    from astrophysics_suite.reduction.pyraf_backend import apply_calibration_pyraf, combine_bias_frames_pyraf

    bias_paths = [str(_write_frame(tmp_path / f"bias_{i}.fits", level=500.0, seed=i)) for i in range(5)]
    master_bias = tmp_path / "master_bias.fits"
    combine_bias_frames_pyraf(bias_paths, str(master_bias))

    science_path = str(_write_frame(tmp_path / "science.fits", level=1500.0, seed=99))
    out_dir = tmp_path / "calibrated"

    output_paths = apply_calibration_pyraf([science_path], str(out_dir), master_bias_path=str(master_bias))

    assert len(output_paths) == 1
    from astropy.io import fits

    with fits.open(output_paths[0]) as hdul:
        assert abs(float(np.median(hdul[0].data)) - 1000.0) < 15.0  # 1500 - 500 de bias
