from __future__ import annotations

from datetime import datetime, timedelta, timezone

from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.discovery.source_tracks import EpochDetection, SourceTrack, group_detections_into_tracks
from astrophysics_suite.models.detection import Detection, MorphologyClass, MorphologySummary, SkyPosition
from astrophysics_suite.models.temporal import MotionEvidence
from astrophysics_suite.temporal.motion import analyze_motion

_PROV = Provenance.now(pipeline_version="t", engine="t", engine_version="1.0")
_T0 = datetime(2026, 9, 10, 20, 0, 0, tzinfo=timezone.utc)


def _detection(index: int, ra: float, dec: float, *, snr: float = 20.0) -> Detection:
    return Detection.create(
        detection_id=f"D{index}",
        observation_id="O",
        position=SkyPosition(x_px=10.0 + index, y_px=10.0, ra_deg=ra, dec_deg=dec),
        morphology=MorphologySummary(morphology_class=MorphologyClass.POINT_SOURCE, area_px=9.0, elongation=1.1, compactness=0.6),
        bands=("L",),
        peak_snr=snr,
        method="test",
        provenance=_PROV,
    )


def _track(positions: list[tuple[float, float]], *, minutes: float = 5.0) -> SourceTrack:
    epochs = [
        EpochDetection(i, _T0 + timedelta(minutes=minutes * i), "L", "p", _detection(i, ra, dec))
        for i, (ra, dec) in enumerate(positions)
    ]
    result = group_detections_into_tracks(epochs, observation_id="OBS", match_radius_arcsec=30.0)
    assert result.grouped, result.ungrouped_reason
    assert len(result.tracks) == 1
    return result.tracks[0]


def test_static_source_across_three_epochs_is_not_declared_moving():
    track = _track([(10.0, 41.0), (10.0, 41.0), (10.0, 41.0)])
    result = analyze_motion(track, detection_id="D0")
    assert result.pm_total.is_available
    assert result.pm_total.value == 0.0
    assert result.moving_source_candidate is False


def test_linear_asteroid_without_registration_reference_is_not_flagged_but_reports_displacement():
    # Una trayectoria perfectamente lineal da residuo de ajuste EXACTAMENTE
    # cero -- ese es el caso límite que antes se confundía con "no se mueve".
    # Sin una referencia externa de error de posición, la significancia no
    # se puede establecer, pero el desplazamiento medido se reporta igual.
    step_deg = 2.0 / 3600.0 / 0.754  # 2"/época en RA a dec=41 (cos 41 = 0.754)
    positions = [(10.0 + i * step_deg, 41.0) for i in range(3)]
    track = _track(positions)
    result = analyze_motion(track, detection_id="D0")
    assert result.pm_total.is_available
    assert result.pm_total.value > 0.0
    assert result.pm_total.error is None
    assert result.moving_source_candidate is False
    assert "por ausencia de desplazamiento" in " ".join(result.pm_total.notes)


def test_linear_asteroid_with_registration_rms_is_flagged_moving():
    # El mismo asteroide, pero ahora con un RMS de registro real conocido:
    # con eso sí se puede calcular una significancia y declarar movimiento.
    step_deg = 2.0 / 3600.0 / 0.754
    positions = [(10.0 + i * step_deg, 41.0) for i in range(3)]
    track = _track(positions)
    result = analyze_motion(track, detection_id="D0", registration_rms_arcsec=0.3)
    assert result.pm_total.is_available
    assert result.pm_total.error is not None
    assert result.pm_total.error > 0.0
    assert result.moving_source_candidate is True


def test_noisy_scatter_without_linear_trend_is_not_flagged_moving():
    # Dispersión de registro sin tendencia real: el ajuste tiene residuo
    # significativo y la pendiente no debe superar el umbral de significancia.
    positions = [(10.0, 41.0), (10.00002, 41.00001), (9.99998, 41.00002)]
    track = _track(positions)
    result = analyze_motion(track, detection_id="D0")
    assert result.pm_total.is_available
    assert result.moving_source_candidate is False


def test_two_epochs_without_registration_reference_is_not_available():
    track = _track([(10.0, 41.0), (10.001, 41.0)])
    result = analyze_motion(track, detection_id="D0")
    assert not result.pm_total.is_available
    assert "RMS de registro" in result.pm_total.reference


def test_two_epochs_with_registration_reference_measures_displacement():
    track = _track([(10.0, 41.0), (10.001, 41.0)])
    result = analyze_motion(track, detection_id="D0", registration_rms_arcsec=0.05)
    assert result.pm_total.is_available
    assert result.pm_total.error is not None
    assert result.moving_source_candidate is True


def test_single_epoch_track_is_not_available_with_reason():
    epochs = [EpochDetection(0, _T0, "L", "p", _detection(0, 10.0, 41.0))]
    tracking = group_detections_into_tracks(epochs, observation_id="OBS")
    assert len(tracking.tracks) == 1  # una traza de una sola época: resultado válido, no se descarta
    result = analyze_motion(tracking.tracks[0], detection_id="D0")
    assert not result.pm_total.is_available
    assert "época" in result.pm_total.reference


def test_roundtrip():
    track = _track([(10.0, 41.0), (10.0, 41.0), (10.0, 41.0)])
    result = analyze_motion(track, detection_id="D0")
    assert MotionEvidence.from_dict(result.to_dict()) == result


def test_provenance_carries_the_real_pipeline_version_and_engine():
    # Antes de este cierre, `analyze_motion` recibía `pipeline_version`
    # y lo descartaba explícitamente (`del pipeline_version`) porque
    # `MotionEvidence` no tenía dónde ponerlo -- ahora debe llegar real
    # hasta el resultado.
    track = _track([(10.0, 41.0), (10.0, 41.0), (10.0, 41.0)])
    result = analyze_motion(track, detection_id="D0", pipeline_version="v9.9.9-test")
    assert result.provenance.pipeline_version == "v9.9.9-test"
    assert result.provenance.engine == "temporal.motion"
    assert result.provenance.produced_at is not None


def test_provenance_is_present_even_when_the_result_is_not_available():
    # "No disponible" es igual de real que una medida positiva -- también
    # debe llevar procedencia, nunca solo las medidas que "salieron bien".
    epochs = [EpochDetection(0, _T0, "L", "p", _detection(0, 10.0, 41.0))]
    tracking = group_detections_into_tracks(epochs, observation_id="OBS")
    result = analyze_motion(tracking.tracks[0], detection_id="D0", pipeline_version="v1")
    assert not result.pm_total.is_available
    assert result.provenance.pipeline_version == "v1"
    assert result.provenance.engine == "temporal.motion"
