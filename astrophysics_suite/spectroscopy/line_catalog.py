"""Catálogos de líneas espectrales -- de lámpara de calibración (§9,
Ne/Ar/He) y de objeto (§20, Balmer, Ca II, Na D, líneas nebulares).

Todas las longitudes de onda son datos físicos públicos (NIST Atomic
Spectra Database, https://physics.nist.gov/PhysRefData/ASD/lines_form.html,
y las series de Balmer/líneas nebulares de cualquier libro de texto de
espectroscopía) -- constantes de la naturaleza, no código ni interfaz de
ningún programa de terceros. Ninguna línea de este archivo procede de
ISIS ni de ningún otro software; son los mismos valores que publicaría
cualquier catálogo de referencia independiente.

Catálogo deliberadamente modesto: mejor una lista corta y verificada que
una larga con algún valor sin confirmar -- el usuario siempre puede
cargar su propia lista (`LineCatalog.from_rows`) para una lámpara o un
objeto que este catálogo no cubra, tal como pide el encargo ("otras
mediante archivo de líneas").
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from astrophysics_suite.spectroscopy.air_vacuum import air_to_vacuum


class LineType(Enum):
    EMISSION = "emission"
    ABSORPTION = "absorption"
    ARC_CALIBRATION = "arc_calibration"
    """Línea de lámpara de calibración -- ni emisión ni absorción de un
    objeto astronómico, una referencia de laboratorio."""


@dataclass(frozen=True)
class SpectralLine:
    wavelength_air_angstrom: float
    label: str
    element: str
    ionization: str = ""
    """P. ej. `"I"`, `"II"` (notación espectroscópica: átomo neutro,
    una vez ionizado...) -- cadena vacía cuando no aplica (líneas
    moleculares/nebulares con notación propia, ya en `label`)."""
    line_type: LineType = LineType.ABSORPTION
    relative_intensity: float | None = None
    """Intensidad relativa dentro de la misma lámpara/fuente, si el
    catálogo de origen la da -- `None`, nunca un valor inventado,
    cuando no hay dato real."""
    reference: str = "NIST ASD"

    @property
    def wavelength_vacuum_angstrom(self) -> float:
        """Longitud de onda equivalente en vacío (§24) -- conversión real
        (`air_vacuum.air_to_vacuum`, Morton 2000), nunca una aproximación
        distinta: todas las líneas de este catálogo se dan en aire (misma
        convención que NIST ASD por encima de 2000 Å), así que esto es
        siempre una conversión, nunca el valor original de la fuente."""
        return float(air_to_vacuum(self.wavelength_air_angstrom))


def _line(wavelength: float, label: str, element: str, ionization: str = "", *,
          line_type: LineType = LineType.ABSORPTION, reference: str = "NIST ASD") -> SpectralLine:
    return SpectralLine(wavelength, label, element, ionization, line_type, reference=reference)


NEON_ARC_LINES: tuple[SpectralLine, ...] = tuple(
    _line(w, f"Ne I {w:.2f}", "Ne", "I", line_type=LineType.ARC_CALIBRATION)
    for w in (
        5852.49, 5944.83, 5975.53, 6029.997, 6074.34, 6096.16, 6143.06, 6163.59,
        6217.28, 6266.49, 6304.79, 6334.43, 6382.99, 6402.25, 6506.53, 6532.88,
        6598.95, 6717.04, 6929.47, 7032.41, 7173.94, 7245.17, 7438.90, 7488.87,
        7535.77, 7943.18, 8082.46, 8377.61, 8495.36, 8591.26, 8634.65, 8654.38,
        9148.68, 9201.76, 9326.51, 9425.38, 9486.68, 9534.16, 9665.42,
    )
)
"""Líneas fuertes de Ne I en el visible/rojo cercano -- el catálogo de
lámpara de calibración más común en espectroscopía amateur de bajo/medio
poder resolutivo (mismo rango que ISIS documenta usar Ne para calibrar,
concepto genérico de la técnica, sin copiar ninguna lista de ISIS)."""

ARGON_ARC_LINES: tuple[SpectralLine, ...] = tuple(
    _line(w, f"Ar I {w:.2f}", "Ar", "I", line_type=LineType.ARC_CALIBRATION)
    for w in (
        6965.43, 7067.22, 7147.04, 7272.94, 7383.98, 7503.87, 7514.65, 7635.11,
        7723.76, 7948.18, 8006.16, 8014.79, 8103.69, 8115.31, 8264.52, 8408.21,
        8424.65, 8521.44, 8667.94,
    )
)

HELIUM_ARC_LINES: tuple[SpectralLine, ...] = tuple(
    _line(w, f"He I {w:.2f}", "He", "I", line_type=LineType.ARC_CALIBRATION)
    for w in (3888.65, 4026.19, 4471.48, 4921.93, 5015.68, 5875.62, 6678.15, 7065.19)
)

HENEAR_ARC_LINES: tuple[SpectralLine, ...] = tuple(sorted(
    NEON_ARC_LINES + ARGON_ARC_LINES + HELIUM_ARC_LINES, key=lambda line: line.wavelength_air_angstrom
))
"""Mezcla Ne+Ar+He, la lámpara combinada más habitual en espectrógrafos
amateur (LHIRES III/Alpy/similares) precisamente para cubrir más rango
espectral con una sola exposición de calibración."""

_ARC_CATALOGS: dict[str, tuple[SpectralLine, ...]] = {
    "Ne": NEON_ARC_LINES, "Ar": ARGON_ARC_LINES, "He": HELIUM_ARC_LINES, "HeNeAr": HENEAR_ARC_LINES,
}


def arc_catalog(lamp_name: str) -> tuple[SpectralLine, ...]:
    """Catálogo de líneas de la lámpara `lamp_name` (`"Ne"`, `"Ar"`,
    `"He"`, `"HeNeAr"`). Para `"ThAr"` u otra lámpara no incluida, el
    llamador debe aportar su propia lista (`LineCatalog` a partir de un
    archivo, §9) -- no se inventa un catálogo de una lámpara que este
    módulo no puede verificar."""
    try:
        return _ARC_CATALOGS[lamp_name]
    except KeyError:
        raise ValueError(
            f"sin catálogo interno para la lámpara {lamp_name!r}; disponibles: {sorted(_ARC_CATALOGS)} "
            "-- para otra lámpara (p. ej. ThAr), aporta tu propia lista de líneas"
        ) from None


# ---------------------------------------------------------------------------
# Líneas de objeto (§20) -- exactamente el ejemplo del encargo, valores
# públicos estándar de la serie de Balmer y líneas nebulares.
# ---------------------------------------------------------------------------

BALMER_LINES: tuple[SpectralLine, ...] = (
    _line(6562.8, "H-alpha", "H", line_type=LineType.EMISSION),
    _line(4861.3, "H-beta", "H", line_type=LineType.EMISSION),
    _line(4340.5, "H-gamma", "H", line_type=LineType.EMISSION),
    _line(4101.7, "H-delta", "H", line_type=LineType.EMISSION),
)

CALCIUM_LINES: tuple[SpectralLine, ...] = (
    _line(3968.5, "Ca II H", "Ca", "II"),
    _line(3933.7, "Ca II K", "Ca", "II"),
)

SODIUM_LINES: tuple[SpectralLine, ...] = (
    _line(5895.9, "Na D1", "Na", "I"),
    _line(5889.95, "Na D2", "Na", "I"),
)

NEBULAR_EMISSION_LINES: tuple[SpectralLine, ...] = (
    _line(5006.8, "[O III]", "O", "III", line_type=LineType.EMISSION),
    _line(4958.9, "[O III]", "O", "III", line_type=LineType.EMISSION),
    _line(6583.4, "[N II]", "N", "II", line_type=LineType.EMISSION),
    _line(6548.0, "[N II]", "N", "II", line_type=LineType.EMISSION),
    _line(6730.8, "[S II]", "S", "II", line_type=LineType.EMISSION),
    _line(6716.4, "[S II]", "S", "II", line_type=LineType.EMISSION),
)

STELLAR_NEBULAR_LINES: tuple[SpectralLine, ...] = tuple(sorted(
    BALMER_LINES + CALCIUM_LINES + SODIUM_LINES + NEBULAR_EMISSION_LINES,
    key=lambda line: line.wavelength_air_angstrom,
))
"""No asume que todas pertenecen a todos los tipos espectrales (§20):
es responsabilidad del llamador elegir el subconjunto relevante (p. ej.
`BALMER_LINES` para una estrella caliente, `NEBULAR_EMISSION_LINES` para
una nebulosa) -- `identify_object_lines`, más abajo, sí filtra por
`line_type` cuando se le pide."""

NAMED_OBJECT_LINE_CATALOGS: dict[str, tuple[SpectralLine, ...]] = {
    "Balmer (H, estelar)": BALMER_LINES,
    "Ca II H&K (estelar)": CALCIUM_LINES,
    "Na D (estelar/interestelar)": SODIUM_LINES,
    "Nebulares ([O III]/[N II]/[S II])": NEBULAR_EMISSION_LINES,
    "Todas (estelar + nebular)": STELLAR_NEBULAR_LINES,
}
"""Única implementación real de "qué catálogo de objeto se llama cómo"
-- antes duplicado de forma privada en `qt_app.processes.registry.
_OBJECT_LINE_CATALOGS`, que ahora importa esto en vez de redeclararlo
(mismo criterio de "una sola implementación real" ya aplicado en el
ciclo de cierre sistemático)."""


@dataclass(frozen=True)
class LineMatch:
    pixel: float
    catalog_line: SpectralLine
    predicted_wavelength: float
    """Longitud de onda que predice la dispersión aproximada dada por el
    llamador en ese píxel -- nunca la propia lámpara, que no se conoce
    todavía (es justo lo que se está identificando)."""
    residual_angstrom: float
    """`predicted_wavelength - catalog_line.wavelength_air_angstrom`."""
    confidence: float
    """En `[0, 1]`: `1 - |residual| / tolerance_angstrom`, recortado a
    `[0, 1]`. Es una medida de cercanía a la predicción aproximada, NO
    una probabilidad estadística -- el nombre deliberadamente evita
    sugerir más precisión de la que hay."""


def match_lines_to_catalog(
    detected_pixels: list[float],
    catalog: tuple[SpectralLine, ...],
    *,
    approx_dispersion_angstrom_per_px: float,
    approx_wavelength_at_pixel0: float,
    tolerance_angstrom: float,
) -> list[LineMatch | None]:
    """Sugiere, para cada píxel detectado, la línea de catálogo más
    cercana bajo una dispersión APROXIMADA dada por el llamador (nunca
    supuesta aquí: viene de la óptica conocida del instrumento, de una
    calibración previa aproximada, o de una estimación manual) -- §10.

    Devuelve una sugerencia por píxel, o `None` si ninguna línea del
    catálogo cae dentro de `tolerance_angstrom` de la predicción -- una
    lista más corta que `detected_pixels` sería indistinguible de "no
    hay pico ahí", así que se preserva la posición con `None` en vez de
    omitirla en silencio.

    Estas son SUGERENCIAS. El encargo es explícito (§10): *"Debe existir
    una etapa de confirmación. No aceptar automáticamente una
    identificación dudosa."* -- este motor no aplica la solución por sí
    solo; el llamador (la GUI, o un script que revise `confidence`)
    decide qué confirmar.
    """
    if tolerance_angstrom <= 0:
        raise ValueError("tolerance_angstrom debe ser positivo")
    if not catalog:
        raise ValueError("catalog está vacío -- no hay nada contra lo que emparejar")

    catalog_wavelengths = [line.wavelength_air_angstrom for line in catalog]
    matches: list[LineMatch | None] = []
    for pixel in detected_pixels:
        predicted = approx_wavelength_at_pixel0 + approx_dispersion_angstrom_per_px * pixel
        best_line, best_residual = None, math.inf
        for line, catalog_wavelength in zip(catalog, catalog_wavelengths):
            residual = predicted - catalog_wavelength
            if abs(residual) < abs(best_residual):
                best_line, best_residual = line, residual
        if best_line is None or abs(best_residual) > tolerance_angstrom:
            matches.append(None)
            continue
        confidence = max(0.0, 1.0 - abs(best_residual) / tolerance_angstrom)
        matches.append(
            LineMatch(
                pixel=pixel, catalog_line=best_line, predicted_wavelength=predicted,
                residual_angstrom=best_residual, confidence=confidence,
            )
        )
    return matches


def nearby_catalog_lines(
    wavelength_air_angstrom: float, catalog: tuple[SpectralLine, ...], *, tolerance_angstrom: float,
) -> tuple[SpectralLine, ...]:
    """Líneas reales de `catalog` dentro de `tolerance_angstrom` de
    `wavelength_air_angstrom`, ordenadas de más a menos cercana --
    identificación manual asistida (clic del usuario sobre un rasgo real
    del espectro YA calibrado, §10): a diferencia de `match_lines_to_
    catalog` (que PREDICE una posición a partir de una dispersión
    aproximada todavía sin calibración real), aquí la posición ya es un
    dato real -- la longitud de onda bajo el punto real que el usuario
    señaló --, y solo se buscan candidatas cercanas. Ninguna se acepta
    aquí: la decisión de cuál (si alguna) aplica es siempre del usuario,
    mismo principio que ya exige `match_lines_to_catalog`."""
    if tolerance_angstrom <= 0:
        raise ValueError("tolerance_angstrom debe ser positivo")
    candidates = [
        line for line in catalog
        if abs(line.wavelength_air_angstrom - wavelength_air_angstrom) <= tolerance_angstrom
    ]
    candidates.sort(key=lambda line: abs(line.wavelength_air_angstrom - wavelength_air_angstrom))
    return tuple(candidates)


def identify_object_lines(
    catalog: tuple[SpectralLine, ...] = STELLAR_NEBULAR_LINES, *, line_type: LineType | None = None
) -> tuple[SpectralLine, ...]:
    """Subconjunto del catálogo de objeto a usar como candidatas para
    `spectroscopy.lines.measure_line` tras calibrar -- filtra por tipo
    (emisión/absorción) cuando se pide, para no ofrecer líneas de
    emisión nebular como candidatas en una estrella de absorción y
    viceversa (§20/§21)."""
    if line_type is None:
        return catalog
    return tuple(line for line in catalog if line.line_type is line_type)
