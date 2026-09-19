"""Óptica real leída de la cabecera FITS/XISF del propio usuario.

La cabecera que escribe el software de captura (N.I.N.A., SharpCap,
APT...) suele traer ya la verdad sobre el equipo: `INSTRUME` con el
nombre de la cámara, `XPIXSZ` con el tamaño de píxel real, `FOCALLEN`
con la focal usada esa noche y `XBINNING` con el binning. Cuando está,
ESO manda sobre cualquier catálogo interno -- el catálogo de
`cameras.py` solo sirve para rellenar lo que la cabecera no diga, o para
reconocer de qué cámara se trata.

Nada se inventa: si la cabecera no trae focal, no hay escala de placa
posible y se devuelve `None` para que el usuario la introduzca.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from astrophysics_suite.instruments.cameras import CameraSpec, find_camera
from astrophysics_suite.instruments.optics import OpticalSetup


def _float_or_none(header: dict, *keys: str) -> float | None:
    for key in keys:
        value = header.get(key)
        if value is None:
            continue
        try:
            number = float(value)
        except (ValueError, TypeError):
            continue
        if math.isfinite(number) and number > 0:
            return number
    return None


def _int_or_none(header: dict, *keys: str) -> int | None:
    value = _float_or_none(header, *keys)
    return int(value) if value is not None else None


@dataclass(frozen=True)
class HeaderOptics:
    """Lo que la cabecera real sabe del equipo -- cada campo es `None`
    cuando la cabecera no lo dice, nunca un valor por defecto."""

    camera_name: str | None
    matched_camera: CameraSpec | None
    """Entrada del catálogo que coincide con `INSTRUME`, si la hay."""
    pixel_size_um: float | None
    focal_length_mm: float | None
    width_px: int | None
    height_px: int | None
    binning: int | None
    center_ra_deg: float | None
    center_dec_deg: float | None
    object_name: str | None

    @property
    def pixel_size_disagreement_um(self) -> float | None:
        """Diferencia real entre el píxel que declara la cabecera y el
        que dice el catálogo para esa misma cámara -- `None` si no hay
        con qué comparar. Cualquier valor distinto de ~0 significa que
        el catálogo interno está mal para esa cámara y hay que creerle a
        la cabecera."""
        if self.matched_camera is None or self.pixel_size_um is None:
            return None
        return abs(self.matched_camera.pixel_size_um - self.pixel_size_um)


def read_header_optics(header: dict) -> HeaderOptics:
    """Extrae la óptica real declarada en la cabecera, sin rellenar
    huecos con suposiciones."""
    camera_name = header.get("INSTRUME")
    camera_name = str(camera_name).strip() if camera_name is not None else None

    ra = _float_or_none(header, "CRVAL1")
    dec = header.get("CRVAL2")
    try:
        dec = float(dec) if dec is not None else None
    except (ValueError, TypeError):
        dec = None
    if ra is None:
        ra = _float_or_none(header, "RA")
    if dec is None:
        raw_dec = header.get("DEC")
        try:
            dec = float(raw_dec) if raw_dec is not None else None
        except (ValueError, TypeError):
            dec = None

    return HeaderOptics(
        camera_name=camera_name,
        matched_camera=find_camera(camera_name) if camera_name else None,
        pixel_size_um=_float_or_none(header, "XPIXSZ", "PIXSIZE1", "PIXSZ1"),
        focal_length_mm=_float_or_none(header, "FOCALLEN", "FOCAL"),
        width_px=_int_or_none(header, "NAXIS1"),
        height_px=_int_or_none(header, "NAXIS2"),
        binning=_int_or_none(header, "XBINNING", "BINNING"),
        center_ra_deg=ra if ra is not None and 0.0 <= ra <= 360.0 else None,
        center_dec_deg=dec if dec is not None and -90.0 <= dec <= 90.0 else None,
        object_name=str(header["OBJECT"]).strip() if header.get("OBJECT") else None,
    )


def optical_setup_from_header(header: dict) -> OpticalSetup | None:
    """Monta el equipo real directamente desde la cabecera cuando trae
    todo lo necesario (píxel + focal + geometría). Devuelve `None` si
    falta cualquier pieza -- que el usuario la introduzca, en vez de
    suponerla.

    Prioridad deliberada: el píxel de la CABECERA por encima del
    catálogo, porque la cabecera la escribió el driver de la cámara real
    del usuario y el catálogo lo escribimos nosotros.
    """
    optics = read_header_optics(header)
    pixel_um = optics.pixel_size_um
    if pixel_um is None and optics.matched_camera is not None:
        pixel_um = optics.matched_camera.pixel_size_um

    width = optics.width_px or (optics.matched_camera.width_px if optics.matched_camera else None)
    height = optics.height_px or (optics.matched_camera.height_px if optics.matched_camera else None)

    if pixel_um is None or optics.focal_length_mm is None or width is None or height is None:
        return None

    return OpticalSetup(
        camera_name=optics.camera_name or (optics.matched_camera.name if optics.matched_camera else "(sin declarar)"),
        pixel_size_um=pixel_um,
        width_px=width,
        height_px=height,
        focal_length_mm=optics.focal_length_mm,
        binning=optics.binning or 1,
    )
