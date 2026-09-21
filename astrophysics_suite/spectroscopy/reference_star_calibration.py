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


def blind_calibrate_from_reference_star(
    pixel: np.ndarray,
    flux: np.ndarray,
    continuum: np.ndarray,
    catalog: tuple[SpectralLine, ...],
    *,
    tolerance_angstrom: float,
    reference_object: str,
    degree: int = 1,
    min_snr: float = 5.0,
    min_separation_px: float = 3.0,
    min_dispersion_angstrom_per_px: float = 0.1,
    max_dispersion_angstrom_per_px: float = 20.0,
) -> WavelengthCalibrationRecord:
    """Igual que `calibrate_from_reference_star`, pero SIN que el
    llamador dé una dispersión/origen aproximados: los busca él mismo
    entre las detecciones reales, probando la transformación lineal
    (dispersión, origen) que implica cada PAR de detecciones reales
    emparejado con cada PAR de líneas del catálogo, y quedándose con la
    que hace que más detecciones reales DISTINTAS caigan dentro de
    `tolerance_angstrom` de una línea de catálogo distinta -- mismo
    principio de "candidato desde un par real, verificado contra el
    resto" que ya usa `astrometry.frame_registration.
    estimate_frame_translation` para registrar fotogramas sin WCS, aquí
    aplicado en 1D a longitud de onda en vez de a posición en el cielo.

    `min_dispersion_angstrom_per_px`/`max_dispersion_angstrom_per_px`
    acotan la búsqueda a valores físicamente plausibles para un
    espectrógrafo amateur (ambos signos: una dispersión negativa es una
    orientación del espectro invertida, real y posible) -- nunca a un
    valor concreto, que es justo lo que no se conoce aquí.

    Exige al menos `degree + 2` detecciones distintas emparejadas --
    NUNCA solo `degree + 1` (el mínimo que sí basta en `calibrate_from_
    reference_star`, porque ahí la dispersión/origen los da el llamador,
    externos a los puntos que se verifican). Aquí la dispersión/origen
    los define el PROPIO par de puntos usado: con exactamente `degree +
    1` puntos (dos, para grado 1) SIEMPRE existe una transformación que
    los hace encajar exactamente, para cualquier asignación a cualquier
    par de líneas del catálogo -- residuo cero por construcción, no por
    evidencia real. Sin un tercer punto real e independiente que
    corrobore la misma transformación, esa "coincidencia" no distingue
    la asignación correcta de una incorrecta que use los mismos dos
    puntos. Hallazgo real de esta sesión: con solo `degree + 1`, la
    búsqueda podía preferir una asignación de catálogo incorrecta que
    reutilizaba las dos detecciones más fuertes bajo una transformación
    distinta -- misma amplitud total, mismo residuo (cero), pero física
    equivocada.

    Calibración incluso MÁS provisional que `calibrate_from_reference_
    star` (`WavelengthCalibrationRecord.blind_search=True`, con su
    propio aviso en `build_wavelength_provenance`): con pocas
    detecciones reales, una combinación puede casar por azar. Lanza
    `ValueError` (nunca un resultado silencioso) si ninguna combinación
    real explica al menos `degree + 2` detecciones distintas.

    Se prefiere, ante todo, la combinación cuyas detecciones usadas
    tengan más amplitud real total (más significativas, menos probable
    que sean ruido) -- el NÚMERO de detecciones que explica y el residuo
    numérico solo desempatan después. Nunca al revés: maximizar primero
    cuántas detecciones caen dentro de tolerancia, sin mirar su fuerza
    real, puede preferir una combinación que casa por azar varias
    detecciones débiles sobre otra que sí ancla en la línea dominante
    real del espectro. Hallazgo real que motivó este orden: sobre un
    espectro real con una línea muchísimo más fuerte que el resto
    (T CrB, Hα), maximizar solo el número de coincidencias encontraba
    una combinación que ignoraba esa línea dominante -- maximizar la
    amplitud total primero la ancla en ella en cuanto participa en la
    combinación."""
    if not reference_object.strip():
        raise ValueError("reference_object no puede estar vacío -- qué estrella se usó es parte de la trazabilidad obligatoria (§13)")
    if min_dispersion_angstrom_per_px <= 0 or max_dispersion_angstrom_per_px <= min_dispersion_angstrom_per_px:
        raise ValueError("min_dispersion_angstrom_per_px debe ser positivo y menor que max_dispersion_angstrom_per_px")

    min_required_matches = degree + 2
    detections = detect_object_lines(
        pixel, flux, continuum, min_snr=min_snr, min_separation_angstrom=min_separation_px
    )
    if len(detections) < min_required_matches:
        raise ValueError(
            f"solo {len(detections)} desviación(es) real(es) del continuo detectada(s) -- la búsqueda ciega "
            f"necesita al menos {min_required_matches} para un ajuste de grado {degree} (degree + 2, no degree + "
            "1: con solo degree + 1 puntos siempre existe una transformación que los hace encajar exactamente, "
            "para cualquier asignación de catálogo -- no es evidencia real sin un punto más que corrobore)"
        )
    detected_pixels = [d[0] for d in detections]
    detected_amplitude = {p: abs(a) for p, a in detections}

    best: tuple[int, float, float] | None = None
    best_pixels: list[float] = []
    best_wavelengths: list[float] = []
    for i, p1 in enumerate(detected_pixels):
        for p2 in detected_pixels[i + 1:]:
            delta_pixel = p2 - p1
            if delta_pixel == 0:
                continue
            for line1 in catalog:
                for line2 in catalog:
                    if line1 is line2:
                        continue
                    dispersion = (line2.wavelength_air_angstrom - line1.wavelength_air_angstrom) / delta_pixel
                    if not (min_dispersion_angstrom_per_px <= abs(dispersion) <= max_dispersion_angstrom_per_px):
                        continue
                    origin = line1.wavelength_air_angstrom - dispersion * p1

                    matches = match_lines_to_catalog(
                        detected_pixels, catalog,
                        approx_dispersion_angstrom_per_px=dispersion, approx_wavelength_at_pixel0=origin,
                        tolerance_angstrom=tolerance_angstrom,
                    )
                    best_per_line: dict[SpectralLine, tuple[float, float]] = {}
                    for detected_pixel, match in zip(detected_pixels, matches):
                        if match is None:
                            continue
                        previous = best_per_line.get(match.catalog_line)
                        if previous is None or abs(match.residual_angstrom) < abs(previous[1]):
                            best_per_line[match.catalog_line] = (detected_pixel, match.residual_angstrom)
                    if len(best_per_line) < min_required_matches:
                        continue
                    total_residual = sum(abs(residual) for _p, residual in best_per_line.values())
                    matched_amplitude = sum(detected_amplitude[p] for p, _r in best_per_line.values())
                    score = (matched_amplitude, len(best_per_line), -total_residual)
                    if best is None or score > best:
                        best = score
                        best_pixels = [p for p, _r in best_per_line.values()]
                        best_wavelengths = [
                            line.wavelength_air_angstrom for line, (p, _r) in best_per_line.items()
                        ]

    if best is None:
        raise ValueError(
            f"ninguna combinación real de dispersión/origen entre [{min_dispersion_angstrom_per_px:g}, "
            f"{max_dispersion_angstrom_per_px:g}] Å/px explica al menos {min_required_matches} de las "
            f"{len(detections)} desviación(es) real(es) detectada(s) contra el catálogo -- prueba dando tú la "
            "dispersión aproximada (\"Calibrar por estrella de referencia...\"), o revisa el catálogo elegido"
        )

    solution = fit_wavelength_solution(best_pixels, best_wavelengths, degree=degree)
    return WavelengthCalibrationRecord(
        solution=solution, source=CalibrationSource.REFERENCE_STAR, n_lines_used=len(best_pixels),
        n_lines_rejected=len(detections) - len(best_pixels), reference_object=reference_object,
        blind_search=True,
    )
