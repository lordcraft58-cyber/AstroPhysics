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
from astrophysics_suite.imtools.ccd_noise import ccd_noise_adu
from astrophysics_suite.imtools.cosmic_rays import detect_cosmic_rays
from astrophysics_suite.imtools.debayer import (
    BAYER_PATTERNS,
    bayer_pattern_from_header,
    debayer_bilinear,
    debayer_superpixel,
    debayer_to_luminance,
    describe_bayer_agreement,
)
from astrophysics_suite.imtools.normalize import normalize_percentile
from astrophysics_suite.imtools.regions import crop
from astrophysics_suite.imtools.statistics import compute_histogram, compute_image_statistics
from astrophysics_suite.photometry.aperture import aperture_photometry, estimate_local_sky, fit_curve_of_growth
from astrophysics_suite.photometry.calibration import fit_zeropoint
from astrophysics_suite.photometry.psf import (
    GaussianPSF,
    MoffatPSF,
    build_empirical_psf,
    compute_psf_fit_diagnostics,
    fit_group_psf_photometry,
    fit_group_psf_photometry_with_position_refinement,
)
from astrophysics_suite.reduction.overscan import subtract_overscan
from astrophysics_suite.spectroscopy.autoprocess import run_autoprocess_spectrum
from astrophysics_suite.spectroscopy.continuum import fit_continuum
from astrophysics_suite.spectroscopy.frame2d import PixelFlag, build_pixel_mask
from astrophysics_suite.spectroscopy.line_catalog import (
    BALMER_LINES,
    CALCIUM_LINES,
    NEBULAR_EMISSION_LINES,
    SODIUM_LINES,
    STELLAR_NEBULAR_LINES,
)
from astrophysics_suite.spectroscopy.line_profile_fit import fit_gaussian_line, fit_voigt_line, spectral_resolution
from astrophysics_suite.spectroscopy.wavelength import local_dispersion_at_pixel
from astrophysics_suite.spectroscopy.lines import measure_line
from astrophysics_suite.spectroscopy.calibration_provenance import build_wavelength_provenance
from astrophysics_suite.spectroscopy.object_line_identification import identify_object_lines_in_spectrum
from astrophysics_suite.spectroscopy.reference_star_calibration import calibrate_from_reference_star
from astrophysics_suite.spectroscopy.qc_report import (
    QCReport,
    dispersion_metric,
    pixel_quality_metric,
    snr_metric,
    trace_quality_metric,
    wavelength_calibration_quality_metric,
    wavelength_range_metric,
)
from astrophysics_suite.spectroscopy.extended_extraction import SpatialRegion, extract_multi_region
from astrophysics_suite.spectroscopy.multiaperture import extract_multi_aperture
from astrophysics_suite.spectroscopy.trace import (
    DEFAULT_SKY_WINDOWS,
    SkyWindow,
    extract_mean,
    extract_optimal,
    extract_sum,
    trace_spectrum,
)
from astrophysics_suite.tables.table import Table
from qt_app.processes.base import ParameterSpec, ProcessDefinition, ProcessResult
from services.instrument_profiles import InstrumentProfileStore
from qt_app.spectroscopy.spectrum_plot_data import SpectrumMarker, SpectrumPlotData, SpectrumSeries, series_color
from qt_app.spectroscopy.trace_overlay_data import TraceOverlay


def _run_debayer(data: np.ndarray, params: dict) -> ProcessResult:
    header = params.get("_header") or {}
    requested = str(params.get("pattern", "auto")).strip().upper()
    if requested in ("AUTO", ""):
        pattern = bayer_pattern_from_header(header)
        if pattern is None:
            raise ValueError(
                "La cabecera de esta imagen no declara BAYERPAT, así que no se puede saber si es un mosaico de color "
                "ni con qué orientación. Elige el patrón a mano si sabes cuál es -- nunca se asume uno por defecto, "
                "porque un patrón equivocado produce colores y fotometría silenciosamente incorrectos."
            )
        pattern_source = f"declarado en la cabecera ({pattern})"
    else:
        if requested not in BAYER_PATTERNS:
            raise ValueError(f"Patrón de Bayer no reconocido: {requested!r} (esperado uno de {', '.join(BAYER_PATTERNS)}, o 'auto').")
        pattern = requested
        pattern_source = f"elegido a mano ({pattern})"

    agreement = describe_bayer_agreement(data, header)
    method = str(params.get("method", "luminancia")).strip().lower()
    if method.startswith("lum"):
        output = debayer_to_luminance(data, pattern)
        summary = (
            f"Mosaico {pattern} -> luminancia {output.shape[1]}x{output.shape[0]} px por SuperPixel "
            f"(patrón {pattern_source}). Ningún valor interpolado: cada píxel es una suma de medidas reales del sensor "
            f"-- es el método correcto para detección y fotometría. La escala de píxel se DUPLICA."
        )
    elif method.startswith("super"):
        output = debayer_superpixel(data, pattern)
        summary = (
            f"Mosaico {pattern} -> RGB {output.shape[1]}x{output.shape[0]} px por SuperPixel (patrón {pattern_source}). "
            f"Ningún valor interpolado. La escala de píxel se DUPLICA."
        )
    elif method.startswith("bilin"):
        output = debayer_bilinear(data, pattern)
        summary = (
            f"Mosaico {pattern} -> RGB {output.shape[1]}x{output.shape[0]} px por interpolación bilineal (patrón "
            f"{pattern_source}). AVISO: la mayoría de los valores de salida son INTERPOLADOS, no medidos -- vale para "
            f"ver la imagen, no para fotometría (usa SuperPixel o Luminancia para medir)."
        )
    else:
        raise ValueError(f"Método de demosaico no reconocido: {method!r} (esperado 'luminancia', 'superpixel' o 'bilineal').")

    log_lines = [agreement.detail]
    if not agreement.agree:
        log_lines.append(
            "El resultado puede tener los colores intercambiados. Comprueba el patrón antes de usar esta imagen para medir."
        )
    return ProcessResult(output_data=output, summary=summary, log_lines=tuple(log_lines))


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
    # tabla de las estrellas emparejadas con éxito contra Gaia, con la
    # columna "usada" real de `fit.used_mask` (misma longitud y orden
    # que `instrumental_mags`/`catalog_mags`) -- ya distingue cuáles
    # sobrevivieron el sigma-clip final, no solo cuántas.
    table = Table(
        columns=("star", "x", "y", "ra", "dec", "instrumental_mag", "catalog_mag", "separation", "usada"),
        units=("", "px", "px", "deg", "deg", "mag", "mag", "arcsec", ""),
        rows=tuple((*row, "sí" if used else "no") for row, used in zip(table_rows, fit.used_mask)),
    )
    return ProcessResult(output_data=None, summary=summary, log_lines=tuple(log_lines), table=table, artifacts={"zeropoint_fit": fit})


def _run_psf_photometry(data: np.ndarray, params: dict) -> ProcessResult:
    points = params.get("_picked_points") or []
    if not points:
        raise ValueError("no se marcó ninguna posición -- haz clic sobre al menos una fuente antes de terminar la selección (clic derecho)")

    uncertainty = np.sqrt(np.clip(data, 1.0, None))  # modelo de ruido Poisson aproximado -- misma nota que fotometría de apertura
    fit_half_size = int(params["fit_half_size"])

    empirical_log_line = None
    if params.get("use_empirical_psf"):
        reference_points = params.get("_psf_reference_points") or []
        if not reference_points:
            raise ValueError("PSF empírica: no se marcó ninguna estrella de referencia -- haz clic sobre al menos una antes de medir")
        # `build_empirical_psf` resta un único nivel de cielo escalar antes
        # de apilar -- se estima con el mismo cielo local robusto de
        # apertura (mediana por anillo, rechazo sigma-clip) en cada
        # referencia y se combina por mediana, en vez de asumir cielo 0.
        sky_levels = [
            estimate_local_sky(data, x, y, r_in=fit_half_size, r_out=fit_half_size * 1.6).median for x, y in reference_points
        ]
        background = float(np.median(sky_levels))
        oversample = int(params.get("empirical_psf_oversample", 4))
        psf_model = build_empirical_psf(data, reference_points, half_size=fit_half_size, oversample=oversample, background=background)
        empirical_log_line = (
            f"PSF empírica construida con {len(reference_points)} estrella(s) de referencia "
            f"(cielo estimado={background:.2f} ADU, sobremuestreo={oversample}x)."
        )
    elif params.get("use_moffat_psf"):
        # colas más pesadas que una Gaussiana -- el modelo analítico
        # preferido para *seeing* atmosférico real (Moffat 1969); motor
        # ya existía desde la Fase 9.3, sin selector en la GUI hasta ahora.
        psf_model = MoffatPSF(alpha=params["moffat_alpha_px"], beta=params["moffat_beta"])
    else:
        psf_model = GaussianPSF(sigma_x=params["sigma_px"])

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

    if empirical_log_line is not None:
        log_lines.insert(0, empirical_log_line)

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


def _saturation_mask_from_header(data: np.ndarray, params: dict) -> tuple[np.ndarray | None, int, float | None]:
    """Máscara de saturación real desde `header['SATURATE']` (nunca un
    umbral inventado -- si la cabecera real no lo trae, la detección
    queda inactiva, misma disciplina que `detection.finder`/`frame2d.
    build_pixel_mask`, del que este helper es solo el punto de entrada
    para los procesos de traza/extracción de la GUI). Devuelve la
    máscara (o `None` sin `SATURATE` real), cuántos píxeles saturados
    hay en TODO el fotograma, y el umbral real usado."""
    header = params.get("_header")
    if not header:
        return None, 0, None
    value = header.get("SATURATE")
    if value is None:
        return None, 0, None
    try:
        saturate_adu = float(value)
    except (TypeError, ValueError):
        return None, 0, None
    if not (np.isfinite(saturate_adu) and saturate_adu > 0):
        return None, 0, None
    mask = build_pixel_mask(data, saturate_adu=saturate_adu)
    n_saturated = int(np.count_nonzero(mask & np.uint16(PixelFlag.SATURATED)))
    return mask, n_saturated, saturate_adu


def _header_positive_float(header: dict | None, key: str) -> float | None:
    if not header:
        return None
    value = header.get(key)
    if value is None:
        return None
    try:
        candidate = float(value)
    except (TypeError, ValueError):
        return None
    return candidate if np.isfinite(candidate) and candidate > 0 else None


def _uncertainty_adu(data: np.ndarray, params: dict) -> tuple[np.ndarray, str | None]:
    """Incertidumbre real en ADU: usa `GAIN`/`RDNOISE` reales de la
    cabecera cuando existen (`ccd_noise_adu`, ruido de disparo en
    ELECTRONES reales + ruido de lectura, convertido de vuelta a ADU) --
    nunca inventa una ganancia. Sin `GAIN` real en la cabecera de ESTA
    exposición concreta, cae al perfil de instrumento real guardado por
    el usuario (`services.instrument_profiles`, Fase 10.2) si eligió uno
    en `params["instrument_profile"]` -- la cabecera de la exposición
    concreta siempre tiene prioridad sobre un perfil general guardado.
    Sin ninguno de los dos, cae al modelo aproximado `sqrt(ADU)`
    (equivalente a asumir gain=1 e-/ADU sin ruido de lectura) ya usado en
    todo el taller, y lo declara como tal (`None`) en vez de aparentar
    precisión que no tiene."""
    header = params.get("_header")
    gain = _header_positive_float(header, "GAIN")
    if gain is not None:
        read_noise = _header_positive_float(header, "RDNOISE") or 0.0
        note = f"GAIN={gain:.3g} e-/ADU" + (f", RDNOISE={read_noise:.3g} e-" if read_noise else "")
        return ccd_noise_adu(data, gain_e_per_adu=gain, read_noise_e=read_noise), note

    profile_name = params.get("instrument_profile")
    if profile_name and profile_name != _NO_INSTRUMENT_PROFILE:
        profile = params.get("_instrument_profiles", {}).get(profile_name)
        if profile is not None:
            note = (
                f"GAIN={profile.gain_e_per_adu:.3g} e-/ADU, RDNOISE={profile.read_noise_e:.3g} e- "
                f"(perfil de instrumento «{profile_name}»)"
            )
            return ccd_noise_adu(data, gain_e_per_adu=profile.gain_e_per_adu, read_noise_e=profile.read_noise_e), note

    return np.sqrt(np.clip(data, 1.0, None)), None


def _run_quality_map(data: np.ndarray, params: dict) -> ProcessResult:
    """Mismos umbrales/motor que `_saturation_mask_from_header`/
    `build_pixel_mask` (ya reales, ya probados) -- la novedad de este
    proceso es solo mostrarlos píxel a píxel en una imagen nueva en vez
    de solo un recuento en el resumen de otro proceso."""
    header = params.get("_header")
    saturate_adu = _header_positive_float(header, "SATURATE")
    mask = build_pixel_mask(data, saturate_adu=saturate_adu)

    detect_cr = bool(params.get("detect_cosmic_rays"))
    cosmic_gain_note = ""
    if detect_cr:
        gain = _header_positive_float(header, "GAIN")
        read_noise = _header_positive_float(header, "RDNOISE") or 0.0
        cr_result = detect_cosmic_rays(data, gain_e_per_adu=gain or 1.0, read_noise_e=read_noise)
        mask = mask | (cr_result.mask.astype(np.uint16) * np.uint16(PixelFlag.COSMIC_RAY))
        cosmic_gain_note = "GAIN real" if gain is not None else "GAIN aproximado=1.0 e-/ADU (sin GAIN real en la cabecera)"

    n_nonfinite = int(np.count_nonzero(mask & np.uint16(PixelFlag.NONFINITE)))
    n_saturated = int(np.count_nonzero(mask & np.uint16(PixelFlag.SATURATED)))
    n_cosmic = int(np.count_nonzero(mask & np.uint16(PixelFlag.COSMIC_RAY)))
    n_bad = int(np.count_nonzero(mask))
    fraction = n_bad / mask.size if mask.size else 0.0

    log_lines = [
        f"NONFINITE (NaN/Inf real): {n_nonfinite} píxel(es).",
        f"SATURATED: {n_saturated} píxel(es)"
        + (f" (SATURATE={saturate_adu:.0f} ADU real)." if saturate_adu else " (sin SATURATE real en la cabecera -- detección inactiva)."),
    ]
    if detect_cr:
        log_lines.append(f"COSMIC_RAY: {n_cosmic} píxel(es) ({cosmic_gain_note}).")

    summary = (
        f"Mapa de calidad: {n_bad} píxel(es) marcados ({fraction:.3%} de la imagen) -- "
        "0 = bueno, valor distinto de 0 = bits de PixelFlag combinados (ver registro)."
    )
    return ProcessResult(output_data=mask.astype(np.float64), summary=summary, log_lines=tuple(log_lines))


_EXTRACTION_METHODS = {
    "suma simple": extract_sum,
    "óptima (Horne 1986)": extract_optimal,
    "media (§3)": extract_mean,
}


def _run_spectral_trace(data: np.ndarray, params: dict) -> ProcessResult:
    points = params.get("_picked_points") or []
    if len(points) != 1:
        raise ValueError("se necesita exactamente un clic marcando el centro espacial inicial de la traza")
    x0, y0 = points[0]

    mask, n_saturated, saturate_adu = _saturation_mask_from_header(data, params)
    trace = trace_spectrum(data, initial_center_px=y0, fit_degree=int(params["fit_degree"]), mask=mask)
    uncertainty, gain_note = _uncertainty_adu(data, params)
    extraction_method = params["extraction_method"]
    extractor = _EXTRACTION_METHODS[extraction_method]
    sky_smooth_degree = int(params["sky_smooth_degree"]) or None
    spectrum = extractor(
        data, uncertainty, trace, aperture_half_width=params["aperture_half_width"], mask=mask,
        sky_smooth_degree=sky_smooth_degree,
    )

    # Una columna que no se pudo medir queda flux=NaN (nunca 0.0): se
    # excluye de la estadística en vez de arrastrar un cero falso a la
    # mediana de S/N -- ver `spectroscopy/trace.py`.
    with np.errstate(divide="ignore", invalid="ignore"):
        snr = np.where(spectrum.flux_uncertainty > 0, spectrum.flux / spectrum.flux_uncertainty, np.nan)
    median_snr = float(np.nanmedian(snr)) if np.any(np.isfinite(snr)) else float("nan")
    n_invalid = spectrum.n_columns_invalid

    pixel = np.arange(spectrum.flux.size, dtype=np.float64)
    plot_data = SpectrumPlotData(
        series=(SpectrumSeries(label="Flujo extraído", x=pixel, y=spectrum.flux, y_error=spectrum.flux_uncertainty),),
        x_label="Píxel (dispersión)", y_label="Flujo extraído (ADU)",
    )
    method = extraction_method
    sky_note = f"; cielo suavizado con un polinomio real de grado {sky_smooth_degree}" if sky_smooth_degree else ""
    invalid_note = f"; {n_invalid} columna(s) sin medida real (huecos en el gráfico)" if n_invalid else ""
    saturation_note = f"; {n_saturated} píxel(es) saturado(s) (SATURATE={saturate_adu:.0f} ADU) excluido(s)" if n_saturated else ""
    noise_note = f"; ruido real ({gain_note})" if gain_note else "; ruido Poisson aproximado (sin GAIN real)"
    summary = (
        f"Traza extraída ({method}) desde y={y0:.1f} en x={x0:.1f}; RMS de traza={trace.rms_residual_px:.2f} px, "
        f"S/N mediana={median_snr:.1f}{invalid_note}{saturation_note}{noise_note}{sky_note}."
    )
    overlay = TraceOverlay(
        trace_columns=trace.columns.astype(np.float64), trace_center_px=trace.center_px,
        aperture_half_width=float(params["aperture_half_width"]), sky_windows=DEFAULT_SKY_WINDOWS, label="Traza",
    )
    return ProcessResult(output_data=None, summary=summary, artifacts={"spectrum": plot_data, "trace_overlay": overlay})


def _qc_report_table(report: QCReport) -> Table:
    return Table(
        columns=("metric", "status", "value", "guideline"),
        units=("", "", "", ""),
        rows=tuple((m.name, m.status.value, m.value_text, m.guideline) for m in report.metrics),
    )


def _run_qc_report(data: np.ndarray, params: dict) -> ProcessResult:
    """Informe de control de calidad unificado (§31) + panel de estado
    por objeto (§42) -- reutiliza EXACTAMENTE la misma traza/extracción
    real que 'Trazar espectro' (mismo clic, mismos parámetros) para no
    calcular una traza distinta solo para este informe, más la
    calibración en longitud de onda YA ajustada sobre esta imagen (si la
    hay, incluido el rango real cubierto y la dispersión real en el
    centro) y la máscara de calidad de TODO el fotograma (mismo motor
    que 'Mapa de calidad 2D'). Ver astrophysics_suite.spectroscopy.
    qc_report para la clasificación OK/WARNING/ERROR de cada número real."""
    points = params.get("_picked_points") or []
    if len(points) != 1:
        raise ValueError(
            "se necesita exactamente un clic marcando el centro espacial inicial de la traza -- "
            "el informe de calidad reutiliza la misma traza real que 'Trazar espectro'"
        )
    _x0, y0 = points[0]

    sat_mask, _n_saturated, saturate_adu = _saturation_mask_from_header(data, params)
    trace = trace_spectrum(data, initial_center_px=y0, fit_degree=int(params["fit_degree"]), mask=sat_mask)
    uncertainty, _gain_note = _uncertainty_adu(data, params)
    spectrum = extract_sum(data, uncertainty, trace, aperture_half_width=params["aperture_half_width"], mask=sat_mask)
    with np.errstate(divide="ignore", invalid="ignore"):
        snr_array = np.where(spectrum.flux_uncertainty > 0, spectrum.flux / spectrum.flux_uncertainty, np.nan)
    median_snr = float(np.nanmedian(snr_array)) if np.any(np.isfinite(snr_array)) else float("nan")

    header = params.get("_header")
    quality_mask = build_pixel_mask(data, saturate_adu=saturate_adu)
    if bool(params.get("detect_cosmic_rays")):
        gain = _header_positive_float(header, "GAIN")
        read_noise = _header_positive_float(header, "RDNOISE") or 0.0
        cr_result = detect_cosmic_rays(data, gain_e_per_adu=gain or 1.0, read_noise_e=read_noise)
        quality_mask = quality_mask | (cr_result.mask.astype(np.uint16) * np.uint16(PixelFlag.COSMIC_RAY))
    n_bad = int(np.count_nonzero(quality_mask))

    wavelength_solution = params.get("_wavelength_solution")
    wavelength_rms = wavelength_solution.rms_residual if wavelength_solution is not None else None
    pixel_min, pixel_max = 0.0, float(data.shape[1] - 1)

    report = QCReport(metrics=(
        trace_quality_metric(trace.rms_residual_px, trace.n_columns_used_for_fit, len(trace.columns)),
        wavelength_calibration_quality_metric(wavelength_rms),
        wavelength_range_metric(wavelength_solution, pixel_min, pixel_max),
        dispersion_metric(wavelength_solution, (pixel_min + pixel_max) / 2.0),
        snr_metric(median_snr),
        pixel_quality_metric(n_bad, quality_mask.size, saturate_available=saturate_adu is not None),
    ))

    log_lines = tuple(f"[{m.status.value}] {m.name}: {m.value_text} -- {m.guideline}" for m in report.metrics)
    summary = (
        f"Informe de calidad -- estado global: {report.overall_status.value}. "
        + "  ·  ".join(f"{m.name}: {m.status.value}" for m in report.metrics)
    )
    return ProcessResult(output_data=None, summary=summary, log_lines=log_lines, table=_qc_report_table(report))


def _run_multi_aperture(data: np.ndarray, params: dict) -> ProcessResult:
    points = params.get("_picked_points") or []
    if not points:
        raise ValueError("no se marcó ninguna posición -- haz clic sobre cada objeto, o activa 'Detectar automáticamente'")
    aperture_centers = [y for _x, y in points]
    uncertainty, gain_note = _uncertainty_adu(data, params)
    mask, n_saturated, saturate_adu = _saturation_mask_from_header(data, params)

    result = extract_multi_aperture(
        data, uncertainty, aperture_centers=aperture_centers,
        optimal_extraction=bool(params["optimal_extraction"]), fit_degree=int(params["fit_degree"]),
        aperture_half_width=params["aperture_half_width"], bg_offset=params["bg_offset"], bg_half_width=params["bg_half_width"],
        mask=mask,
    )
    # flux=NaN en columnas sin medida real (nunca 0.0, ver spectroscopy/trace.py):
    # se excluyen de la mediana en vez de sesgarla hacia abajo.

    log_lines = [
        f"Apertura {a.aperture_id}: centro y={a.initial_center_px:.1f} px, RMS de traza={a.trace.rms_residual_px:.2f} px."
        for a in result.apertures
    ]
    log_lines.extend(
        f"Apertura {f.aperture_id} (y={f.initial_center_px:.1f} px): no se pudo extraer -- {f.reason}" for f in result.failures
    )
    if not result.apertures:
        raise ValueError("ninguna de las aperturas marcadas se pudo trazar/extraer: " + "; ".join(f.reason for f in result.failures))

    plot_data = SpectrumPlotData(
        series=tuple(
            SpectrumSeries(
                label=f"Apertura {a.aperture_id} (y={a.initial_center_px:.1f} px)",
                x=np.arange(a.spectrum.flux.size, dtype=np.float64), y=a.spectrum.flux,
                y_error=a.spectrum.flux_uncertainty, color=series_color(i),
            )
            for i, a in enumerate(result.apertures)
        ),
        x_label="Píxel (dispersión)", y_label="Flujo extraído (ADU)",
    )

    method = "óptima (Horne 1986)" if params["optimal_extraction"] else "suma simple"
    failed_note = f", {len(result.failures)} fallida(s)" if result.failures else ""
    saturation_note = f" ({n_saturated} píxel(es) saturado(s), SATURATE={saturate_adu:.0f} ADU, excluido(s))" if n_saturated else ""
    noise_note = f" (ruido real: {gain_note})" if gain_note else ""
    summary = f"{len(result.apertures)} apertura(s) extraída(s) ({method}){failed_note}{saturation_note}{noise_note}."

    table = Table(
        columns=("aperture_id", "center_px", "trace_rms_px", "median_flux"),
        units=("", "px", "px", "ADU"),
        rows=tuple((a.aperture_id, a.initial_center_px, a.trace.rms_residual_px, float(np.nanmedian(a.spectrum.flux))) for a in result.apertures),
    )
    sky_windows = (
        SkyWindow(offset_px=-params["bg_offset"], half_width_px=params["bg_half_width"]),
        SkyWindow(offset_px=params["bg_offset"], half_width_px=params["bg_half_width"]),
    )
    overlays = tuple(
        TraceOverlay(
            trace_columns=a.trace.columns.astype(np.float64), trace_center_px=a.trace.center_px,
            aperture_half_width=float(params["aperture_half_width"]), sky_windows=sky_windows,
            label=f"Apertura {a.aperture_id}",
        )
        for a in result.apertures
    )
    return ProcessResult(
        output_data=None, summary=summary, log_lines=tuple(log_lines), table=table,
        artifacts={"spectrum": plot_data, "trace_overlay": overlays},
    )


def _run_extended_extraction(data: np.ndarray, params: dict) -> ProcessResult:
    points = params.get("_picked_points") or []
    if len(points) < 2:
        raise ValueError(
            "marca dos clics por cada región (fila inicial y fila final del objeto extendido) -- clic derecho para terminar"
        )
    if len(points) % 2 != 0:
        raise ValueError(
            f"se marcaron {len(points)} clic(s) -- cada región necesita EXACTAMENTE dos (fila inicial y fila final); "
            "el último clic quedó sin pareja"
        )

    regions = []
    for i in range(0, len(points), 2):
        _x1, y1 = points[i]
        _x2, y2 = points[i + 1]
        row_start, row_end = sorted((float(y1), float(y2)))
        regions.append(SpatialRegion(row_start=row_start, row_end=row_end, label=f"región {i // 2 + 1}"))

    uncertainty, gain_note = _uncertainty_adu(data, params)
    mask, n_saturated, saturate_adu = _saturation_mask_from_header(data, params)
    sky_windows = (
        SkyWindow(offset_px=-params["bg_offset"], half_width_px=params["bg_half_width"]),
        SkyWindow(offset_px=params["bg_offset"], half_width_px=params["bg_half_width"]),
    )
    result = extract_multi_region(data, uncertainty, regions, mask=mask, sky_windows=sky_windows)

    log_lines = [
        f"{e.region.label}: filas {e.region.row_start:.1f}-{e.region.row_end:.1f} px."
        for e in result.extractions
    ]
    log_lines.extend(
        f"{f.region.label} (filas {f.region.row_start:.1f}-{f.region.row_end:.1f} px): no se pudo extraer -- {f.reason}"
        for f in result.failures
    )
    if not result.extractions:
        raise ValueError("ninguna de las regiones marcadas se pudo extraer: " + "; ".join(f.reason for f in result.failures))

    plot_data = SpectrumPlotData(
        series=tuple(
            SpectrumSeries(
                label=f"{e.region.label} (filas {e.region.row_start:.1f}-{e.region.row_end:.1f} px)",
                x=np.arange(e.spectrum.flux.size, dtype=np.float64), y=e.spectrum.flux,
                y_error=e.spectrum.flux_uncertainty, color=series_color(i),
            )
            for i, e in enumerate(result.extractions)
        ),
        x_label="Píxel (dispersión)", y_label="Flujo extraído (ADU)",
    )

    failed_note = f", {len(result.failures)} fallida(s)" if result.failures else ""
    saturation_note = f" ({n_saturated} píxel(es) saturado(s), SATURATE={saturate_adu:.0f} ADU, excluido(s))" if n_saturated else ""
    noise_note = f" (ruido real: {gain_note})" if gain_note else ""
    summary = f"{len(result.extractions)} región(es) extendida(s) extraída(s) por suma simple{failed_note}{saturation_note}{noise_note}."

    table = Table(
        columns=("region", "row_start_px", "row_end_px", "median_flux"),
        units=("", "px", "px", "ADU"),
        rows=tuple(
            (e.region.label, e.region.row_start, e.region.row_end, float(np.nanmedian(e.spectrum.flux)))
            for e in result.extractions
        ),
    )
    n_columns = data.shape[1]
    overlays = tuple(
        TraceOverlay(
            trace_columns=np.arange(n_columns, dtype=np.float64),
            trace_center_px=np.full(n_columns, e.region.center_px, dtype=np.float64),
            aperture_half_width=e.region.half_width_px, sky_windows=sky_windows, label=e.region.label,
        )
        for e in result.extractions
    )
    return ProcessResult(
        output_data=None, summary=summary, log_lines=tuple(log_lines), table=table,
        artifacts={"spectrum": plot_data, "trace_overlay": overlays},
    )


def _run_continuum_fit_central_row(data: np.ndarray, params: dict) -> ProcessResult:
    row_index = data.shape[0] // 2
    flux = data[row_index, :].astype(np.float64)
    pixel = np.arange(flux.size, dtype=np.float64)
    uncertainty_full, _gain_note = _uncertainty_adu(data, params)
    flux_uncertainty = uncertainty_full[row_index, :].astype(np.float64)

    fit = fit_continuum(pixel, flux, degree=int(params["degree"]), sigma_clip=params["sigma_clip"])
    summary = f"Continuo ajustado sobre la fila central (grado {int(params['degree'])}); RMS={fit.rms_residual:.2f}, {fit.n_rejected} píxel(es) rechazados."
    plot_data = SpectrumPlotData(
        series=(
            SpectrumSeries(label="Flujo", x=pixel, y=flux, y_error=flux_uncertainty),
            SpectrumSeries(label="Continuo ajustado", x=pixel, y=fit.continuum, color=series_color(1), style="dashed"),
        ),
        x_label="Píxel (fila central)", y_label="Flujo (ADU)",
    )
    return ProcessResult(output_data=None, summary=summary, artifacts={"spectrum": plot_data})


def _run_line_measurement_central_row(data: np.ndarray, params: dict) -> ProcessResult:
    points = params.get("_picked_points") or []
    if not points:
        raise ValueError("no se marcó ninguna posición -- haz clic sobre el pico de la línea antes de medir")
    x0, _y0 = points[0]

    row_index = data.shape[0] // 2
    flux = data[row_index, :].astype(np.float64)
    pixel = np.arange(flux.size, dtype=np.float64)
    # ruido real (GAIN/RDNOISE de cabecera) si están disponibles, o el
    # mismo modelo Poisson aproximado (sqrt(ADU)) que photometry.aperture
    # si no -- ver `_uncertainty_adu`.
    uncertainty_full, _gain_note = _uncertainty_adu(data, params)
    flux_uncertainty = uncertainty_full[row_index, :].astype(np.float64)

    continuum_fit = fit_continuum(pixel, flux, degree=int(params["degree"]), sigma_clip=params["sigma_clip"])
    window_halfwidth = params["window_halfwidth_px"]

    result = measure_line(
        pixel, flux, continuum_fit.continuum,
        expected_wavelength=x0, window_halfwidth=window_halfwidth, flux_uncertainty=flux_uncertainty,
    )
    if result is None:
        raise ValueError(
            f"La ventana [{x0 - window_halfwidth:.1f}, {x0 + window_halfwidth:.1f}] px deja menos de 3 "
            "puntos reales dentro del espectro -- amplía la ventana o revisa dónde hiciste clic."
        )

    fwhm_text = f"{result.fwhm:.2f} px" if result.fwhm is not None else "N/D (el perfil no cruza la media altura dentro de la ventana)"
    ew_text = (
        f"{result.equivalent_width:.2f} ± {result.equivalent_width_error:.2f} px"
        if result.equivalent_width is not None
        else "N/D (continuo no positivo en toda la ventana)"
    )
    flux_error_text = f"{result.integrated_flux_error:.1f}" if result.integrated_flux_error is not None else "N/D"
    summary = (
        f"Centro={result.center_wavelength:.2f} px  ·  FWHM={fwhm_text}  ·  "
        f"Flujo integrado={result.integrated_flux:.1f} ± {flux_error_text}  ·  EW={ew_text}"
    )
    log_lines = (
        f"Ventana de medición: [{result.window[0]:.1f}, {result.window[1]:.1f}] px ({result.n_points} punto(s) reales).",
        f"Ajuste de continuo: grado {int(params['degree'])}, {continuum_fit.n_rejected} píxel(es) rechazados por sigma-clip.",
        "Eje horizontal en píxeles de la fila central sin calibrar -- misma convención que 'Ajuste de continuo (fila central)'; "
        "usa 'Calibrar longitud de onda' primero si necesitas el resultado en unidades físicas.",
    )
    table = Table(
        columns=("center_px", "fwhm_px", "integrated_flux", "integrated_flux_error", "equivalent_width_px", "equivalent_width_error_px"),
        units=("px", "px", "ADU·px", "ADU·px", "px", "px"),
        rows=(
            (
                result.center_wavelength,
                result.fwhm if result.fwhm is not None else float("nan"),
                result.integrated_flux,
                result.integrated_flux_error if result.integrated_flux_error is not None else float("nan"),
                result.equivalent_width if result.equivalent_width is not None else float("nan"),
                result.equivalent_width_error if result.equivalent_width_error is not None else float("nan"),
            ),
        ),
    )
    plot_data = SpectrumPlotData(
        series=(
            SpectrumSeries(label="Flujo", x=pixel, y=flux, y_error=flux_uncertainty),
            SpectrumSeries(label="Continuo ajustado", x=pixel, y=continuum_fit.continuum, color=series_color(1), style="dashed"),
        ),
        x_label="Píxel (fila central)", y_label="Flujo (ADU)",
        markers=(SpectrumMarker(x_start=result.window[0], x_end=result.window[1], label="Ventana de medición"),),
    )
    return ProcessResult(output_data=None, summary=summary, log_lines=log_lines, table=table, artifacts={"spectrum": plot_data})


def _run_line_profile_fit_central_row(data: np.ndarray, params: dict) -> ProcessResult:
    points = params.get("_picked_points") or []
    if not points:
        raise ValueError("no se marcó ninguna posición -- haz clic sobre el pico de la línea antes de ajustar")
    x0, _y0 = points[0]

    row_index = data.shape[0] // 2
    flux = data[row_index, :].astype(np.float64)
    pixel = np.arange(flux.size, dtype=np.float64)
    uncertainty_full, _gain_note = _uncertainty_adu(data, params)
    flux_uncertainty = uncertainty_full[row_index, :].astype(np.float64)

    continuum_fit = fit_continuum(pixel, flux, degree=int(params["degree"]), sigma_clip=params["sigma_clip"])
    window_halfwidth = params["window_halfwidth_px"]
    profile = params["profile"]
    min_significance_sigma = params["min_significance_sigma"]

    fit_kwargs = dict(
        expected_wavelength=x0, window_halfwidth=window_halfwidth, flux_uncertainty=flux_uncertainty,
        min_significance_sigma=min_significance_sigma,
    )
    if profile == "gaussian":
        result = fit_gaussian_line(pixel, flux, continuum_fit.continuum, **fit_kwargs)
    else:
        result = fit_voigt_line(pixel, flux, continuum_fit.continuum, **fit_kwargs)

    if result is None:
        raise ValueError(
            f"El ajuste {profile} no convergió a una línea real (>= {min_significance_sigma:g}σ) en "
            f"[{x0 - window_halfwidth:.1f}, {x0 + window_halfwidth:.1f}] px -- revisa dónde hiciste clic, "
            "amplía la ventana, o baja el umbral de significancia."
        )

    if profile == "gaussian":
        fwhm_unc_text = f" ± {result.fwhm_uncertainty:.2f}" if result.fwhm_uncertainty is not None else ""
        chi2_text = f"{result.reduced_chi_square:.2f}" if result.reduced_chi_square is not None else "N/D (sin incertidumbre real de flujo)"
        summary = (
            f"Gaussiana: centro={result.center_wavelength:.2f} ± {result.center_wavelength_uncertainty:.2f} px  ·  "
            f"FWHM={result.fwhm:.2f}{fwhm_unc_text} px  ·  σ_detección={result.significance:.1f}  ·  χ²_red={chi2_text}"
        )
        log_lines = (
            f"Ventana de ajuste: [{result.window[0]:.1f}, {result.window[1]:.1f}] px ({result.n_points} punto(s) reales).",
            f"Ajuste de continuo: grado {int(params['degree'])}, {continuum_fit.n_rejected} píxel(es) rechazados por sigma-clip.",
            "Perfil Gaussiano real (astropy.modeling, mínimos cuadrados no lineales) -- incertidumbre real de la "
            "matriz de covarianza del ajuste, distinto del centroide de momento de 'Medición de línea (splot)'.",
        )
        table = Table(
            columns=("center_px", "center_unc_px", "fwhm_px", "fwhm_unc_px", "integrated_flux", "integrated_flux_unc", "equivalent_width_px", "significance", "reduced_chi_square"),
            units=("px", "px", "px", "px", "ADU·px", "ADU·px", "px", "", ""),
            rows=((
                result.center_wavelength, result.center_wavelength_uncertainty, result.fwhm, result.fwhm_uncertainty,
                result.integrated_flux, result.integrated_flux_uncertainty,
                result.equivalent_width if result.equivalent_width is not None else float("nan"),
                result.significance, result.reduced_chi_square if result.reduced_chi_square is not None else float("nan"),
            ),),
        )
    else:
        summary = (
            f"Voigt: centro={result.center_wavelength:.2f} ± {result.center_wavelength_uncertainty:.2f} px  ·  "
            f"FWHM_Voigt={result.fwhm_voigt:.2f} px (L={result.fwhm_lorentzian:.2f}, G={result.fwhm_gaussian:.2f})  ·  "
            f"σ_detección={result.significance:.1f}"
        )
        log_lines = (
            f"Ventana de ajuste: [{result.window[0]:.1f}, {result.window[1]:.1f}] px ({result.n_points} punto(s) reales).",
            f"Ajuste de continuo: grado {int(params['degree'])}, {continuum_fit.n_rejected} píxel(es) rechazados por sigma-clip.",
            "Perfil de Voigt real (astropy.modeling.Voigt1D) -- flujo integrado/EW son la integral numérica del "
            "modelo ajustado, sin incertidumbre propagada (limitación documentada en line_profile_fit.py).",
        )
        table = Table(
            columns=("center_px", "center_unc_px", "fwhm_lorentzian_px", "fwhm_gaussian_px", "fwhm_voigt_px", "integrated_flux", "equivalent_width_px", "significance"),
            units=("px", "px", "px", "px", "px", "ADU·px", "px", ""),
            rows=((
                result.center_wavelength, result.center_wavelength_uncertainty, result.fwhm_lorentzian, result.fwhm_gaussian,
                result.fwhm_voigt, result.integrated_flux, result.equivalent_width if result.equivalent_width is not None else float("nan"),
                result.significance,
            ),),
        )

    # Resolución espectral real (§32): R = λ/FWHM, SIEMPRE en unidades
    # físicas reales -- nunca en píxeles, y nunca confundida con la
    # dispersión (Å/píxel). Solo se calcula cuando hay una calibración en
    # longitud de onda REAL ya ajustada sobre esta imagen (`_wavelength_
    # solution`, poblada por `main_window` cuando existe); sin ella se
    # informa honestamente que no está disponible, en vez de asumir una
    # dispersión inventada.
    wavelength_solution = params.get("_wavelength_solution")
    center_wavelength_angstrom: float | None = None
    fwhm_angstrom: float | None = None
    resolution: float | None = None
    if wavelength_solution is not None:
        center_px = result.center_wavelength  # nombre genérico del dataclass -- aquí siempre en píxel
        fwhm_px = result.fwhm if profile == "gaussian" else result.fwhm_voigt
        dispersion_angstrom_per_px = local_dispersion_at_pixel(wavelength_solution, center_px)
        center_wavelength_angstrom = float(wavelength_solution.pixel_to_wavelength(center_px))
        fwhm_angstrom = abs(fwhm_px * dispersion_angstrom_per_px)
        if fwhm_angstrom > 0:
            resolution = spectral_resolution(center_wavelength_angstrom, fwhm_angstrom)

    if center_wavelength_angstrom is not None:
        resolution_text = f"R≈{resolution:.0f}" if resolution is not None else "R=N/D"
        summary += f"  ·  λ={center_wavelength_angstrom:.2f} Å  ·  FWHM={fwhm_angstrom:.3f} Å  ·  {resolution_text}"
        log_lines = log_lines + (
            f"Resolución espectral real (§32): dispersión local real de {dispersion_angstrom_per_px:.4f} Å/píxel "
            f"en el centro ajustado -- R = λ/FWHM en Å (nunca la dispersión Å/píxel) = "
            f"{center_wavelength_angstrom:.2f}/{fwhm_angstrom:.3f} ≈ {resolution_text}.",
        )
    else:
        log_lines = log_lines + (
            "Resolución espectral real (§32) no disponible: esta imagen no tiene una calibración en longitud de "
            "onda ajustada todavía -- usa antes \"Calibrar longitud de onda...\" (menú Espectroscopía) para obtenerla.",
        )

    table = Table(
        columns=table.columns + ("center_wavelength_angstrom", "fwhm_angstrom", "resolution"),
        units=table.units + ("Å", "Å", ""),
        rows=tuple(
            row + (
                center_wavelength_angstrom if center_wavelength_angstrom is not None else float("nan"),
                fwhm_angstrom if fwhm_angstrom is not None else float("nan"),
                resolution if resolution is not None else float("nan"),
            )
            for row in table.rows
        ),
    )

    plot_data = SpectrumPlotData(
        series=(
            SpectrumSeries(label="Flujo", x=pixel, y=flux, y_error=flux_uncertainty),
            SpectrumSeries(label="Continuo ajustado", x=pixel, y=continuum_fit.continuum, color=series_color(1), style="dashed"),
        ),
        x_label="Píxel (fila central)", y_label="Flujo (ADU)",
        markers=(SpectrumMarker(x_start=result.window[0], x_end=result.window[1], label=f"Ajuste {profile}"),),
    )
    return ProcessResult(output_data=None, summary=summary, log_lines=log_lines, table=table, artifacts={"spectrum": plot_data})


_OBJECT_LINE_CATALOGS: dict[str, tuple] = {
    "Balmer (H, estelar)": BALMER_LINES,
    "Ca II H&K (estelar)": CALCIUM_LINES,
    "Na D (estelar/interestelar)": SODIUM_LINES,
    "Nebulares ([O III]/[N II]/[S II])": NEBULAR_EMISSION_LINES,
    "Todas (estelar + nebular)": STELLAR_NEBULAR_LINES,
}


def _run_identify_object_lines(data: np.ndarray, params: dict) -> ProcessResult:
    solution = params.get("_wavelength_solution")
    if solution is None:
        raise ValueError(
            "Esta imagen no tiene una calibración en longitud de onda ajustada todavía -- usa antes "
            "\"Calibrar longitud de onda...\" (menú Espectroscopía)."
        )

    row_index = data.shape[0] // 2
    flux = data[row_index, :].astype(np.float64)
    pixel = np.arange(flux.size, dtype=np.float64)
    wavelength = np.asarray(solution.pixel_to_wavelength(pixel), dtype=np.float64)
    uncertainty_full, _gain_note = _uncertainty_adu(data, params)
    flux_uncertainty = uncertainty_full[row_index, :].astype(np.float64)

    continuum_fit = fit_continuum(wavelength, flux, degree=int(params["degree"]), sigma_clip=params["sigma_clip"], reject=params["continuum_reject"])
    catalog = _OBJECT_LINE_CATALOGS[params["catalog"]]
    tolerance_angstrom = params["tolerance_angstrom"]

    matches = identify_object_lines_in_spectrum(
        wavelength, flux, continuum_fit.continuum, catalog,
        min_snr=params["min_snr"], min_separation_angstrom=params["min_separation_angstrom"],
        tolerance_angstrom=tolerance_angstrom, flag_telluric=params["flag_telluric"],
    )

    n_type_mismatch = sum(1 for m in matches if not m.line_type_agrees)
    n_telluric = sum(1 for m in matches if m.telluric_overlap is not None)
    summary = (
        f"{len(matches)} línea(s) identificada(s) contra «{params['catalog']}» "
        f"({n_type_mismatch} con el tipo (absorción/emisión) sin concordar, {n_telluric} solapando una banda telúrica conocida)."
        if matches else f"Ninguna línea real detectada coincide con «{params['catalog']}» dentro de {tolerance_angstrom:g} Å."
    )
    log_lines = (
        f"Ajuste de continuo: grado {int(params['degree'])}, {continuum_fit.n_rejected} píxel(es) rechazados por sigma-clip.",
        "SUGERENCIAS únicamente (§10/§21): ninguna identificación se acepta automáticamente -- revisa cada una, "
        "en particular las marcadas con tipo sin concordar o solape telúrico, antes de darlas por buenas.",
    )
    table = Table(
        columns=(
            "catalog_label", "element", "detected_wavelength", "catalog_wavelength_air",
            "catalog_wavelength_vacuum", "residual_angstrom", "confidence", "type_agrees", "telluric_band",
        ),
        units=("", "", "Å", "Å", "Å", "Å", "", "", ""),
        rows=tuple(
            (
                m.catalog_line.label, m.catalog_line.element, m.detected_wavelength,
                m.catalog_line.wavelength_air_angstrom, m.catalog_line.wavelength_vacuum_angstrom,
                m.residual_angstrom, m.confidence,
                "sí" if m.line_type_agrees else "NO", m.telluric_overlap.name if m.telluric_overlap else "",
            )
            for m in matches
        ),
    )
    markers = tuple(
        SpectrumMarker(
            x_start=m.detected_wavelength - tolerance_angstrom, x_end=m.detected_wavelength + tolerance_angstrom,
            label=m.catalog_line.label + (" ¿telúrica?" if m.telluric_overlap else ""),
            color="#e05252" if not m.line_type_agrees else ("#e0a852" if m.telluric_overlap else "#f0b429"),
        )
        for m in matches
    )
    plot_data = SpectrumPlotData(
        series=(
            SpectrumSeries(label="Flujo", x=wavelength, y=flux, y_error=flux_uncertainty),
            SpectrumSeries(label="Continuo ajustado", x=wavelength, y=continuum_fit.continuum, color=series_color(1), style="dashed"),
        ),
        x_label="Longitud de onda (Å)", y_label="Flujo (ADU)", markers=markers, x_unit="Å",
    )
    return ProcessResult(output_data=None, summary=summary, log_lines=log_lines, table=table, artifacts={"spectrum": plot_data})


def _run_reference_star_calibration(data: np.ndarray, params: dict) -> ProcessResult:
    """Calibración en longitud de onda PROVISIONAL por estrella de
    referencia (§13) -- misma convención de fila central que "Calibrar
    longitud de onda..." (`_open_wavelength_fit_flow`), pero detectando
    líneas de objeto reales (absorción Y emisión) contra un catálogo de
    objeto en vez de líneas de arco. `reference_object` se lee del
    `OBJECT` real de la cabecera FITS si lo hay -- nunca se inventa un
    nombre de estrella."""
    row_index = data.shape[0] // 2
    flux = data[row_index, :].astype(np.float64)
    pixel = np.arange(flux.size, dtype=np.float64)
    continuum_fit = fit_continuum(pixel, flux, degree=int(params["continuum_degree"]), sigma_clip=params["sigma_clip"])

    header = params.get("_header")
    object_name = (header or {}).get("OBJECT")
    reference_object = str(object_name).strip() if object_name else "(objeto sin nombre en la cabecera FITS)"

    try:
        record = calibrate_from_reference_star(
            pixel, flux, continuum_fit.continuum, _OBJECT_LINE_CATALOGS[params["catalog"]],
            approx_dispersion_angstrom_per_px=params["approx_dispersion_angstrom_per_px"],
            approx_wavelength_at_pixel0=params["approx_wavelength_at_pixel0"],
            tolerance_angstrom=params["tolerance_angstrom"], reference_object=reference_object,
            degree=int(params["degree"]), min_snr=params["min_snr"],
        )
    except ValueError as exc:
        raise ValueError(f"No se pudo inferir una calibración por estrella de referencia: {exc}") from exc

    provenance = build_wavelength_provenance(record)
    summary = (
        f"Calibración PROVISIONAL por estrella de referencia ({reference_object}): grado {record.solution.degree}, "
        f"{record.n_lines_used} línea(s) real(es) usada(s) (RMS={record.solution.rms_residual:.4f} Å)."
    )
    log_lines = tuple(record.describe()) + tuple(f"AVISO: {w}" for w in provenance.warnings)
    table = Table(
        columns=("degree", "n_lines_used", "n_lines_rejected", "rms_residual_angstrom", "reference_object"),
        units=("", "", "", "Å", ""),
        rows=((
            record.solution.degree, record.n_lines_used, record.n_lines_rejected,
            record.solution.rms_residual, reference_object,
        ),),
    )
    return ProcessResult(
        output_data=None, summary=summary, log_lines=log_lines, table=table,
        artifacts={"wavelength_calibration_record": record, "wavelength_calibration_spectrum": flux},
    )


def _run_autoprocess_spectrum(data: np.ndarray, params: dict) -> ProcessResult:
    """Autoprocesar espectro (§34): un único clic encadena TODA la cadena
    real de este taller para un espectro estelar ya reducido -- trazado
    -> extracción -> calibración en longitud de onda por estrella de
    referencia (§13, PROVISIONAL) -> identificación de líneas
    (SUGERENCIAS) -> informe de calidad (§31/§42) -- reutilizando
    exactamente los mismos motores que ya usan por separado 'Extracción
    de traza', 'Calibrar por estrella de referencia' e 'Identificar
    líneas automáticamente' (ver astrophysics_suite.spectroscopy.
    autoprocess.run_autoprocess_spectrum, que hace la orquestación real).
    Cada etapa reporta su propio estado real («ok»/«omitido»/«error»)
    en el registro de operaciones -- un fallo en una etapa opcional
    (calibración, identificación) nunca oculta lo que sí se completó
    antes.

    FUERA de alcance (mismos límites que documenta el módulo de
    orquestación): bias/dark/flat (aplícalos antes, desde el menú
    "Reducción", sobre CUALQUIER imagen) y calibración de flujo
    (sensfunc, necesita un espectro de estrella ESTÁNDAR aparte)."""
    points = params.get("_picked_points") or []
    if len(points) != 1:
        raise ValueError("se necesita exactamente un clic marcando el centro espacial inicial de la traza")
    _x0, y0 = points[0]

    header = params.get("_header")
    sat_mask, _n_saturated, saturate_adu = _saturation_mask_from_header(data, params)
    uncertainty, gain_note = _uncertainty_adu(data, params)
    extraction_method = params["extraction_method"]
    extractor = _EXTRACTION_METHODS[extraction_method]
    sky_smooth_degree = int(params["sky_smooth_degree"]) or None

    quality_mask = build_pixel_mask(data, saturate_adu=saturate_adu)
    if bool(params.get("detect_cosmic_rays")):
        gain = _header_positive_float(header, "GAIN")
        read_noise = _header_positive_float(header, "RDNOISE") or 0.0
        cr_result = detect_cosmic_rays(data, gain_e_per_adu=gain or 1.0, read_noise_e=read_noise)
        quality_mask = quality_mask | (cr_result.mask.astype(np.uint16) * np.uint16(PixelFlag.COSMIC_RAY))

    object_name = (header or {}).get("OBJECT")
    reference_object = str(object_name).strip() if object_name else "(objeto sin nombre en la cabecera FITS)"

    result = run_autoprocess_spectrum(
        data, uncertainty, y0,
        mask=sat_mask, quality_mask=quality_mask, saturate_available=saturate_adu is not None,
        fit_degree=int(params["fit_degree"]), aperture_half_width=params["aperture_half_width"],
        extractor=extractor, extraction_method_label=extraction_method, sky_smooth_degree=sky_smooth_degree,
        calibrate_wavelength=bool(params["calibrate_wavelength"]),
        calibration_catalog=_OBJECT_LINE_CATALOGS[params["calibration_catalog"]], reference_object=reference_object,
        approx_dispersion_angstrom_per_px=params["approx_dispersion_angstrom_per_px"],
        approx_wavelength_at_pixel0=params["approx_wavelength_at_pixel0"],
        calibration_tolerance_angstrom=params["calibration_tolerance_angstrom"],
        identify_lines=bool(params["identify_lines"]),
        identify_catalog=_OBJECT_LINE_CATALOGS[params["identify_catalog"]],
        identify_tolerance_angstrom=params["identify_tolerance_angstrom"],
    )

    pixel = np.arange(result.spectrum.flux.size, dtype=np.float64)
    if result.wavelength_solution is not None:
        x = np.asarray(result.wavelength_solution.pixel_to_wavelength(pixel), dtype=np.float64)
        x_label, x_unit = "Longitud de onda (Å)", "Å"
    else:
        x, x_label, x_unit = pixel, "Píxel (dispersión)", ""

    markers = tuple(
        SpectrumMarker(
            x_start=m.detected_wavelength - params["identify_tolerance_angstrom"],
            x_end=m.detected_wavelength + params["identify_tolerance_angstrom"],
            label=m.catalog_line.label + (" ¿telúrica?" if m.telluric_overlap else ""),
            color="#e05252" if not m.line_type_agrees else ("#e0a852" if m.telluric_overlap else "#f0b429"),
        )
        for m in result.line_matches
    )
    plot_data = SpectrumPlotData(
        series=(SpectrumSeries(label="Flujo extraído", x=x, y=result.spectrum.flux, y_error=result.spectrum.flux_uncertainty),),
        x_label=x_label, y_label="Flujo extraído (ADU)", markers=markers, x_unit=x_unit,
    )
    overlay = TraceOverlay(
        trace_columns=result.trace.columns.astype(np.float64), trace_center_px=result.trace.center_px,
        aperture_half_width=float(params["aperture_half_width"]), sky_windows=DEFAULT_SKY_WINDOWS,
        label="Traza (autoproceso)",
    )

    noise_note = f"; ruido real ({gain_note})" if gain_note else "; ruido Poisson aproximado (sin GAIN real)"
    summary = (
        f"Autoproceso desde y={y0:.1f} ({extraction_method}){noise_note} -- "
        f"estado global: {result.qc_report.overall_status.value}. "
        + "  ·  ".join(f"{s.name}: {s.status}" for s in result.steps)
    )
    log_lines = tuple(f"[{s.status}] {s.name}: {s.detail}" for s in result.steps)

    artifacts: dict = {"spectrum": plot_data, "trace_overlay": overlay}
    if result.calibration_record is not None:
        artifacts["wavelength_calibration_record"] = result.calibration_record
        artifacts["wavelength_calibration_spectrum"] = result.spectrum.flux
    return ProcessResult(
        output_data=None, summary=summary, log_lines=log_lines, table=_qc_report_table(result.qc_report), artifacts=artifacts,
    )


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


_NO_INSTRUMENT_PROFILE = "(usar cabecera FITS)"


def build_process_registry(*, profile_store: InstrumentProfileStore | None = None) -> list[ProcessDefinition]:
    """`profile_store` es inyectable para pruebas (mismo patrón que
    `ReduceSessionDialog`) -- por defecto lee los perfiles de instrumento
    REALES ya guardados por el usuario (`services.instrument_profiles`,
    Fase 10.2) para ofrecerlos como respaldo de GAIN/RDNOISE en los
    procesos de espectroscopía que todavía no tienen esos valores en la
    cabecera FITS de la exposición concreta."""
    profile_names = tuple(sorted((profile_store or InstrumentProfileStore()).load_all().keys()))
    instrument_profile_choices = (_NO_INSTRUMENT_PROFILE, *profile_names)
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
            process_id="imtools.debayer",
            name="Demosaico de mosaico de color (OSC/Bayer)",
            category="Utilidades de imagen",
            description=(
                "Convierte el mosaico CFA/Bayer de una cámara de color (OSC) en una imagen utilizable. "
                "'Luminancia' y 'SuperPixel' NO interpolan ningún valor (cada píxel de salida es una medida real del "
                "sensor) y son los correctos para detección y fotometría; 'Bilineal' conserva la resolución completa "
                "interpolando los canales que faltan -- se ve mejor, pero la mayoría de sus valores son inventados por "
                "interpolación y falsean la fotometría. Luminancia y SuperPixel duplican la escala de píxel."
            ),
            parameters=(
                ParameterSpec("method", "Método", "choice", "luminancia", choices=("luminancia", "superpixel", "bilineal")),
                ParameterSpec("pattern", "Patrón", "choice", "auto", choices=("auto", *BAYER_PATTERNS)),
            ),
            run=_run_debayer,
        ),
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
                ParameterSpec("sigma_px", "Sigma de la PSF gaussiana (px)", "float", 2.0, minimum=0.3, maximum=30.0),
                ParameterSpec("fit_half_size", "Semiancho de la caja de ajuste (px)", "int", 7, minimum=2, maximum=100),
                ParameterSpec(
                    "use_moffat_psf", "Usar perfil de Moffat (colas realistas)", "bool", False,
                    help_text="En vez de la Gaussiana, usa un perfil de Moffat -- colas más pesadas, el modelo preferido para seeing atmosférico real.",
                ),
                ParameterSpec("moffat_alpha_px", "Escala radial de Moffat, alpha (px)", "float", 2.0, minimum=0.3, maximum=30.0),
                ParameterSpec("moffat_beta", "Índice de colas de Moffat, beta", "float", 2.5, minimum=1.1, maximum=20.0),
                ParameterSpec(
                    "use_empirical_psf", "Usar PSF empírica (estrellas de referencia)", "bool", False,
                    help_text="Construye la PSF apilando estrellas de referencia reales en vez de un modelo analítico -- captura aberraciones que ni Gaussiana ni Moffat describen. Al pulsar Aplicar se piden primero las estrellas de referencia (clic izq. marca, clic derecho termina) y luego las fuentes a medir. Tiene prioridad sobre Moffat/Gaussiana si está activa.",
                ),
                ParameterSpec("empirical_psf_oversample", "Sobremuestreo de la PSF empírica", "int", 4, minimum=1, maximum=10),
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
            process_id="spectroscopy.quality_map",
            name="Mapa de calidad de píxeles (NaN/saturación/rayos cósmicos)",
            category="Espectroscopía",
            description="Muestra en una imagen nueva QUÉ píxeles reales se excluirían de cualquier traza/extracción y POR QUÉ (frame2d.PixelFlag: no finito siempre, saturado si SATURATE real está en la cabecera, rayo cósmico real si se activa la detección) -- el mismo motor y los mismos umbrales que ya usan spectroscopy.trace/multiaperture/extended_extraction, aquí visibles píxel a píxel en vez de solo un recuento en el resumen de otro proceso. 0 = píxel bueno.",
            parameters=(
                ParameterSpec("detect_cosmic_rays", "Detectar también rayos cósmicos reales (L.A.Cosmic)", "bool", False),
            ),
            run=_run_quality_map,
        ),
        ProcessDefinition(
            process_id="spectroscopy.trace",
            name="Extracción de traza (apall)",
            category="Espectroscopía",
            description="Traza espacial + extracción por suma, media u óptima (Horne 1986) -- eje 0 espacial, eje 1 dispersión. Al pulsar Aplicar, marca con un clic el centro espacial inicial de la traza. El resultado se muestra como una tira 1D repetida (el taller todavía no tiene un visor de espectros dedicado).",
            parameters=(
                ParameterSpec("fit_degree", "Grado del ajuste de traza", "int", 3, minimum=1, maximum=10),
                ParameterSpec("aperture_half_width", "Semiancho de apertura (px)", "float", 4.0, minimum=1.0, maximum=100.0),
                ParameterSpec(
                    "extraction_method", "Método de extracción", "choice", "óptima (Horne 1986)",
                    choices=tuple(_EXTRACTION_METHODS),
                    help_text="suma simple / óptima (Horne 1986, mejor S/N para una fuente débil) / media (§3, flujo medio por píxel de apertura en vez de flujo total).",
                ),
                ParameterSpec(
                    "sky_smooth_degree", "Suavizado polinómico del cielo (grado, 0 = sin suavizar)", "int", 0,
                    minimum=0, maximum=6,
                    help_text="§5: 0 desactiva el suavizado (cielo tal cual por columna); >0 ajusta un polinomio real de ese grado al cielo ya estimado, con rechazo iterativo de outliers.",
                ),
                ParameterSpec(
                    "instrument_profile", "Perfil de instrumento (respaldo GAIN/RDNOISE)", "choice",
                    _NO_INSTRUMENT_PROFILE, choices=instrument_profile_choices,
                    help_text="Solo se usa si la cabecera FITS de esta exposición no trae GAIN real -- la cabecera siempre tiene prioridad.",
                ),
            ),
            run=_run_spectral_trace,
            requires_picking=1,
        ),
        ProcessDefinition(
            process_id="spectroscopy.qc_report",
            name="Informe de control de calidad / panel de estado",
            category="Espectroscopía",
            description="Reúne en un solo informe, con un semáforo OK/WARNING/ERROR por métrica, seis diagnósticos reales ya calculados por separado en otros procesos de este taller: RMS de la traza espacial (mismo motor que 'Extracción de traza'), RMS/rango/dispersión de la calibración en longitud de onda YA ajustada sobre esta imagen (si la hay), S/N mediana de la extracción, y fracción de píxeles marcados en todo el fotograma (mismo motor que 'Mapa de calidad de píxeles'). Los umbrales son guías orientativas, no un estándar absoluto -- se explican en el registro de operaciones. Al pulsar Aplicar, marca con un clic el centro espacial inicial de la traza (misma traza real que 'Extracción de traza').",
            parameters=(
                ParameterSpec("fit_degree", "Grado del ajuste de traza", "int", 3, minimum=1, maximum=10),
                ParameterSpec("aperture_half_width", "Semiancho de apertura (px)", "float", 4.0, minimum=1.0, maximum=100.0),
                ParameterSpec("detect_cosmic_rays", "Incluir rayos cósmicos reales en la calidad de píxeles (L.A.Cosmic)", "bool", False),
                ParameterSpec(
                    "instrument_profile", "Perfil de instrumento (respaldo GAIN/RDNOISE)", "choice",
                    _NO_INSTRUMENT_PROFILE, choices=instrument_profile_choices,
                    help_text="Solo se usa si la cabecera FITS de esta exposición no trae GAIN real -- la cabecera siempre tiene prioridad.",
                ),
            ),
            run=_run_qc_report,
            requires_picking=1,
        ),
        ProcessDefinition(
            process_id="spectroscopy.multiaperture",
            name="Extracción multi-apertura (apall, varios objetos)",
            category="Espectroscopía",
            description="Traza y extrae varios objetos reales de la misma imagen (misma rendija o varias fibras) -- equivalente a apall con varias aperturas. Detecta automáticamente los picos del perfil espacial (mediana a lo largo de toda la dispersión), o desactiva 'Detectar automáticamente' para marcar cada centro a mano (clic izquierdo por objeto, clic derecho para terminar). Una apertura que no se puede trazar se informa como fallo real en el registro en vez de detener todo el lote.",
            parameters=(
                ParameterSpec(
                    "auto_detect", "Detectar automáticamente (perfil espacial)", "bool", True,
                    help_text="Detecta picos reales del perfil espacial colapsado sobre toda la dispersión (mediana robusta) -- desactiva para marcar cada centro a mano.",
                ),
                ParameterSpec("min_snr", "S/N mínima de pico (detección automática)", "float", 5.0, minimum=1.0, maximum=50.0),
                ParameterSpec("min_separation_px", "Separación mínima entre aperturas (px)", "float", 10.0, minimum=1.0, maximum=200.0),
                ParameterSpec("max_apertures", "Máximo de aperturas (detección automática)", "int", 20, minimum=1, maximum=50),
                ParameterSpec("fit_degree", "Grado del ajuste de traza", "int", 3, minimum=1, maximum=10),
                ParameterSpec("aperture_half_width", "Semiancho de apertura (px)", "float", 4.0, minimum=1.0, maximum=100.0),
                ParameterSpec("bg_offset", "Desplazamiento del fondo (px)", "float", 10.0, minimum=1.0, maximum=200.0),
                ParameterSpec("bg_half_width", "Semiancho del fondo (px)", "float", 4.0, minimum=1.0, maximum=100.0),
                ParameterSpec("optimal_extraction", "Extracción óptima (Horne)", "bool", True),
                ParameterSpec(
                    "instrument_profile", "Perfil de instrumento (respaldo GAIN/RDNOISE)", "choice",
                    _NO_INSTRUMENT_PROFILE, choices=instrument_profile_choices,
                    help_text="Solo se usa si la cabecera FITS de esta exposición no trae GAIN real -- la cabecera siempre tiene prioridad.",
                ),
            ),
            run=_run_multi_aperture,
            requires_picking=0,
        ),
        ProcessDefinition(
            process_id="spectroscopy.extended_extraction",
            name="Extracción de objeto extendido (nebulosa/galaxia)",
            category="Espectroscopía",
            description="Extracción por suma simple sobre una o más regiones espaciales FIJAS que tú defines directamente -- NUNCA por extracción óptima (Horne 1986), que asume un único perfil de fuente puntual y describiría mal una emisión difusa/plana o multi-pico real (§27). Por cada región, marca DOS clics: fila inicial y fila final del objeto (en cualquier orden) -- clic derecho para terminar. Puedes marcar varias regiones seguidas (p. ej. núcleo y borde de una misma nebulosa) para resolverla espacialmente.",
            parameters=(
                ParameterSpec("bg_offset", "Desplazamiento del fondo (px)", "float", 20.0, minimum=1.0, maximum=400.0),
                ParameterSpec("bg_half_width", "Semiancho del fondo (px)", "float", 4.0, minimum=1.0, maximum=100.0),
                ParameterSpec(
                    "instrument_profile", "Perfil de instrumento (respaldo GAIN/RDNOISE)", "choice",
                    _NO_INSTRUMENT_PROFILE, choices=instrument_profile_choices,
                    help_text="Solo se usa si la cabecera FITS de esta exposición no trae GAIN real -- la cabecera siempre tiene prioridad.",
                ),
            ),
            run=_run_extended_extraction,
            requires_picking=0,
        ),
        ProcessDefinition(
            process_id="spectroscopy.line",
            name="Medición de línea (splot)",
            category="Espectroscopía",
            description="Centroide, FWHM, ancho equivalente y flujo integrado de una línea real sobre la fila central, tratada como espectro 1D igual que 'Ajuste de continuo' -- equivalente a splot/fitprofs. Al pulsar Aplicar, marca con un clic dónde está el pico de la línea (el taller nunca la busca por su cuenta); el ancho de ventana define hasta dónde se integra a cada lado.",
            parameters=(
                ParameterSpec("window_halfwidth_px", "Semiancho de ventana (px)", "float", 15.0, minimum=1.0, maximum=500.0),
                ParameterSpec("degree", "Grado del ajuste de continuo", "int", 3, minimum=1, maximum=10),
                ParameterSpec("sigma_clip", "Umbral σ de rechazo del continuo", "float", 2.5, minimum=0.5, maximum=10.0),
                ParameterSpec(
                    "instrument_profile", "Perfil de instrumento (respaldo GAIN/RDNOISE)", "choice",
                    _NO_INSTRUMENT_PROFILE, choices=instrument_profile_choices,
                    help_text="Solo se usa si la cabecera FITS de esta exposición no trae GAIN real -- la cabecera siempre tiene prioridad.",
                ),
            ),
            run=_run_line_measurement_central_row,
            requires_picking=1,
        ),
        ProcessDefinition(
            process_id="spectroscopy.line_profile_fit",
            name="Ajuste de perfil de línea (Gaussiana/Voigt)",
            category="Espectroscopía",
            description="Ajuste paramétrico real por mínimos cuadrados no lineales (astropy.modeling) de una línea sobre la fila central -- a diferencia de 'Medición de línea (splot)' (centroide de momento, sin forma de perfil), da una incertidumbre REAL por parámetro desde la covarianza del ajuste. Nunca acepta un ajuste sin convergencia o por debajo del umbral de significancia como una línea real. Al pulsar Aplicar, marca con un clic dónde está el pico.",
            parameters=(
                ParameterSpec("profile", "Perfil", "choice", "gaussian", choices=("gaussian", "voigt")),
                ParameterSpec("window_halfwidth_px", "Semiancho de ventana (px)", "float", 15.0, minimum=1.0, maximum=500.0),
                ParameterSpec("degree", "Grado del ajuste de continuo", "int", 3, minimum=1, maximum=10),
                ParameterSpec("sigma_clip", "Umbral σ de rechazo del continuo", "float", 2.5, minimum=0.5, maximum=10.0),
                ParameterSpec("min_significance_sigma", "Umbral de detección (σ)", "float", 3.0, minimum=1.0, maximum=50.0),
                ParameterSpec(
                    "instrument_profile", "Perfil de instrumento (respaldo GAIN/RDNOISE)", "choice",
                    _NO_INSTRUMENT_PROFILE, choices=instrument_profile_choices,
                    help_text="Solo se usa si la cabecera FITS de esta exposición no trae GAIN real -- la cabecera siempre tiene prioridad.",
                ),
            ),
            run=_run_line_profile_fit_central_row,
            requires_picking=1,
        ),
        ProcessDefinition(
            process_id="spectroscopy.identify_lines",
            name="Identificar líneas automáticamente",
            category="Espectroscopía",
            description="Detecta desviaciones reales del continuo sobre la fila central YA calibrada en longitud de onda (exige haber usado antes \"Calibrar longitud de onda...\") y sugiere, para cada una, la línea de catálogo más cercana -- nunca acepta una identificación automáticamente: revisa el tipo (absorción/emisión, marcado si no concuerda) y el posible solape con una banda telúrica conocida antes de darla por buena. Sin selección de posiciones: opera sobre todo el espectro de una vez.",
            parameters=(
                ParameterSpec("catalog", "Catálogo de líneas", "choice", "Todas (estelar + nebular)", choices=tuple(_OBJECT_LINE_CATALOGS)),
                ParameterSpec("degree", "Grado del ajuste de continuo", "int", 3, minimum=1, maximum=10),
                ParameterSpec("continuum_reject", "Rechazo del continuo", "choice", "both", choices=("both", "absorption", "emission")),
                ParameterSpec("sigma_clip", "Umbral σ de rechazo del continuo", "float", 2.5, minimum=0.5, maximum=10.0),
                ParameterSpec("min_snr", "S/N mínima de detección", "float", 5.0, minimum=1.0, maximum=50.0),
                ParameterSpec("min_separation_angstrom", "Separación mínima entre líneas (Å)", "float", 2.0, minimum=0.1, maximum=200.0),
                ParameterSpec("tolerance_angstrom", "Tolerancia de emparejamiento (Å)", "float", 3.0, minimum=0.1, maximum=200.0),
                ParameterSpec("flag_telluric", "Avisar de solape con bandas telúricas conocidas", "bool", True),
            ),
            run=_run_identify_object_lines,
        ),
        ProcessDefinition(
            process_id="spectroscopy.reference_star_calibration",
            name="Calibrar por estrella de referencia",
            category="Espectroscopía",
            description="Infiere una calibración en longitud de onda PROVISIONAL (§13) sobre la fila central, a partir de líneas reales de objeto (Balmer, Ca II, Na D...) detectadas y emparejadas contra el catálogo elegido -- SIN necesitar una lámpara de calibración real. Nunca al mismo nivel de fiabilidad que una lámpara: la posición de una línea estelar depende también de velocidad radial y ensanchamiento, avisado explícitamente en el registro de operaciones. La dispersión/origen aproximados (de la óptica conocida del instrumento, o de una calibración previa) son responsabilidad tuya -- el taller nunca los supone. Sin selección de posiciones: opera sobre toda la fila central de una vez. La estrella de referencia se toma del OBJECT real de la cabecera FITS si lo tiene.",
            parameters=(
                ParameterSpec("catalog", "Catálogo de líneas de la estrella", "choice", "Balmer (H, estelar)", choices=tuple(_OBJECT_LINE_CATALOGS)),
                ParameterSpec("approx_dispersion_angstrom_per_px", "Dispersión aprox. (Å/px)", "float", 1.4, minimum=0.01, maximum=100.0),
                ParameterSpec("approx_wavelength_at_pixel0", "λ en píxel 0 aprox. (Å)", "float", 3800.0, minimum=0.0, maximum=20000.0),
                ParameterSpec("tolerance_angstrom", "Tolerancia de emparejamiento (Å)", "float", 15.0, minimum=0.1, maximum=500.0),
                ParameterSpec("degree", "Grado del polinomio", "int", 1, minimum=1, maximum=6),
                ParameterSpec("continuum_degree", "Grado del ajuste de continuo", "int", 3, minimum=1, maximum=10),
                ParameterSpec("sigma_clip", "Umbral σ de rechazo del continuo", "float", 2.5, minimum=0.5, maximum=10.0),
                ParameterSpec("min_snr", "S/N mínima de detección", "float", 5.0, minimum=1.0, maximum=50.0),
            ),
            run=_run_reference_star_calibration,
        ),
        ProcessDefinition(
            process_id="spectroscopy.autoprocess",
            name="Autoprocesar espectro (§34)",
            category="Espectroscopía",
            description=(
                "Encadena en un único clic TODA la cadena real de este taller para un espectro estelar YA REDUCIDO: "
                "trazado -> extracción -> calibración en longitud de onda por estrella de referencia (§13, "
                "PROVISIONAL) -> identificación de líneas (SUGERENCIAS) -> informe de calidad (§31/§42) -- los "
                "mismos motores que ya usan por separado 'Extracción de traza', 'Calibrar por estrella de "
                "referencia' e 'Identificar líneas automáticamente', aquí en un solo paso. Cada etapa reporta su "
                "propio estado real (ok/omitido/error) en el registro de operaciones -- un fallo en una etapa "
                "OPCIONAL (p. ej. la calibración, si no hay líneas reales que emparejar) nunca oculta lo que sí se "
                "completó antes (traza y extracción siguen disponibles). NO incluye bias/dark/flat (aplícalos "
                "antes, desde el menú 'Reducción', sobre cualquier imagen) ni calibración de flujo (sensfunc, "
                "necesita un espectro de estrella ESTÁNDAR aparte). Al pulsar Aplicar, marca con un clic el centro "
                "espacial inicial de la traza (misma traza real que 'Extracción de traza')."
            ),
            parameters=(
                ParameterSpec("fit_degree", "Grado del ajuste de traza", "int", 3, minimum=1, maximum=10),
                ParameterSpec("aperture_half_width", "Semiancho de apertura (px)", "float", 4.0, minimum=1.0, maximum=100.0),
                ParameterSpec(
                    "extraction_method", "Método de extracción", "choice", "óptima (Horne 1986)",
                    choices=tuple(_EXTRACTION_METHODS),
                    help_text="suma simple / óptima (Horne 1986) / media (§3).",
                ),
                ParameterSpec(
                    "sky_smooth_degree", "Suavizado polinómico del cielo (grado, 0 = sin suavizar)", "int", 0,
                    minimum=0, maximum=6,
                ),
                ParameterSpec("calibrate_wavelength", "Calibrar en longitud de onda (§13, por estrella de referencia)", "bool", True),
                ParameterSpec(
                    "calibration_catalog", "Catálogo para la calibración", "choice", "Balmer (H, estelar)",
                    choices=tuple(_OBJECT_LINE_CATALOGS),
                ),
                ParameterSpec("approx_dispersion_angstrom_per_px", "Dispersión aprox. (Å/px)", "float", 1.4, minimum=0.01, maximum=100.0),
                ParameterSpec("approx_wavelength_at_pixel0", "λ en píxel 0 aprox. (Å)", "float", 3800.0, minimum=0.0, maximum=20000.0),
                ParameterSpec("calibration_tolerance_angstrom", "Tolerancia de emparejamiento de calibración (Å)", "float", 15.0, minimum=0.1, maximum=500.0),
                ParameterSpec("identify_lines", "Identificar líneas de objeto (sugerencias)", "bool", True),
                ParameterSpec(
                    "identify_catalog", "Catálogo para identificación", "choice", "Todas (estelar + nebular)",
                    choices=tuple(_OBJECT_LINE_CATALOGS),
                ),
                ParameterSpec("identify_tolerance_angstrom", "Tolerancia de emparejamiento de identificación (Å)", "float", 3.0, minimum=0.1, maximum=200.0),
                ParameterSpec("detect_cosmic_rays", "Incluir rayos cósmicos reales en la calidad de píxeles (L.A.Cosmic)", "bool", False),
                ParameterSpec(
                    "instrument_profile", "Perfil de instrumento (respaldo GAIN/RDNOISE)", "choice",
                    _NO_INSTRUMENT_PROFILE, choices=instrument_profile_choices,
                    help_text="Solo se usa si la cabecera FITS de esta exposición no trae GAIN real -- la cabecera siempre tiene prioridad.",
                ),
            ),
            run=_run_autoprocess_spectrum,
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
