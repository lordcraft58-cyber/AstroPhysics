"""La reducción declara de verdad qué le hizo a cada LIGHT.

`CalibrationSteps` decía desde su primera versión que existía "para que
la procedencia pueda declarar exactamente qué calibración recibió cada
imagen" -- pero esa procedencia nunca se construía, y el FITS calibrado
se escribía con la cabecera cruda tal cual. Estas pruebas fijan el
contrato nuevo."""
from __future__ import annotations

import numpy as np
import pytest
from astropy.io import fits

from astrophysics_suite.io.fits_writer import UNCERTAINTY_EXTENSION_NAME, save_fits_image
from astrophysics_suite.reduction.calibration import CalibrationSteps
from astrophysics_suite.reduction.master_frames import MasterFrame
from astrophysics_suite.reduction.provenance import (
    ReductionRecord,
    build_reduction_provenance,
    reduction_header_cards,
)
from astrophysics_suite.reduction.session_pipeline import reduce_light_frames


def _master(kind: str, value: float, shape=(8, 8), exposure=None):
    return MasterFrame(
        kind=kind,
        data=np.full(shape, value, dtype=np.float64),
        uncertainty=np.full(shape, 0.1),
        n_combined=np.full(shape, 5, dtype=np.int64),
        exposure_s=exposure,
    )


def test_record_describes_only_the_steps_really_applied():
    record = ReductionRecord(
        steps=CalibrationSteps(bias_subtracted=True, dark_subtracted=True, dark_scale_factor=0.5, flat_divided=True),
        overscan_corrected=True, sky_subtracted=True, sky_degree=2,
    )
    described = record.describe()
    assert "overscan restado" in described
    assert "bias maestro restado" in described
    assert "dark maestro restado (escala 0.5000)" in described
    assert "dividido por flat maestro" in described
    assert "fondo de cielo restado (superficie de grado 2)" in described
    # no se aplicó: no aparece
    assert not any("píxeles defectuosos" in s for s in described)
    assert not any("franjas" in s for s in described)


def test_a_frame_with_no_calibration_says_so_instead_of_pretending():
    record = ReductionRecord(steps=CalibrationSteps())
    assert record.describe() == ()
    cards = reduction_header_cards(record)
    assert cards["APSRED"] is True  # sí pasó por el pipeline...
    assert cards["APSBIAS"] is False  # ...pero sin restar bias, y se dice
    assert any("ningún paso" in line for line in cards["HISTORY"])  # en memoria conserva el castellano real


def test_provenance_warns_about_missing_essential_calibration():
    provenance = build_reduction_provenance(ReductionRecord(steps=CalibrationSteps()))
    assert provenance.engine == "reduction.session_pipeline"
    joined = " ".join(provenance.warnings)
    assert "bias ni dark" in joined
    assert "sin flat" in joined

    full = build_reduction_provenance(
        ReductionRecord(steps=CalibrationSteps(bias_subtracted=True, flat_divided=True))
    )
    assert full.warnings == ()


def test_pipeline_now_produces_a_real_record_and_provenance():
    lights = [np.full((8, 8), 120.0), np.full((8, 8), 118.0)]
    result = reduce_light_frames(
        lights, master_bias=_master("bias", 10.0), master_flat=_master("flat", 1.0), subtract_sky=False
    )
    for frame in result.frames:
        assert frame.record is not None
        assert frame.provenance is not None
        assert frame.record.steps.bias_subtracted is True
        assert frame.record.steps.flat_divided is True
        assert frame.provenance.warnings == ()  # bias y flat presentes: nada que advertir


def test_pipeline_record_tracks_the_optional_steps_it_really_ran():
    lights = [np.full((8, 8), 120.0)]
    result = reduce_light_frames(lights, master_bias=_master("bias", 10.0), subtract_sky=True, sky_degree=1)
    record = result.frames[0].record
    assert record.sky_subtracted is True
    assert record.sky_degree == 1
    assert record.fringe_removed is False
    assert record.illumination_corrected is False


def test_header_cards_round_trip_through_a_real_fits_file(tmp_path):
    """Lo que de verdad importa: que un visor FITS cualquiera pueda leer
    qué se le hizo al archivo."""
    record = ReductionRecord(
        steps=CalibrationSteps(bias_subtracted=True, dark_subtracted=True, dark_scale_factor=1.25, flat_divided=True),
        overscan_corrected=True, gain_e_per_adu=1.4, read_noise_e=3.2,
    )
    provenance = build_reduction_provenance(record, pipeline_version="test")
    path = tmp_path / "calibrada.fits"

    save_fits_image(
        str(path), np.full((6, 6), 42.0), header=reduction_header_cards(record, provenance=provenance),
        uncertainty=np.full((6, 6), 1.5),
    )

    with fits.open(path) as hdul:
        header = hdul[0].header
        assert header["APSRED"] is True
        assert header["APSBIAS"] is True
        assert header["APSDARK"] is True
        assert header["APSFLAT"] is True
        assert header["APSDKSCL"] == pytest.approx(1.25)
        assert header["APSGAIN"] == pytest.approx(1.4)
        assert header["APSRDNS"] == pytest.approx(3.2)
        assert "reduction.session_pipeline" in header["APSENG"]

        history = "\n".join(str(line) for line in header["HISTORY"])
        # el estándar FITS solo admite ASCII: el castellano se translitera,
        # NO se descarta en silencio (que es lo que pasaba antes)
        assert "reduccion aplicada" in history
        assert "bias maestro restado" in history
        assert "dark maestro restado (escala 1.2500)" in history

        # y la incertidumbre propagada ya NO se tira al guardar
        assert UNCERTAINTY_EXTENSION_NAME in hdul
        np.testing.assert_allclose(hdul[UNCERTAINTY_EXTENSION_NAME].data, 1.5)


def test_saving_uncertainty_of_the_wrong_shape_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="misma forma"):
        save_fits_image(str(tmp_path / "bad.fits"), np.zeros((4, 4)), uncertainty=np.zeros((5, 5)))


def test_an_image_saved_without_uncertainty_has_no_empty_extension(tmp_path):
    path = tmp_path / "sin_incertidumbre.fits"
    save_fits_image(str(path), np.zeros((4, 4)))
    with fits.open(path) as hdul:
        assert len(hdul) == 1  # nunca una extensión vacía fingiendo que hay error medido


def test_accented_spanish_is_transliterated_not_silently_dropped(tmp_path):
    """El estándar FITS solo admite ASCII imprimible. Antes, cualquier
    valor con tilde se perdía entero por un `except ValueError`."""
    path = tmp_path / "acentos.fits"
    save_fits_image(
        str(path), np.zeros((3, 3)),
        header={"OBJECT": "Galaxia de Andrómeda", "HISTORY": ["reducción aplicada a los píxeles"]},
    )
    with fits.open(path) as hdul:
        assert hdul[0].header["OBJECT"] == "Galaxia de Andromeda"  # transliterado, no perdido
        assert "reduccion aplicada a los pixeles" in "\n".join(str(x) for x in hdul[0].header["HISTORY"])


def test_scaling_keywords_from_the_raw_header_are_never_copied(tmp_path):
    """Hallazgo con los LIGHTS reales de M 31 (ASI533MC Pro): el diálogo
    de reducción escribía el archivo calibrado copiando la cabecera CRUDA,
    que en esa cámara trae `BITPIX=16` con `BZERO=32768`. Al releer, astropy
    aplicaba `dato * BSCALE + BZERO` sobre datos que ya eran float, y cada
    píxel calibrado aparecía desplazado +32768 ADU -- sin que nada fallara."""
    path = tmp_path / "calibrada.fits"
    raw_header = {"BZERO": 32768, "BSCALE": 1, "BITPIX": 16, "OBJECT": "M 31", "EXPTIME": 300.0}

    save_fits_image(str(path), np.full((5, 5), 7.0, dtype=np.float64), header=raw_header)

    with fits.open(path) as hdul:
        assert "BZERO" not in hdul[0].header
        assert "BSCALE" not in hdul[0].header
        np.testing.assert_allclose(hdul[0].data, 7.0)  # 7.0, no 32775.0
        # lo que sí es metadato real de la observación se conserva
        assert hdul[0].header["OBJECT"] == "M 31"
        assert hdul[0].header["EXPTIME"] == pytest.approx(300.0)
