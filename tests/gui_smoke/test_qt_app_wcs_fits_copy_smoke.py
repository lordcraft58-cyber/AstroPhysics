"""La copia FITS con WCS, desde la ventana real, para los CUATRO motores
que producen un WCS -- y diciendo la verdad sobre cuál fue.

Antes de esto: solo las dos resoluciones automáticas ofrecían guardar la
copia (un ajuste manual o un WCS desde la óptica se perdían al cerrar), y
la línea `HISTORY` que se escribía nombraba siempre `astrometry.wcs_fit`,
incluso cuando la placa se había resuelto en ciego.

Requiere PySide6 y un display X -- se salta si no están disponibles.
"""
from __future__ import annotations

import re

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS

PySide6 = pytest.importorskip("PySide6", reason="PySide6 no instalado en este entorno")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from astrophysics_suite.astrometry.optical_wcs import build_wcs_from_optics  # noqa: E402
from astrophysics_suite.astrometry.provenance import (  # noqa: E402
    SOURCE_BLIND_SOLVE,
    SOURCE_MANUAL_FIT,
    SOURCE_OPTICS,
    SOURCE_PLATE_SOLVE,
    WCSRecord,
)
from astrophysics_suite.astrometry.wcs_fit import angular_separation_deg, fit_wcs  # noqa: E402

def _history_text(header_or_cards) -> str:
    """Las tarjetas `HISTORY` se parten a 72 caracteres, así que una
    frase puede quedar repartida entre dos líneas. Se rejuntan y se
    normalizan los espacios antes de buscar nada en ellas."""
    lines = header_or_cards["HISTORY"]
    return re.sub(r"\s+", " ", " ".join(str(line).strip() for line in lines))


SHAPE = (120, 120)
# Cabecera tal como llega de un LIGHT real del usuario: enteros de 16
# bits con BZERO, y una solución TAN-SIP completa que el ASIAIR Mini ya
# había escrito antes de que este programa tocara el archivo.
REAL_HEADER = {
    "NAXIS1": 120, "NAXIS2": 120, "BITPIX": 16, "BZERO": 32768, "BSCALE": 1,
    "OBJECT": "M 31", "INSTRUME": "ZWO ASI533MC Pro", "FOCALLEN": 749, "EXPTIME": 300.0,
    "CTYPE1": "RA---TAN-SIP", "CTYPE2": "DEC--TAN-SIP",
    "CRPIX1": 2742.23504639, "CRPIX2": 1803.1729126,
    "CRVAL1": 11.1796601226, "CRVAL2": 41.1564927933,
    "CD1_1": 0.00024526073423, "CD1_2": 0.000149811575305,
    "CD2_1": -0.000149725811201, "CD2_2": 0.000245166648117,
    "A_ORDER": 2, "A_0_2": 8.85419124639e-08, "A_1_1": -1.80429583591e-08, "A_2_0": -1.71420952156e-07,
    "B_ORDER": 2, "B_0_2": -2.33170271127e-08, "B_1_1": -1.03548257795e-07, "B_2_0": 1.4898448321e-07,
    "AP_ORDER": 2, "AP_0_0": -5.88806080492e-05,
    "BP_ORDER": 2, "BP_0_0": 3.16252687371e-05,
}


def _display_available() -> bool:
    try:
        app = QApplication.instance() or QApplication([])
    except Exception:
        return False
    return app is not None


pytestmark = pytest.mark.skipif(not _display_available(), reason="sin display X disponible (ni real ni Xvfb) o Qt no puede inicializar")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def main_window(qapp):
    from qt_app.main_window import MainWindow

    window = MainWindow()
    yield window
    window.close()


@pytest.fixture
def view(main_window):
    sub = main_window.add_image_window(
        np.full(SHAPE, 1234.0, dtype=np.float32), "M 31", header=dict(REAL_HEADER), source_path="/tmp/m31.fit"
    )
    return sub.widget()


def _accept_and_save_to(monkeypatch, path):
    """Acepta la pregunta y devuelve `path` en el selector de archivo."""
    asked = {}

    def fake_question(_parent, _title, text, *args, **kwargs):
        asked["text"] = text
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr("qt_app.main_window.QMessageBox.question", staticmethod(fake_question))
    monkeypatch.setattr(
        "qt_app.main_window.QFileDialog.getSaveFileName",
        staticmethod(lambda *a, **k: (str(path), "FITS (*.fits)")),
    )
    return asked


def _measured_solution(n_stars=10, seed=3):
    rng = np.random.default_rng(seed)
    truth = build_wcs_from_optics(
        center_ra_deg=10.6847, center_dec_deg=41.2687, pixel_scale_arcsec=1.0355, image_shape=SHAPE
    )
    xy = rng.uniform(5, SHAPE[1] - 5, size=(n_stars, 2))
    sky = [truth.pixel_to_sky(x, y) for x, y in xy]
    noisy = xy + rng.normal(0.0, 0.3, size=(n_stars, 2))
    return fit_wcs([tuple(p) for p in noisy], sky, crpix_px=(SHAPE[1] / 2.0, SHAPE[0] / 2.0))


@pytest.mark.parametrize("source", [SOURCE_PLATE_SOLVE, SOURCE_BLIND_SOLVE, SOURCE_MANUAL_FIT])
def test_the_saved_copy_names_the_engine_that_really_solved_it(main_window, view, tmp_path, monkeypatch, source):
    out = tmp_path / f"{source.split('.')[-1]}.fits"
    _accept_and_save_to(monkeypatch, out)
    solution = _measured_solution()

    main_window._offer_to_save_wcs_fits_copy(view, WCSRecord(solution=solution, source=source))

    assert out.exists()
    with fits.open(out) as hdul:
        header = hdul[0].header
        assert header["APSWCSRC"] == source
        assert header["APSWCSMD"] is True
        assert header["WCSNSTR"] == solution.n_stars
        history = _history_text(header)
        assert source in history

        # el WCS releído apunta a donde apunta la solución
        reread = WCS(header, naxis=2)
        ra_file, dec_file = reread.all_pix2world([[60.0, 60.0]], 0)[0]
        ra_ref, dec_ref = solution.pixel_to_sky(60.0, 60.0)
        assert angular_separation_deg(ra_ref, dec_ref, ra_file, dec_file) * 3600.0 < 1e-6

        # y no se arrastra el escalado del crudo de 16 bits
        assert "BZERO" not in header
        np.testing.assert_allclose(float(np.median(hdul[0].data)), 1234.0)
        assert header["OBJECT"] == "M 31"  # los metadatos reales sí siguen

        # ni un solo resto del solve anterior del ASIAIR: los
        # coeficientes SIP sobrevivían a sobrescribir CRVAL/CRPIX/CD y
        # astropy los aplicaba sobre la solución nueva.
        for stale in ("A_ORDER", "A_2_0", "B_1_1", "AP_0_0", "BP_ORDER"):
            assert stale not in header
        assert header["CTYPE1"] == "RA---TAN"  # sin el sufijo -SIP


def test_an_optical_wcs_saved_to_disk_does_not_claim_a_perfect_fit(main_window, view, tmp_path, monkeypatch):
    out = tmp_path / "optico.fits"
    asked = _accept_and_save_to(monkeypatch, out)
    solution = build_wcs_from_optics(
        center_ra_deg=10.6847, center_dec_deg=41.2687, pixel_scale_arcsec=1.0355, image_shape=SHAPE
    )

    main_window._offer_to_save_wcs_fits_copy(
        view, WCSRecord(solution=solution, source=SOURCE_OPTICS, optics_description="ZWO ASI533MC Pro (3.76 um) a 749 mm")
    )

    # la propia pregunta ya avisa, antes de guardar nada
    assert "sin error medido" in asked["text"]
    assert "la escala es exacta" in asked["text"]

    with fits.open(out) as hdul:
        header = hdul[0].header
        assert header["APSWCSRC"] == SOURCE_OPTICS
        assert header["APSWCSMD"] is False
        assert "WCSRMS" not in header  # nunca un 0.0 que se lea como ajuste perfecto
        assert "WCSNSTR" not in header
        assert header["APSWCSSC"] == pytest.approx(1.0355, abs=1e-3)
        history = _history_text(header)
        assert "749 mm" in history


def test_a_three_star_fit_warns_the_user_before_writing_the_file(main_window, view, tmp_path, monkeypatch):
    out = tmp_path / "tres_estrellas.fits"
    asked = _accept_and_save_to(monkeypatch, out)

    main_window._offer_to_save_wcs_fits_copy(
        view, WCSRecord(solution=_measured_solution(n_stars=3), source=SOURCE_MANUAL_FIT)
    )

    assert "no mide el error real" in asked["text"]
    with fits.open(out) as hdul:
        history = _history_text(hdul[0].header)
        assert "no mide el error real" in history  # el aviso viaja con el archivo


def test_declining_the_question_writes_nothing(main_window, view, tmp_path, monkeypatch):
    out = tmp_path / "no_deberia_existir.fits"
    monkeypatch.setattr(
        "qt_app.main_window.QMessageBox.question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No),
    )
    monkeypatch.setattr(
        "qt_app.main_window.QFileDialog.getSaveFileName",
        staticmethod(lambda *a, **k: (str(out), "FITS (*.fits)")),
    )
    main_window._offer_to_save_wcs_fits_copy(view, WCSRecord(solution=_measured_solution(), source=SOURCE_MANUAL_FIT))
    assert not out.exists()
