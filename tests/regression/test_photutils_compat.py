"""Regresión de dos bugs reales de compatibilidad con photutils >= 2.0
(verificados con photutils 3.0.0 instalado en este entorno), encontrados
perfilando por qué Discovery era lento en datos reales:

1. `from photutils.background import Background2D, MedianBackground,
   SigmaClip` lanzaba `ImportError` (photutils dejó de reexportar
   `SigmaClip`, que ahora vive solo en `astropy.stats`) -- apagando
   `HAS_PHOTUTILS_BACKGROUND` por completo y forzando SIEMPRE el bucle
   Python tile-a-tile de `estimate_background` (varios segundos extra
   por imagen, en cada llamada, no solo en casos raros).
2. `DAOStarFinder` (photutils reciente) devuelve columnas `x_centroid`/
   `y_centroid` (con guion bajo), no `xcentroid`/`ycentroid` -- `_dao_column`
   no las reconocía, disparando un `RuntimeError` capturado que hacía
   caer SIEMPRE a `_detect_point_sources_legacy` (un detector Python
   puro con un bucle O(candidatos × aceptados), notablemente más lento
   en campos con muchas fuentes).

Ninguna prueba existente detectaba esto porque `Detection.method` es una
etiqueta fija ("DAOStarFinder"), no una prueba de qué código se ejecutó
de verdad -- por eso aquí se prueba el mecanismo interno directamente,
no solo el resultado final.
"""
from __future__ import annotations

import time

import numpy as np

import legacy.AstroPhysicsSuite_v57_3_COMMERCIAL as legacy


def test_photutils_background_imports_succeed_in_this_environment():
    """Si esto es `False`, TODAS las llamadas a `estimate_background` de
    la aplicación (fotometría, detección, plate solving, Discovery) caen
    al bucle Python lento -- sin ningún aviso visible para el usuario."""
    assert legacy.HAS_PHOTUTILS_BACKGROUND is True
    assert legacy.Background2D is not None
    assert legacy.SigmaClip is not None


def test_estimate_background_uses_the_real_background2d_path_not_the_slow_fallback(monkeypatch):
    """Prueba directa del mecanismo, no solo del resultado: espía
    `Background2D` para confirmar que de verdad se instancia (el camino
    rápido y vectorizado), en vez de inferirlo indirectamente por
    velocidad (frágil en CI)."""
    calls = []
    real_background2d = legacy.Background2D

    def spy_background2d(*args, **kwargs):
        calls.append((args, kwargs))
        return real_background2d(*args, **kwargs)

    monkeypatch.setattr(legacy, "Background2D", spy_background2d)

    rng = np.random.default_rng(1)
    data = np.full((256, 256), 500.0, dtype=np.float32) + rng.normal(0, 5.0, (256, 256)).astype(np.float32)
    bkg = legacy.estimate_background(data)

    assert len(calls) == 1, "estimate_background debió llamar a Background2D exactamente una vez"
    assert bkg.bkg.shape == data.shape
    assert np.all(bkg.rms > 0)


def test_dao_column_resolves_both_old_and_new_photutils_column_names():
    """`_dao_column` debe encontrar la columna de centroide tanto con el
    nombre antiguo de photutils (`xcentroid`) como con el nuevo
    (`x_centroid`, verificado con photutils 3.0.0) -- la regresión real
    fue que solo reconocía el antiguo."""

    class _FakeOldTable:
        colnames = ["id", "xcentroid", "ycentroid", "flux"]

    class _FakeNewTable:
        colnames = ["id", "x_centroid", "y_centroid", "sharpness", "flux"]

    assert legacy._dao_column(_FakeOldTable(), "xcentroid") == "xcentroid"
    assert legacy._dao_column(_FakeOldTable(), "ycentroid") == "ycentroid"
    assert legacy._dao_column(_FakeNewTable(), "xcentroid") == "x_centroid"
    assert legacy._dao_column(_FakeNewTable(), "ycentroid") == "y_centroid"


def test_detect_point_sources_uses_real_daostarfinder_not_legacy_fallback(caplog):
    """Regresión end-to-end: contra un campo sintético real, la
    detección no debe caer al detector legacy -- lo que antes ocurría
    SIEMPRE con photutils reciente, silenciosamente (solo un
    `LOG.warning` fácil de pasar por alto)."""
    import logging

    rng = np.random.default_rng(3)
    shape = (300, 300)
    data = np.full(shape, 300.0, dtype=np.float32)
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    positions = [(60, 60), (150, 200), (220, 90)]
    for x0, y0 in positions:
        data += 4000.0 * np.exp(-(((xx - x0) ** 2 + (yy - y0) ** 2)) / (2 * 1.8**2))
    data += rng.normal(0, 3.0, shape).astype(np.float32)

    bkg = legacy.estimate_background(data)
    with caplog.at_level(logging.WARNING):
        sources = legacy.detect_point_sources(data, bkg, fwhm_px=3.0, threshold_sigma=5.0)

    assert len(sources) >= len(positions)
    fallback_messages = [r.message for r in caplog.records if "detector robusto legacy" in r.message]
    assert fallback_messages == [], f"cayó al detector legacy en vez de usar DAOStarFinder real: {fallback_messages}"


def test_full_frame_background_and_detection_complete_in_reasonable_time_on_a_realistic_sensor_size():
    """No es una prueba de rendimiento estricta (el tiempo exacto
    depende de la máquina), pero documenta y acota de forma honesta el
    coste real por imagen tras las dos correcciones de esta ronda -- una
    imagen de ~26 MP (tamaño real de sensor, p. ej. ASI2600MM) no debe
    tardar minutos en fondo+detección."""
    rng = np.random.default_rng(5)
    shape = (2088, 3124)  # 1/4 de un sensor de 26 MP -- suficiente para acotar sin alargar demasiado el test
    data = np.full(shape, 500.0, dtype=np.float32) + rng.normal(0, 15.0, shape).astype(np.float32)

    t0 = time.monotonic()
    bkg = legacy.estimate_background(data)
    sources = legacy.detect_point_sources(data, bkg, fwhm_px=3.0, threshold_sigma=5.0, max_sources=3000)
    elapsed = time.monotonic() - t0

    assert elapsed < 15.0, f"fondo+detección tardó {elapsed:.1f}s en una imagen de prueba de {shape} -- posible regresión de rendimiento"
    assert sources is not None
