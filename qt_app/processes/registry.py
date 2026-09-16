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
from astrophysics_suite.imtools.normalize import normalize_percentile
from astrophysics_suite.imtools.regions import crop
from astrophysics_suite.imtools.statistics import compute_histogram, compute_image_statistics
from astrophysics_suite.photometry.aperture import aperture_photometry
from astrophysics_suite.photometry.psf import GaussianPSF, fit_group_psf_photometry
from astrophysics_suite.reduction.overscan import subtract_overscan
from astrophysics_suite.spectroscopy.continuum import fit_continuum
from astrophysics_suite.spectroscopy.trace import extract_optimal, extract_sum, trace_spectrum
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


def _run_psf_photometry(data: np.ndarray, params: dict) -> ProcessResult:
    points = params.get("_picked_points") or []
    if not points:
        raise ValueError("no se marcó ninguna posición -- haz clic sobre al menos una fuente antes de terminar la selección (clic derecho)")

    uncertainty = np.sqrt(np.clip(data, 1.0, None))  # modelo de ruido Poisson aproximado -- misma nota que fotometría de apertura
    psf_model = GaussianPSF(sigma_x=params["sigma_px"])
    results = fit_group_psf_photometry(data, uncertainty, psf_model, points, fit_half_size=int(params["fit_half_size"]))

    log_lines = tuple(
        f"({x:.1f}, {y:.1f})  ->  flujo={r.flux:.1f} ± {r.flux_uncertainty:.1f} ADU" for (x, y), r in zip(points, results)
    )
    summary = f"PSF ajustada simultáneamente para {len(results)} fuente(s) (desmezclado incluido si se solapan)."
    return ProcessResult(output_data=None, summary=summary, log_lines=log_lines)


def _run_spectral_trace(data: np.ndarray, params: dict) -> ProcessResult:
    points = params.get("_picked_points") or []
    if len(points) != 1:
        raise ValueError("se necesita exactamente un clic marcando el centro espacial inicial de la traza")
    x0, y0 = points[0]

    trace = trace_spectrum(data, initial_center_px=y0, fit_degree=int(params["fit_degree"]))
    uncertainty = np.sqrt(np.clip(data, 1.0, None))
    extractor = extract_optimal if params["optimal_extraction"] else extract_sum
    spectrum = extractor(data, uncertainty, trace, aperture_half_width=params["aperture_half_width"])

    with np.errstate(divide="ignore", invalid="ignore"):
        snr = np.where(spectrum.flux_uncertainty > 0, spectrum.flux / spectrum.flux_uncertainty, 0.0)
    median_snr = float(np.median(snr))

    # el taller todavía no tiene un visor de espectros 1D dedicado -- se
    # repite el perfil extraído en varias filas para que sea una tira
    # visible e inspeccionable con STF, en vez de perder el resultado por
    # falta de un widget de gráfico (ver "Qué queda").
    strip = np.tile(spectrum.flux, (20, 1))
    method = "óptima (Horne 1986)" if params["optimal_extraction"] else "suma simple"
    summary = f"Traza extraída ({method}) desde y={y0:.1f} en x={x0:.1f}; RMS de traza={trace.rms_residual_px:.2f} px, S/N mediana={median_snr:.1f}."
    return ProcessResult(output_data=strip, summary=summary)


def _run_continuum_fit_central_row(data: np.ndarray, params: dict) -> ProcessResult:
    row_index = data.shape[0] // 2
    flux = data[row_index, :].astype(np.float64)
    pixel = np.arange(flux.size, dtype=np.float64)

    fit = fit_continuum(pixel, flux, degree=int(params["degree"]), sigma_clip=params["sigma_clip"])
    summary = f"Continuo ajustado sobre la fila central (grado {int(params['degree'])}); RMS={fit.rms_residual:.2f}, {fit.n_rejected} píxel(es) rechazados."
    return ProcessResult(output_data=None, summary=summary)


def _run_crop(data: np.ndarray, params: dict) -> ProcessResult:
    points = params.get("_picked_points") or []
    if len(points) != 2:
        raise ValueError("se necesitan exactamente dos clics marcando las esquinas opuestas del recorte")
    (x0, y0), (x1, y1) = points
    row_start, row_end = sorted((int(round(y0)), int(round(y1))))
    col_start, col_end = sorted((int(round(x0)), int(round(x1))))
    cropped = crop(data, (slice(row_start, row_end + 1), slice(col_start, col_end + 1)))
    summary = f"Recorte a {cropped.shape[1]}x{cropped.shape[0]} px (filas {row_start}:{row_end + 1}, columnas {col_start}:{col_end + 1})."
    return ProcessResult(output_data=cropped, summary=summary)


def _run_normalize_percentile(data: np.ndarray, params: dict) -> ProcessResult:
    low, high = params["low_percentile"], params["high_percentile"]
    normalized = normalize_percentile(data, low=low, high=high)
    summary = f"Normalizada por percentiles [{low:.1f}, {high:.1f}] -> rango aproximado [0, 1] (robusta frente a outliers, a diferencia de min/máx)."
    return ProcessResult(output_data=normalized, summary=summary)


def _run_image_statistics(data: np.ndarray, params: dict) -> ProcessResult:
    stats = compute_image_statistics(data)
    bins = int(params["bins"])
    hist = compute_histogram(data, bins=bins)

    # el taller todavía no tiene un widget de histograma dedicado -- se
    # dibuja como una imagen de barras (misma disciplina que la tira 1D de
    # `spectroscopy.trace`), en vez de perder el histograma por falta de
    # un widget de gráfico.
    bar_height = 100
    max_count = int(hist.counts.max()) if hist.counts.max() > 0 else 1
    bar_chart = np.zeros((bar_height, bins), dtype=np.float64)
    for col, count in enumerate(hist.counts):
        filled = int(round((count / max_count) * bar_height))
        if filled > 0:
            bar_chart[bar_height - filled :, col] = 1.0

    summary = (
        f"media={stats.mean:.2f}  mediana={stats.median:.2f}  std={stats.std:.2f}  "
        f"MAD-sigma={stats.mad_sigma:.2f}  min={stats.minimum:.2f}  max={stats.maximum:.2f}  n={stats.n_pixels}"
    )
    log_lines = (
        f"Percentiles: 1%={stats.percentile_1:.2f}  5%={stats.percentile_5:.2f}  95%={stats.percentile_95:.2f}  99%={stats.percentile_99:.2f}",
        f"Histograma: {bins} contenedores entre {hist.bin_edges[0]:.2f} y {hist.bin_edges[-1]:.2f} (mostrado como imagen de barras en una nueva ventana).",
    )
    return ProcessResult(output_data=bar_chart, summary=summary, log_lines=log_lines)


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
        # La aritmética entre dos imágenes necesita elegir una SEGUNDA ventana
        # MDI, algo que no encaja en "un proceso transforma la imagen activa"
        # (ProcessDefinition.run) -- se resuelve con un diálogo dedicado en el
        # menú "Herramientas" (qt_app/imtools/arithmetic_dialog.py), mismo
        # patrón que bias/dark/flat maestros en "Reducción".
        ProcessDefinition(
            process_id="imtools.crop",
            name="Recortar (imcopy)",
            category="Utilidades de imagen",
            description="Recorta la imagen a la región marcada -- clic para cada esquina opuesta del rectángulo.",
            run=_run_crop,
            requires_picking=2,
        ),
        ProcessDefinition(
            process_id="imtools.normalize",
            name="Normalización por percentiles",
            category="Utilidades de imagen",
            description="Reescala la imagen a [0, 1] usando percentiles como extremos en vez de mínimo/máximo -- mucho menos sensible a un solo píxel extremo (saturación, rayo cósmico) que una normalización min/máx clásica.",
            parameters=(
                ParameterSpec("low_percentile", "Percentil inferior", "float", 1.0, minimum=0.0, maximum=49.0),
                ParameterSpec("high_percentile", "Percentil superior", "float", 99.0, minimum=51.0, maximum=100.0),
            ),
            run=_run_normalize_percentile,
        ),
        ProcessDefinition(
            process_id="imtools.statistics",
            name="Estadísticas e histograma",
            category="Utilidades de imagen",
            description="Media, mediana, desviación estándar y robusta (MAD), percentiles y rango -- equivalente a imstatistics. El histograma se muestra como una imagen de barras en una ventana nueva (el taller no tiene todavía un widget de gráfico dedicado).",
            parameters=(ParameterSpec("bins", "Contenedores del histograma", "int", 64, minimum=4, maximum=512),),
            run=_run_image_statistics,
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
            description="Ajuste simultáneo de PSF (Gaussiana) para desmezclar fuentes superpuestas -- equivalente a nstar/allstar. Al pulsar Aplicar, marca cada fuente con clic izquierdo sobre la imagen y termina con clic derecho.",
            parameters=(
                ParameterSpec("sigma_px", "Sigma de la PSF (px)", "float", 2.0, minimum=0.3, maximum=30.0),
                ParameterSpec("fit_half_size", "Semiancho de la caja de ajuste (px)", "int", 7, minimum=2, maximum=100),
            ),
            run=_run_psf_photometry,
            requires_picking=0,
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
            description="Traza espacial + extracción por suma u óptima (Horne 1986) -- eje 0 espacial, eje 1 dispersión. Al pulsar Aplicar, marca con un clic el centro espacial inicial de la traza. El resultado se muestra como una tira 1D repetida (el taller todavía no tiene un visor de espectros dedicado).",
            parameters=(
                ParameterSpec("fit_degree", "Grado del ajuste de traza", "int", 3, minimum=1, maximum=10),
                ParameterSpec("aperture_half_width", "Semiancho de apertura (px)", "float", 4.0, minimum=1.0, maximum=100.0),
                ParameterSpec("optimal_extraction", "Extracción óptima (Horne)", "bool", True),
            ),
            run=_run_spectral_trace,
            requires_picking=1,
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
