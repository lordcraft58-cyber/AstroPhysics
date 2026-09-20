"""Un WCS guardado en un FITS dice de qué motor salió -- y qué no mide.

Antes, la copia con WCS se escribía desde la ventana Qt con las tarjetas
construidas a mano, y la línea `HISTORY` nombraba siempre
`astrometry.wcs_fit` aunque la placa se hubiera resuelto en ciego.
"""
from __future__ import annotations

import re

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS

from astrophysics_suite.astrometry.optical_wcs import build_wcs_from_optics
from astrophysics_suite.astrometry.provenance import (
    MIN_STARS_FOR_MEANINGFUL_RMS,
    SOURCE_BLIND_SOLVE,
    SOURCE_MANUAL_FIT,
    SOURCE_OPTICS,
    SOURCE_PLATE_SOLVE,
    WCSRecord,
    build_wcs_provenance,
    is_wcs_keyword,
    strip_wcs_keywords,
    wcs_header_cards,
)
from astrophysics_suite.astrometry.wcs_fit import WCSSolution, angular_separation_deg, fit_wcs
from astrophysics_suite.io.fits_writer import save_fits_image

def _history_text(header_or_cards) -> str:
    """Las tarjetas `HISTORY` se parten a 72 caracteres, así que una
    frase puede quedar repartida entre dos líneas. Se rejuntan y se
    normalizan los espacios antes de buscar nada en ellas."""
    lines = header_or_cards["HISTORY"]
    return re.sub(r"\s+", " ", " ".join(str(line).strip() for line in lines))


# WCS real del usuario: ASI533MC Pro (3.76 um) a 749 mm sobre M 31.
SHAPE = (3008, 3008)
CENTER = (10.6847, 41.2687)
SCALE_ARCSEC = 1.0355


def _optical_solution() -> WCSSolution:
    return build_wcs_from_optics(
        center_ra_deg=CENTER[0], center_dec_deg=CENTER[1],
        pixel_scale_arcsec=SCALE_ARCSEC, image_shape=SHAPE,
    )


def _measured_solution(n_stars: int, noise_px: float = 0.4, seed: int = 7) -> WCSSolution:
    """Ajuste real sobre estrellas con error de centroide real."""
    rng = np.random.default_rng(seed)
    truth = _optical_solution()
    xy = rng.uniform(200, SHAPE[1] - 200, size=(n_stars, 2))
    sky = [truth.pixel_to_sky(x, y) for x, y in xy]
    noisy = xy + rng.normal(0.0, noise_px, size=(n_stars, 2))
    return fit_wcs([tuple(p) for p in noisy], sky, crpix_px=(SHAPE[1] / 2.0, SHAPE[0] / 2.0))


def test_the_file_names_the_engine_that_really_solved_it():
    for source in (SOURCE_PLATE_SOLVE, SOURCE_BLIND_SOLVE, SOURCE_MANUAL_FIT):
        record = WCSRecord(solution=_measured_solution(8), source=source)
        cards = wcs_header_cards(record)
        assert cards["APSWCSRC"] == source
        history = _history_text(cards)
        assert source in history
        # y NO el de otro motor cualquiera
        others = {SOURCE_PLATE_SOLVE, SOURCE_BLIND_SOLVE, SOURCE_MANUAL_FIT} - {source}
        assert not any(other in history for other in others)


def test_an_optical_wcs_never_claims_a_perfect_fit():
    """`build_wcs_from_optics` deja `rms=0.0` y `n_stars=0` a propósito.
    Volcarlos a la cabecera escribiría `WCSRMS = 0.0`, que cualquier
    lector entendería como un ajuste perfecto."""
    record = WCSRecord(
        solution=_optical_solution(), source=SOURCE_OPTICS,
        optics_description="ZWO ASI533MC Pro (3.76 um) a 749 mm",
    )
    assert record.is_measured is False

    cards = wcs_header_cards(record)
    assert "WCSRMS" not in cards
    assert "WCSNSTR" not in cards
    assert cards["APSWCSMD"] is False
    history = _history_text(cards)
    assert "sin ajuste contra estrellas" in history
    assert "749 mm" in history


def test_a_measured_wcs_does_report_its_quality():
    record = WCSRecord(solution=_measured_solution(12), source=SOURCE_PLATE_SOLVE, catalog="Gaia DR3")
    cards = wcs_header_cards(record)
    assert cards["APSWCSMD"] is True
    assert cards["WCSNSTR"] == 12
    assert cards["WCSRMS"] > 0.0
    assert cards["APSWCSCT"] == "Gaia DR3"


def test_the_pixel_scale_written_is_the_one_the_matrix_really_implies():
    record = WCSRecord(solution=_optical_solution(), source=SOURCE_OPTICS)
    assert wcs_header_cards(record)["APSWCSSC"] == pytest.approx(SCALE_ARCSEC, abs=1e-4)


def test_a_three_star_fit_is_warned_about_because_its_rms_is_a_lie():
    """Medido, no supuesto: ver `MIN_STARS_FOR_MEANINGFUL_RMS`."""
    record = WCSRecord(solution=_measured_solution(3), source=SOURCE_MANUAL_FIT)
    warnings = build_wcs_provenance(record).warnings
    assert any("no mide el error real" in w for w in warnings)

    plenty = WCSRecord(solution=_measured_solution(12), source=SOURCE_MANUAL_FIT)
    assert build_wcs_provenance(plenty).warnings == ()


def test_the_three_star_rms_really_does_understate_the_error():
    """El aviso anterior solo vale si el hecho que denuncia es cierto.
    Con el mismo ruido de centroide, 3 estrellas declaran un RMS
    órdenes de magnitud menor que el error real, y 12 no."""
    truth = _optical_solution()
    center = (SHAPE[1] / 2.0, SHAPE[0] / 2.0)

    def median_ratio(n_stars: int) -> float:
        ratios = []
        for seed in range(60):
            solution = _measured_solution(n_stars, seed=1000 + seed)
            fitted = solution.pixel_to_sky(*center)
            real = truth.pixel_to_sky(*center)
            true_error = angular_separation_deg(*fitted, *real) * 3600.0
            ratios.append(true_error / max(solution.rms_residual_arcsec, 1e-12))
        return float(np.median(ratios))

    assert median_ratio(3) > 20.0  # el RMS queda MUY por debajo del error real
    assert median_ratio(12) < 2.0  # con estrellas de sobra ya es del orden correcto
    assert MIN_STARS_FOR_MEANINGFUL_RMS == 4


def test_provenance_of_an_optical_wcs_says_what_it_cannot_guarantee():
    record = WCSRecord(solution=_optical_solution(), source=SOURCE_OPTICS)
    provenance = build_wcs_provenance(record, pipeline_version="test")
    assert provenance.engine == SOURCE_OPTICS
    joined = " ".join(provenance.warnings)
    assert "la escala es exacta" in joined
    assert "el centro y la rotación" in joined


def test_the_cards_round_trip_as_a_real_wcs_through_a_real_file(tmp_path):
    """Lo que de verdad importa: que otro programa cualquiera relea el
    WCS y apunte al mismo sitio del cielo."""
    solution = _measured_solution(10)
    record = WCSRecord(solution=solution, source=SOURCE_BLIND_SOLVE, catalog="Gaia DR3", n_matched_stars=10)
    provenance = build_wcs_provenance(record, pipeline_version="test")
    path = tmp_path / "con_wcs.fits"

    save_fits_image(str(path), np.zeros((64, 64), dtype=np.float32),
                    header=wcs_header_cards(record, provenance=provenance))

    with fits.open(path) as hdul:
        header = hdul[0].header
        assert header["APSWCS"] is True
        assert header["APSWCSRC"] == SOURCE_BLIND_SOLVE
        assert header["APSWCSNM"] == 10
        assert "APSWCSDT" in header

        # el WCS releído por astropy apunta a donde apunta la solución
        reread = WCS(header, naxis=2)
        for x_px, y_px in ((0.0, 0.0), (1504.0, 1504.0), (3007.0, 512.0)):
            ra_ref, dec_ref = solution.pixel_to_sky(x_px, y_px)
            ra_file, dec_file = reread.all_pix2world([[x_px, y_px]], 0)[0]
            assert angular_separation_deg(ra_ref, dec_ref, ra_file, dec_file) * 3600.0 < 1e-6

        history = _history_text(header)
        assert SOURCE_BLIND_SOLVE in history
        assert "Gaia DR3" in history


# Cabecera REAL de un LIGHT de M 31 del usuario: el ASIAIR Mini ya había
# resuelto la placa y dejó una solución TAN-SIP completa dentro.
_REAL_ASIAIR_SOLVED_HEADER = {
    "OBJECT": "M 31", "INSTRUME": "ZWO ASI533MC Pro", "FOCALLEN": 749, "EXPTIME": 300.0,
    "CTYPE1": "RA---TAN-SIP", "CTYPE2": "DEC--TAN-SIP",
    "CRPIX1": 2742.23504639, "CRPIX2": 1803.1729126,
    "CRVAL1": 11.1796601226, "CRVAL2": 41.1564927933,
    "CD1_1": 0.00024526073423, "CD1_2": 0.000149811575305,
    "CD2_1": -0.000149725811201, "CD2_2": 0.000245166648117,
    "A_ORDER": 2, "A_0_2": 8.85419124639e-08, "A_1_1": -1.80429583591e-08, "A_2_0": -1.71420952156e-07,
    "B_ORDER": 2, "B_0_2": -2.33170271127e-08, "B_1_1": -1.03548257795e-07, "B_2_0": 1.4898448321e-07,
    "AP_ORDER": 2, "AP_0_0": -5.88806080492e-05, "AP_1_1": 1.7978765818e-08,
    "BP_ORDER": 2, "BP_0_0": 3.16252687371e-05, "BP_1_1": 1.03487034533e-07,
    "WCSRMS": 0.42, "WCSNSTR": 33, "APSWCSRC": "astrometry.plate_solve",
}


def test_stripping_removes_every_wcs_card_and_nothing_else():
    cleaned = strip_wcs_keywords(_REAL_ASIAIR_SOLVED_HEADER)

    for key in _REAL_ASIAIR_SOLVED_HEADER:
        if key in ("OBJECT", "INSTRUME", "FOCALLEN", "EXPTIME"):
            continue
        assert key not in cleaned, f"{key} describe la solución anterior y debe desaparecer"

    # los metadatos reales de la observación no son WCS: se quedan
    assert cleaned["OBJECT"] == "M 31"
    assert cleaned["INSTRUME"] == "ZWO ASI533MC Pro"
    assert cleaned["FOCALLEN"] == 749
    assert cleaned["EXPTIME"] == 300.0
    # y no muta la original
    assert "A_ORDER" in _REAL_ASIAIR_SOLVED_HEADER


def test_focallen_is_not_mistaken_for_a_wcs_card():
    """`FOCALLEN` empieza por las mismas letras que nada, pero
    `CDELT`/`CD1_1` sí se parecen a otras claves reales."""
    assert is_wcs_keyword("CD1_1") is True
    assert is_wcs_keyword("CDELT1") is True
    assert is_wcs_keyword("A_2_0") is True
    assert is_wcs_keyword("PV2_1") is True
    for safe in ("FOCALLEN", "APERTURE", "CCD-TEMP", "BAYERPAT", "DATE-OBS", "AIRMASS", "CREATOR", "XPIXSZ"):
        assert is_wcs_keyword(safe) is False, f"{safe} no es una tarjeta de WCS"


def test_a_new_solution_written_over_the_asiair_one_is_not_bent_by_its_sip(tmp_path):
    """El fallo real: `CTYPE`/`CRVAL`/`CRPIX`/`CD` se sobrescribían, pero
    los 24 coeficientes SIP del solve anterior sobrevivían, y astropy los
    aplicaba sobre la solución nueva -- hasta 0.56 arcsec en las
    esquinas, y exactamente 0 en el centro, así que una comprobación
    centrada no veía nada."""
    solution = _optical_solution()
    record = WCSRecord(solution=solution, source=SOURCE_OPTICS)

    leaky = dict(_REAL_ASIAIR_SOLVED_HEADER)
    leaky.update(wcs_header_cards(record))
    clean = strip_wcs_keywords(_REAL_ASIAIR_SOLVED_HEADER)
    clean.update(wcs_header_cards(record))

    def worst_corner_error(header: dict) -> float:
        path = tmp_path / f"{'sucia' if 'A_ORDER' in header else 'limpia'}.fits"
        save_fits_image(str(path), np.zeros((16, 16), dtype=np.float32), header=header)
        with fits.open(path) as hdul:
            reread = WCS(hdul[0].header, naxis=2)
        worst = 0.0
        for x_px, y_px in ((0.0, 0.0), (3007.0, 0.0), (0.0, 3007.0), (3007.0, 3007.0)):
            ra_ref, dec_ref = solution.pixel_to_sky(x_px, y_px)
            ra_file, dec_file = reread.all_pix2world([[x_px, y_px]], 0)[0]
            worst = max(worst, angular_separation_deg(ra_ref, dec_ref, ra_file, dec_file) * 3600.0)
        return worst

    assert worst_corner_error(leaky) > 0.1  # el SIP heredado desvía medio píxel
    assert worst_corner_error(clean) < 1e-6
