"""La lógica de clasificación (classify_against_gaia_neighbors) es pura y
no necesita red -- se prueba exhaustivamente aquí. query_gaia_neighbors
sí necesita red real a Gaia; ver test_gaia_network.py, que se salta si no
hay conectividad (en este entorno de desarrollo el host de Gaia no está
en la lista de permitidos del proxy)."""
from __future__ import annotations

from astrophysics_suite.catalogs.gaia import classify_against_gaia_neighbors, identify_detection
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


def test_no_gaia_rows_when_gaia_unavailable_is_discovery_review_not_unmatched():
    """Bug real encontrado probando con FITS de M 31 reales en un entorno
    sin red hacia Gaia: sin este distingo, 141 candidatos reales salían
    UNMATCHED aunque Gaia nunca respondió -- una afirmación falsa que
    confunde "no se pudo consultar" con "se consultó y no había nada"."""
    d = _detection_with_sky()
    state, matches, non_matches = classify_against_gaia_neighbors(
        d, [], gaia_available=False, gaia_unavailable_detail="Error 403: Host not in allowlist",
    )
    assert state is IdentificationState.DISCOVERY_REVIEW
    assert matches == ()
    assert non_matches[0].reason.startswith("Gaia no disponible")
    assert "403" in non_matches[0].reason


def test_gaia_rows_present_is_still_classified_normally_even_if_gaia_available_is_false():
    """`gaia_available=False` solo importa cuando la lista viene vacía --
    si de alguna forma sí hay filas (p. ej. una llamada anterior en el
    mismo hilo que sí funcionó), la clasificación real de esas filas
    manda, nunca se descarta por la bandera."""
    d = _detection_with_sky(ra_deg=280.0, dec_deg=38.0)
    gaia_rows = [{"ra_deg": 280.0 + 0.0001, "dec_deg": 38.0, "source_id": "12345", "mag_g": 15.2}]
    state, matches, _ = classify_against_gaia_neighbors(d, gaia_rows, match_radius_arcsec=3.0, gaia_available=False)
    assert state is IdentificationState.KNOWN
    assert matches[0].catalog_id == "12345"


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


def test_identify_detection_does_not_leak_unavailable_state_from_a_previous_real_call(monkeypatch):
    """Bug real encontrado ejecutando la suite completa tras arreglar
    UNMATCHED-vs-DISCOVERY_REVIEW: `last_gaia_availability()` es un
    estado por HILO, no por llamada -- sin reiniciarlo al empezar
    `identify_detection`, una llamada real anterior en el mismo hilo que
    dejó `available=False` puesto (p. ej. otra detección de la misma
    tanda, o incluso otra prueba en el mismo proceso de pytest, que
    corren en el mismo hilo principal salvo que usen un hilo de fondo
    real) contaminaba silenciosamente esta llamada aunque
    `query_gaia_neighbors` estuviera sustituida por un doble que nunca
    toca ese estado."""
    import astrophysics_suite.catalogs.gaia as gaia_module

    # Simula el residuo real: una llamada previa en este mismo hilo dejó
    # el estado marcado como "Gaia no disponible".
    gaia_module._gaia_availability_state.available = False
    gaia_module._gaia_availability_state.detail = "residuo de una prueba anterior"

    d = _detection_with_sky(ra_deg=280.0, dec_deg=38.0)
    monkeypatch.setattr(gaia_module, "query_gaia_neighbors", lambda *a, **k: [])

    state, matches, non_matches = identify_detection(d, match_radius_arcsec=3.0)

    assert state is IdentificationState.UNMATCHED, (
        "un doble simula 'Gaia respondió, lista vacía' -- el residuo de una llamada real "
        f"anterior en el mismo hilo no debe filtrarse aquí (estado real: {state}, razón: {non_matches[0].reason if non_matches else None})"
    )
