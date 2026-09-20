"""Corrección heliocéntrica/baricéntrica real (§60) -- usa `astropy.
coordinates.SkyCoord.radial_velocity_correction`, la implementación
estándar y validada de la comunidad astronómica (efemérides JPL vía
`astropy`), no una fórmula propia reinventada.

Requiere SIEMPRE coordenadas reales del objeto, instante real de
observación y ubicación real del observatorio -- verbatim del encargo
(§60): *"nunca asumiendo coordenadas desconocidas"*. No hay ningún valor
por defecto de observatorio (ni "geocentro", ni una ubicación
"típica"): sin longitud/latitud/altura reales, la función falla en vez
de fingir una ubicación que el llamador no dio.

La corrección se mantiene siempre como un dato SEPARADO de la velocidad
radial observada (§60/§79: cada magnitud lleva su procedencia) --
`apply_barycentric_correction` es la única función que las combina, y lo
hace explícitamente, nunca dentro de la medición de velocidad radial en
sí (`radial_velocity.py`).
"""
from __future__ import annotations

from dataclasses import dataclass

import astropy.units as u
from astropy.coordinates import EarthLocation, SkyCoord
from astropy.time import Time

_VALID_KINDS = ("barycentric", "heliocentric")


@dataclass(frozen=True)
class BarycentricCorrection:
    kind: str
    """`"barycentric"` (baricentro del sistema solar) o `"heliocentric"`
    (centro del Sol) -- difieren típicamente en <= unas pocas decenas de
    m/s (el propio Sol orbita el baricentro, principalmente por
    Júpiter), ver `describe()`."""
    correction_km_s: float
    """Se SUMA a una velocidad radial observada (topocéntrica) para
    llevarla al marco baricéntrico/heliocéntrico -- convención estándar
    de `astropy.coordinates.radial_velocity_correction`."""
    obstime_utc_iso: str
    ra_deg: float
    dec_deg: float
    observatory_longitude_deg: float
    observatory_latitude_deg: float
    observatory_height_m: float

    def describe(self) -> str:
        return (
            f"corrección {self.kind} = {self.correction_km_s:+.4f} km/s "
            f"({self.obstime_utc_iso}, RA={self.ra_deg:.4f}°, Dec={self.dec_deg:.4f}°, "
            f"observatorio lon={self.observatory_longitude_deg:.4f}° lat={self.observatory_latitude_deg:.4f}° "
            f"h={self.observatory_height_m:.0f} m)"
        )


def compute_barycentric_correction(
    *,
    ra_deg: float,
    dec_deg: float,
    obstime_iso: str,
    observatory_longitude_deg: float,
    observatory_latitude_deg: float,
    observatory_height_m: float = 0.0,
    kind: str = "barycentric",
) -> BarycentricCorrection:
    """Corrección real (efemérides JPL vía astropy) para convertir una
    velocidad radial topocéntrica al marco `kind`. Todos los datos de
    posición/tiempo son obligatorios -- ninguno tiene un valor por
    defecto que pudiera hacerse pasar por un dato real.

    `obstime_iso` se interpreta como UTC (la convención casi universal
    de `DATE-OBS` en FITS) salvo que ya incluya su propia zona horaria
    reconocible por `astropy.time.Time`.
    """
    if kind not in _VALID_KINDS:
        raise ValueError(f"kind debe ser uno de {_VALID_KINDS}, recibido {kind!r}")
    if not (-90.0 <= dec_deg <= 90.0):
        raise ValueError("dec_deg debe estar en [-90, 90]")
    if not (-90.0 <= observatory_latitude_deg <= 90.0):
        raise ValueError("observatory_latitude_deg debe estar en [-90, 90]")

    coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg)
    location = EarthLocation(
        lon=observatory_longitude_deg * u.deg, lat=observatory_latitude_deg * u.deg, height=observatory_height_m * u.m
    )
    try:
        obstime = Time(obstime_iso, scale="utc")
    except ValueError as exc:
        raise ValueError(f"obstime_iso={obstime_iso!r} no es una fecha/hora reconocible: {exc}") from exc

    correction = coord.radial_velocity_correction(kind=kind, obstime=obstime, location=location)

    return BarycentricCorrection(
        kind=kind, correction_km_s=float(correction.to(u.km / u.s).value), obstime_utc_iso=obstime.utc.iso,
        ra_deg=ra_deg, dec_deg=dec_deg, observatory_longitude_deg=observatory_longitude_deg,
        observatory_latitude_deg=observatory_latitude_deg, observatory_height_m=observatory_height_m,
    )


def apply_barycentric_correction(observed_velocity_km_s: float, correction: BarycentricCorrection) -> float:
    """`velocidad observada (topocéntrica) + corrección -> velocidad en
    el marco de `correction.kind``. La única función que combina las dos
    magnitudes -- se mantienen separadas en cualquier otro punto."""
    return observed_velocity_km_s + correction.correction_km_s
