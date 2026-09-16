"""Ajuste de solución astrométrica WCS -- equivalente propio de
`ccmap`/`ccsetwcs` de IRAF: dado un conjunto de pares (posición de
píxel, posición celeste) de estrellas identificadas contra un catálogo,
ajusta una proyección tangente (TAN/gnomónica) lineal -- punto de
referencia (CRVAL), píxel de referencia (CRPIX) y matriz CD -- por
mínimos cuadrados.

Alcance deliberado: proyección TAN lineal solamente (rotación + escala +
oblicuidad, sin distorsión de orden superior tipo SIP/TPV). Es
exactamente lo que resuelve `ccmap` en su modo por defecto; los términos
de distorsión de campo amplio quedan fuera de esta primera versión.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

_DEG_TO_RAD = math.pi / 180.0
_RAD_TO_DEG = 180.0 / math.pi


def gnomonic_project(ra_deg: np.ndarray, dec_deg: np.ndarray, ra0_deg: float, dec0_deg: float) -> tuple[np.ndarray, np.ndarray]:
    """Proyecta coordenadas celestes `(ra, dec)` a coordenadas estándar
    `(xi, eta)` (grados) en el plano tangente centrado en `(ra0, dec0)` --
    la proyección gnomónica clásica de placa astrométrica."""
    ra, dec = np.asarray(ra_deg) * _DEG_TO_RAD, np.asarray(dec_deg) * _DEG_TO_RAD
    ra0, dec0 = ra0_deg * _DEG_TO_RAD, dec0_deg * _DEG_TO_RAD

    cos_c = math.sin(dec0) * np.sin(dec) + math.cos(dec0) * np.cos(dec) * np.cos(ra - ra0)
    xi = np.cos(dec) * np.sin(ra - ra0) / cos_c
    eta = (math.cos(dec0) * np.sin(dec) - math.sin(dec0) * np.cos(dec) * np.cos(ra - ra0)) / cos_c
    return xi * _RAD_TO_DEG, eta * _RAD_TO_DEG


def gnomonic_deproject(xi_deg: np.ndarray, eta_deg: np.ndarray, ra0_deg: float, dec0_deg: float) -> tuple[np.ndarray, np.ndarray]:
    """Inversa de `gnomonic_project`: coordenadas estándar `(xi, eta)` de
    vuelta a `(ra, dec)`."""
    xi, eta = np.asarray(xi_deg) * _DEG_TO_RAD, np.asarray(eta_deg) * _DEG_TO_RAD
    ra0, dec0 = ra0_deg * _DEG_TO_RAD, dec0_deg * _DEG_TO_RAD

    rho = np.sqrt(xi**2 + eta**2)
    c = np.arctan(rho)
    sin_c, cos_c = np.sin(c), np.cos(c)
    # en rho=0 (el propio punto de referencia) sin_c/rho es indeterminado
    # (0/0) -- el límite correcto es 1, que es justo lo que hace que
    # dec == dec0 y ra == ra0 ahí.
    with np.errstate(invalid="ignore", divide="ignore"):
        sinc_over_rho = np.where(rho > 1e-12, sin_c / rho, 1.0)

    dec = np.arcsin(cos_c * math.sin(dec0) + eta * sinc_over_rho * math.cos(dec0))
    ra = ra0 + np.arctan2(xi * sinc_over_rho, cos_c * math.cos(dec0) - eta * sinc_over_rho * math.sin(dec0))
    return (ra * _RAD_TO_DEG) % 360.0, dec * _RAD_TO_DEG


def angular_separation_deg(ra1_deg: float, dec1_deg: float, ra2_deg: float, dec2_deg: float) -> float:
    """Separación angular de gran círculo -- fórmula haversine, estable
    numéricamente incluso para separaciones muy pequeñas (a diferencia de
    la ley de cosenos esférica ingenua)."""
    ra1, dec1 = ra1_deg * _DEG_TO_RAD, dec1_deg * _DEG_TO_RAD
    ra2, dec2 = ra2_deg * _DEG_TO_RAD, dec2_deg * _DEG_TO_RAD
    dra, ddec = ra2 - ra1, dec2 - dec1
    a = math.sin(ddec / 2) ** 2 + math.cos(dec1) * math.cos(dec2) * math.sin(dra / 2) ** 2
    return 2.0 * math.asin(min(1.0, math.sqrt(a))) * _RAD_TO_DEG


@dataclass(frozen=True)
class WCSSolution:
    crval_deg: tuple[float, float]
    crpix_px: tuple[float, float]
    cd_matrix_deg_per_px: np.ndarray
    """2x2: fila 0 -> derivada de RA*cos(dec) respecto a (x,y); fila 1 ->
    derivada de Dec respecto a (x,y). En grados por píxel."""
    residuals_arcsec: tuple[float, ...]
    rms_residual_arcsec: float
    n_stars: int

    def pixel_to_sky(self, x_px: float, y_px: float) -> tuple[float, float]:
        offset = np.array([x_px - self.crpix_px[0], y_px - self.crpix_px[1]])
        xi, eta = self.cd_matrix_deg_per_px @ offset
        ra, dec = gnomonic_deproject(xi, eta, self.crval_deg[0], self.crval_deg[1])
        return float(ra), float(dec)

    def sky_to_pixel(self, ra_deg: float, dec_deg: float) -> tuple[float, float]:
        xi, eta = gnomonic_project(np.array([ra_deg]), np.array([dec_deg]), self.crval_deg[0], self.crval_deg[1])
        offset = np.linalg.solve(self.cd_matrix_deg_per_px, np.array([xi[0], eta[0]]))
        return float(offset[0] + self.crpix_px[0]), float(offset[1] + self.crpix_px[1])


def wcs_solution_from_astropy(wcs, *, crpix_px: tuple[float, float] | None = None) -> WCSSolution:
    """Convierte un WCS real ya cargado de un FITS (`astropy.wcs.WCS`,
    p. ej. `ImageView.wcs`) al `WCSSolution` propio del proyecto, para
    poder reutilizarlo con `registration.reproject_to_reference` sin
    duplicar ninguna álgebra.

    Es una lectura directa de la cabecera, no un ajuste -- por eso
    `residuals_arcsec`/`rms_residual_arcsec`/`n_stars` quedan vacíos/cero:
    no representan la calidad de ningún ajuste hecho aquí, a diferencia
    de un `WCSSolution` que sí viene de `fit_wcs`.

    `crpix_px`, si se omite, usa el `CRPIX` de la cabecera, convertido de
    la convención FITS (1-indexada) a la 0-indexada que usa el resto del
    proyecto (misma convención que las posiciones de píxel marcadas a
    clic sobre `ImageView`).
    """
    if crpix_px is None:
        crpix_px = (float(wcs.wcs.crpix[0]) - 1.0, float(wcs.wcs.crpix[1]) - 1.0)
    crval_deg = (float(wcs.wcs.crval[0]), float(wcs.wcs.crval[1]))
    cd_matrix = np.asarray(wcs.pixel_scale_matrix, dtype=np.float64)
    return WCSSolution(
        crval_deg=crval_deg,
        crpix_px=crpix_px,
        cd_matrix_deg_per_px=cd_matrix,
        residuals_arcsec=(),
        rms_residual_arcsec=0.0,
        n_stars=0,
    )


def wcs_solution_to_astropy(solution: WCSSolution):
    """Inversa de `wcs_solution_from_astropy`: convierte un `WCSSolution`
    propio (de `fit_wcs`, manual o de `plate_solve.solve_plate`,
    automático) a un `astropy.wcs.WCS` real, listo para escribir en un
    header FITS real (`WCS.to_header()`) -- la forma de que una solución
    resuelta en el taller sobreviva a guardar/reabrir el archivo."""
    from astropy.wcs import WCS

    wcs = WCS(naxis=2)
    # `WCSSolution.crpix_px` usa la convención 0-indexada del resto del
    # proyecto (posiciones de píxel marcadas a clic); FITS/WCS es 1-indexado.
    wcs.wcs.crpix = [solution.crpix_px[0] + 1.0, solution.crpix_px[1] + 1.0]
    wcs.wcs.crval = list(solution.crval_deg)
    wcs.wcs.cd = solution.cd_matrix_deg_per_px.tolist()
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wcs


def fit_wcs(
    pixel_xy: list[tuple[float, float]],
    sky_radec: list[tuple[float, float]],
    *,
    crpix_px: tuple[float, float],
) -> WCSSolution:
    """Ajusta CRVAL/CD por mínimos cuadrados a partir de >= 3 pares
    píxel<->cielo (con 3 se puede resolver el sistema pero sin ningún
    grado de libertad para evaluar el ajuste; se recomiendan >= 6 en la
    práctica, igual que `ccmap`). `crpix_px` es un punto de referencia
    fijo elegido por el llamador (típicamente el centro de la imagen) --
    CRVAL se resuelve para que caiga exactamente ahí.
    """
    n = len(pixel_xy)
    if n < 3:
        raise ValueError(f"fit_wcs necesita al menos 3 pares píxel<->cielo; recibidos {n}")
    if len(sky_radec) != n:
        raise ValueError("pixel_xy y sky_radec deben tener la misma longitud")

    xs = np.array([p[0] for p in pixel_xy], dtype=np.float64)
    ys = np.array([p[1] for p in pixel_xy], dtype=np.float64)
    ras = np.array([s[0] for s in sky_radec], dtype=np.float64)
    decs = np.array([s[1] for s in sky_radec], dtype=np.float64)

    ra0_guess, dec0_guess = float(np.mean(ras)), float(np.mean(decs))
    xi0, eta0 = gnomonic_project(ras, decs, ra0_guess, dec0_guess)

    design = np.column_stack([xs, ys, np.ones(n)])
    coeffs_xi, _, _, _ = np.linalg.lstsq(design, xi0, rcond=None)
    coeffs_eta, _, _, _ = np.linalg.lstsq(design, eta0, rcond=None)

    xi_at_crpix = coeffs_xi[0] * crpix_px[0] + coeffs_xi[1] * crpix_px[1] + coeffs_xi[2]
    eta_at_crpix = coeffs_eta[0] * crpix_px[0] + coeffs_eta[1] * crpix_px[1] + coeffs_eta[2]
    crval = gnomonic_deproject(np.array([xi_at_crpix]), np.array([eta_at_crpix]), ra0_guess, dec0_guess)
    crval_deg = (float(crval[0][0]), float(crval[1][0]))

    xi, eta = gnomonic_project(ras, decs, crval_deg[0], crval_deg[1])
    dx, dy = xs - crpix_px[0], ys - crpix_px[1]
    zero_intercept_design = np.column_stack([dx, dy])
    cd_row0, _, _, _ = np.linalg.lstsq(zero_intercept_design, xi, rcond=None)
    cd_row1, _, _, _ = np.linalg.lstsq(zero_intercept_design, eta, rcond=None)
    cd_matrix = np.array([cd_row0, cd_row1])

    predicted_offset = cd_matrix @ np.vstack([dx, dy])
    predicted_ra, predicted_dec = gnomonic_deproject(predicted_offset[0], predicted_offset[1], crval_deg[0], crval_deg[1])
    residuals_arcsec = tuple(
        angular_separation_deg(ra, dec, p_ra, p_dec) * 3600.0
        for ra, dec, p_ra, p_dec in zip(ras, decs, predicted_ra, predicted_dec)
    )
    rms_arcsec = math.sqrt(sum(r**2 for r in residuals_arcsec) / n)

    return WCSSolution(
        crval_deg=crval_deg,
        crpix_px=crpix_px,
        cd_matrix_deg_per_px=cd_matrix,
        residuals_arcsec=residuals_arcsec,
        rms_residual_arcsec=rms_arcsec,
        n_stars=n,
    )
