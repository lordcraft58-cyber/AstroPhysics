"""La lógica de clasificación (classify_against_gaia_neighbors) es pura y
no necesita red -- se prueba exhaustivamente aquí. query_gaia_neighbors
sí necesita red real a Gaia; ver test_gaia_network.py, que se salta si no
hay conectividad (en este entorno de desarrollo el host de Gaia no está
en la lista de permitidos del proxy)."""
from __future__ import annotations

from astrophysics_suite.catalogs.gaia import classify_against_gaia_neighbors
from astrophysics_suite.core.enums import IdentificationState
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.models.detection import Detection, MorphologyClass, MorphologySummary, SkyPosition


def _detection_with_sky(ra_deg=280.0, dec_deg=38.0) -> Detection:
    return Detection.create(
        detection_id="DET-0001",
        observation_id="OBS-0001",
        position=SkyPosition(x_px=100.0, y_px=100.0, ra_deg=ra_deg, dec_deg=dec_deg),
        morphology=MorphologySummary(morphology_class=MorphologyClass.POINT_SOURCE, area_px=20.0, elongation=1.1, compactness=0.5),
        bands=("OIII",),
        peak_snr=10.0,
        method="test",
        provenance=Provenance.now(pipeline_version="test", engine="test", engine_version="1.0"),
    )


def test_no_sky_coordinates_goes_to_discovery_review():
    d = Detection.create(
        detection_id="DET-0001",
        observation_id="OBS-0001",
        position=SkyPosition(x_px=10.0, y_px=10.0),  # sin WCS
        morphology=MorphologySummary(morphology_class=MorphologyClass.POINT_SOURCE, area_px=20.0, elongation=1.1, compactness=0.5),
        bands=("OIII",),
        peak_snr=10.0,
        method="test",
        provenance=Provenance.now(pipeline_version="test", engine="test", engine_version="1.0"),
    )
    state, matches, non_matches = classify_against_gaia_neighbors(d, [{"ra_deg": 1.0, "dec_deg": 1.0, "source_id": "x"}])
    assert state is IdentificationState.DISCOVERY_REVIEW
    assert matches == ()
    assert non_matches[0].reason.startswith("sin coordenadas")


def test_no_gaia_rows_is_unmatched():
    d = _detection_with_sky()
    state, matches, non_matches = classify_against_gaia_neighbors(d, [])
    assert state is IdentificationState.UNMATCHED
    assert matches == ()
    assert len(non_matches) == 1


def test_close_gaia_source_is_known():
    d = _detection_with_sky(ra_deg=280.0, dec_deg=38.0)
    gaia_rows = [{"ra_deg": 280.0 + 0.0001, "dec_deg": 38.0, "source_id": "12345", "mag_g": 15.2}]
    state, matches, non_matches = classify_against_gaia_neighbors(d, gaia_rows, match_radius_arcsec=3.0)
    assert state is IdentificationState.KNOWN
    assert len(matches) == 1
    assert matches[0].catalog_id == "12345"
    assert matches[0].magnitude.value == 15.2
    assert non_matches == ()


def test_far_gaia_source_is_unmatched_not_known():
    d = _detection_with_sky(ra_deg=280.0, dec_deg=38.0)
    gaia_rows = [{"ra_deg": 280.5, "dec_deg": 38.5, "source_id": "99999", "mag_g": 12.0}]  # muy lejos
    state, matches, non_matches = classify_against_gaia_neighbors(d, gaia_rows, match_radius_arcsec=3.0)
    assert state is IdentificationState.UNMATCHED
    assert matches == ()


def test_picks_closest_of_several_candidates():
    d = _detection_with_sky(ra_deg=280.0, dec_deg=38.0)
    gaia_rows = [
        {"ra_deg": 280.0 + 0.002, "dec_deg": 38.0, "source_id": "far", "mag_g": 14.0},
        {"ra_deg": 280.0 + 0.0002, "dec_deg": 38.0, "source_id": "near", "mag_g": 16.0},
    ]
    state, matches, _ = classify_against_gaia_neighbors(d, gaia_rows, match_radius_arcsec=5.0)
    assert state is IdentificationState.KNOWN
    assert matches[0].catalog_id == "near"
