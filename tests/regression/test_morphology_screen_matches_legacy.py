"""`artifacts/morphology_screen.classify_morphology` debe producir
EXACTAMENTE lo mismo que `legacy..._label_discovery_morphology`: misma
cadena de umbrales, mismo (state, reason) -- byte a byte, sin ninguna
excepción (a diferencia de la migración de Detection, aquí no hay
ningún cálculo con unidades que corregir, solo comparaciones directas
sobre escalares ya medidos). Esta es la prueba que autoriza a que
`morphology_screen.py` deje de depender de
`legacy.AstroPhysicsSuite_v57_3_COMMERCIAL` (informe 87, cierre del
motor de rechazo de artefactos).
"""
from __future__ import annotations

import itertools

import pytest

from astrophysics_suite.artifacts.morphology_screen import classify_morphology
from astrophysics_suite.core.enums import MorphologyClass
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.models.detection import Detection, MorphologySummary, SkyPosition
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _label_discovery_morphology as _legacy_classify

# Barrido de todos los cruces de umbral reales del clasificador legado
# (elongación 8.0, área 2.0, S/N 4.0, elongación 2.5 + compactness 0.18)
# más valores claramente a cada lado -- no solo el caso feliz.
_AREAS = (1.0, 2.0, 2.1, 50.0)
_ELONGATIONS = (1.0, 2.5, 2.6, 7.9, 8.0, 9.0)
_COMPACTNESSES = (0.05, 0.17, 0.18, 0.19, 0.5)
_PEAK_SNRS = (1.0, 3.9, 4.0, 4.1, 20.0)


def _detection(*, area_px, elongation, compactness, peak_snr) -> Detection:
    return Detection.create(
        detection_id="DET-REGRESSION",
        observation_id="OBS-REGRESSION",
        position=SkyPosition(x_px=1.0, y_px=1.0),
        morphology=MorphologySummary(
            morphology_class=MorphologyClass.POINT_SOURCE, area_px=area_px, elongation=elongation, compactness=compactness,
        ),
        bands=("HA",),
        peak_snr=peak_snr,
        method="test",
        provenance=Provenance.now(pipeline_version="test", engine="test", engine_version="1.0"),
    )


@pytest.mark.parametrize("area,elongation,compactness,peak_snr", list(itertools.product(_AREAS, _ELONGATIONS, _COMPACTNESSES, _PEAK_SNRS)))
def test_classify_morphology_matches_legacy_across_every_threshold_crossing(area, elongation, compactness, peak_snr):
    detection = _detection(area_px=area, elongation=elongation, compactness=compactness, peak_snr=peak_snr)

    native_state, native_reason = classify_morphology(detection)
    legacy_state, legacy_reason = _legacy_classify(area, elongation, compactness, peak_snr)

    assert native_state == legacy_state
    assert native_reason == legacy_reason


def test_classify_morphology_matches_legacy_for_a_non_finite_measurement():
    detection = _detection(area_px=float("nan"), elongation=1.0, compactness=0.3, peak_snr=10.0)

    native_state, native_reason = classify_morphology(detection)
    legacy_state, legacy_reason = _legacy_classify(float("nan"), 1.0, 0.3, 10.0)

    assert native_state == legacy_state == "QUALITY_LIMITED"
    assert native_reason == legacy_reason
