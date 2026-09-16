"""Catálogo de procesos disponibles en el explorador -- organizado por
categoría, igual que el árbol de procesos de PixInsight. Los procesos
con `run` real llaman directamente a `astrophysics_suite.*`; los que
todavía no tienen `run` (ver `ProcessDefinition.is_wired`) documentan la
cobertura completa de IRAF que el plan de la Fase 9 se propone alcanzar,
sin fingir una ejecución que todavía no existe.
"""
from __future__ import annotations

import math

import numpy as np
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import angular_separation_arcsec

from astrophysics_suite.catalogs.gaia import query_gaia_neighbors
from astrophysics_suite.imtools.cosmic_rays import detect_cosmic_rays
from astrophysics_suite.imtools.normalize import normalize_percentile
from astrophysics_suite.imtools.regions import crop
from astrophysics_suite.imtools.statistics import compute_histogram, compute_image_statistics
from astrophysics_suite.photometry.aperture import aperture_photometry, fit_curve_of_growth
from astrophysics_suite.photometry.calibration import fit_zeropoint
from astrophysics_suite.photometry.psf import (
    GaussianPSF,
    compute_psf_fit_diagnostics,
    fit_group_psf_photometry,
    fit_group_psf_photometry_with_position_refinement,
)
from astrophysics_suite.reduction.overscan import subtract_overscan
from astrophysics_suite.spectroscopy.continuum import fit_continuum
from astrophysics_suite.spectroscopy.trace import extract_optimal, extract_sum, trace_spectrum
from astrophysics_suite.tables.table import Table
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


def _growth_curve_radii(radius_px: float, sky_r_in: float, n: int = 8) -> list[float]:
    """Radios de muestreo para la curva de crecimiento alrededor del radio
    de apertura elegido por el usuario -- acotados para no salir del
    anillo de cielo (`sky_r_in`), donde la apertura y el fondo dejarían de
    ser regiones separadas."""
    r_min = max(1.0, radius_px * 0.3)
    r_max = max(radius_px * 1.2, min(radius_px * 3.0, sky_r_in * 0.9))
    if r_max <= r_min:
        r_max = r_min * 3.0
    return [float(r) for r in np.geomspace(r_min, r_max, n)]


def _run_aperture_photometry_center(data: np.ndarray, params: dict) -> ProcessResult:
    points = params.get("_picked_points") or []
    if not points:
        raise ValueError("no se marcó ninguna posición -- haz clic sobre la fuente antes de medir")
    x0, y0 = points[0]
    uncertainty = np.sqrt(np.clip(data, 1.0, None))  # modelo de ruido Poisson aproximado -- ver nota en la ayuda del proceso
    radius_px, sky_r_in, sky_r_out = params["radius_px"], params["sky_r_in"], params["sky_r_out"]

    measurements = aperture_photometry(
        data, uncertainty, x0, y0,
        radii=[radius_px],
        sky_r_in=sky_r_in,
        sky_r_out=sky_r_out,
        zeropoint_mag=params["zeropoint_mag"],
    )
    m = measurements[0]
    mag_text = f"{m.magnitude:.3f} ± {m.magnitude_uncertainty:.3f}" if m.magnitude is not None else "N/D (flujo neto <= 0)"
    snr_text = f"{m.snr:.1f}" if m.snr is not None else "N/D"
    summary = f"Flujo neto: {m.net_flux:.1f} ± {m.net_flux_uncertainty:.1f} ADU  ·  mag={mag_text}  ·  S/N={snr_text}"
    log_lines = [
        f"Centro de apertura: x={x0:.1f}, y={y0:.1f} (marcado a clic)",
        f"Cielo local: {m.sky_per_pixel:.2f} ± {m.sky_sigma_per_pixel:.2f} ADU/px ({m.n_pixels:.1f} px efectivos de apertura)",
    ]

    table = None
    if params.get("fit_curve_of_growth"):
        growth_radii = _growth_curve_radii(radius_px, sky_r_in)
        growth_measurements = aperture_photometry(
            data, uncertainty, x0, y0, radii=growth_radii, sky_r_in=sky_r_in, sky_r_out=sky_r_out, zeropoint_mag=params["zeropoint_mag"]
        )
        try:
            fit = fit_curve_of_growth(growth_measurements)
        except ValueError as exc:
            log_lines.append(f"Curva de crecimiento: no se pudo ajustar ({exc}).")
        else:
            log_lines.append(
                f"Curva de crecimiento: radio óptimo (máx. S/N medida) = {fit.optimal_radius_px:.1f} px "
                f"(S/N={fit.optimal_snr:.1f}), captura {fit.flux_fraction_at_optimal:.1%} del flujo asintótico "
                f"ajustado ({fit.asymptotic_flux:.1f} ADU, RMS del ajuste={fit.rms_residual:.2f} ADU)."
            )
            table = Table(
                columns=("radius_px", "net_flux", "snr"),
                units=("px", "ADU", ""),
                rows=tuple(
                    (gm.radius_px, gm.net_flux, gm.snr if gm.snr is not None else float("nan")) for gm in growth_measurements
                ),
            )
    return ProcessResult(output_data=None, summary=summary, log_lines=tuple(log_lines), table=table)


def _pixel_to_sky(wcs, x: float, y: float) -> tuple[float, float] | tuple[None, None]:
    if wcs is None:
        return None, None
    try:
        ra, dec = wcs.celestial.all_pix2world(x, y, 0)
        ra, dec = float(ra), float(dec)
    except Exception:  # noqa: BLE001 -- un WCS mal formado no debe tirar todo el proceso, solo esa posición
        return None, None
    if not (math.isfinite(ra) and math.isfinite(dec)):
        return None, None
    return ra, dec


def _run_photometric_zeropoint(data: np.ndarray, params: dict) -> ProcessResult:
    points = params.get("_picked_points") or []
    if not points:
        raise ValueError("no se marcó ninguna posición -- haz clic sobre al menos una estrella de referencia (clic derecho para terminar)")
    wcs = params.get("_wcs")
    if wcs is None:
        raise ValueError("la imagen activa no tiene WCS -- no se puede resolver un punto cero contra un catálogo sin coordenadas celestes reales")

    uncertainty = np.sqrt(np.clip(data, 1.0, None))  # modelo de ruido Poisson aproximado -- misma nota que fotometría de apertura
    radius_px, sky_r_in, sky_r_out = params["radius_px"], params["sky_r_in"], params["sky_r_out"]
    match_radius_arcsec = params["match_radius_arcsec"]

    instrumental_mags: list[float] = []
    catalog_mags: list[float] = []
    log_lines: list[str] = []
    table_rows: list[tuple] = []
    for x, y in points:
        measurement = aperture_photometry(
            data, uncertainty, x, y, radii=[radius_px], sky_r_in=sky_r_in, sky_r_out=sky_r_out, zeropoint_mag=0.0
        )[0]
        if measurement.magnitude is None:
            log_lines.append(f"({x:.1f}, {y:.1f}): flujo neto <= 0 -- descartada.")
            continue
        ra, dec = _pixel_to_sky(wcs, x, y)
        if ra is None:
            log_lines.append(f"({x:.1f}, {y:.1f}): sin coordenadas celestes válidas -- descartada.")
            continue
        gaia_rows = query_gaia_neighbors(ra, dec, radius_arcsec=match_radius_arcsec)
        if not gaia_rows:
            log_lines.append(f"({x:.1f}, {y:.1f}) [RA={ra:.5f}, Dec={dec:.5f}]: sin fuentes Gaia en el radio de búsqueda -- descartada.")
            continue
        best = min(gaia_rows, key=lambda row: angular_separation_arcsec(ra, dec, row["ra_deg"], row["dec_deg"]))
        separation = angular_separation_arcsec(ra, dec, best["ra_deg"], best["dec_deg"])
        if separation > match_radius_arcsec:
            log_lines.append(f"({x:.1f}, {y:.1f}): fuente Gaia más cercana a {separation:.2f}\", fuera del radio -- descartada.")
            continue
        catalog_mag = best.get("mag_g")
        if catalog_mag is None or not math.isfinite(float(catalog_mag)):
            log_lines.append(f"({x:.1f}, {y:.1f}): la fuente Gaia emparejada no tiene magnitud G -- descartada.")
            continue
        instrumental_mags.append(measurement.magnitude)
        catalog_mags.append(float(catalog_mag))
        log_lines.append(f"({x:.1f}, {y:.1f}): mag_instr={measurement.magnitude:.3f}  Gaia G={float(catalog_mag):.3f}  sep={separation:.2f}\"")
        table_rows.append((len(table_rows) + 1, x, y, ra, dec, measurement.magnitude, float(catalog_mag), separation))

    if not instrumental_mags:
        raise ValueError("ninguna de las posiciones marcadas pudo emparejarse con Gaia -- revisa el WCS de la imagen o el radio de búsqueda")

    fit = fit_zeropoint(instrumental_mags, catalog_mags)
    summary = (
        f"Punto cero = {fit.zeropoint_mag:.3f} ± {fit.zeropoint_uncertainty_mag:.3f} mag  ·  "
        f"{fit.n_stars_used} estrella(s) usadas, {fit.n_stars_rejected} rechazada(s)  ·  RMS={fit.rms_residual_mag:.3f} mag"
    )
    # tabla de las estrellas emparejadas con éxito contra Gaia (antes del
    # rechazo robusto final de fit_zeropoint, que no expone qué índice
    # original rechazó) -- sigue siendo un export real y útil: las
    # medidas de entrada al ajuste, no un resultado inventado.
    table = Table(
        columns=("star", "x", "y", "ra", "dec", "instrumental_mag", "catalog_mag", "separation"),
        units=("", "px", "px", "deg", "deg", "mag", "mag", "arcsec"),
        rows=tuple(table_rows),
    )
    return ProcessResult(output_data=None, summary=summary, log_lines=tuple(log_lines), table=table)


def _run_psf_photometry(data: np.ndarray, params: dict) -> ProcessResult:
    points = params.get("_picked_points") or []
    if not points:
        raise ValueError("no se marcó ninguna posición -- haz clic sobre al menos una fuente antes de terminar la selección (clic derecho)")

    uncertainty = np.sqrt(np.clip(data, 1.0, None))  # modelo de ruido Poisson aproximado -- misma nota que fotometría de apertura
    psf_model = GaussianPSF(sigma_x=params["sigma_px"])
    fit_half_size = int(params["fit_half_size"])

    if params.get("refine_positions"):
        results = fit_group_psf_photometry_with_position_refinement(
            data, uncertainty, psf_model, points, fit_half_size=fit_half_size, max_position_shift_px=params["max_position_shift_px"]
        )
        log_lines = [
            f"({x0:.1f}, {y0:.1f}) -> ({r.x:.2f}, {r.y:.2f})  flujo={r.flux:.1f} ± {r.flux_uncertainty:.1f} ADU  "
            f"(desplazamiento={math.hypot(r.x - x0, r.y - y0):.2f} px)"
            for (x0, y0), r in zip(points, results)
        ]
        summary = f"PSF ajustada con refinamiento de posición (allstar) para {len(results)} fuente(s)."
    else:
        results = fit_group_psf_photometry(data, uncertainty, psf_model, points, fit_half_size=fit_half_size)
        log_lines = [f"({x:.1f}, {y:.1f})  ->  flujo={r.flux:.1f} ± {r.flux_uncertainty:.1f} ADU" for (x, y), r in zip(points, results)]
        summary = f"PSF ajustada simultáneamente para {len(results)} fuente(s) (desmezclado incluido si se solapan)."

    output_data = None
    if params.get("report_fit_diagnostics"):
        try:
            diagnostics = compute_psf_fit_diagnostics(data, uncertainty, psf_model, results, fit_half_size=fit_half_size)
        except ValueError as exc:
            log_lines.append(f"Diagnóstico de ajuste: no se pudo calcular ({exc}).")
        else:
            log_lines.append(
                f"Diagnóstico de ajuste: chi² reducido={diagnostics.reduced_chi2:.2f} "
                f"({diagnostics.n_pixels_used} píxeles, {diagnostics.n_free_parameters} parámetros libres, "
                f"cielo recuperado={diagnostics.sky_level:.2f} ADU). Imagen de residuo abierta en una ventana nueva."
            )
            output_data = diagnostics.residual_image

    table = Table(
        columns=("x", "y", "flux", "flux_uncertainty"),
        units=("px", "px", "ADU", "ADU"),
        rows=tuple((r.x, r.y, r.flux, r.flux_uncertainty) for r in results),
    )
    return ProcessResult(output_data=output_data, summary=summary, log_lines=tuple(log_lines), table=table)


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
            name="Fotometría de apertura (clic)",
            category="Fotometría",
            description="Apertura circular con cielo local por anillo -- equivalente a phot. Al pulsar Aplicar, marca la fuente con un clic (o activa 'Detectar automáticamente' para usar la fuente más brillante detectada, sin clic). Nota: usa un modelo de ruido Poisson aproximado (sin ganancia/lectura reales) mientras el taller no importa la incertidumbre real de calibración.",
            parameters=(
                ParameterSpec("radius_px", "Radio de apertura (px)", "float", 6.0, minimum=1.0, maximum=200.0),
                ParameterSpec("sky_r_in", "Radio interior de cielo (px)", "float", 12.0, minimum=1.0, maximum=400.0),
                ParameterSpec("sky_r_out", "Radio exterior de cielo (px)", "float", 18.0, minimum=2.0, maximum=500.0),
                ParameterSpec("zeropoint_mag", "Punto cero (mag)", "float", 25.0, minimum=-10.0, maximum=40.0),
                ParameterSpec(
                    "fit_curve_of_growth", "Ajustar curva de crecimiento (radio óptimo)", "bool", False,
                    help_text="Mide en varios radios adicionales alrededor del radio de apertura y recomienda el que maximiza la señal/ruido medida -- no cambia la medida principal, añade un diagnóstico y una tabla exportable (radio, flujo, S/N).",
                ),
                ParameterSpec("auto_detect", "Detectar automáticamente (omite clic)", "bool", False, help_text="Usa la fuente más brillante detectada (DAOStarFinder) en vez de pedir un clic manual."),
                ParameterSpec("detect_fwhm_px", "FWHM esperado para detección (px)", "float", 3.0, minimum=0.5, maximum=50.0),
                ParameterSpec("detect_threshold_sigma", "Umbral de detección (σ)", "float", 5.0, minimum=1.0, maximum=50.0),
            ),
            run=_run_aperture_photometry_center,
            requires_picking=1,
        ),
        ProcessDefinition(
            process_id="photometry.zeropoint",
            name="Calibración fotométrica (punto cero, Gaia)",
            category="Fotometría",
            description="Resuelve el punto cero fotométrico real contra Gaia DR3 -- equivalente a photcal/fitparams. Marca varias estrellas de referencia con clic izquierdo, termina con clic derecho (o activa 'Detectar automáticamente' para usar las fuentes más brillantes detectadas, sin clics). Requiere que la imagen activa tenga WCS real (cargada de un FITS con astrometría, no simulada).",
            parameters=(
                ParameterSpec("radius_px", "Radio de apertura (px)", "float", 6.0, minimum=1.0, maximum=200.0),
                ParameterSpec("sky_r_in", "Radio interior de cielo (px)", "float", 12.0, minimum=1.0, maximum=400.0),
                ParameterSpec("sky_r_out", "Radio exterior de cielo (px)", "float", 18.0, minimum=2.0, maximum=500.0),
                ParameterSpec("match_radius_arcsec", "Radio de emparejamiento (arcsec)", "float", 3.0, minimum=0.1, maximum=30.0),
                ParameterSpec("auto_detect", "Detectar automáticamente (omite clics)", "bool", False, help_text="Usa hasta 20 de las fuentes más brillantes detectadas (DAOStarFinder) en vez de pedir clics manuales."),
                ParameterSpec("detect_fwhm_px", "FWHM esperado para detección (px)", "float", 3.0, minimum=0.5, maximum=50.0),
                ParameterSpec("detect_threshold_sigma", "Umbral de detección (σ)", "float", 5.0, minimum=1.0, maximum=50.0),
            ),
            run=_run_photometric_zeropoint,
            requires_picking=0,
        ),
        ProcessDefinition(
            process_id="photometry.psf",
            name="Fotometría de PSF (daophot)",
            category="Fotometría",
            description="Ajuste simultáneo de PSF (Gaussiana) para desmezclar fuentes superpuestas -- equivalente a nstar/allstar. Al pulsar Aplicar, marca cada fuente con clic izquierdo sobre la imagen y termina con clic derecho (o activa 'Detectar automáticamente' para una selección de estrellas de referencia tipo pstselect: aislamiento + redondez + señal/ruido).",
            parameters=(
                ParameterSpec("sigma_px", "Sigma de la PSF (px)", "float", 2.0, minimum=0.3, maximum=30.0),
                ParameterSpec("fit_half_size", "Semiancho de la caja de ajuste (px)", "int", 7, minimum=2, maximum=100),
                ParameterSpec(
                    "refine_positions", "Refinar posición (allstar)", "bool", False,
                    help_text="Ajuste no lineal iterativo de posición además del flujo -- útil cuando las posiciones marcadas/detectadas son solo aproximadas.",
                ),
                ParameterSpec("max_position_shift_px", "Desplazamiento máximo permitido (px)", "float", 3.0, minimum=0.1, maximum=20.0),
                ParameterSpec(
                    "report_fit_diagnostics", "Diagnóstico de ajuste (chi², residuo)", "bool", False,
                    help_text="Reporta el chi² reducido y abre la imagen de residuo (datos - modelo) en una ventana nueva.",
                ),
                ParameterSpec("auto_detect", "Detectar automáticamente (pstselect)", "bool", False, help_text="Selecciona estrellas de referencia automáticamente (aislamiento + redondez + S/N) en vez de marcarlas a mano."),
                ParameterSpec("detect_fwhm_px", "FWHM esperado para detección (px)", "float", 3.0, minimum=0.5, maximum=50.0),
                ParameterSpec("detect_threshold_sigma", "Umbral de detección (σ)", "float", 5.0, minimum=1.0, maximum=50.0),
                ParameterSpec("psf_min_separation_px", "Aislamiento mínimo (px)", "float", 15.0, minimum=1.0, maximum=200.0),
                ParameterSpec("psf_max_ellipticity", "Elipticidad máxima (redondez)", "float", 0.3, minimum=0.0, maximum=1.0),
                ParameterSpec("psf_min_snr", "S/N mínima de pico", "float", 15.0, minimum=1.0, maximum=1000.0),
                ParameterSpec("psf_max_stars", "Máximo de estrellas de referencia", "int", 12, minimum=1, maximum=100),
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
        # La calibración en longitud de onda necesita que el usuario
        # empareje cada línea de arco detectada con una longitud de onda
        # conocida (una tabla, no un formulario de parámetros) -- se
        # resuelve con un diálogo dedicado en el menú "Espectroscopía"
        # (qt_app/spectroscopy/wavelength_fit_dialog.py), mismo patrón que
        # el ajuste de WCS en Astrometría.
        ProcessDefinition(
            process_id="spectroscopy.fluxcal",
            name="Calibración de flujo (sensfunc/calibrate)",
            category="Espectroscopía",
            description="Función de sensibilidad desde un espectro de estrella estándar + corrección de extinción atmosférica -- motor real (astrophysics_suite.spectroscopy.fluxcal), pero necesita un espectro ya extraído y calibrado en longitud de onda más un catálogo de flujos estándar -- pendiente de esa interacción.",
        ),
        # El ajuste de WCS y el registro entre imágenes también necesitan
        # interacción que no encaja en un formulario de parámetros (tabla
        # de coordenadas a mano; selección de una segunda ventana) -- se
        # resuelven con diálogos dedicados en el menú "Astrometría"
        # (qt_app/astrometry/), retirados de aquí por el mismo motivo que
        # imtools.arithmetic y los fotogramas maestros de ccdred: dejarlos
        # listados como "(pendiente)" sería información obsoleta y
        # engañosa una vez que la capacidad existe, solo que accesible
        # desde otro sitio. El registro por PARES de estrellas emparejadas
        # entre dos ventanas (a diferencia del registro por WCS compartido,
        # que sí está cableado) sigue sin camino de uso -- ver
        # docs/audit/18-FASE13-ASTROMETRIA.md §7.
    ]
