"""Prueba end-to-end (no simulada) de photometry/quality.py: FITS
sintético real con una fuente inyectada, medida con measure_source_quality
heredado y traducida a CharacterizationResult."""
from __future__ import annotations

import numpy as np

from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.io.fits_loader import load_image
from astrophysics_suite.models.detection import Detection, MorphologyClass, MorphologySummary, SkyPosition
from astrophysics_suite.photometry.quality import characterize_point_source
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d


def _detection_at(x, y) -> Detection:
    return Detection.create(
        detection_id="DET-0001",
        observation_id="OBS-0001",
        position=SkyPosition(x_px=x, y_px=y),
        morphology=MorphologySummary(morphology_class=MorphologyClass.POINT_SOURCE, area_px=10.0, elongation=1.0, compactness=0.5),
        bands=("HA",),
        peak_snr=10.0,
        method="test",
        provenance=Provenance.now(pipeline_version="test", engine="test", engine_version="1.0"),
    )


def _star_field(shape, x, y, amplitude=900.0, sigma=2.2, background=100.0):
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    field = background + amplitude * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma**2))
    return field.astype(np.float32)


def test_characterize_point_source_measures_real_fwhm(tmp_path):
    field = _star_field((64, 64), 32, 32, sigma=2.2)
    path = tmp_path / "field_HA.fits"
    _write_minimal_fits_2d(path, field)
    loaded = load_image(str(path), band="HA")

    result = characterize_point_source(loaded, _detection_at(32, 32))

    assert result.fwhm is not None
    assert result.fwhm.kind is ValueKind.OBSERVED
    # sigma=2.2 -> FWHM teórico = 2.3548*sigma ~= 5.18 px; tolerancia amplia
    # porque la medida heredada usa una caja recortada y ruido de fondo cero.
    assert 3.0 < result.fwhm.value < 8.0
    assert result.elongation is not None
    # Fuente sintética perfectamente circular: elongación debe ser ~1.0.
    assert 0.9 < result.elongation.value < 1.3


def test_characterize_point_source_reports_not_available_when_cutout_too_small(tmp_path):
    field = _star_field((64, 64), 32, 32)
    path = tmp_path / "field_HA.fits"
    _write_minimal_fits_2d(path, field)
    loaded = load_image(str(path), band="HA")

    # cutout_size=3 -> recorte de 3x3, por debajo del mínimo de 5x5 que
    # exige measure_source_quality ("Cutout demasiado pequeño").
    result = characterize_point_source(loaded, _detection_at(32, 32), cutout_size=3)

    assert result.fwhm is None
    assert "quality_measurement" in result.extra
    assert not result.extra["quality_measurement"].is_available
