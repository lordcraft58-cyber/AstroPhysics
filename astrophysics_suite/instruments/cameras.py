"""Catálogo de cámaras astronómicas reales -- geometría del sensor
(resolución y tamaño de píxel) necesaria para derivar la escala de placa
de una óptica concreta sin tener que resolver la placa contra el cielo.

AVISO DE PROCEDENCIA, importante: estos valores son de catálogo del
fabricante, NO medidos por este programa. Un tamaño de píxel equivocado
produce un WCS silenciosamente mal escalado, así que el flujo real
(`qt_app/astrometry/optical_wcs_dialog.py`) SIEMPRE contrasta la cámara
elegida contra lo que diga la cabecera FITS real de la imagen
(`XPIXSZ`/`FOCALLEN`) y avisa si no coinciden -- la cabecera del archivo
del usuario manda sobre este catálogo, nunca al revés.

Por eso también existe siempre la opción de cámara personalizada: si la
cámara del usuario no está aquí, introduce su geometría a mano en vez de
que el programa elija una "parecida".
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CameraSpec:
    name: str
    sensor: str
    width_px: int
    height_px: int
    pixel_size_um: float
    color: bool
    """`True` para sensores de color (mosaico de Bayer, OSC) -- relevante
    porque el demosaico por SuperPixel/luminancia duplica la escala de
    píxel efectiva (ver `imtools/debayer.py`)."""

    @property
    def sensor_width_mm(self) -> float:
        return self.width_px * self.pixel_size_um / 1000.0

    @property
    def sensor_height_mm(self) -> float:
        return self.height_px * self.pixel_size_um / 1000.0

    @property
    def megapixels(self) -> float:
        return self.width_px * self.height_px / 1e6


ZWO_ASI533MC_PRO = CameraSpec(
    name="ZWO ASI533MC Pro", sensor="Sony IMX533 (1\")", width_px=3008, height_px=3008, pixel_size_um=3.76, color=True
)

BUILTIN_CAMERAS: tuple[CameraSpec, ...] = (
    ZWO_ASI533MC_PRO,
    CameraSpec(name="ZWO ASI533MM Pro", sensor="Sony IMX533 (1\")", width_px=3008, height_px=3008, pixel_size_um=3.76, color=False),
    CameraSpec(name="ZWO ASI2600MC Pro", sensor="Sony IMX571 (APS-C)", width_px=6248, height_px=4176, pixel_size_um=3.76, color=True),
    CameraSpec(name="ZWO ASI2600MM Pro", sensor="Sony IMX571 (APS-C)", width_px=6248, height_px=4176, pixel_size_um=3.76, color=False),
    CameraSpec(name="ZWO ASI294MC Pro", sensor="Sony IMX294 (4/3\")", width_px=4144, height_px=2822, pixel_size_um=4.63, color=True),
    CameraSpec(name="ZWO ASI183MC Pro", sensor="Sony IMX183 (1\")", width_px=5496, height_px=3672, pixel_size_um=2.4, color=True),
    CameraSpec(name="ZWO ASI1600MM Pro", sensor="Panasonic MN34230 (4/3\")", width_px=4656, height_px=3520, pixel_size_um=3.8, color=False),
    CameraSpec(name="ZWO ASI6200MC Pro", sensor="Sony IMX455 (full frame)", width_px=9576, height_px=6388, pixel_size_um=3.76, color=True),
)


def find_camera(name: str) -> CameraSpec | None:
    """Busca por nombre exacto (sin distinguir mayúsculas ni espacios
    sobrantes). Devuelve `None` si no está -- nunca la "más parecida",
    que sería elegir una geometría de sensor equivocada en silencio."""
    normalized = name.strip().casefold()
    for camera in BUILTIN_CAMERAS:
        if camera.name.casefold() == normalized:
            return camera
    return None


def camera_matching_pixel_size(pixel_size_um: float, *, tolerance_um: float = 0.01) -> list[CameraSpec]:
    """Cámaras del catálogo cuyo tamaño de píxel coincide con el dado
    (p. ej. el `XPIXSZ` real de una cabecera FITS) -- una ayuda para
    sugerir, nunca para elegir sola: varias cámaras distintas comparten
    el mismo píxel de 3.76 µm."""
    return [c for c in BUILTIN_CAMERAS if abs(c.pixel_size_um - pixel_size_um) <= tolerance_um]
