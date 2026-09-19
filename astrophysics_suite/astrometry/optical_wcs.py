"""WCS construido desde la óptica real del usuario, no descubierto.

A diferencia de `plate_solve.py`/`blind_solve.py` (que INTENTAN adivinar
la solución contrastando estrellas detectadas contra un catálogo), aquí
la escala sale de un dato que el usuario conoce con certeza -- el tamaño
de píxel de su cámara y la focal de su telescopio -- y el centro/la
orientación los aporta él mismo.

Lo que esto SÍ da, exacto: la escala de placa y la geometría del campo.
Lo que NO puede dar por sí solo, y por eso se pide explícitamente:
  - el centro real (RA/Dec) al que apuntaba el telescopio,
  - el ángulo de rotación de la cámara respecto al norte,
  - si la imagen está reflejada (diagonal invertida por un espejo o un
    tren óptico con un número impar de reflexiones).
Ninguno de los tres se inventa: si el usuario no los sabe, el WCS
resultante será igual de erróneo que sus datos de entrada, y el informe
de procedencia lo dice (`n_stars=0`, sin residuales: no hay ajuste real
detrás, es una construcción geométrica).
"""
from __future__ import annotations

import math

import numpy as np

from astrophysics_suite.astrometry.wcs_fit import WCSSolution


def build_wcs_from_optics(
    *,
    center_ra_deg: float,
    center_dec_deg: float,
    pixel_scale_arcsec: float,
    image_shape: tuple[int, int],
    rotation_deg: float = 0.0,
    mirrored: bool = False,
) -> WCSSolution:
    """Construye la solución TAN que corresponde a una óptica real.

    `image_shape` es `(alto, ancho)`, la convención de numpy que usa todo
    el proyecto. `rotation_deg` es el ángulo de posición del eje +Y de la
    imagen medido desde el norte hacia el este (0 = norte arriba).
    `mirrored=True` para una imagen reflejada (el este queda a la derecha
    en vez de a la izquierda).

    El píxel de referencia es el centro geométrico `(ancho/2, alto/2)` en
    coordenadas de array 0-based -- exactamente la misma convención que
    ya usan `plate_solve.solve_plate` y `blind_solve`, para que las tres
    soluciones sean intercambiables sin desplazamientos de medio píxel.
    """
    if not math.isfinite(center_ra_deg) or not math.isfinite(center_dec_deg):
        raise ValueError("center_ra_deg/center_dec_deg deben ser números reales finitos")
    if not (-90.0 <= center_dec_deg <= 90.0):
        raise ValueError(f"center_dec_deg fuera de rango físico: {center_dec_deg}")
    if pixel_scale_arcsec <= 0 or not math.isfinite(pixel_scale_arcsec):
        raise ValueError("pixel_scale_arcsec debe ser un número positivo")
    height, width = image_shape
    if height < 1 or width < 1:
        raise ValueError("image_shape debe ser (alto, ancho) con ambos >= 1")

    scale_deg = pixel_scale_arcsec / 3600.0
    theta = math.radians(rotation_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)

    # Convención estándar de una imagen del cielo con el norte arriba: la
    # RA CRECE hacia la izquierda, así que avanzar en +x baja la RA -> el
    # término CD1_1 es negativo. Una imagen reflejada invierte esa fila
    # (y solo esa): el este pasa a la derecha.
    parity = 1.0 if mirrored else -1.0
    cd = np.array(
        [
            [parity * scale_deg * cos_t, -parity * scale_deg * sin_t],
            [scale_deg * sin_t, scale_deg * cos_t],
        ],
        dtype=np.float64,
    )

    return WCSSolution(
        crval_deg=(float(center_ra_deg) % 360.0, float(center_dec_deg)),
        crpix_px=(width / 2.0, height / 2.0),
        cd_matrix_deg_per_px=cd,
        # No hay ajuste detrás: es geometría declarada por el usuario, no
        # un encaje contra estrellas reales. Dejar residuales vacíos y
        # n_stars=0 es lo honesto -- cualquier informe que los lea verá
        # que esta solución no tiene calidad medida, en vez de leer un
        # RMS de 0" e interpretarlo como un ajuste perfecto.
        residuals_arcsec=(),
        rms_residual_arcsec=0.0,
        n_stars=0,
    )


def is_optical_wcs(solution: WCSSolution) -> bool:
    """`True` si la solución viene de `build_wcs_from_optics` (geometría
    declarada) y no de un ajuste real contra estrellas -- para que la
    GUI y los informes puedan decirlo en vez de mostrar un RMS de 0"
    como si fuera un ajuste perfecto."""
    return solution.n_stars == 0 and not solution.residuals_arcsec


def pixel_scale_of(solution: WCSSolution) -> float:
    """Escala media real (arcsec/px) que implica la matriz CD de
    CUALQUIER solución -- la raíz de su determinante, que es invariante
    frente a rotación y reflexión. Útil para contrastar un WCS ya
    existente (de cabecera o de plate solve) contra la óptica declarada
    por el usuario."""
    determinant = abs(float(np.linalg.det(solution.cd_matrix_deg_per_px)))
    return math.sqrt(determinant) * 3600.0
