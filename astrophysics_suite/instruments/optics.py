"""Óptica del equipo real -- escala de placa, campo de visión y relación
focal a partir de la geometría que el usuario conoce de verdad (tamaño
de píxel de su cámara y longitud focal de su telescopio), sin tener que
resolver la placa contra el cielo.

Es la misma cuenta que hace cualquier calculadora de campo
(astronomy.tools y equivalentes), pero aquí es la ÚNICA fuente de la
fórmula en todo el proyecto: `astrometry/plate_solve.py` la importa en
vez de repetirla, por la misma disciplina de "nada se mide por una
segunda vía" que ya rige el resto de motores.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

ARCSEC_PER_RADIAN = 180.0 * 3600.0 / math.pi
"""206264.806... -- el factor exacto, no la constante redondeada 206265."""


def pixel_scale_arcsec_per_px(*, pixel_size_um: float, focal_length_mm: float, binning: int = 1) -> float:
    """Escala de placa real: `arctan(px / focal)` en segundos de arco.

    Para los ángulos diminutos de un píxel real (microsegundos de radián)
    la aproximación de ángulo pequeño es exacta a más decimales de los
    que tiene sentido usar, pero aquí se calcula el arcotangente de
    verdad -- no cuesta nada y no introduce una aproximación gratuita.
    """
    if pixel_size_um <= 0 or not math.isfinite(pixel_size_um):
        raise ValueError("pixel_size_um debe ser un número positivo (micras)")
    if focal_length_mm <= 0 or not math.isfinite(focal_length_mm):
        raise ValueError("focal_length_mm debe ser un número positivo (milímetros)")
    if binning < 1:
        raise ValueError("binning debe ser un entero >= 1")

    pixel_mm = (pixel_size_um * binning) / 1000.0
    return math.atan(pixel_mm / focal_length_mm) * ARCSEC_PER_RADIAN


def field_of_view_deg(*, pixel_scale_arcsec: float, width_px: int, height_px: int, binning: int = 1) -> tuple[float, float]:
    """Campo cubierto `(ancho, alto)` en grados, con el binning ya
    aplicado al número de píxeles (un bin 2x2 deja la mitad de píxeles,
    cada uno el doble de grande: el campo total no cambia)."""
    if width_px < 1 or height_px < 1:
        raise ValueError("width_px y height_px deben ser >= 1")
    if binning < 1:
        raise ValueError("binning debe ser un entero >= 1")
    binned_width, binned_height = width_px // binning, height_px // binning
    return (binned_width * pixel_scale_arcsec / 3600.0, binned_height * pixel_scale_arcsec / 3600.0)


def pixel_scale_from_wcs_header(header: dict) -> float | None:
    """Escala de placa (arcsec/px) que declara la ASTROMETRÍA de una
    cabecera, por orden de fiabilidad: `CDELT`, luego la matriz `CD`
    (raíz de su determinante, invariante frente a rotación y espejo) y
    por último las claves directas `PIXSCALE`/`SECPIX`/`PLTSCALE`.

    Es una vía DISTINTA a `pixel_scale_arcsec_per_px`: esta lee lo que
    dice el WCS ya resuelto; aquella la deduce de la óptica física. Las
    dos deben coincidir sobre una imagen bien calibrada, y
    `compare_pixel_scales` existe precisamente para comprobarlo en vez
    de dejar que discrepen sin que nadie se entere.

    Devuelve `None` si la cabecera no dice nada utilizable -- nunca un
    valor por defecto.
    """
    for key in ("CDELT2", "CDELT1"):
        value = _finite_positive(header.get(key), allow_negative=True)
        if value is not None:
            return abs(value) * 3600.0

    cd_values = [_finite_positive(header.get(k), allow_negative=True) for k in ("CD1_1", "CD1_2", "CD2_1", "CD2_2")]
    if all(v is not None for v in cd_values):
        determinant = abs(cd_values[0] * cd_values[3] - cd_values[1] * cd_values[2])
        if determinant > 0:
            return math.sqrt(determinant) * 3600.0

    for key in ("PIXSCALE", "SECPIX", "PLTSCALE"):
        value = _finite_positive(header.get(key))
        if value is not None:
            return value
    return None


def _finite_positive(value, *, allow_negative: bool = False) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if not allow_negative and number <= 0:
        return None
    if allow_negative and number == 0:
        return None
    return number


@dataclass(frozen=True)
class PixelScaleComparison:
    """Las dos vías de conocer la escala, y si concuerdan de verdad."""

    from_optics_arcsec: float | None
    from_wcs_arcsec: float | None
    relative_difference: float | None
    """Diferencia relativa entre ambas -- `None` si falta alguna."""

    @property
    def agree(self) -> bool | None:
        """`True`/`False` cuando se pueden comparar de verdad; `None`
        cuando falta una de las dos (que no es lo mismo que discrepar)."""
        if self.relative_difference is None:
            return None
        return self.relative_difference <= 0.02


def compare_pixel_scales(*, from_optics_arcsec: float | None, from_wcs_arcsec: float | None) -> PixelScaleComparison:
    """Contrasta la escala deducida de la óptica declarada contra la que
    trae la astrometría de la cabecera. Una discrepancia real significa
    que una de las dos miente: focal mal declarada, binning no tenido en
    cuenta, un demosaico que cambió el tamaño, o un WCS heredado de otra
    imagen. Antes esto no se comprobaba en ningún sitio."""
    if from_optics_arcsec is None or from_wcs_arcsec is None or from_wcs_arcsec <= 0:
        return PixelScaleComparison(from_optics_arcsec, from_wcs_arcsec, None)
    difference = abs(from_optics_arcsec - from_wcs_arcsec) / from_wcs_arcsec
    return PixelScaleComparison(from_optics_arcsec, from_wcs_arcsec, difference)


@dataclass(frozen=True)
class OpticalSetup:
    """Equipo real del usuario: su cámara sobre su telescopio."""

    camera_name: str
    pixel_size_um: float
    width_px: int
    height_px: int
    focal_length_mm: float
    aperture_mm: float | None = None
    binning: int = 1

    @property
    def pixel_scale_arcsec(self) -> float:
        return pixel_scale_arcsec_per_px(
            pixel_size_um=self.pixel_size_um, focal_length_mm=self.focal_length_mm, binning=self.binning
        )

    @property
    def field_of_view_deg(self) -> tuple[float, float]:
        return field_of_view_deg(
            pixel_scale_arcsec=self.pixel_scale_arcsec, width_px=self.width_px, height_px=self.height_px, binning=self.binning
        )

    @property
    def focal_ratio(self) -> float | None:
        """f/N real -- `None` si el usuario no dio la abertura (no se
        inventa una abertura "típica" para poder enseñar un número)."""
        if self.aperture_mm is None or self.aperture_mm <= 0:
            return None
        return self.focal_length_mm / self.aperture_mm

    @property
    def dawes_limit_arcsec(self) -> float | None:
        """Límite de resolución de Dawes (116/D mm) -- criterio empírico
        clásico para separar estrellas dobles. `None` sin abertura."""
        if self.aperture_mm is None or self.aperture_mm <= 0:
            return None
        return 116.0 / self.aperture_mm

    def sampling_ratio(self, fwhm_arcsec: float) -> float | None:
        """Píxeles reales por FWHM del seeing -- el criterio de muestreo
        que importa de verdad. Por debajo de ~2 el campo está
        submuestreado (se pierde información espacial real); muy por
        encima de ~3 está sobremuestreado (se reparte la misma señal
        entre más píxeles sin ganar nada). `None` si el FWHM dado no es
        un número positivo real."""
        if fwhm_arcsec is None or fwhm_arcsec <= 0 or not math.isfinite(fwhm_arcsec):
            return None
        return fwhm_arcsec / self.pixel_scale_arcsec

    def describe_sampling(self, fwhm_arcsec: float) -> str | None:
        ratio = self.sampling_ratio(fwhm_arcsec)
        if ratio is None:
            return None
        if ratio < 2.0:
            verdict = "submuestreado (se pierde detalle real del seeing)"
        elif ratio <= 3.5:
            verdict = "bien muestreado (cerca del criterio de Nyquist)"
        else:
            verdict = "sobremuestreado (la misma señal repartida entre más píxeles)"
        return f"{ratio:.1f} px por FWHM de {fwhm_arcsec:.1f}\" -- {verdict}"
