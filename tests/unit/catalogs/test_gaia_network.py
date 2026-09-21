"""Prueba de red real contra el servicio Gaia TAP+.

Se salta explícitamente si la consulta real falla por falta de
conectividad -- no es una razón para fallar la suite, es una limitación
conocida del entorno donde se ejecute. Nota: una comprobación previa por
socket TCP no basta para detectar esto de forma fiable en entornos con
proxy de salida (el proxy puede aceptar la conexión TCP y aun así
devolver un 403 a nivel HTTP para hosts fuera de su lista de permitidos,
como se observó en este entorno de desarrollo) -- por eso cada test
intenta la consulta real y se salta si falla, en vez de precomprobar
la conectividad por separado.
"""
from __future__ import annotations

import pytest

from astrophysics_suite.catalogs.gaia import identify_detection, query_gaia_neighbors
from astrophysics_suite.core.enums import IdentificationState
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.models.detection import Detection, MorphologyClass, MorphologySummary, SkyPosition


def _skip_if_gaia_unreachable(rows: list) -> None:
    if not rows:
        pytest.skip("consulta a Gaia devolvió vacío -- probablemente sin conectividad real (host fuera de la lista de permitidos del proxy de red)")


def test_query_gaia_neighbors_against_a_known_bright_field():
    # M13 (NGC 6205), un campo denso -- debe devolver al menos una fuente
    # si la consulta real llega a completarse.
    rows = query_gaia_neighbors(250.4235, 36.4613, radius_arcsec=30.0, mag_limit=18.0, max_rows=25)
    _skip_if_gaia_unreachable(rows)
    assert "source_id" in rows[0] and "ra_deg" in rows[0]


def test_identify_detection_end_to_end():
    detection = Detection.create(
        detection_id="DET-0001",
        observation_id="OBS-0001",
        position=SkyPosition(x_px=1.0, y_px=1.0, ra_deg=250.4235, dec_deg=36.4613),
        morphology=MorphologySummary(morphology_class=MorphologyClass.POINT_SOURCE, area_px=10.0, elongation=1.0, compactness=0.5),
        bands=("OIII",),
        peak_snr=10.0,
        method="test",
        provenance=Provenance.now(pipeline_version="test", engine="test", engine_version="1.0"),
    )
    probe_rows = query_gaia_neighbors(250.4235, 36.4613, radius_arcsec=30.0, mag_limit=18.0, max_rows=1)
    _skip_if_gaia_unreachable(probe_rows)

    state, matches, non_matches = identify_detection(detection, match_radius_arcsec=30.0)
    assert state in set(IdentificationState)
    assert bool(matches) != bool(non_matches), "debe haber exactamente match o no-match, nunca ambos ni ninguno"


def test_identify_detection_reaches_discovery_review_not_unmatched_when_gaia_really_unreachable():
    """Confirma contra la condición de red REAL de este entorno (Gaia
    bloqueada por la política de salida del sandbox) que
    `identify_detection` degrada a DISCOVERY_REVIEW, nunca a UNMATCHED --
    bug real encontrado probando con FITS de M 31 reales (ver
    tests/unit/catalogs/test_gaia.py y
    docs/audit/34-PRUEBAS-CON-FITS-REALES.md). Si el entorno donde corre
    esto SÍ tiene red real hacia Gaia, esta prueba se salta -- no es su
    propósito verificar el camino feliz (ya cubierto por
    test_identify_detection_end_to_end)."""
    detection = Detection.create(
        detection_id="DET-0002",
        observation_id="OBS-0001",
        position=SkyPosition(x_px=1.0, y_px=1.0, ra_deg=10.9131301993, dec_deg=41.2120838282),  # M 31, campo real
        morphology=MorphologySummary(morphology_class=MorphologyClass.POINT_SOURCE, area_px=10.0, elongation=1.0, compactness=0.5),
        bands=("L",),
        peak_snr=10.0,
        method="test",
        provenance=Provenance.now(pipeline_version="test", engine="test", engine_version="1.0"),
    )
    probe_rows = query_gaia_neighbors(10.9131301993, 41.2120838282, radius_arcsec=60.0, mag_limit=20.0, max_rows=1)
    if probe_rows:
        pytest.skip("Gaia respondió de verdad en este entorno -- esta prueba solo cubre el camino sin red")

    state, matches, non_matches = identify_detection(detection, match_radius_arcsec=3.0)
    assert state is IdentificationState.DISCOVERY_REVIEW
    assert matches == ()
    assert non_matches[0].reason.startswith("Gaia no disponible")
