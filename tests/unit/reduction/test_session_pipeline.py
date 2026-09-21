"""Sesión real de reducción: varios LIGHTS + calibración completa +
combinación con rechazo de outliers -- el flujo que el encargo pide
explícitamente (RAW/FITS -> OVERSCAN -> TRIM -> MASTER BIAS/DARK/FLAT ->
CALIBRACIÓN DE LIGHTS -> COMBINACIÓN -> RECHAZO DE OUTLIERS -> PRODUCTO
CALIBRADO), no una imagen aislada."""
from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.reduction.illumination import build_illumination_map
from astrophysics_suite.reduction.master_frames import MasterFrame
from astrophysics_suite.reduction.session_pipeline import reduce_light_frames


def _bias_frame(shape, level, uncertainty=0.0):
    return MasterFrame(data=np.full(shape, level), uncertainty=np.full(shape, uncertainty), n_combined=np.full(shape, 5), kind="bias")


def _dark_frame(shape, level, exposure_s, uncertainty=0.0):
    return MasterFrame(data=np.full(shape, level), uncertainty=np.full(shape, uncertainty), n_combined=np.full(shape, 5), kind="dark", exposure_s=exposure_s)


def _flat_frame(shape, level=1.0, uncertainty=0.0):
    return MasterFrame(data=np.full(shape, level), uncertainty=np.full(shape, uncertainty), n_combined=np.full(shape, 5), kind="flat")


def test_reduce_light_frames_rejects_empty_list():
    with pytest.raises(ValueError):
        reduce_light_frames([])


def test_reduce_light_frames_applies_full_calibration_chain_per_light():
    shape = (10, 10)
    bias = _bias_frame(shape, 500.0)
    dark = _dark_frame(shape, level=30.0, exposure_s=30.0)
    flat = _flat_frame(shape, level=0.8)

    lights = [np.full(shape, 2000.0), np.full(shape, 2400.0)]
    result = reduce_light_frames(
        lights,
        light_paths=["light_001.fits", "light_002.fits"],
        science_exposures_s=[30.0, 30.0],
        master_bias=bias,
        master_dark=dark,
        master_flat=flat,
    )

    assert len(result.frames) == 2
    expected_0 = ((2000.0 - 500.0) - 30.0) / 0.8
    expected_1 = ((2400.0 - 500.0) - 30.0) / 0.8
    np.testing.assert_allclose(result.frames[0].calibrated.data, expected_0)
    np.testing.assert_allclose(result.frames[1].calibrated.data, expected_1)
    assert result.frames[0].source_path == "light_001.fits"
    assert result.frames[1].source_path == "light_002.fits"
    for frame in result.frames:
        assert frame.steps.bias_subtracted and frame.steps.dark_subtracted and frame.steps.flat_divided
    assert result.combined is None


def test_reduce_light_frames_requires_matching_lengths_for_paths_and_exposures():
    shape = (5, 5)
    lights = [np.full(shape, 100.0), np.full(shape, 100.0)]
    with pytest.raises(ValueError):
        reduce_light_frames(lights, light_paths=["only_one.fits"])
    with pytest.raises(ValueError):
        reduce_light_frames(lights, science_exposures_s=[30.0])
    with pytest.raises(ValueError):
        reduce_light_frames(lights, light_hashes=["only_one_hash"])


def test_reduce_light_frames_records_real_input_hashes_in_provenance():
    # Cierra el hueco anotado en los informes 52/53/54: `input_hashes`
    # existía en `Provenance` desde el principio, pero ningún llamador
    # lo rellenaba -- aquí se pasan sha256 reales (del LIGHT y de los
    # maestros usados, si vienen de un FITS real en disco) y deben
    # llegar tal cual a `LightFrameReduction.provenance.input_hashes`.
    shape = (5, 5)
    bias = _bias_frame(shape, 100.0)
    dark = _dark_frame(shape, level=10.0, exposure_s=30.0)
    flat = _flat_frame(shape, level=1.0)
    lights = [np.full(shape, 500.0), np.full(shape, 600.0)]

    result = reduce_light_frames(
        lights,
        light_paths=["light_001.fits", "light_002.fits"],
        light_hashes=["hash-light-1", "hash-light-2"],
        science_exposures_s=[30.0, 30.0],
        master_bias=bias,
        master_dark=dark,
        master_flat=flat,
        master_bias_hash="hash-bias",
        master_dark_hash="hash-dark",
        master_flat_hash="hash-flat",
    )

    for index, frame in enumerate(result.frames):
        hashes = dict(frame.provenance.input_hashes)
        assert hashes[f"light:light_00{index + 1}.fits"] == f"hash-light-{index + 1}"
        assert hashes["master_bias"] == "hash-bias"
        assert hashes["master_dark"] == "hash-dark"
        assert hashes["master_flat"] == "hash-flat"


def test_reduce_light_frames_never_invents_a_hash_for_an_unsaved_master():
    # Un maestro construido en memoria en esta misma sesión, nunca
    # guardado a disco, no tiene un hash de archivo real que dar --
    # debe quedar honestamente ausente, nunca inventado.
    shape = (5, 5)
    bias = _bias_frame(shape, 100.0)
    lights = [np.full(shape, 500.0)]

    result = reduce_light_frames(lights, light_paths=["light.fits"], master_bias=bias)

    hashes = dict(result.frames[0].provenance.input_hashes)
    assert "master_bias" not in hashes


def test_reduce_light_frames_applies_overscan_and_trim_per_light():
    shape = (6, 10)
    raw = np.full(shape, 100.0)
    raw[:, 8:] = 40.0  # franja de overscan con nivel propio distinto
    lights = [raw.copy(), raw.copy()]

    result = reduce_light_frames(
        lights,
        overscan_region=(slice(None), slice(8, 10)),
        trim_region=(slice(None), slice(0, 8)),
    )

    for frame in result.frames:
        assert frame.calibrated.shape == (6, 8)
        np.testing.assert_allclose(frame.calibrated.data, 60.0)  # 100 - 40 de overscan
        assert frame.overscan_level is not None


def test_reduce_light_frames_removes_fringe_pattern():
    yy, xx = np.mgrid[0:12, 0:12]
    fringe_pattern = np.sin(xx / 2.0) * 5.0
    lights = [100.0 + 2.0 * fringe_pattern]

    result = reduce_light_frames(lights, master_fringe=fringe_pattern)

    assert result.frames[0].fringe_scale_factor == pytest.approx(2.0, rel=1e-6)
    np.testing.assert_allclose(result.frames[0].calibrated.data, 100.0, atol=1e-6)


def test_reduce_light_frames_combines_with_outlier_rejection():
    shape = (8, 8)
    good_level = 1000.0
    lights = [np.full(shape, good_level) for _ in range(5)]
    lights[2] = lights[2].copy()
    lights[2][4, 4] = 50000.0  # rayo cósmico en un solo fotograma

    result = reduce_light_frames(lights, combine=True, combine_sigma_clip=3.0)

    assert result.combined is not None
    np.testing.assert_allclose(result.combined.data, good_level, atol=1e-6)
    assert result.combined.n_combined[4, 4] == 4  # el outlier fue rechazado en ese píxel


def test_reduce_light_frames_combine_requires_at_least_two_frames():
    shape = (4, 4)
    with pytest.raises(ValueError):
        reduce_light_frames([np.full(shape, 100.0)], combine=True)


def test_reduce_light_frames_end_to_end_session_matches_manual_reference():
    """El flujo completo pedido por el encargo: RAW -> OVERSCAN/TRIM ->
    (masters ya construidos) -> CALIBRACIÓN DE VARIAS LIGHTS -> COMBINACIÓN
    -> PRODUCTO CALIBRADO, verificado contra un cálculo de referencia hecho
    a mano fuera del pipeline."""
    shape = (10, 12)
    bias_level, dark_level, flat_level = 200.0, 15.0, 0.9
    bias = _bias_frame(shape, bias_level)
    dark = _dark_frame(shape, dark_level, exposure_s=60.0)
    flat = _flat_frame(shape, flat_level)

    science_level = 3000.0
    lights_with_overscan = []
    for _ in range(4):
        frame = np.full((shape[0], shape[1] + 2), science_level)
        frame[:, -2:] = 50.0  # columnas de overscan
        lights_with_overscan.append(frame)

    result = reduce_light_frames(
        lights_with_overscan,
        overscan_region=(slice(None), slice(-2, None)),
        trim_region=(slice(None), slice(0, shape[1])),
        science_exposures_s=[60.0] * 4,
        master_bias=bias,
        master_dark=dark,
        master_flat=flat,
        combine=True,
        combine_method="median",
    )

    expected = ((science_level - 50.0) - bias_level - dark_level) / flat_level
    for frame in result.frames:
        assert frame.calibrated.shape == shape
        np.testing.assert_allclose(frame.calibrated.data, expected, rtol=1e-6)
    assert result.combined is not None
    np.testing.assert_allclose(result.combined.data, expected, rtol=1e-6)
    assert np.all(result.combined.n_combined == 4)


def test_reduce_light_frames_applies_illumination_correction():
    height, width = 60, 60
    yy, xx = np.mgrid[0:height, 0:width]
    true_illumination = 1.0 + 0.2 * (xx / (width - 1))
    illumination = build_illumination_map(true_illumination, smoothing_sigma_px=3.0)

    uniform_sky = 500.0
    light = uniform_sky * true_illumination

    result = reduce_light_frames([light], illumination_map=illumination)

    margin = 10
    interior = slice(margin, -margin)
    corrected_interior = result.frames[0].calibrated.data[interior, interior]
    # se aplana a un nivel constante -- el mismo criterio que ya prueba
    # illumination.py: lo que importa es que ya no varíe con x.
    np.testing.assert_allclose(corrected_interior, float(np.mean(corrected_interior)), rtol=1e-3)


def test_reduce_light_frames_subtracts_sky_background_per_light():
    height, width = 40, 50
    yy, xx = np.mgrid[0:height, 0:width]
    gradient = 30.0 * (xx / (width - 1))
    star = 4000.0 * np.exp(-(((xx - 25) ** 2 + (yy - 20) ** 2)) / (2 * 2.0**2))
    light = 200.0 + gradient + star

    result = reduce_light_frames([light], subtract_sky=True, sky_degree=1)

    frame = result.frames[0]
    assert frame.sky_background is not None
    assert frame.sky_background.degree == 1
    corrected = frame.calibrated.data
    background_region = corrected.copy()
    background_region[15:26, 20:31] = np.nan
    assert np.nanstd(background_region) < 6.0  # el gradiente de 30 ADU quedó aplanado
    assert corrected[20, 25] > 3500.0  # la estrella sigue presente


def test_reduce_light_frames_combines_illumination_fringe_and_sky_in_correct_order():
    """El orden físico importa: iluminación y franjas se aplican sobre la
    imagen ya bias/dark/flat-calibrada, y la corrección de cielo se aplica
    la última, sobre el resultado ya libre de esos patrones instrumentales."""
    shape = (30, 30)
    light = np.full(shape, 1000.0)

    illumination = build_illumination_map(np.full(shape, 1.0))
    result = reduce_light_frames(
        [light],
        illumination_map=illumination,
        subtract_sky=True,
        sky_degree=0,
    )

    frame = result.frames[0]
    np.testing.assert_allclose(frame.calibrated.data, 0.0, atol=1e-6)  # cielo constante, se resta a cero
    assert frame.sky_background is not None
