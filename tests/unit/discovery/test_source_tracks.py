from __future__ import annotations

from datetime import datetime, timedelta, timezone

from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.discovery.source_tracks import EpochDetection, group_detections_into_tracks
from astrophysics_suite.models.detection import Detection, MorphologyClass, MorphologySummary, SkyPosition

_PROV = Provenance.now(pipeline_version="t", engine="t", engine_version="1.0")
_T0 = datetime(2026, 9, 10, 20, 0, 0, tzinfo=timezone.utc)


def _detection(index: int, ra: float | None, dec: float | None, *, x_px: float = 10.0, snr: float = 20.0) -> Detection:
    return Detection.create(
        detection_id=f"D{index}",
        observation_id="O",
        position=SkyPosition(x_px=x_px + index, y_px=10.0, ra_deg=ra, dec_deg=dec),
        morphology=MorphologySummary(morphology_class=MorphologyClass.POINT_SOURCE, area_px=9.0, elongation=1.1, compactness=0.6),
        bands=("L",),
        peak_snr=snr,
        method="test",
        provenance=_PROV,
    )


def _epoch(index: int, ra: float | None, dec: float | None, *, minutes: float = 5.0, snr: float = 20.0) -> EpochDetection:
    return EpochDetection(index, _T0 + timedelta(minutes=minutes * index), "L", "p", _detection(index, ra, dec, snr=snr))


def test_same_source_across_three_epochs_groups_into_one_track():
    epochs = [_epoch(i, 10.0, 41.0) for i in range(3)]
    result = group_detections_into_tracks(epochs, observation_id="OBS")
    assert result.grouped
    assert len(result.tracks) == 1
    assert result.tracks[0].n_epochs == 3


def test_two_distinct_sources_never_merge_into_the_same_track():
    # Dos fuentes reales en la época 0, muy separadas entre sí; en la época 1
    # solo aparece la primera (p.ej. la segunda estaba fuera del campo por
    # dithering). Una traza NUNCA puede contener dos detecciones de la MISMA
    # época -- ese es el guard que evita fundir dos fuentes distintas.
    epochs = [
        _epoch(0, 10.0, 41.0),  # fuente A, época 0
        EpochDetection(0, _T0, "L", "p", _detection(1, 10.05, 41.0)),  # fuente B, época 0, muy separada
        EpochDetection(1, _T0 + timedelta(minutes=5), "L", "p", _detection(2, 10.0002, 41.0001)),  # fuente A, época 1
    ]
    result = group_detections_into_tracks(epochs, observation_id="OBS", match_radius_arcsec=2.0)
    assert result.grouped
    assert len(result.tracks) == 2
    epoch_counts = sorted(track.n_epochs for track in result.tracks)
    assert epoch_counts == [1, 2]
    # Ninguna traza puede tener dos observaciones con el mismo epoch_index.
    for track in result.tracks:
        indices = [obs.epoch_index for obs in track.observations]
        assert len(indices) == len(set(indices))


def test_dithered_epochs_still_match_within_radius():
    # Las tres tomas reales de M31 están desplazadas entre sí por dithering:
    # el emparejamiento debe seguir funcionando con un pequeño desplazamiento
    # dentro del radio, no solo con coordenadas idénticas.
    epochs = [
        _epoch(0, 10.0, 41.0),
        EpochDetection(1, _T0 + timedelta(minutes=5), "L", "p", _detection(1, 10.0002, 41.0001)),
        EpochDetection(2, _T0 + timedelta(minutes=10), "L", "p", _detection(2, 9.9998, 41.0002)),
    ]
    result = group_detections_into_tracks(epochs, observation_id="OBS", match_radius_arcsec=3.0)
    assert result.grouped
    assert len(result.tracks) == 1
    assert result.tracks[0].n_epochs == 3


def test_missing_sky_coordinates_refuses_grouping_explicitly():
    epochs = [_epoch(i, None, None) for i in range(3)]
    result = group_detections_into_tracks(epochs, observation_id="OBS")
    assert not result.grouped
    assert "coordenadas celestes" in result.ungrouped_reason
    # Cada detección queda como su propia traza de una época, no se descarta.
    assert len(result.tracks) == 3
    assert all(track.n_epochs == 1 for track in result.tracks)


def test_single_epoch_is_a_valid_ungrouped_result():
    epochs = [_epoch(0, 10.0, 41.0)]
    result = group_detections_into_tracks(epochs, observation_id="OBS")
    assert not result.grouped
    assert "una época" in result.ungrouped_reason
    assert len(result.tracks) == 1


def test_reference_picks_highest_snr_observation():
    epochs = [
        _epoch(0, 10.0, 41.0, snr=5.0),
        EpochDetection(1, _T0 + timedelta(minutes=5), "L", "p", _detection(1, 10.0, 41.0, snr=50.0)),
    ]
    result = group_detections_into_tracks(epochs, observation_id="OBS")
    assert result.tracks[0].reference.detection.peak_snr == 50.0


def test_position_scatter_is_none_with_a_single_epoch():
    epochs = [_epoch(0, 10.0, 41.0)]
    result = group_detections_into_tracks(epochs, observation_id="OBS")
    assert result.tracks[0].position_scatter_arcsec() is None


def test_position_scatter_reflects_real_dispersion():
    epochs = [
        _epoch(0, 10.0, 41.0),
        EpochDetection(1, _T0 + timedelta(minutes=5), "L", "p", _detection(1, 10.001, 41.0)),
    ]
    result = group_detections_into_tracks(epochs, observation_id="OBS", match_radius_arcsec=5.0)
    scatter = result.tracks[0].position_scatter_arcsec()
    assert scatter is not None
    assert scatter > 0.0
