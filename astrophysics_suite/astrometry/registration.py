"""Registro espacial y reproyección entre imágenes -- equivalente propio
de la parte de `images.immatch`/`geomap`/`geotran` de IRAF que corrige
desplazamiento, rotación y escala entre exposiciones (p. ej. alinear
OIII y Hα antes de restarlos), más reproyección completa vía WCS cuando
ambas imágenes ya tienen una solución astrométrica (`wcs_fit.py`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from astrophysics_suite.astrometry.wcs_fit import WCSSolution, gnomonic_deproject, gnomonic_project


@dataclass(frozen=True)
class AffineTransform:
    matrix: np.ndarray
    """2x2: `target_xy = matrix @ reference_xy + offset`."""
    offset: np.ndarray
    """2-vector."""
    rms_residual_px: float
    n_points: int

    def apply_to_points(self, xy: np.ndarray) -> np.ndarray:
        return xy @ self.matrix.T + self.offset


def fit_affine_transform(
    reference_xy: list[tuple[float, float]],
    target_xy: list[tuple[float, float]],
    *,
    model: str = "affine",
) -> AffineTransform:
    """Ajusta la transformación que lleva puntos de `reference_xy` a
    `target_xy` (mismo orden -- ya emparejados, p. ej. por cruce de
    catálogo entre dos detecciones de las mismas estrellas en ambas
    imágenes).

    `model`:
      - "affine": 6 parámetros libres (rotación, escala independiente
        por eje, oblicuidad, traslación) -- el caso general.
      - "similarity": 4 parámetros (rotación + escala uniforme +
        traslación, sin oblicuidad) -- más robusto con pocas estrellas,
        apropiado cuando se sabe que no hay distorsión anisotrópica
        entre las dos tomas (mismo instrumento, mismo *pixel scale*).
    """
    n = len(reference_xy)
    if n < 3:
        raise ValueError(f"fit_affine_transform necesita al menos 3 pares de puntos; recibidos {n}")
    if len(target_xy) != n:
        raise ValueError("reference_xy y target_xy deben tener la misma longitud")
    if model not in ("affine", "similarity"):
        raise ValueError(f"model debe ser 'affine' o 'similarity'; recibido {model!r}")

    ref = np.asarray(reference_xy, dtype=np.float64)
    tgt = np.asarray(target_xy, dtype=np.float64)

    if model == "affine":
        design = np.column_stack([ref, np.ones(n)])
        coeffs_x, _, _, _ = np.linalg.lstsq(design, tgt[:, 0], rcond=None)
        coeffs_y, _, _, _ = np.linalg.lstsq(design, tgt[:, 1], rcond=None)
        matrix = np.array([coeffs_x[:2], coeffs_y[:2]])
        offset = np.array([coeffs_x[2], coeffs_y[2]])
    else:
        # similitud (rotación + escala uniforme + traslación) como
        # mínimos cuadrados lineales en (s*cos, s*sin, tx, ty) -- el
        # truco estándar de Umeyama simplificado para 2D.
        design = np.column_stack([ref[:, 0], -ref[:, 1], np.ones(n), np.zeros(n)])
        design2 = np.column_stack([ref[:, 1], ref[:, 0], np.zeros(n), np.ones(n)])
        full_design = np.vstack([design, design2])
        full_target = np.concatenate([tgt[:, 0], tgt[:, 1]])
        params, _, _, _ = np.linalg.lstsq(full_design, full_target, rcond=None)
        a, b, tx, ty = params
        matrix = np.array([[a, -b], [b, a]])
        offset = np.array([tx, ty])

    predicted = ref @ matrix.T + offset
    residuals = np.sqrt(np.sum((predicted - tgt) ** 2, axis=1))
    rms_px = float(math.sqrt(np.mean(residuals**2)))

    return AffineTransform(matrix=matrix, offset=offset, rms_residual_px=rms_px, n_points=n)


def apply_affine_transform(
    data: np.ndarray,
    transform: AffineTransform,
    *,
    output_shape: tuple[int, int] | None = None,
    order: int = 3,
    cval: float = 0.0,
) -> np.ndarray:
    """Remuestrea `data` (definida en el sistema "referencia") al
    sistema "target" descrito por `transform`. `scipy.ndimage.
    affine_transform` mapea coordenadas de SALIDA a coordenadas de
    ENTRADA con la matriz inversa, y lo hace en orden de array
    `(fila, columna)` = `(y, x)` -- mientras que `AffineTransform`, como
    el resto del proyecto, usa convención `(x, y)`. Se permutan los ejes
    aquí (una vez, en la frontera con scipy) para que el resto del
    módulo no tenga que pensar en el orden de scipy en ningún otro sitio.
    """
    swap = np.array([[0.0, 1.0], [1.0, 0.0]])
    matrix_yx = swap @ transform.matrix @ swap
    offset_yx = swap @ transform.offset
    inverse_matrix_yx = np.linalg.inv(matrix_yx)
    inverse_offset_yx = -inverse_matrix_yx @ offset_yx
    shape = output_shape if output_shape is not None else data.shape
    return ndimage.affine_transform(
        data, matrix=inverse_matrix_yx, offset=inverse_offset_yx, output_shape=shape, order=order, cval=cval, mode="constant"
    )


def reproject_to_reference(
    data: np.ndarray,
    source_wcs: WCSSolution,
    reference_wcs: WCSSolution,
    *,
    output_shape: tuple[int, int],
    order: int = 1,
    cval: float = 0.0,
) -> np.ndarray:
    """Reproyecta `data` (definida en la rejilla de `source_wcs`) a la
    rejilla de `reference_wcs` -- para alinear dos imágenes que ya tienen
    cada una su propia solución astrométrica en vez de una simple
    transformación afín ajustada por estrellas (más correcto cuando las
    dos imágenes cubren campos ligeramente distintos o tienen
    proyecciones distintas, a costa de necesitar ambas soluciones WCS).
    """
    height, width = output_shape
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float64)

    # `WCSSolution.pixel_to_sky`/`sky_to_pixel` están pensados para un
    # único punto (devuelven `float`); aquí hace falta la misma álgebra
    # vectorizada sobre la rejilla completa, así que se reimplementa en
    # línea en vez de llamarlos en un bucle Python por píxel.
    offset_x = xx.ravel() - reference_wcs.crpix_px[0]
    offset_y = yy.ravel() - reference_wcs.crpix_px[1]
    xi_eta = reference_wcs.cd_matrix_deg_per_px @ np.vstack([offset_x, offset_y])
    from astrophysics_suite.astrometry.wcs_fit import gnomonic_deproject, gnomonic_project

    ra_grid, dec_grid = gnomonic_deproject(xi_eta[0], xi_eta[1], reference_wcs.crval_deg[0], reference_wcs.crval_deg[1])

    xi_src, eta_src = gnomonic_project(np.asarray(ra_grid), np.asarray(dec_grid), source_wcs.crval_deg[0], source_wcs.crval_deg[1])
    source_offsets = np.linalg.solve(source_wcs.cd_matrix_deg_per_px, np.vstack([xi_src, eta_src]))
    source_x = source_offsets[0] + source_wcs.crpix_px[0]
    source_y = source_offsets[1] + source_wcs.crpix_px[1]

    resampled = ndimage.map_coordinates(
        data, [source_y.reshape(height, width), source_x.reshape(height, width)], order=order, mode="constant", cval=cval
    )
    return resampled
