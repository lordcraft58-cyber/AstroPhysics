"""Catálogo de procesos disponibles en el explorador -- organizado por
categoría, igual que el árbol de procesos de PixInsight. Los procesos
con `run` real llaman directamente a `astrophysics_suite.*`; los que
todavía no tienen `run` (ver `ProcessDefinition.is_wired`) documentan la
cobertura completa de IRAF que el plan de la Fase 9 se propone alcanzar,
sin fingir una ejecución que todavía no existe.
"""
from __future__ import annotations

import numpy as np

from astrophysics_suite.imtools.cosmic_rays import detect_cosmic_rays
from astrophysics_suite.photometry.aperture import aperture_photometry
from astrophysics_suite.reduction.overscan import subtract_overscan
from astrophysics_suite.spectroscopy.continuum import fit_continuum
from qt_app.processes.base import ParameterSpec, ProcessDefinition, ProcessResult


def _run_cosmic_ray_removal(data: np.ndarray, params: dict) -> ProcessResult:
    result = detect_cosmic_rays(
        data,
        gain_e_per_adu=params["gain_e_per_adu"],
        read_noise_e=params["read_noise_e"],
        sigclip=params["sigclip"],
        sigfrac=params["sigfrac"],
        objlim=params["objlim"],
    )
    summary = f"{result.n_pixels_flagged} píxel(es) marcados como rayo cósmico ({result.fraction_flagged:.3%} de la imagen)."
    return ProcessResult(output_data=result.cleaned_data, summary=summary, log_lines=(f"Iteraciones usadas: {result.n_iterations_used}",))


def _run_overscan_subtraction(data: np.ndarray, params: dict) -> ProcessResult:
    height, width = data.shape
    n = int(params["overscan_width_px"])
    n = max(1, min(n, width - 1))
    if params["from_right"]:
        overscan_region = (slice(None), slice(width - n, width))
        trim_region = (slice(None), slice(0, width - n))
    else:
        overscan_region = (slice(None), slice(0, n))
        trim_region = (slice(None), slice(n, width))

    result = subtract_overscan(data, overscan_region=overscan_region, trim_region=trim_region, fit_axis=0, function="median")
    summary = f"Overscan sustraído (mediana={float(np.mean(result.overscan_level)):.2f} ADU); imagen recortada a {result.data.shape}."
    return ProcessResult(output_data=result.data, summary=summary)


def _run_aperture_photometry_center(data: np.ndarray, params: dict) -> ProcessResult:
    height, width = data.shape
    x0, y0 = width / 2.0, height / 2.0
    uncertainty = np.sqrt(np.clip(data, 1.0, None))  # modelo de ruido Poisson aproximado -- ver nota en la ayuda del proceso

    measurements = aperture_photometry(
        data, uncertainty, x0, y0,
        radii=[params["radius_px"]],
        sky_r_in=params["sky_r_in"],
        sky_r_out=params["sky_r_out"],
        zeropoint_mag=params["zeropoint_mag"],
    )
    m = measurements[0]
    mag_text = f"{m.magnitude:.3f} ± {m.magnitude_uncertainty:.3f}" if m.magnitude is not None else "N/D (flujo neto <= 0)"
    snr_text = f"{m.snr:.1f}" if m.snr is not None else "N/D"
    summary = f"Flujo neto: {m.net_flux:.1f} ± {m.net_flux_uncertainty:.1f} ADU  ·  mag={mag_text}  ·  S/N={snr_text}"
    log_lines = (
        f"Centro de apertura: x={x0:.1f}, y={y0:.1f} (centro de la imagen)",
        f"Cielo local: {m.sky_per_pixel:.2f} ± {m.sky_sigma_per_pixel:.2f} ADU/px ({m.n_pixels:.1f} px efectivos de apertura)",
    )
    return ProcessResult(output_data=None, summary=summary, log_lines=log_lines)


def _run_continuum_fit_central_row(data: np.ndarray, params: dict) -> ProcessResult:
    row_index = data.shape[0] // 2
    flux = data[row_index, :].astype(np.float64)
    pixel = np.arange(flux.size, dtype=np.float64)

    fit = fit_continuum(pixel, flux, degree=int(params["degree"]), sigma_clip=params["sigma_clip"])
    summary = f"Continuo ajustado sobre la fila central (grado {int(params['degree'])}); RMS={fit.rms_residual:.2f}, {fit.n_rejected} píxel(es) rechazados."
    return ProcessResult(output_data=None, summary=summary)


def build_process_registry() -> list[ProcessDefinition]:
    return [
        ProcessDefinition(
            process_id="reduction.overscan",
            name="Corrección de overscan",
            category="Reducción CCD",
            description="Sustrae el nivel de bias medido en una franja de overscan y recorta la imagen (equivalente a colbias/ccdproc).",
            parameters=(
                ParameterSpec("overscan_width_px", "Ancho de overscan (px)", "int", 20, minimum=1, maximum=500),
                ParameterSpec("from_right", "Overscan a la derecha", "bool", True),
            ),
            run=_run_overscan_subtraction,
        ),
        # Bias/dark/flat maestros y la aplicación de calibración necesitan varios
        # fotogramas de entrada y una pequeña biblioteca con estado propio -- no
        # encajan en "un proceso transforma la imagen activa" (ProcessDefinition.run),
        # así que se resuelven con diálogos dedicados en el menú "Reducción" del
        # propio menú principal (qt_app/reduction/), no como entradas de este árbol.
        ProcessDefinition(
            process_id="imtools.cosmic_rays",
            name="Rayos cósmicos (L.A.Cosmic)",
            category="Utilidades de imagen",
            description="Detecta y limpia rayos cósmicos por Laplaciano submuestreado (van Dokkum 2001) -- equivalente a crmedian.",
            parameters=(
                ParameterSpec("gain_e_per_adu", "Ganancia (e-/ADU)", "float", 1.0, minimum=0.01, maximum=100.0),
                ParameterSpec("read_noise_e", "Ruido de lectura (e-)", "float", 5.0, minimum=0.0, maximum=200.0),
                ParameterSpec("sigclip", "Umbral σ", "float", 4.5, minimum=1.0, maximum=20.0),
                ParameterSpec("sigfrac", "Fracción de crecimiento", "float", 0.3, minimum=0.0, maximum=1.0),
                ParameterSpec("objlim", "Límite de contraste", "float", 5.0, minimum=0.5, maximum=20.0),
            ),
            run=_run_cosmic_ray_removal,
        ),
        ProcessDefinition(
            process_id="imtools.arithmetic",
            name="Aritmética de imágenes",
            category="Utilidades de imagen",
            description="Suma/resta/producto/cociente con propagación de incertidumbre. Pendiente de una vista de dos imágenes en esta primera versión del taller.",
        ),
        ProcessDefinition(
            process_id="photometry.aperture",
            name="Fotometría de apertura (centro)",
            category="Fotometría",
            description="Apertura circular con cielo local por anillo, centrada en la imagen -- equivalente a phot. Nota: usa un modelo de ruido Poisson aproximado (sin ganancia/lectura reales) mientras el taller no importa la incertidumbre real de calibración.",
            parameters=(
                ParameterSpec("radius_px", "Radio de apertura (px)", "float", 6.0, minimum=1.0, maximum=200.0),
                ParameterSpec("sky_r_in", "Radio interior de cielo (px)", "float", 12.0, minimum=1.0, maximum=400.0),
                ParameterSpec("sky_r_out", "Radio exterior de cielo (px)", "float", 18.0, minimum=2.0, maximum=500.0),
                ParameterSpec("zeropoint_mag", "Punto cero (mag)", "float", 25.0, minimum=-10.0, maximum=40.0),
            ),
            run=_run_aperture_photometry_center,
        ),
        ProcessDefinition(
            process_id="photometry.psf",
            name="Fotometría de PSF (daophot)",
            category="Fotometría",
            description="Ajuste simultáneo de PSF para desmezclar fuentes superpuestas. Requiere seleccionar posiciones de fuentes en la imagen -- pendiente de esa interacción en esta primera versión del taller.",
        ),
        ProcessDefinition(
            process_id="spectroscopy.continuum",
            name="Ajuste de continuo (fila central)",
            category="Espectroscopía",
            description="Ajuste polinómico iterativo con sigma-clipping sobre la fila central de la imagen, tratada como espectro 1D -- equivalente a continuum.",
            parameters=(
                ParameterSpec("degree", "Grado del polinomio", "int", 3, minimum=1, maximum=10),
                ParameterSpec("sigma_clip", "Umbral σ de rechazo", "float", 2.5, minimum=0.5, maximum=10.0),
            ),
            run=_run_continuum_fit_central_row,
        ),
        ProcessDefinition(
            process_id="spectroscopy.trace",
            name="Extracción de traza (apall)",
            category="Espectroscopía",
            description="Traza espacial + extracción por suma u óptima (Horne 1986). Requiere una imagen 2D orientada espectro/espacial e indicar el centro inicial -- pendiente de esa interacción.",
        ),
        ProcessDefinition(
            process_id="spectroscopy.wavelength",
            name="Calibración en longitud de onda (identify)",
            category="Espectroscopía",
            description="Identificación de líneas de arco + ajuste polinómico píxel->longitud de onda. Requiere un catálogo de líneas de referencia -- pendiente de esa interacción.",
        ),
        ProcessDefinition(
            process_id="astrometry.wcs_fit",
            name="Ajuste de WCS (ccmap)",
            category="Astrometría",
            description="Ajuste de proyección TAN desde pares píxel<->cielo. Requiere resolver identificaciones contra un catálogo -- pendiente de esa interacción.",
        ),
        ProcessDefinition(
            process_id="astrometry.registration",
            name="Registro entre imágenes (geomap/geotran)",
            category="Astrometría",
            description="Alineación por estrellas emparejadas o por WCS compartido. Requiere una segunda imagen de referencia -- pendiente de una vista de dos imágenes.",
        ),
    ]
