"""Calibración en longitud de onda inferida de una estrella de
referencia (§13): cuando no hay una lámpara de calibración real
disponible, pero sí un espectro de una estrella de tipo espectral
conocido cuyas líneas (Balmer, Ca II, Na D...) tienen una posición de
reposo publicada -- la misma idea que `CalibrationSource.REFERENCE_STAR`
ya distingue en `calibration_provenance.py` desde antes de este módulo,
sin que hasta ahora existiera ningún motor real que la produjera.

Reutiliza tres motores ya reales y ya probados, sin duplicar ninguno:

- `object_line_identification.detect_object_lines` para localizar
  desviaciones reales del continuo (mismo detector de dos pasadas con
  signo, absorción Y emisión) -- aquí en espacio de PÍXEL en vez de
  longitud de onda, porque la calibración todavía no existe: la función
  es unidad-agnóstica (solo usa el espaciado real entre puntos), así que
  pasar píxeles en vez de Å es una reutilización directa, no una
  reimplementación.
- `line_catalog.match_lines_to_catalog` para sugerir, con una dispersión
  APROXIMADA dada por el llamador (de la óptica conocida o de una
  calibración previa), a qué línea del catálogo de la estrella
  corresponde cada detección real -- exactamente el mismo motor que ya
  usa el flujo de lámpara de arco (`wavelength_fit_dialog.py`).
- `wavelength.fit_wavelength_solution` para el ajuste final píxel ->
  longitud de onda, sobre los pares (píxel, longitud de onda de
  catálogo) ya emparejados.

Calibración PROVISIONAL, nunca al nivel de una lámpara real (§13,
`calibration_provenance.py`): la posición observada de una línea
estelar depende también de la velocidad radial real del objeto y de su
ensanchamiento (rotación, presión...), no solo de la dispersión óptica
del instrumento -- `build_wavelength_provenance` ya avisa de esto
automáticamente para todo `WavelengthCalibrationRecord` con
`source=CalibrationSource.REFERENCE_STAR`.
"""
from __future__ import annotations

import numpy as np

from astrophysics_suite.spectroscopy.calibration_provenance import CalibrationSource, WavelengthCalibrationRecord
from astrophysics_suite.spectroscopy.line_catalog import SpectralLine, match_lines_to_catalog
from astrophysics_suite.spectroscopy.object_line_identification import detect_object_lines
from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution


def calibrate_from_reference_star(
    pixel: np.ndarray,
    flux: np.ndarray,
    continuum: np.ndarray,
    catalog: tuple[SpectralLine, ...],
    *,
    approx_dispersion_angstrom_per_px: float,
    approx_wavelength_at_pixel0: float,
    tolerance_angstrom: float,
    reference_object: str,
    degree: int = 1,
    min_snr: float = 5.0,
    min_separation_px: float = 3.0,
) -> WavelengthCalibrationRecord:
    """Infiere una solución de longitud de onda PROVISIONAL a partir de
    líneas reales detectadas en `flux` (fila/espectro sin calibrar
    todavía, en píxel) y emparejadas contra `catalog` (p. ej.
    `line_catalog.BALMER_LINES` para una estrella caliente conocida).

    `approx_dispersion_angstrom_per_px`/`approx_wavelength_at_pixel0` son
    responsabilidad del llamador -- de la óptica conocida del
    instrumento, o de una calibración previa aproximada -- nunca
    supuestos aquí (mismo contrato que `match_lines_to_catalog`).

    Devuelve el registro completo (`WavelengthCalibrationRecord`, con
    `source=CalibrationSource.REFERENCE_STAR` y `reference_object` ya
    puesto) -- nunca solo la solución desnuda, para que el aviso
    obligatorio de `build_wavelength_provenance` nunca se pueda perder
    aguas abajo. Lanza `ValueError` (nunca `None` silencioso) si ninguna
    línea real detectada llega a emparejarse dentro de
    `tolerance_angstrom`, o si las que sí lo hacen no bastan para el
    grado de ajuste pedido -- mismos mensajes que ya daría
    `fit_wavelength_solution` directamente, con el contexto añadido de
    cuántas detecciones reales hubo antes de intentar el ajuste.
    """
    if not reference_object.strip():
        raise ValueError("reference_object no puede estar vacío -- qué estrella se usó es parte de la trazabilidad obligatoria (§13)")

    detections = detect_object_lines(
        pixel, flux, continuum, min_snr=min_snr, min_separation_angstrom=min_separation_px
    )
    if not detections:
        raise ValueError(
            "ninguna desviación real del continuo se detectó en el espectro -- no hay ninguna línea real "
            "de la que inferir una calibración por estrella de referencia"
        )

    detected_pixels = [d[0] for d in detections]
    matches = match_lines_to_catalog(
        detected_pixels, catalog,
        approx_dispersion_angstrom_per_px=approx_dispersion_angstrom_per_px,
        approx_wavelength_at_pixel0=approx_wavelength_at_pixel0,
        tolerance_angstrom=tolerance_angstrom,
    )
    matched = [(p, m) for p, m in zip(detected_pixels, matches) if m is not None]
    if len(matched) < degree + 1:
        raise ValueError(
            f"solo {len(matched)} de {len(detections)} línea(s) real(es) detectada(s) coincidió/coincidieron con "
            f"el catálogo dentro de {tolerance_angstrom:g} Å de la dispersión aproximada dada -- se necesitan al "
            f"menos {degree + 1} para un ajuste de grado {degree}; revisa la dispersión/origen aproximados o el catálogo elegido"
        )

    matched_pixels = [p for p, _m in matched]
    matched_wavelengths = [m.catalog_line.wavelength_air_angstrom for _p, m in matched]
    solution = fit_wavelength_solution(matched_pixels, matched_wavelengths, degree=degree)

    return WavelengthCalibrationRecord(
        solution=solution, source=CalibrationSource.REFERENCE_STAR, n_lines_used=len(matched),
        n_lines_rejected=len(detections) - len(matched), reference_object=reference_object,
    )
