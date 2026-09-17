"""Modo genérico del Discovery Engine: `Observation -> list[Candidate]`,
agnóstico del tipo de objeto -- el equivalente tipado del antiguo
Discovery Workspace v57 (`discovery_scan_observation`), pero construido
sobre los motores reales extraídos en la Fase 6 en vez de reimplementar
su propia detección/identificación por separado (el defecto original
que la Fase 1 documentó: tres pipelines de descubrimiento paralelos que
no se hablaban entre sí -- ver docs/audit/01-..., seccion 6).

Orden de ejecución, siguiendo la filosofía central del encargo:

    POR IMAGEN: IMÁGENES -> DEMOSAICO -> WCS -> DETECCIÓN -> FILTRO
    MORFOLÓGICO BARATO -> CARACTERIZACIÓN -> ESTADÍSTICA DE CAMPO ->
    CRIBADO REAL DE ARTEFACTOS (autoritativo, `artifacts/artifact_screen`)

    ENTRE IMÁGENES: AGRUPACIÓN MULTIÉPOCA POR BANDA
    (`discovery/source_tracks`) -> VARIABILIDAD Y MOVIMIENTO POR TRAZA
    (>= 2 épocas) -> IDENTIFICACIÓN (una vez por traza, sobre la época de
    referencia) -> VECTOR DE ANOMALÍA -> CADENA DE EVIDENCIA -> CANDIDATO

El cribado de artefactos ocurre ANTES de que nada se considere candidato
(una detección rechazada por `screen_detection` nunca llega a producir
un Candidate) -- no después, como una anotación sobre un candidato ya
creado. Y el Candidate se construye una vez POR TRAZA física, no una vez
por detección cruda por imagen: antes, con 3 lights reales de M 31, cada
estrella real producía 3 candidatos duplicados en vez de 1 con 3 épocas
de evidencia (ver `discovery/source_tracks.py`, medido: 416/412/492
detecciones por época sobre el mismo campo)."""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable

from astrophysics_suite.anomaly.vector import build_anomaly_vector
from astrophysics_suite.artifacts.artifact_screen import FieldStatistics, compute_field_statistics, screen_detection
from astrophysics_suite.artifacts.morphology_screen import classify_morphology
from astrophysics_suite.astrometry import blind_solve
from astrophysics_suite.astrometry.plate_solve import PlateSolveResult, estimate_approx_pointing_from_header, solve_plate
from astrophysics_suite.astrometry.wcs_fit import angular_separation_deg, rescale_wcs_for_binning, wcs_solution_to_astropy
from astrophysics_suite.catalogs.local_cache import CatalogCache
from astrophysics_suite.imtools.debayer import bayer_pattern_from_header, debayer_to_luminance, describe_bayer_agreement
from astrophysics_suite.catalogs.gaia import identify_detection
from astrophysics_suite.catalogs.simbad import resolve_object_coordinates
from astrophysics_suite.core.enums import IdentificationState, QualityLevel, ValueKind
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.detection.point_sources import detect_point_sources
from astrophysics_suite.discovery.source_tracks import EpochDetection, SourceTrack, group_detections_into_tracks
from astrophysics_suite.evidence.chain_builder import build_evidence_chain
from astrophysics_suite.io.fits_loader import LoadedImage
from astrophysics_suite.models.candidate import ArtifactCheck, Candidate, CatalogMatch, CatalogQuery, QualityCheckItem, QualitySummary
from astrophysics_suite.models.characterization import CharacterizationResult
from astrophysics_suite.models.detection import Detection
from astrophysics_suite.models.observation import Observation
from astrophysics_suite.models.temporal import MotionEvidence, TemporalEvidence
from astrophysics_suite.photometry.calibration import ZeropointFit, fit_zeropoint
from astrophysics_suite.photometry.quality import characterize_point_source
from astrophysics_suite.temporal.motion import analyze_motion
from astrophysics_suite.temporal.variability import analyze_variability

_QUALITY_LEVEL_FOR_STATE = {
    "SCIENCE_CANDIDATE": QualityLevel.PASS,
    "REVIEW": QualityLevel.WARNING,
    "QUALITY_LIMITED": QualityLevel.WARNING,
}


class DiscoveryCancelled(Exception):
    """El usuario canceló la ejecución -- ver `cancel` en
    `run_generic_discovery`. Mismo patrón que `AnalysisCancelled` en el
    código heredado (`legacy...analyze_pair_core`)."""


# Estados reales y mutuamente excluyentes del WCS de cada imagen al
# entrar en Discovery -- nunca "sin WCS" a secas: el motivo concreto
# (ya lo traía / se resolvió automáticamente / se intentó y falló / no
# se intentó) debe llegar a la GUI para que el usuario sepa exactamente
# qué análisis pudieron ejecutarse con coordenadas celestes y cuáles no.
WCS_STATE_PRESENT = "WCS_PRESENTE"
WCS_STATE_AUTO_RESOLVED = "WCS_RESUELTO_Y_VALIDADO_AUTOMATICAMENTE"
WCS_STATE_BLIND_RESOLVED = "WCS_RESUELTO_EN_CIEGO_SIN_PUNTERO"
WCS_STATE_SOLVE_FAILED = "PLATE_SOLVING_FALLIDO"
WCS_STATE_SOLVE_NOT_RUN = "PLATE_SOLVING_NO_EJECUTADO"

# Estados reales del mosaico de color (CFA/Bayer) de cada imagen. Un
# sensor OSC entrega un mosaico donde cada píxel mide UN solo color:
# detectar y medir sobre él directamente sesga fondo, flujo y PSF (ver
# docs/audit/35-DEBAYERING-OSC.md, con la comprobación real sobre lights
# de M 31: 45 fuentes sobre el mosaico crudo frente a 416 tras
# demosaicar). Como con el WCS, el motivo concreto llega siempre a la
# GUI -- nunca se demosaica (ni se deja de hacer) en silencio.
CFA_STATE_DEBAYERED = "MOSAICO_DEMOSAICADO"
CFA_STATE_NOT_CFA = "SIN_MOSAICO_DECLARADO"
CFA_STATE_DISABLED = "DEMOSAICO_DESACTIVADO"
CFA_STATE_FAILED = "DEMOSAICO_FALLIDO"


@dataclass(frozen=True)
class ImageWCSStatus:
    """Resultado real de intentar asegurar un WCS para una imagen antes
    de detectar/identificar fuentes -- consumido por la GUI para mostrar
    con claridad qué pasó con cada imagen (nunca solo "Error")."""

    path: str
    band: str
    state: str
    """Uno de `WCS_STATE_*` -- nunca un texto genérico inventado aquí."""
    detail: str
    """Mensaje legible: por qué ya tenía WCS, qué encontró el plate
    solving (proveedor, RMS, nº de estrellas) o por qué falló/no se
    intentó."""


@dataclass(frozen=True)
class ImageCFAStatus:
    """Qué se hizo con el mosaico de color de una imagen antes de
    detectar fuentes -- consumido por la GUI igual que `ImageWCSStatus`."""

    path: str
    band: str
    state: str
    """Uno de `CFA_STATE_*`."""
    detail: str
    """Mensaje legible: patrón usado, si los datos lo respaldan o no, y
    la nueva escala de píxel tras el demosaico."""


@dataclass(frozen=True)
class DiscoveryRunSummary:
    """El resumen que el usuario final ve tras un escaneo -- ver el
    encargo original: "N fuentes detectadas, M identificadas, X no
    asociadas, Y anomalías y Z candidatos para revisión"."""

    observation_id: str
    n_images: int
    n_detected: int
    n_artifact_rejected: int
    n_candidates: int
    n_known: int
    n_unmatched: int
    n_discovery_review: int
    wcs_status: tuple[ImageWCSStatus, ...] = ()
    cfa_status: tuple[ImageCFAStatus, ...] = ()


def _resolve_approx_pointing(header: dict, target_name: str) -> tuple[float, float, str] | None:
    """Puntero aproximado para `solve_plate`: primero el header FITS (si
    trae RA/DEC u OBJCTRA/OBJCTDEC reconocibles); si no, SIMBAD por el
    NOMBRE del objetivo de la observación (el mismo que el usuario
    escribió en "Nueva observación") -- igual que "Spectrophotometric
    Color Calibration" de PixInsight: el usuario da el nombre real, no
    depende de que la cámara/montura haya escrito RA/Dec en el header
    (con software de captura real, a menudo falta o está en una clave
    distinta). Nunca inventa un puntero -- `None` si ninguna de las dos
    fuentes resuelve."""
    pointing = estimate_approx_pointing_from_header(header)
    if pointing is not None:
        return pointing[0], pointing[1], "header FITS"
    resolved = resolve_object_coordinates(target_name)
    if resolved is not None:
        ra, dec, source = resolved
        return ra, dec, source
    return None


def _debayer_if_cfa(loaded: LoadedImage, image_ref, *, auto_debayer: bool) -> ImageCFAStatus:
    """Convierte un mosaico CFA/Bayer real en un plano de luminancia ANTES
    de detectar o medir nada -- ver `imtools/debayer.py` para el porqué y
    `docs/audit/35-DEBAYERING-OSC.md` para la comprobación con datos
    reales (45 fuentes detectadas sobre el mosaico crudo frente a 416
    tras demosaicar, en el mismo light de M 31).

    Modifica `loaded.legacy_image` en el sitio (datos, WCS y escala de
    píxel, las tres coherentes entre sí tras el binificado 2x2) -- mismo
    patrón que `_ensure_wcs`, que ya escribe `fits_image.wcs`. Nunca
    demosaica sin declararlo: el estado y el motivo real vuelven siempre
    en el `ImageCFAStatus`."""
    fits_image = loaded.legacy_image
    pattern = bayer_pattern_from_header(fits_image.header or {})
    if pattern is None:
        return ImageCFAStatus(
            path=image_ref.path, band=image_ref.band, state=CFA_STATE_NOT_CFA,
            detail="La cabecera no declara BAYERPAT -- se trata como imagen monocroma o ya demosaicada, sin tocar los píxeles.",
        )
    if not auto_debayer:
        return ImageCFAStatus(
            path=image_ref.path, band=image_ref.band, state=CFA_STATE_DISABLED,
            detail=f"La imagen declara un mosaico {pattern} pero el demosaico está desactivado para este análisis -- "
                   f"la detección y la fotometría corren sobre el mosaico crudo, con el sesgo que eso implica.",
        )
    try:
        agreement = describe_bayer_agreement(fits_image.data, fits_image.header or {})
        luminance = debayer_to_luminance(fits_image.data, pattern)
    except Exception as exc:
        return ImageCFAStatus(
            path=image_ref.path, band=image_ref.band, state=CFA_STATE_FAILED,
            detail=f"El demosaico falló ({type(exc).__name__}: {exc}) -- se continúa sobre el mosaico crudo, "
                   f"con el sesgo que eso implica en fondo, flujo y PSF.",
        )

    fits_image.data = luminance
    if fits_image.wcs is not None:
        fits_image.wcs = rescale_wcs_for_binning(fits_image.wcs, 2)
    previous_scale = fits_image.pixel_scale_arcsec
    if previous_scale is not None:
        fits_image.pixel_scale_arcsec = previous_scale * 2.0
    scale_note = (
        f" Escala de píxel: {previous_scale:.4f}\" -> {previous_scale * 2.0:.4f}\"/px."
        if previous_scale is not None else ""
    )
    return ImageCFAStatus(
        path=image_ref.path, band=image_ref.band, state=CFA_STATE_DEBAYERED,
        detail=f"Mosaico {pattern} demosaicado a luminancia por SuperPixel (sin interpolar ningún valor, "
               f"{luminance.shape[1]}x{luminance.shape[0]} px).{scale_note} {agreement.detail}",
    )


def _ensure_wcs(
    loaded: LoadedImage, image_ref, *, target_name: str, auto_plate_solve: bool,
    report: Callable[[float, str], None], progress_fraction: float, pipeline_version: str = "",
) -> ImageWCSStatus:
    """Se asegura de que `loaded.legacy_image.wcs` esté disponible antes
    de detectar fuentes, intentando plate solving automático si falta --
    nunca inventa un WCS ni convierte su ausencia en una excepción:
    cuando no se puede, lo registra explícitamente y Discovery continúa
    (el resto de motores ya degradan con gracia sin WCS, ver
    `catalogs/gaia.py`)."""
    fits_image = loaded.legacy_image
    if fits_image.wcs is not None:
        return ImageWCSStatus(
            path=image_ref.path, band=image_ref.band, state=WCS_STATE_PRESENT,
            detail="El FITS ya traía un WCS válido en la cabecera -- no hizo falta resolver la placa.",
        )
    if not auto_plate_solve:
        return ImageWCSStatus(
            path=image_ref.path, band=image_ref.band, state=WCS_STATE_SOLVE_NOT_RUN,
            detail="Resolución automática de placa desactivada para este análisis -- WCS no disponible, "
                   "continuando sin coordenadas celestes para esta imagen.",
        )
    approx = _resolve_approx_pointing(fits_image.header or {}, target_name)
    pointed_result = None
    if approx is not None:
        approx_ra, approx_dec, pointing_source = approx
        pointing_note = f" (puntero: {pointing_source})"
        report(progress_fraction, f"Resolviendo WCS automáticamente para {image_ref.band}{pointing_note}...")
        pointed_result = solve_plate(
            fits_image.data, fits_image.header or {}, approx_ra_deg=approx_ra, approx_dec_deg=approx_dec,
            pipeline_version=pipeline_version,
        )
        if pointed_result.success:
            fits_image.wcs = wcs_solution_to_astropy(pointed_result.solution)
            return ImageWCSStatus(
                path=image_ref.path, band=image_ref.band, state=WCS_STATE_AUTO_RESOLVED,
                detail=f"WCS resuelto y validado automáticamente ({pointed_result.provider}), puntero{pointing_note}: {pointed_result.reason}.",
            )

    # Sin puntero utilizable, o el puntero disponible no dio una solución
    # válida: se intenta resolución CIEGA (sin ningún puntero, ver
    # `astrometry/blind_solve.py`) contra lo que ya haya en la caché
    # local de catálogos -- nunca golpea la red a ciegas sobre "todo el
    # cielo", así que sin ninguna descarga previa esto falla explícito,
    # no inventa nada.
    report(progress_fraction, f"Intentando resolución de placa ciega (sin puntero) para {image_ref.band}...")
    blind_result = _try_blind_solve(fits_image, pipeline_version=pipeline_version)
    if blind_result.success:
        fits_image.wcs = wcs_solution_to_astropy(blind_result.solution)
        return ImageWCSStatus(
            path=image_ref.path, band=image_ref.band, state=WCS_STATE_BLIND_RESOLVED,
            detail=f"WCS resuelto SIN puntero, por coincidencia de asterismos contra el catálogo local "
                   f"({blind_result.provider}): {blind_result.reason}.",
        )

    if pointed_result is not None:
        pointing_hint = f" El puntero disponible{pointing_note} tampoco produjo una solución válida: {pointed_result.reason}."
    else:
        pointing_hint = (
            " Ninguna posición aproximada disponible (ni en el header FITS ni resolviendo por SIMBAD el nombre "
            "del objetivo) -- comprueba que el nombre de la observación sea un objeto real reconocible."
        )
    return ImageWCSStatus(
        path=image_ref.path, band=image_ref.band, state=WCS_STATE_SOLVE_FAILED,
        detail=f"Plate solving falló (con puntero y en ciego): {blind_result.reason}{pointing_hint} -- WCS no "
               f"disponible, continuando sin coordenadas celestes para esta imagen (usa Astrometría -> Resolver "
               f"placa automáticamente... o Ajustar WCS manualmente... para intentarlo con otros parámetros).",
    )


def _try_blind_solve(fits_image, *, pipeline_version: str = "") -> PlateSolveResult:
    """Intenta resolución ciega usando TODO lo que haya en la caché local
    de Gaia (`CatalogCache.all_rows()`), sin importar qué zona del cielo
    cubra -- es justo el caso "no sé dónde apunta esto" el que necesita
    el resolutor ciego. Nunca lanza: un problema de lectura de la caché
    se trata igual que "sin catálogo disponible", no aborta el análisis."""
    try:
        catalog_rows = CatalogCache("gaia").all_rows()
    except Exception as exc:
        return PlateSolveResult(
            success=False, solution=None, provider=blind_solve.PROVIDER_NAME, n_detected_stars=0, n_catalog_stars=0, n_matched=0,
            reason=f"no se pudo leer la caché local de catálogos ({type(exc).__name__}: {exc})",
            provenance=Provenance.now(pipeline_version=pipeline_version, engine=blind_solve.ENGINE_NAME, engine_version=blind_solve.ENGINE_VERSION),
        )
    return blind_solve.solve_plate_blind(
        fits_image.data, fits_image.header or {}, catalog_rows=catalog_rows, pipeline_version=pipeline_version,
    )


@dataclass(frozen=True)
class _ProcessedSource:
    """Todo lo que se ha medido de verdad sobre una detección concreta de
    una imagen concreta, antes de agrupar por traza. Vive solo dentro de
    este módulo -- `EpochDetection` (de `source_tracks`) referencia el
    `Detection`, y esto es lo que hay que recuperar a partir de su
    `detection_id` para construir el `Candidate` final."""

    detection: Detection
    characterization: CharacterizationResult
    artifact_checks: tuple[ArtifactCheck, ...]
    image_index: int
    morphology_state: str
    morphology_reason: str


@dataclass(frozen=True)
class _TrackContext:
    """Todo lo real ya calculado para una traza (variabilidad,
    movimiento, identificación de catálogo) entre el Pase A (por traza)
    y el Pase C (vector de anomalía + Candidate) del bucle principal --
    existe para que el Pase B (ajuste de punto cero por imagen, que
    necesita conocer TODAS las trazas de una imagen antes de ajustar
    nada) pueda intercalarse entre ambos sin recalcular identificación."""

    track: SourceTrack
    reference_detection: Detection
    reference: _ProcessedSource
    temporal: TemporalEvidence | None
    motion: MotionEvidence | None
    identification_state: IdentificationState
    catalog_matches: tuple[CatalogMatch, ...]
    catalog_non_matches: tuple[CatalogQuery, ...]
    field_stats: FieldStatistics


def _find_cross_band_reference_matches(
    tracks: list[SourceTrack], *, match_radius_arcsec: float,
) -> dict[str, dict[str, EpochDetection]]:
    """Empareja, por posición celeste real, las referencias de trazas de
    BANDAS DISTINTAS que caen en el mismo punto del cielo.

    `source_tracks.group_detections_into_tracks` agrupa deliberadamente
    solo DENTRO de cada banda (ver el comentario en `run_generic_
    discovery`): fundir bandas distintas en una misma traza confundiría
    "mismo objeto, visto en dos filtros" con "mismo objeto, visto en dos
    épocas", que es justo lo que la variabilidad/el movimiento no deben
    mezclar. Esta función es un emparejamiento aparte, solo para
    reconstruir el flujo real multibanda de una fuente física a partir
    de las referencias YA elegidas de cada traza -- nunca toca la
    agrupación temporal en sí."""
    references = [(track, track.reference) for track in tracks if track.reference.detection.position.has_sky_coordinates]
    matches: dict[str, dict[str, EpochDetection]] = {}
    for track, ref in references:
        ra, dec = ref.detection.position.ra_deg, ref.detection.position.dec_deg
        companions: dict[str, EpochDetection] = {ref.band: ref}
        for other_track, other_ref in references:
            if other_track is track or other_ref.band in companions:
                continue
            other_ra, other_dec = other_ref.detection.position.ra_deg, other_ref.detection.position.dec_deg
            if angular_separation_deg(ra, dec, other_ra, other_dec) * 3600.0 <= match_radius_arcsec:
                companions[other_ref.band] = other_ref
        matches[track.track_id] = companions
    return matches


def _aggregate_multi_band_characterization(
    band_companions: dict[str, EpochDetection], reference_characterization: CharacterizationResult, processed_by_id: dict[str, _ProcessedSource],
) -> CharacterizationResult:
    """Con >= 2 bandas emparejadas por posición real
    (`_find_cross_band_reference_matches`), agrega el flujo medido en
    CADA banda -- antes `characterization.band_flux`/`band_ratios`
    solo reflejaban la banda de la época de referencia (`detection.
    bands` es siempre de un solo elemento, ver `detection/point_
    sources.py`), así que `band_ratios` quedaba vacío en TODA ejecución
    real del pipeline genérico con más de una banda, y con ello la
    dimensión espectral del vector de anomalía y la relación OIII/Hα
    que espera `physics/observables.py` nunca tenían con qué
    activarse. Con una sola banda (el caso dominante hoy), devuelve
    `reference_characterization` sin tocar -- cero cambio de
    comportamiento."""
    if len(band_companions) < 2:
        return reference_characterization

    band_flux: dict[str, Quantity] = {}
    for band, epoch_det in band_companions.items():
        source = processed_by_id.get(epoch_det.detection.detection_id)
        if source is None:
            continue
        flux = source.characterization.band_flux.get(band)
        if flux is not None and flux.is_available and flux.value is not None:
            band_flux[band] = flux

    if len(band_flux) < 2:
        return reference_characterization

    def _ratio(name: str, numerator: Quantity, denominator: Quantity) -> Quantity | None:
        if denominator.value is None or denominator.value == 0 or numerator.value is None:
            return None
        ratio = float(numerator.value) / float(denominator.value)
        ratio_error = None
        if numerator.error is not None and denominator.error is not None and numerator.value != 0:
            relative = math.sqrt((numerator.error / numerator.value) ** 2 + (denominator.error / denominator.value) ** 2)
            ratio_error = abs(ratio) * relative
        return Quantity(
            value=ratio, error=ratio_error, unit="dimensionless", kind=ValueKind.OBSERVED, method="multi_band_flux_ratio",
            notes=(f"{name}: {numerator.value:.4g} {numerator.unit} / {denominator.value:.4g} {denominator.unit}",),
        )

    band_ratios: dict[str, Quantity] = {}
    bands_sorted = sorted(band_flux)
    for index, band_a in enumerate(bands_sorted):
        for band_b in bands_sorted[index + 1 :]:
            key = f"{band_a}/{band_b}"
            ratio = _ratio(key, band_flux[band_a], band_flux[band_b])
            if ratio is not None:
                band_ratios[key] = ratio

    # Alias con la orientación canónica que espera `physics/observables.
    # py` (`"OIII/HA"`) -- el orden alfabético genérico de arriba daría
    # "HA/OIII", que ese motor nunca busca.
    if "OIII" in band_flux and "HA" in band_flux:
        oiii_ha = _ratio("OIII/HA", band_flux["OIII"], band_flux["HA"])
        if oiii_ha is not None:
            band_ratios["OIII/HA"] = oiii_ha

    return replace(reference_characterization, band_flux=band_flux, band_ratios=band_ratios)


_MIN_ZEROPOINT_STARS = 5
"""Mismo mínimo que `compute_field_statistics` exige para sus propias
estadísticas de campo (`artifacts/artifact_screen.py`): por debajo de
esto, un ajuste robusto de punto cero (mediana + sigma-clip MAD) no es
fiable -- se deja sin ajustar en vez de calibrar con dos o tres
estrellas."""


def _instrumental_magnitude(flux_adu: float) -> float | None:
    """Magnitud instrumental de punto cero arbitrario 0 -- misma
    convención que ya usa el proceso manual de punto cero de la GUI
    (`qt_app/processes/registry.py::_run_photometric_zeropoint`, vía
    `aperture_photometry(..., zeropoint_mag=0.0)`), para que el ajuste de
    campo automático sea comparable al que ya hace un usuario a mano.
    `None` para flujo neto no positivo (fuente no detectada por encima
    del cielo local): una magnitud no está definida ahí, nunca se
    inventa un valor."""
    if flux_adu <= 0:
        return None
    return -2.5 * math.log10(flux_adu)


def _parse_epoch_time(header: dict) -> datetime | None:
    """Instante real de adquisición a partir de `DATE-OBS`, necesario
    para agrupar multiépoca por tiempo real (`source_tracks`) y para el
    ajuste de trayectoria de `temporal/motion.py`. Nunca se inventa: sin
    una cabecera FITS con `DATE-OBS` en un formato ISO 8601 reconocible,
    la imagen simplemente no aporta tiempo real a su traza -- ambos
    motores ya declaran explícitamente qué hacen sin él."""
    raw = (header or {}).get("DATE-OBS")
    if not raw or not isinstance(raw, str):
        return None
    try:
        value = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _brightness_epochs(track: SourceTrack, processed_by_id: dict[str, _ProcessedSource]) -> list[dict]:
    """Serie temporal de brillo real para `temporal/variability.py`: pico
    en ADU (`peak_adu`, ya medido por `characterize_point_source`) con su
    incertidumbre real (`noise_adu`) en cada época con tiempo conocido.

    Es un proxy INSTRUMENTAL, no flujo calibrado: usa `peak_adu`/
    `noise_adu` (pico de un solo píxel) en vez del flujo de apertura ya
    conectado en `characterization.band_flux` desde el cierre del motor
    de fotometría de apertura -- `temporal/variability.py` todavía no
    migró a esa medida más completa, no porque no exista, sino porque no
    era parte de ese cierre. Se usa igualmente porque es una magnitud
    real medida sobre los píxeles en cada época, nunca inventada; migrar
    esta función a flujo de apertura integrado es una mejora futura
    concreta, no parte de este cierre tampoco."""
    times = [obs.epoch_time for obs in track.observations if obs.epoch_time is not None]
    if not times:
        return []
    t0 = min(times)
    epochs: list[dict] = []
    for obs in sorted(track.observations, key=lambda o: o.epoch_index):
        if obs.epoch_time is None:
            continue
        processed = processed_by_id.get(obs.detection.detection_id)
        if processed is None:
            continue
        peak = processed.characterization.extra.get("peak_adu")
        noise = processed.characterization.extra.get("noise_adu")
        if peak is None or not peak.is_available or peak.value is None:
            continue
        if noise is None or not noise.is_available or noise.value is None or noise.value <= 0:
            continue
        epochs.append({
            "time": (obs.epoch_time - t0).total_seconds() / 3600.0,
            "value": float(peak.value),
            "error": float(noise.value),
        })
    return epochs


def _upgrade_identification_state(
    base_state: IdentificationState, temporal: TemporalEvidence | None, motion: MotionEvidence | None,
) -> IdentificationState:
    """Reclasifica el estado base con evidencia multiépoca REAL -- nunca
    hacia una de las categorías especiales del vocabulario (§2 de
    docs/audit/02-...) sin que el motor correspondiente haya concluido
    algo real sobre esta traza (`variable_candidate`/
    `moving_source_candidate`, no la mera presencia de un objeto
    `TemporalEvidence`/`MotionEvidence` con menos épocas de las que hacen
    falta). Movimiento significativo prevalece sobre variabilidad: un
    objeto que se desplaza es más específico que uno que solo cambia de
    brillo."""
    if motion is not None and motion.moving_source_candidate:
        return IdentificationState.MOVING_SOURCE_CANDIDATE
    if temporal is not None and temporal.variable_candidate:
        if base_state is IdentificationState.KNOWN:
            return IdentificationState.KNOWN_VARIANT
        return IdentificationState.TRANSIENT_CANDIDATE
    return base_state


def run_generic_discovery(
    observation: Observation,
    loaded_images: dict[str, LoadedImage],
    *,
    fwhm_px: float = 3.0,
    threshold_sigma: float = 5.0,
    max_sources: int = 3000,
    match_radius_arcsec: float = 3.0,
    gaia_mag_limit: float = 20.0,
    pipeline_version: str = "",
    progress: Callable[[float, str], None] | None = None,
    cancel: threading.Event | None = None,
    auto_plate_solve: bool = True,
    auto_debayer: bool = True,
) -> tuple[list[Candidate], DiscoveryRunSummary]:
    """Ejecuta el modo genérico sobre todas las imágenes de una
    `Observation` ya cargada (ver `io.fits_loader.build_observation`).

    `loaded_images` debe mapear `ImageRef.path` -> `LoadedImage`, tal como
    lo devuelve `build_observation`.

    `progress(fraccion_0_a_1, mensaje)` y `cancel` (un `threading.Event`)
    siguen la misma convención que `legacy...analyze_pair_core` -- pensado
    para ejecutarse en un hilo de fondo desde una GUI, nunca en el hilo
    principal (ver docs/audit/10-FASE8-GUI.md).

    Antes de detectar fuentes en cada imagen, si le falta WCS y
    `auto_plate_solve` está activo (por defecto), se intenta resolución
    automática (`astrometry.plate_solve.solve_plate`) -- la ausencia de
    WCS nunca aborta el análisis: si no se puede resolver, se registra
    el motivo exacto en `DiscoveryRunSummary.wcs_status` y esa imagen
    sigue por el resto del pipeline sin coordenadas celestes (las
    identificaciones que las necesiten degradan con gracia, ver
    `catalogs/gaia.py`)."""

    def report(fraction: float, message: str) -> None:
        if progress is not None:
            progress(fraction, message)

    def check_cancelled() -> None:
        if cancel is not None and cancel.is_set():
            raise DiscoveryCancelled("Análisis cancelado por el usuario")

    candidates: list[Candidate] = []
    n_detected = 0
    n_rejected = 0
    n_images = max(1, len(observation.images))
    wcs_statuses: list[ImageWCSStatus] = []
    cfa_statuses: list[ImageCFAStatus] = []

    # Estado acumulado ENTRE imágenes, para la agrupación multiépoca y la
    # reconstrucción del Candidate tras agrupar (ver el docstring del
    # módulo: nada de esto existía antes de esta fase de cierre).
    processed_by_id: dict[str, _ProcessedSource] = {}
    field_stats_by_image: dict[int, FieldStatistics] = {}
    epoch_detections_by_band: dict[str, list[EpochDetection]] = {}

    for image_index, image_ref in enumerate(observation.images):
        check_cancelled()
        loaded = loaded_images[image_ref.path]
        # El demosaico va ANTES que el WCS y que la detección: si hay que
        # resolver la placa, resolverla sobre la luminancia real (no sobre
        # el mosaico) da muchas más estrellas con las que emparejar.
        cfa_status = _debayer_if_cfa(loaded, image_ref, auto_debayer=auto_debayer)
        cfa_statuses.append(cfa_status)
        if cfa_status.state == CFA_STATE_DEBAYERED:
            report(image_index / n_images, f"Mosaico de color demosaicado en {image_ref.band} ({image_index + 1}/{n_images})")
        # El binificado 2x2 del SuperPixel divide por dos la FWHM medida en
        # píxeles: usar la original detectaría con un núcleo del doble de
        # ancho que la PSF real y perdería la mayoría de las estrellas.
        image_fwhm_px = fwhm_px / 2.0 if cfa_status.state == CFA_STATE_DEBAYERED else fwhm_px
        wcs_statuses.append(
            _ensure_wcs(
                loaded, image_ref, target_name=observation.target_name, auto_plate_solve=auto_plate_solve,
                report=report, progress_fraction=image_index / n_images, pipeline_version=pipeline_version,
            )
        )
        epoch_time = _parse_epoch_time(loaded.legacy_image.header or {})
        check_cancelled()
        report(image_index / n_images, f"Detectando fuentes en {image_ref.band} ({image_index + 1}/{n_images})")
        detections = detect_point_sources(
            loaded,
            observation_id=observation.observation_id,
            band=image_ref.band,
            fwhm_px=image_fwhm_px,
            threshold_sigma=threshold_sigma,
            max_sources=max_sources,
            pipeline_version=pipeline_version,
            image_index=image_index,
        )
        n_detected += len(detections)

        # --- Pase 1: filtro morfológico barato (sin tocar píxeles) +
        # caracterización real de lo que sobrevive. El filtro barato solo
        # descarta lo más extremo (elongación >= 8, área <= 2 px) -- mucho
        # más laxo que `screen_detection`, así que nunca rechaza algo que
        # el cribado real habría aceptado; existe solo para no gastar
        # caracterización de píxeles en basura evidente.
        kept: list[tuple[Detection, CharacterizationResult, str, str]] = []
        for detection_index, detection in enumerate(detections):
            check_cancelled()
            if detections:
                within_image = detection_index / len(detections)
                report((image_index + within_image) / n_images, f"Caracterizando fuente {detection_index + 1}/{len(detections)}")

            state, reason = classify_morphology(detection)
            if state == "ARTIFACT_REJECTED":
                n_rejected += 1
                continue
            characterization = characterize_point_source(loaded, detection, pipeline_version=pipeline_version)
            kept.append((detection, characterization, state, reason))

        # --- Pase 2: estadística de campo real, una vez por imagen -- la
        # necesitan COSMIC_RAY/PSF_DEFECT de `screen_detection` (comparan
        # contra la PSF real del campo, no un umbral fijo inventado).
        field_stats = compute_field_statistics([c for _, c, _, _ in kept])
        field_stats_by_image[image_index] = field_stats

        # --- Pase 3: cribado REAL de artefactos -- el gate autoritativo.
        # Ninguna detección se convierte en Candidate sin pasar por aquí.
        for detection, characterization, state, reason in kept:
            check_cancelled()
            screen = screen_detection(detection, characterization, field_stats)
            if screen.rejected:
                n_rejected += 1
                continue
            processed_by_id[detection.detection_id] = _ProcessedSource(
                detection=detection, characterization=characterization, artifact_checks=screen.checks,
                image_index=image_index, morphology_state=state, morphology_reason=reason,
            )
            epoch_detections_by_band.setdefault(image_ref.band, []).append(
                EpochDetection(image_index, epoch_time, image_ref.band, image_ref.path, detection)
            )

    # --- Agrupación multiépoca, POR BANDA: el dithering entre tomas del
    # mismo campo mueve la misma fuente a píxeles distintos, así que solo
    # tiene sentido emparejar detecciones de la MISMA banda entre sí (ver
    # `discovery/source_tracks.py`). Bandas distintas de la misma toma
    # (p. ej. Hα y OIII) nunca se funden en una traza -- no son épocas de
    # lo mismo, son mediciones simultáneas de bandas distintas.
    tracks: list[SourceTrack] = []
    for band, epoch_dets in epoch_detections_by_band.items():
        tracking = group_detections_into_tracks(
            epoch_dets, match_radius_arcsec=match_radius_arcsec, observation_id=f"{observation.observation_id}-{band}",
        )
        tracks.extend(tracking.tracks)

    # Emparejamiento aparte, solo por posición (ver el docstring de
    # `_find_cross_band_reference_matches`): reconstruye qué trazas de
    # bandas distintas son la MISMA fuente física, sin tocar la
    # agrupación temporal de arriba. Con una sola banda en toda la
    # observación no hay nada que cruzar -- se salta el barrido O(n²).
    cross_band_matches = (
        _find_cross_band_reference_matches(tracks, match_radius_arcsec=match_radius_arcsec)
        if len(epoch_detections_by_band) >= 2 else {}
    )

    # --- Pase A, por cada traza física: variabilidad/movimiento (si hay
    # >= 2 épocas) e identificación (una sola vez, sobre la época de
    # referencia). El vector de anomalía y el Candidate se construyen
    # después (Pase C), porque su dimensión fotométrica necesita el
    # punto cero de la imagen (Pase B), que a su vez necesita conocer
    # TODAS las trazas identificadas de esa imagen, no solo las
    # procesadas hasta ahora en este bucle.
    track_contexts: list[_TrackContext] = []
    zeropoint_samples_by_image: dict[int, list[tuple[float, float]]] = {}
    for track in tracks:
        check_cancelled()
        reference_detection = track.reference.detection
        reference = processed_by_id[reference_detection.detection_id]

        temporal: TemporalEvidence | None = None
        motion: MotionEvidence | None = None
        if track.n_epochs >= 2:
            brightness_epochs = _brightness_epochs(track, processed_by_id)
            if len(brightness_epochs) >= 2:
                temporal = analyze_variability(brightness_epochs, detection_id=reference_detection.detection_id, pipeline_version=pipeline_version)
            motion = analyze_motion(track, detection_id=reference_detection.detection_id, pipeline_version=pipeline_version)

        identification_state, catalog_matches, catalog_non_matches = identify_detection(
            reference_detection, match_radius_arcsec=match_radius_arcsec, mag_limit=gaia_mag_limit,
        )

        # Cada traza KNOWN con flujo de apertura real aporta un punto de
        # calibración al ajuste de punto cero de SU imagen -- mismo par
        # (magnitud instrumental, magnitud de catálogo) que mediría a
        # mano el proceso manual de punto cero, pero tomado de
        # identificaciones que el pipeline ya hace de todos modos (cero
        # consultas nuevas a Gaia).
        if catalog_matches and catalog_matches[0].magnitude is not None and catalog_matches[0].magnitude.is_available:
            catalog_mag = float(catalog_matches[0].magnitude.value)
            for band in reference_detection.bands:
                flux_quantity = reference.characterization.band_flux.get(band)
                if flux_quantity is None or not flux_quantity.is_available or flux_quantity.value is None:
                    continue
                instrumental_mag = _instrumental_magnitude(float(flux_quantity.value))
                if instrumental_mag is None:
                    continue
                zeropoint_samples_by_image.setdefault(reference.image_index, []).append((instrumental_mag, catalog_mag))

        field_stats = field_stats_by_image.get(reference.image_index, FieldStatistics(n_sources=0, median_fwhm_px=None, fwhm_scatter_px=None))
        track_contexts.append(
            _TrackContext(
                track=track, reference_detection=reference_detection, reference=reference,
                temporal=temporal, motion=motion, identification_state=identification_state,
                catalog_matches=catalog_matches, catalog_non_matches=catalog_non_matches, field_stats=field_stats,
            )
        )

    # --- Pase B: ajuste real de punto cero por imagen (mediana + sigma-
    # clip MAD, `photometry/calibration.py::fit_zeropoint` -- el mismo
    # ajuste robusto que ya usa el proceso manual de la GUI desde la
    # Fase 12, nunca un punto cero inventado). Por debajo de
    # `_MIN_ZEROPOINT_STARS` estrellas identificadas en la imagen, se
    # deja sin ajustar -- la dimensión fotométrica de esas trazas
    # quedará NOT_AVAILABLE con el motivo real, no un ajuste sobre dos
    # estrellas disfrazado de calibración.
    zeropoint_fit_by_image: dict[int, ZeropointFit] = {}
    for image_index, samples in zeropoint_samples_by_image.items():
        if len(samples) < _MIN_ZEROPOINT_STARS:
            continue
        zeropoint_fit_by_image[image_index] = fit_zeropoint([s[0] for s in samples], [s[1] for s in samples])

    # --- Pase C: vector de anomalía (con expectativa fotométrica real
    # cuando la imagen tiene punto cero ajustado y la traza tiene match
    # de catálogo), cadena de evidencia y Candidate.
    for ctx in track_contexts:
        check_cancelled()
        reference_detection = ctx.reference_detection
        reference = ctx.reference
        multi_band_characterization = _aggregate_multi_band_characterization(
            cross_band_matches.get(ctx.track.track_id, {}), reference.characterization, processed_by_id,
        )

        expected_band_flux: dict[str, Quantity] = {}
        zeropoint_fit = zeropoint_fit_by_image.get(reference.image_index)
        if (
            zeropoint_fit is not None and ctx.catalog_matches
            and ctx.catalog_matches[0].magnitude is not None and ctx.catalog_matches[0].magnitude.is_available
        ):
            catalog_magnitude = ctx.catalog_matches[0].magnitude
            expected_instrumental_mag = float(catalog_magnitude.value) - zeropoint_fit.zeropoint_mag
            expected_flux = 10.0 ** (-0.4 * expected_instrumental_mag)
            # Incertidumbre del punto cero (siempre real, aunque sea 0.0
            # con una sola estrella usada) más la de la magnitud de
            # catálogo (cuando el catálogo la trae) en cuadratura -- antes
            # se descartaba por completo, lo que subestimaba la
            # incertidumbre real de `expected_flux` y podía inflar la
            # significancia de `_photometric_anomaly`.
            catalog_error = float(catalog_magnitude.error) if catalog_magnitude.error is not None else 0.0
            expected_mag_error = math.sqrt(zeropoint_fit.zeropoint_uncertainty_mag ** 2 + catalog_error ** 2)
            expected_flux_error = 0.4 * math.log(10.0) * expected_flux * expected_mag_error if expected_mag_error > 0 else None
            expected_flux_quantity = Quantity(
                value=expected_flux, error=expected_flux_error, unit="adu", kind=ValueKind.MODEL_INFERENCE,
                method="zeropoint_calibration",
                notes=(f"punto cero {zeropoint_fit.zeropoint_mag:.4f} ± {zeropoint_fit.zeropoint_uncertainty_mag:.4f} mag",),
            )
            for band in reference_detection.bands:
                expected_band_flux[band] = expected_flux_quantity

        anomaly = build_anomaly_vector(
            detection_id=reference_detection.detection_id,
            characterization=multi_band_characterization,
            temporal=ctx.temporal,
            motion=ctx.motion,
            field_median_fwhm_px=ctx.field_stats.median_fwhm_px,
            field_fwhm_scatter_px=ctx.field_stats.fwhm_scatter_px,
            expected_band_flux=expected_band_flux or None,
        )
        evidence_chain = build_evidence_chain(
            detection_id=reference_detection.detection_id,
            anomaly=anomaly,
            temporal=ctx.temporal,
            motion=ctx.motion,
            catalog_matches=ctx.catalog_matches,
            catalog_non_matches=ctx.catalog_non_matches,
            artifact_checks=reference.artifact_checks,
        )

        final_state = _upgrade_identification_state(ctx.identification_state, ctx.temporal, ctx.motion)
        quality = QualitySummary(
            overall_level=_QUALITY_LEVEL_FOR_STATE[reference.morphology_state],
            checks=(QualityCheckItem(name="morphology_screen", level=_QUALITY_LEVEL_FOR_STATE[reference.morphology_state], detail=reference.morphology_reason),),
        )
        snr = Quantity(value=reference_detection.peak_snr, error=None, unit="dimensionless", kind=ValueKind.OBSERVED, method=reference_detection.method)

        candidates.append(
            Candidate.create(
                candidate_id=f"{observation.observation_id}-{reference_detection.detection_id}",
                observation_id=observation.observation_id,
                detection_id=reference_detection.detection_id,
                position=reference.characterization.position,
                morphology=reference_detection.morphology,
                size=reference.characterization.fwhm,
                flux=multi_band_characterization.band_flux,
                snr=snr,
                bands=reference_detection.bands,
                catalog_matches=ctx.catalog_matches,
                catalog_non_matches=ctx.catalog_non_matches,
                temporal_evidence=ctx.temporal,
                motion_evidence=ctx.motion,
                anomaly_evidence=anomaly,
                artifact_checks=reference.artifact_checks,
                provenance=reference_detection.provenance,
                identification_state=final_state,
                evidence_chain=evidence_chain,
                quality=quality,
            )
        )

    report(1.0, f"Completado: {len(candidates)} candidatos de {n_detected} detecciones")
    summary = DiscoveryRunSummary(
        observation_id=observation.observation_id,
        n_images=len(observation.images),
        n_detected=n_detected,
        n_artifact_rejected=n_rejected,
        n_candidates=len(candidates),
        n_known=sum(1 for c in candidates if c.identification_state.value == "KNOWN"),
        n_unmatched=sum(1 for c in candidates if c.identification_state.value == "UNMATCHED"),
        n_discovery_review=sum(1 for c in candidates if c.identification_state.value == "DISCOVERY_REVIEW"),
        wcs_status=tuple(wcs_statuses),
        cfa_status=tuple(cfa_statuses),
    )
    return candidates, summary
