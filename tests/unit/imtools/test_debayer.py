"""Pruebas del demosaico real de mosaicos CFA/Bayer (`imtools.debayer`).

Los mosaicos de prueba se construyen entrelazando planos de color con
niveles conocidos, así que el resultado correcto se puede comprobar de
forma exacta -- no "parece razonable", sino el valor que debe salir."""
from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.imtools.debayer import (
    BayerError,
    bayer_pattern_from_header,
    debayer_bilinear,
    debayer_superpixel,
    debayer_to_luminance,
    describe_bayer_agreement,
    infer_bayer_pattern_from_data,
    shift_bayer_pattern,
)


def _mosaic(pattern: str, *, red: float, green: float, blue: float, shape=(8, 8)) -> np.ndarray:
    """Mosaico sintético donde cada color tiene un nivel plano conocido."""
    levels = {"R": red, "G": green, "B": blue}
    data = np.zeros(shape, dtype=np.float64)
    for index, channel in enumerate(pattern):
        row, col = index // 2, index % 2
        data[row::2, col::2] = levels[channel]
    return data


def test_bayer_pattern_from_header_reads_real_keywords():
    assert bayer_pattern_from_header({"BAYERPAT": "RGGB"}) == "RGGB"
    assert bayer_pattern_from_header({"BAYERPAT": "'GBRG'"}) == "GBRG"  # entrecomillado, como lo escribe FITS
    assert bayer_pattern_from_header({"COLORTYP": "bggr"}) == "BGGR"
    assert bayer_pattern_from_header({}) is None
    assert bayer_pattern_from_header(None) is None
    assert bayer_pattern_from_header({"BAYERPAT": "XYZW"}) is None, "un patrón no reconocido nunca se 'arregla' a uno por defecto"


def test_bayer_pattern_from_header_applies_real_offsets():
    # XBAYROFF=1 desplaza el origen del mosaico una columna: RGGB pasa a GRBG
    assert bayer_pattern_from_header({"BAYERPAT": "RGGB", "XBAYROFF": 1}) == "GRBG"
    assert bayer_pattern_from_header({"BAYERPAT": "RGGB", "YBAYROFF": 1}) == "GBRG"
    assert bayer_pattern_from_header({"BAYERPAT": "RGGB", "XBAYROFF": 1, "YBAYROFF": 1}) == "BGGR"
    assert bayer_pattern_from_header({"BAYERPAT": "RGGB", "XBAYROFF": 2}) == "RGGB", "un desplazamiento par deja el patrón igual"


def test_shift_bayer_pattern_rejects_unknown_pattern():
    with pytest.raises(BayerError, match="no reconocido"):
        shift_bayer_pattern("XXXX")


@pytest.mark.parametrize("pattern", ["RGGB", "BGGR", "GRBG", "GBRG"])
def test_superpixel_recovers_each_channel_exactly_for_every_pattern(pattern):
    data = _mosaic(pattern, red=100.0, green=200.0, blue=300.0)
    rgb = debayer_superpixel(data, pattern)
    assert rgb.shape == (4, 4, 3)
    assert np.allclose(rgb[:, :, 0], 100.0), "el rojo debe venir del fotosito rojo real"
    assert np.allclose(rgb[:, :, 1], 200.0), "el verde debe ser la media de los dos verdes reales"
    assert np.allclose(rgb[:, :, 2], 300.0), "el azul debe venir del fotosito azul real"


def test_superpixel_averages_the_two_real_green_photosites():
    data = _mosaic("RGGB", red=100.0, green=0.0, blue=300.0)
    data[0::2, 1::2] = 180.0  # primer verde
    data[1::2, 0::2] = 220.0  # segundo verde
    rgb = debayer_superpixel(data, "RGGB")
    assert np.allclose(rgb[:, :, 1], 200.0), "G debe ser la media real (180+220)/2, nunca solo uno de los dos"


def test_superpixel_never_invents_values_only_real_measurements():
    rng = np.random.default_rng(0)
    data = rng.uniform(1000.0, 5000.0, size=(6, 6))
    rgb = debayer_superpixel(data, "RGGB")
    # R y B salen tal cual del sensor, sin interpolar
    assert np.array_equal(rgb[:, :, 0], data[0::2, 0::2])
    assert np.array_equal(rgb[:, :, 2], data[1::2, 1::2])


def test_luminance_is_a_weighted_sum_of_real_measurements():
    data = _mosaic("RGGB", red=100.0, green=200.0, blue=300.0)
    lum = debayer_to_luminance(data, "RGGB")
    assert lum.shape == (4, 4)
    # pesos por defecto (1/4, 1/2, 1/4) = proporción real de fotositos
    assert np.allclose(lum, 0.25 * 100.0 + 0.5 * 200.0 + 0.25 * 300.0)


def test_bilinear_keeps_every_measured_pixel_untouched():
    """La interpolación solo debe RELLENAR los canales que faltan -- el
    valor realmente medido en cada fotosito nunca se altera."""
    rng = np.random.default_rng(1)
    data = rng.uniform(1000.0, 5000.0, size=(10, 10))
    rgb = debayer_bilinear(data, "RGGB")
    assert rgb.shape == (10, 10, 3)
    assert np.array_equal(rgb[0::2, 0::2, 0], data[0::2, 0::2]), "el rojo medido debe quedar intacto"
    assert np.array_equal(rgb[1::2, 1::2, 2], data[1::2, 1::2]), "el azul medido debe quedar intacto"
    assert np.array_equal(rgb[0::2, 1::2, 1], data[0::2, 1::2]), "el verde medido debe quedar intacto"


def test_bilinear_interpolates_missing_channels_to_the_real_neighbour_level():
    data = _mosaic("RGGB", red=100.0, green=200.0, blue=300.0, shape=(12, 12))
    rgb = debayer_bilinear(data, "RGGB")
    # lejos del borde, el canal ausente debe interpolar al nivel real de sus vecinos
    assert np.allclose(rgb[4:8, 4:8, 0], 100.0, atol=1e-9)
    assert np.allclose(rgb[4:8, 4:8, 2], 300.0, atol=1e-9)


def test_odd_sized_mosaic_drops_the_incomplete_block_instead_of_guessing():
    data = _mosaic("RGGB", red=100.0, green=200.0, blue=300.0, shape=(9, 7))
    rgb = debayer_superpixel(data, "RGGB")
    assert rgb.shape == (4, 3, 3), "un bloque 2x2 incompleto no tiene los 4 colores -- se descarta, nunca se rellena"


def test_rejects_non_2d_input():
    with pytest.raises(BayerError, match="2D"):
        debayer_superpixel(np.zeros((4, 4, 3)), "RGGB")


def test_infer_pattern_identifies_the_green_diagonal_from_real_statistics():
    """Los dos planos verdes comparten filtro: mismo nivel y misma
    dispersión. R y B difieren -- es lo que permite deducir la
    orientación a partir de los propios píxeles."""
    rng = np.random.default_rng(2)
    shape = (60, 60)
    data = np.zeros(shape)
    # RGGB: verdes en la antidiagonal (0,1) y (1,0)
    data[0::2, 0::2] = rng.normal(1000.0, 30.0, (30, 30))   # R
    data[0::2, 1::2] = rng.normal(1500.0, 80.0, (30, 30))   # G
    data[1::2, 0::2] = rng.normal(1500.0, 80.0, (30, 30))   # G
    data[1::2, 1::2] = rng.normal(1000.0, 10.0, (30, 30))   # B (mismo nivel que R, otra dispersión)

    candidates, detail = infer_bayer_pattern_from_data(data)
    assert candidates == ("RGGB", "BGGR"), f"esperada la familia con verdes en la antidiagonal; detalle: {detail}"
    assert "antidiagonal" in detail


def test_infer_pattern_uses_more_than_the_median():
    """Regresión del bug real encontrado con los lights de M 31: con datos
    enteros de 16 bits, las medianas de los planos rojo y azul coinciden
    EXACTAMENTE muy a menudo (domina el nivel de bias). Una heurística
    basada solo en la mediana declara empate y no decide nada."""
    rng = np.random.default_rng(3)
    data = np.zeros((60, 60))
    data[0::2, 0::2] = np.round(rng.normal(2992.0, 107.0, (30, 30)))  # R
    data[0::2, 1::2] = np.round(rng.normal(3168.0, 122.0, (30, 30)))  # G
    data[1::2, 0::2] = np.round(rng.normal(3168.0, 122.0, (30, 30)))  # G
    data[1::2, 1::2] = np.round(rng.normal(2992.0, 79.0, (30, 30)))   # B -- misma mediana que R, distinta dispersión

    candidates, detail = infer_bayer_pattern_from_data(data)
    assert candidates == ("RGGB", "BGGR"), f"debe decidir pese al empate de medianas; detalle: {detail}"


def test_infer_pattern_says_so_when_the_image_is_not_a_real_mosaic():
    rng = np.random.default_rng(4)
    uniform = rng.normal(1000.0, 50.0, (60, 60))  # imagen monocroma normal
    candidates, detail = infer_bayer_pattern_from_data(uniform)
    assert candidates == (), "sin pareja verde distinguible no se debe inventar un patrón"
    assert "no parece un CFA" in detail


def test_agreement_confirms_a_header_the_data_supports():
    rng = np.random.default_rng(5)
    data = np.zeros((60, 60))
    data[0::2, 0::2] = rng.normal(1000.0, 30.0, (30, 30))
    data[0::2, 1::2] = rng.normal(1500.0, 80.0, (30, 30))
    data[1::2, 0::2] = rng.normal(1500.0, 80.0, (30, 30))
    data[1::2, 1::2] = rng.normal(1000.0, 10.0, (30, 30))

    agreement = describe_bayer_agreement(data, {"BAYERPAT": "RGGB"})
    assert agreement.agree is True
    assert agreement.header_pattern == "RGGB"
    assert "lo respaldan" in agreement.detail


def test_agreement_warns_when_header_and_data_disagree():
    """Caso real: un FITS guardado con las filas invertidas respecto a la
    orientación en que se escribió BAYERPAT."""
    rng = np.random.default_rng(6)
    data = np.zeros((60, 60))
    # verdes en la DIAGONAL principal -> familia GRBG/GBRG
    data[0::2, 0::2] = rng.normal(1500.0, 80.0, (30, 30))
    data[1::2, 1::2] = rng.normal(1500.0, 80.0, (30, 30))
    data[0::2, 1::2] = rng.normal(1000.0, 30.0, (30, 30))
    data[1::2, 0::2] = rng.normal(1000.0, 10.0, (30, 30))

    agreement = describe_bayer_agreement(data, {"BAYERPAT": "RGGB"})
    assert agreement.agree is False
    assert agreement.candidate_patterns == ("GRBG", "GBRG")
    assert "AVISO" in agreement.detail
