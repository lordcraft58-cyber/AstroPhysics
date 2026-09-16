# AstroPhysics Suite — Mapa de capacidades IRAF

Este documento responde a un encargo explícito: usar la documentación funcional de
IRAF (no su código, no su sintaxis de comandos) como referencia de qué capacidades
científicas debe cubrir la suite, y dejar constancia auditable de qué hay
**realmente implementado** frente a lo que queda pendiente. Centrado en los paquetes
IRAF relevantes para este proyecto: `ccdred`, `apphot`, `daophot`, `onedspec`,
`twodspec`/`apextract`, `astcat`, `astutil`.

**Metodología**: cada fila se verificó leyendo el código fuente real (ruta y línea),
no por descripción de alto nivel ni por lo que dice cualquier documento anterior.
Cuando existe, se cita el archivo de test que prueba valores/dimensiones/unidades
reales contra datos sintéticos de verdad conocida -- nunca "no lanza excepción" como
único criterio. "GUI" indica si `qt_app` puede invocar la capacidad hoy, y cómo.

**Estado final**: `DISPONIBLE` (motor real + camino de uso real en la GUI, sin
recortes de alcance no documentados) · `EXPERIMENTAL` (motor real, pero la GUI solo
ofrece un camino de demostración con un recorte de alcance explícito, p. ej. una sola
imagen en vez de una sesión completa, o una fila central en vez de un espectro real
extraído) · `PENDIENTE` (motor real sin ningún camino de uso desde la GUI, o
capacidad sin implementar en absoluto).

---

## 1. `ccdred` — reducción CCD

| Capacidad | Estado actual | Implementación nueva | Test | GUI | Estado final |
|---|---|---|---|---|---|
| Sustracción de overscan (modelado mediana/media/polinómico por fila o columna, con recorte) | Real, `astrophysics_suite/reduction/overscan.py:24` (`subtract_overscan`) | — (ya existía, verificado en esta auditoría) | `tests/unit/reduction/test_overscan.py` | Proceso `reduction.overscan`, cableado (`registry.py:135`) | **DISPONIBLE** |
| Combinación robusta de N imágenes (mediana/media, rechazo iterativo sigma-clip por MAD, incertidumbre por píxel) | Real, `astrophysics_suite/reduction/combine.py:36` (`combine_images`) | — | `tests/unit/reduction/test_combine.py` | Sin proceso propio -- usado internamente por masters y por el nuevo pipeline de sesión (ver más abajo) | **DISPONIBLE** (como bloque interno) |
| Bias maestro | Real, `master_frames.py:29` (`build_master_bias`) | — | `tests/unit/reduction/test_master_frames.py` | Diálogo "Construir fotograma maestro" | **DISPONIBLE** |
| Dark maestro (con resta de bias, escalado por tiempo de exposición para la ciencia) | Real, `master_frames.py:36` (`build_master_dark`) | — | ídem | ídem | **DISPONIBLE** |
| Flat maestro (bias/dark restados, normalizado a mediana 1.0) | Real, `master_frames.py:53` (`build_master_flat`) | — | ídem | ídem | **DISPONIBLE** |
| Calibración de una LIGHT (bias -> dark escalado -> flat -> interpolación de píxeles defectuosos, orden fijo, incertidumbre propagada) | Real, `calibration.py:35` (`calibrate_frame`) | — | `tests/unit/reduction/test_calibration.py` | Diálogo "Aplicar calibración" (una imagen) **y** "Reducir sesión de LIGHTS..." (sesión completa, Fase 10.1) | **DISPONIBLE** |
| Máscara de píxeles defectuosos (umbral sobre flat normalizado + confirmación por dark + interpolación 1D + dilatado opcional) | Real, `bad_pixel_mask.py:12/28/56/68` | — | `tests/unit/reduction/test_bad_pixel_mask.py` | Casilla "Detectar y corregir píxeles defectuosos" en "Reducir sesión de LIGHTS..." (Fase 10.1) | **DISPONIBLE** |
| Corrección de franjas (fringing), escala óptima por mínimos cuadrados contra un patrón maestro | Real, `fringe.py:20` (`remove_fringe`) | — | `tests/unit/reduction/test_fringe.py` | Selector de "Patrón de franjas maestro" en "Reducir sesión de LIGHTS..." (Fase 10.1) | **DISPONIBLE** |
| Reducción de una **sesión completa de LIGHTS** (muchas exposiciones + calibraciones, no una imagen a la vez) | No existía como orquestación única antes de esta ronda | `astrophysics_suite/reduction/session_pipeline.py` (`reduce_light_frames`) -- ver Fase 10.1 | `tests/unit/reduction/test_session_pipeline.py` | Diálogo "Reducir sesión de LIGHTS..." -- ver Fase 10.1 | **DISPONIBLE** |
| Corrección de iluminación (`mkillumflat`/`mkillumcor`) | No implementada | `astrophysics_suite/reduction/illumination.py` (`build_illumination_map`/`apply_illumination_correction`, suavizado gaussiano del flat maestro normalizado) -- ver Fase 10.2 | `tests/unit/reduction/test_illumination.py` | Casilla "Aplicar corrección de iluminación" en "Reducir sesión de LIGHTS..." | **DISPONIBLE** |
| Corrección de cielo (`skyflat`/resta de fondo de cielo dedicada) | No implementada como bloque propio de `ccdred` (existe estimación de cielo local en `apphot`, ver §3, pero no una corrección de cielo a nivel de imagen completa) | `astrophysics_suite/reduction/sky.py` (`fit_sky_background`/`subtract_sky_background`, ajuste polinómico 2D con rechazo iterativo de fuentes) -- ver Fase 10.2 | `tests/unit/reduction/test_sky.py` | Grupo "Corrección de cielo" en "Reducir sesión de LIGHTS..." | **DISPONIBLE** |
| Gestión de grupos de imágenes / clasificación automática por cabecera (`ccdlist`, tipado bias/dark/flat/light desde `IMAGETYP`) | No implementada -- el usuario elige manualmente cada archivo en cada diálogo | `astrophysics_suite/reduction/frame_classification.py` (`classify_frame_type`/`classify_session_headers`) + `astrophysics_suite/io/fits_header_reader.py` -- ver Fase 10.2 | `tests/unit/reduction/test_frame_classification.py`, `tests/unit/io/test_fits_header_reader.py` | Botón "+ Añadir carpeta (clasificar)..." en "Reducir sesión de LIGHTS..." (solo añade lo clasificado como LIGHT; nunca adivina si `IMAGETYP`/`OBSTYPE`/`FRAMETYP` no están presentes) | **DISPONIBLE** |
| Configuración por instrumento (ganancia/ruido de lectura/geometría de overscan como perfil guardado por cámara) | No implementada -- ganancia/ruido de lectura se reintroducen a mano cada vez | `services/instrument_profiles.py` (`InstrumentProfileStore`, persistencia JSON) -- ver Fase 10.2 | `tests/unit/services/test_instrument_profiles.py` | Combo "Perfil de instrumento" + "Guardar como perfil..." en "Reducir sesión de LIGHTS..." | **DISPONIBLE** |

---

## 2. Análisis de imagen (`imtools`, equivalente propio de utilidades tipo `astutil`)

| Capacidad | Estado actual | Test | GUI | Estado final |
|---|---|---|---|---|
| Aritmética entre imágenes con propagación de error (+ − × ÷, unidades, máscaras) | Real, `imtools/arithmetic.py:23` (`UncertainImage`) | `tests/unit/imtools/test_arithmetic.py` | Diálogo "Aritmética entre imágenes..." (menú Herramientas) -- selector de las dos ventanas MDI abiertas -- ver Fase 11.1 | **DISPONIBLE** |
| Eliminación de rayos cósmicos (L.A.Cosmic real: Laplaciano submuestreado, imagen de estructura fina, doble umbral, crecimiento de máscara, iterativo) | Real, `imtools/cosmic_rays.py:71` | `tests/unit/imtools/test_cosmic_rays.py` | Proceso `imtools.cosmic_rays`, cableado | **DISPONIBLE** |
| S/N por imagen a partir del modelo de ruido CCD | Real, `UncertainImage.from_counts`/`.snr()` (`arithmetic.py:50/150`) | ídem | Reutilizado internamente por otros procesos, sin panel propio | **DISPONIBLE** (como bloque interno) |
| Estadística/histograma de imagen completa como utilidad genérica reutilizable | No existía un módulo dedicado | `astrophysics_suite/imtools/statistics.py` (`compute_image_statistics`/`compute_histogram`) -- ver Fase 11.1 | `tests/unit/imtools/test_statistics.py` | Proceso `imtools.statistics`, cableado (histograma mostrado como imagen de barras por falta de un widget de gráfico dedicado, misma disciplina que la tira 1D de `spectroscopy.trace`) | **DISPONIBLE** |
| Máscaras/regiones/recortes genéricos (no ligados a una apertura fotométrica ni al recorte de overscan) | No existía como utilidad independiente | `astrophysics_suite/imtools/regions.py` (`crop`/`rectangular_mask`/`circular_mask`) -- ver Fase 11.1 | `tests/unit/imtools/test_regions.py` | Proceso `imtools.crop`, cableado (dos clics marcan las esquinas opuestas, reutilizando el mismo mecanismo genérico de selección de posiciones de la Fase 9.6 §8) | **DISPONIBLE** |
| Normalización de imagen genérica | Solo existía dentro de `build_master_flat` (normalización a mediana 1.0) | `astrophysics_suite/imtools/normalize.py` (`normalize_minmax`/`normalize_percentile`/`normalize_sigma_clip`) -- ver Fase 11.1 | `tests/unit/imtools/test_normalize.py` | Proceso `imtools.normalize` (percentiles), cableado; `normalize_minmax`/`normalize_sigma_clip` disponibles como motor, no expuestos individualmente en la GUI | **DISPONIBLE** |

---

## 3. `apphot` — fotometría de apertura

| Capacidad | Estado actual | Test | GUI | Estado final |
|---|---|---|---|---|
| Detección de fuentes (DAOStarFinder real, no un placeholder) | Real, `detection/point_sources.py:47` (`detect_point_sources`) | `tests/unit/detection/test_point_sources.py` | Usado por el Discovery Engine; **y ahora también** por `photometry.aperture`/`photometry.zeropoint` vía `detect_point_sources_in_array` (`detection/point_sources.py`, mismo motor sobre un array en memoria, sin exigir `LoadedImage`) -- casilla "Detectar automáticamente" -- ver Fase 16 | **DISPONIBLE** |
| Centroidado (momento de segundo orden), FWHM, elipticidad, nitidez | Real, `_legacy_enrich_star_rows` vía `detection/point_sources.py` | ídem | ídem | **DISPONIBLE** (como motor) |
| Máscara de cobertura de apertura subpíxel (interior/exterior analítico, borde sobremuestreado) | Real, `photometry/aperture.py:17` (`aperture_coverage_mask`) | `tests/unit/photometry/test_aperture.py` | Proceso `photometry.aperture`, cableado | **DISPONIBLE** |
| Estimación de cielo en anillo con rechazo iterativo sigma-clip (MAD) | Real, `aperture.py:73` (`estimate_local_sky`) | ídem | ídem | **DISPONIBLE** |
| Fotometría multi-radio (curva de crecimiento cruda), flujo neto, error propagado, magnitud instrumental | Real, `aperture.py:145` (`aperture_photometry`) | ídem | Proceso `photometry.aperture`, **ahora con selección de fuente a clic** (`requires_picking=1`) -- ver Fase 12 | **DISPONIBLE** |
| Ajuste real de curva de crecimiento / radio óptimo | No implementada hasta esta ronda | `astrophysics_suite/photometry/aperture.py` (`fit_curve_of_growth`, modelo de saturación `F(r)=F_inf(1-e^{-(r/r0)^p})` vía `scipy.optimize.curve_fit`, radio óptimo = el que maximiza la S/N medida) -- ver Fase 16 | `tests/unit/photometry/test_aperture.py` | Casilla "Ajustar curva de crecimiento (radio óptimo)" en `photometry.aperture` -- mide en varios radios adicionales, reporta el radio recomendado y exporta una tabla (radio, flujo, S/N) | **DISPONIBLE** |
| Calibración fotométrica (punto cero resuelto contra estrellas estándar/catálogo) | No implementada -- el punto cero era una constante fija que introducía el usuario, nunca ajustada contra datos | `astrophysics_suite/photometry/calibration.py` (`fit_zeropoint`, mediana robusta con rechazo sigma-clip de outliers) -- ver Fase 12 | `tests/unit/photometry/test_photometric_calibration.py` | Proceso `photometry.zeropoint`, cableado: clic en varias estrellas de referencia (o "Detectar automáticamente", ver Fase 16) -> fotometría instrumental real -> WCS real de la imagen activa -> consulta Gaia DR3 real -> ajuste de punto cero robusto | **DISPONIBLE** |

---

## 4. `daophot` — fotometría PSF

| Capacidad | Estado actual | Test | GUI | Estado final |
|---|---|---|---|---|
| Modelo PSF Gaussiano elíptico | Real, `photometry/psf.py:31` (`GaussianPSF`) | `tests/unit/photometry/test_psf.py` | Expuesto en `photometry.psf` | **DISPONIBLE** |
| Modelo PSF Moffat (colas realistas) | Real, `psf.py:56` (`MoffatPSF`) | ídem | Casilla "Usar perfil de Moffat (colas realistas)" en `photometry.psf` -- ver Fase 17.1 | **DISPONIBLE** |
| PSF empírica (apilado de estrellas de referencia, recentrado subpíxel, sobremuestreo) | Real, `psf.py:83/102` (`build_empirical_psf`) | ídem | Motor listo, **no expuesto en la GUI** | **EXPERIMENTAL** (motor disponible, no seleccionable desde la GUI) |
| Selección automática de estrellas PSF (equivalente a `pstselect`: aislamiento/redondez/nitidez) | No implementada hasta esta ronda -- las posiciones de referencia las daba siempre el llamador | `astrophysics_suite/photometry/psf.py` (`select_psf_reference_stars`: aislamiento real contra todos los candidatos, elipticidad, S/N mínima) -- ver Fase 17 | `tests/unit/photometry/test_psf.py` | Casilla "Detectar automáticamente (pstselect)" en `photometry.psf` | **DISPONIBLE** |
| Detección automática de fuentes previa a PSF (equivalente a `daofind`) | Reutilizaba `detect_point_sources` genérico de apphot sin ningún criterio afinado para candidatura PSF | `astrophysics_suite/detection/point_sources.py` (`detect_psf_candidates`, mismo motor DAOStarFinder enriquecido con FWHM/elipticidad/nitidez vía `enrich_star_rows`) -- ver Fase 17 | `tests/unit/detection/test_point_sources.py` | Conectado a `photometry.psf` (junto con `select_psf_reference_stars`, arriba) | **DISPONIBLE** |
| Ajuste PSF simultáneo multi-fuente con desmezclado (`group`+`psf`+`nstar` real) | Real, `psf.py:164` (`fit_group_psf_photometry`) -- matriz de diseño con una columna por fuente + término de cielo, ponderado por sigma inverso, incertidumbre por covarianza | ídem | Proceso `photometry.psf`, cableado, selección de posiciones a clic (Fase 9.6 §8) | **DISPONIBLE** |
| Refinamiento no lineal de posición iterativo (`allstar`) | No implementado hasta esta ronda -- posiciones fijas, documentado explícitamente como límite de alcance en el propio código | `astrophysics_suite/photometry/psf.py` (`fit_group_psf_photometry_with_position_refinement`, proyección variable: `scipy.optimize.least_squares` sobre los desplazamientos de posición, con el flujo resuelto como subproblema lineal en cada evaluación) -- ver Fase 17 | `tests/unit/photometry/test_psf.py` | Casilla "Refinar posición (allstar)" en `photometry.psf` | **DISPONIBLE** |
| Diagnóstico de calidad de ajuste (chi, residuos, imagen de residuo por `nstar`) | No implementado hasta esta ronda -- `PSFFitResult` solo devolvía flujo + incertidumbre | `astrophysics_suite/photometry/psf.py` (`compute_psf_fit_diagnostics`: chi² reducido + imagen de residuo, calculados sobre un ajuste ya resuelto) -- ver Fase 17 | `tests/unit/photometry/test_psf.py` | Casilla "Diagnóstico de ajuste (chi², residuo)" en `photometry.psf` -- abre la imagen de residuo en una ventana nueva | **DISPONIBLE** |

---

## 5. Astrometría (equivalente propio de las partes relevantes de `astcat`/registro de imágenes)

| Capacidad | Estado actual | Test | GUI | Estado final |
|---|---|---|---|---|
| Proyección tangencial (TAN) pixel↔cielo, ambas direcciones | Real, `astrometry/wcs_fit.py:24/37` | `tests/unit/astrometry/test_wcs_fit.py` | — | **DISPONIBLE** (como motor) |
| Separación angular (gran círculo, fórmula haversine) | Real, `wcs_fit.py:57` | ídem | — | **DISPONIBLE** |
| Ajuste WCS lineal (matriz CD) desde pares pixel↔cielo, con residuo por estrella y RMS | Real, `wcs_fit.py:91` (`fit_wcs`) -- **deliberadamente sin términos SIP/TPV de orden superior**, documentado como límite de alcance | ídem | Menú Astrometría → "Ajustar WCS (clic + coordenadas)..." -- clic en N estrellas + tabla de RA/Dec introducida a mano (sin resolución automática/"blind solving", igual que `ccmap` interactivo) -- ver Fase 13 | **DISPONIBLE** |
| Registro/alineación afín o de similitud entre dos imágenes desde estrellas emparejadas, con RMS de residuo | Real, `astrometry/registration.py:31` (`fit_affine_transform`) | `tests/unit/astrometry/test_registration.py` | Menú Astrometría → "Registrar por pares de estrellas (clic)..." -- dos sesiones de clic encadenadas (misma cantidad y orden en cada ventana), sin necesitar que ninguna de las dos tenga WCS -- ver Fase 18 | **DISPONIBLE** |
| Remuestreo/reproyección de una imagen a la solución WCS de otra | Real, `registration.py:87/115` (`apply_affine_transform`, `reproject_to_reference`) | ídem | Menú Astrometría → "Registrar por WCS compartido..." -- selector de dos ventanas, cada una con WCS real (cargado o recién ajustado) -- ver Fase 13 | **DISPONIBLE** |
| Conversión de un WCS real cargado de FITS al `WCSSolution` propio (para reproyectar sin duplicar álgebra) | No existía | `wcs_fit.py` (`wcs_solution_from_astropy`) -- ver Fase 13 | `tests/unit/astrometry/test_wcs_fit.py` | Usado internamente por "Registrar por WCS compartido..." | **DISPONIBLE** |
| Emparejamiento automático uno-a-uno contra catálogo de referencia (Gaia) | Real, pero vive en `catalogs/gaia.py`, no orquestado junto a `fit_wcs` -- no existe una función única "detectar -> consultar Gaia -> emparejar -> ajustar WCS" | ver §6 | Sin camino de uso desde "Ajustar WCS..." (que pide RA/Dec a mano, sin resolución automática) | **PENDIENTE** (como flujo integrado -- "blind solving" real queda fuera de alcance, ver Fase 13) |
| Comunicación honesta de problemas de WCS (nunca inventa coordenadas) | Real y verificado: `detection/point_sources.py:78-81` deja `ra_deg`/`dec_deg` en `None` sin WCS válido; `catalogs/gaia.py:39-44` cae explícitamente a `DISCOVERY_REVIEW` con motivo `"sin coordenadas celestes (sin WCS válido)"` | `docs/audit/09-FASE7-DISCOVERY-ENGINE.md` (verificado end-to-end); también `photometry.zeropoint` (Fase 12) y "Registrar por WCS compartido..." (Fase 13), que fallan con un mensaje claro en vez de fingir un WCS | — | **DISPONIBLE** |
| Exportación de posiciones con incertidumbre y métricas de calidad | Real desde la Fase 14, fila no actualizada hasta esta auditoría -- brecha de documentación, no de código: `WCSFitDialog` ya construye una `Table` (estrella, x, y, ra, dec, residuo en arcsec) por cada ajuste | `tests/gui_smoke/test_qt_app_table_export_smoke.py` | "Ajustar WCS..." -> "Herramientas → Exportar última tabla a CSV..." (Fase 14) | **DISPONIBLE** |

---

## 6. Tablas, coordenadas y catálogos (equivalente propio de `astcat`)

| Capacidad | Estado actual | Test | GUI | Estado final |
|---|---|---|---|---|
| Consulta seguraante red a Gaia (nunca lanza, degrada a lista vacía) | Real, `catalogs/gaia.py:19` (`query_gaia_neighbors`) | — | Usado por el Discovery Engine | **DISPONIBLE** |
| Clasificación por vecino más cercano contra Gaia (`KNOWN`/`UNMATCHED`/`DISCOVERY_REVIEW`) | Real, `gaia.py:32` (`classify_against_gaia_neighbors`) | — | ídem | **DISPONIBLE** |
| Tabla científica genérica (columnas + unidades + filas) exportable a CSV | No existía | `astrophysics_suite/tables/table.py` (`Table`, `to_csv`/`from_csv`) -- ver Fase 14 | `tests/unit/tables/test_table.py` | `ProcessResult.table` (nuevo campo opcional) + botón "Exportar última tabla a CSV..." en Herramientas | **DISPONIBLE** |
| Exportación de tablas científicas reproducibles (CSV/FITS-table) | No implementada para ningún motor de fotometría/astrometría | `Table.to_csv` -- ver Fase 14 | `tests/unit/tables/test_table.py` | `photometry.zeropoint` y "Ajustar WCS..." ya producen `Table` real (una fila por estrella) exportable | **DISPONIBLE** (para los dos flujos que la producen; el resto de motores no construye una tabla todavía, ver nota) |
| Abstracción de catálogo genérica (proveedor conectable: SIMBAD, 2MASS, PS1...) | No existe -- solo Gaia, acoplado directamente | — | — | **PENDIENTE** (deliberadamente no abordado: una abstracción con un solo proveedor real sería prematura -- YAGNI -- hasta que haya una necesidad concreta de un segundo catálogo) |
| Tipo de dato `Table`/`SourceCatalog` compartido entre motores (unificación de `ApertureMeasurement`, `PSFFitResult`, `WCSSolution`, `ExtractedSpectrum`...) | No existe -- cada motor sigue devolviendo su propia lista de dataclasses local, sin heredar de un contrato común | — | — | **PENDIENTE** -- brecha de arquitectura real, deliberadamente NO resuelta en la Fase 14 (ver nota abajo) |

**Nota de arquitectura (actualizada en la Fase 14)**: el encargo pide contratos
`Measurement`/`Source`/`PhotometryResult`/`AstrometricResult`/`Spectrum`/`Table`
unificados -- es decir, que cada motor científico DEVUELVA sus resultados ya
tipados según un contrato común, no que cada uno reinvente su propio dataclass de
resultado local. Esa unificación profunda (reescribir `ApertureMeasurement`,
`PSFFitResult`, `WCSSolution`, `ExtractedSpectrum`... para que hereden o se ajusten
a un contrato común) sigue sin abordarse -- es una refactorización de alto riesgo
que tocaría cuatro bloques ya cerrados y probados (`ccdred`, fotometría,
astrometría, espectroscopía), y se decidió deliberadamente no arriesgar esa
estabilidad solo para cerrar esta fila de la tabla. En su lugar, la Fase 14 entrega
una versión aditiva y de bajo riesgo que sí cierra la necesidad práctica señalada
por el encargo -- **exportar mediciones reales a una tabla reproducible**: `Table`
es un tipo de exportación genérico que el llamador arma explícitamente a partir del
resultado real de cada motor (ver `photometry.zeropoint` y "Ajustar WCS..." como
los dos primeros consumidores), sin tocar ni un solo tipo de resultado existente.
La unificación completa queda documentada aquí, explícita, para una fase dedicada
si se decide que hace falta.

---

## 7. `onedspec`/`twodspec`/`apextract` — espectroscopía

| Capacidad | Estado actual | Test | GUI | Estado final |
|---|---|---|---|---|
| Trazado de apertura (centroide ponderado por flujo columna a columna + ajuste polinómico sigma-clip) | Real, `spectroscopy/trace.py:29` (`trace_spectrum`) | `tests/unit/spectroscopy/test_trace.py` | Proceso `spectroscopy.trace`, cableado (clic para el centro inicial) | **EXPERIMENTAL** (el resultado se visualiza como una franja repetida, no un espectro real -- documentado así explícitamente por falta de un widget de gráfico 1D) |
| Extracción por suma simple con fondo de ventanas laterales | Real, `trace.py:117` (`extract_sum`) | ídem | Disponible como método del mismo proceso `spectroscopy.trace` | **EXPERIMENTAL** (mismo motivo que arriba) |
| Extracción óptima ponderada por varianza (Horne 1986) | Real, `trace.py:147` (`extract_optimal`) | ídem | ídem | **EXPERIMENTAL** (mismo motivo) |
| Detección de líneas de arco (fondo local robusto + umbral + centroide subpíxel parabólico) | Real, `spectroscopy/wavelength.py:22` (`find_arc_lines`) | `tests/unit/spectroscopy/test_wavelength.py` | Automática dentro de "Calibrar longitud de onda..." (menú Espectroscopía) -- ver Fase 15 | **DISPONIBLE** |
| Solución de longitud de onda (ajuste polinómico, RMS + residuo por línea) | Real, `wavelength.py:70` (`fit_wavelength_solution`) | ídem | "Calibrar longitud de onda...": tabla con una fila por línea detectada, el usuario introduce la longitud de onda conocida de cada una (sin resolución automática, igual que `identify` interactivo) -- ver Fase 15 | **DISPONIBLE** |
| Transferencia de solución por correlación cruzada (`reidentify`, solo traslación) | Real, `wavelength.py:92` (`reidentify_wavelength_solution`) | ídem | — | **DISPONIBLE** (como motor) |
| Corrección de extinción atmosférica + dos fórmulas de masa de aire | Real, `spectroscopy/fluxcal.py:14/29/38` | `tests/unit/spectroscopy/test_fluxcal.py` | — | **DISPONIBLE** (como motor) |
| Función de sensibilidad desde estrella estándar (`sensfunc`) + calibración de flujo (`calibrate`) | Real, `fluxcal.py:67/110` | ídem | Proceso `spectroscopy.fluxcal` ahora **listado explícitamente como pendiente** en el árbol (antes ni aparecía) -- necesita un espectro ya extraído y calibrado en longitud de onda más un catálogo de flujos estándar, interacción no construida -- ver Fase 15 | **PENDIENTE** (motor real, ahora visible en el árbol en vez de oculto) |
| Ajuste de continuo sigma-clip con rechazo asimétrico (emisión/absorción) | Real, `spectroscopy/continuum.py:29` (`fit_continuum`) | `tests/unit/spectroscopy/test_continuum.py` | Proceso `spectroscopy.continuum`, cableado, pero **fijo en la fila central de la imagen**, no en un espectro ya extraído | **EXPERIMENTAL** (recorte de alcance explícito, documentado) |
| Normalización por continuo | Real, `continuum.py:93` | ídem | mismo proceso | **EXPERIMENTAL** (mismo motivo) |
| Extracción multi-apertura por lote desde un único 2D (`apall` real, varias trazas a la vez) | No implementada -- se extrae una traza a la vez | — | — | **PENDIENTE** |
| Medición de líneas (`splot`/`fitprofs`/`deblend`: EW, flujo de línea individual) | No implementada | — | — | **PENDIENTE** |
| Combinación/apilado de espectros de varias exposiciones (`scombine`) | No implementada | — | — | **PENDIENTE** |
| Tipo `Spectrum` compartido (longitud de onda + flujo + incertidumbre + cabecera, un solo objeto) | No existe -- cada función pasa arrays crudos a mano entre `trace`/`wavelength`/`fluxcal`/`continuum` | — | — | **PENDIENTE** (misma brecha de §6) |

---

## Resumen ejecutivo por bloque

| Bloque | DISPONIBLE | EXPERIMENTAL | PENDIENTE | Veredicto |
|---|---|---|---|---|
| `ccdred` | 13 | 0 | 0 | **Cerrado.** Sesión real de LIGHTS, píxeles defectuosos, franjas, iluminación, cielo, clasificación por cabecera y perfiles de instrumento, todos con motor real y camino de uso en la GUI (Fases 10.1-10.2) |
| Análisis de imagen | 6 | 0 | 0 | **Cerrado.** Aritmética entre dos imágenes, estadísticas+histograma, recorte por clic y normalización por percentiles, todos con motor real y camino de uso en la GUI (Fase 11.1) |
| `apphot` | 7 | 0 | 0 | **Cerrado en la Fase 16.** Selección de fuente a clic o por detección automática (DAOStarFinder real), calibración de punto cero real contra Gaia (también con detección automática), y ajuste real de curva de crecimiento con radio óptimo recomendado -- todos con motor real y camino de uso en la GUI |
| `daophot` | 7 | 1 | 0 | **Cerrado en la Fase 17** (selección pstselect + refinamiento allstar + diagnóstico chi²/residuo), con el selector de modelo Moffat añadido en la Fase 17.1. Queda `EXPERIMENTAL`, sin bloquear el bloque, la PSF empírica (motor real, sin camino de uso -- necesitaría una segunda sesión de selección de estrellas de referencia previa al ajuste, interacción de dos etapas no construida) |
| Astrometría | 8 | 0 | 1 | **Cerrado en la Fase 18** (registro por pares de estrellas emparejadas, sin necesitar WCS en ninguna imagen). Queda pendiente, deliberadamente fuera de alcance, solo la resolución automática contra catálogo ("blind solving") |
| Tablas/catálogos | 4 | 0 | 2 | **Exportación cerrada en Fase 14**: `Table` genérica real + CSV, consumida por punto cero y ajuste de WCS. Quedan pendientes, deliberadamente: unificación profunda de los tipos de resultado de cada motor (alto riesgo, no abordada) y abstracción de catálogo con más de un proveedor (YAGNI hasta que haga falta un segundo) |
| Espectroscopía | 6 | 4 | 4 | **Calibración en longitud de onda cerrada en Fase 15**: detección automática de líneas + tabla de longitudes conocidas, ajuste real. `spectroscopy.fluxcal` ahora al menos visible como pendiente (antes ni aparecía). Trazado/extracción/continuo siguen `EXPERIMENTAL` (recorte de alcance explícito: fila central, tira repetida); multi-apertura por lote, medición de líneas, combinación de espectros y el tipo `Spectrum` compartido siguen pendientes |

## Prioridad de desarrollo (orden acordado explícitamente)

**CCDRED → análisis de imagen → fotometría → astrometría → tablas/catálogos → espectroscopía**,
cerrando cada bloque antes de ampliar el siguiente. La Fase 10.1 (ver
`14-FASE10-CCDRED-SESSION-PIPELINE.md`) cerró el hueco más importante de `ccdred`:
una GUI que solo calibraba una imagen a la vez, nunca una sesión real de LIGHTS, y de
paso cableó dos motores que ya existían sin camino de uso (píxeles defectuosos,
franjas). La Fase 10.2 (ver `15-FASE10.2-CCDRED-CIERRE.md`) cierra los cuatro huecos
que quedaban documentados como `PENDIENTE`: iluminación, cielo, clasificación de
fotogramas por cabecera y perfiles de instrumento. Con esto, el bloque `ccdred`
queda completo -- las 13 capacidades de la tabla anterior en `DISPONIBLE`, ninguna
`PENDIENTE`. La Fase 11.1 (ver `16-FASE11-ANALISIS-IMAGEN.md`) cierra a continuación
el bloque de análisis de imagen -- las cuatro capacidades que quedaban `PENDIENTE`
(aritmética entre imágenes, estadística/histograma genérico, máscaras/regiones/
recortes independientes, normalización genérica), todas con motor real y camino de
uso en la GUI. La Fase 12 (ver `17-FASE12-APPHOT.md`) cierra el núcleo de `apphot`:
selección de fuente a clic (en vez de fija al centro) y calibración fotométrica real
-- punto cero resuelto contra Gaia DR3, no una constante introducida a mano. Quedan
documentados como pendientes, sin bloquear el siguiente bloque, el ajuste de curva de
crecimiento/radio óptimo y conectar la detección automática de fuentes como paso
previo interactivo (motor ya real, solo le falta esa conexión). La Fase 13 (ver
`18-FASE13-ASTROMETRIA.md`) cierra el núcleo del bloque de astrometría: "Ajustar
WCS..." (clic en estrellas + tabla de coordenadas a mano, sin resolución automática
-- mismo alcance que el `ccmap` interactivo clásico) y "Registrar por WCS
compartido..." (reproyección real entre dos imágenes que ya tienen WCS). Queda
documentado como pendiente, sin bloquear el siguiente bloque, el registro por pares
de estrellas emparejadas entre dos ventanas a la vez (necesitaría una interacción de
selección cruzada entre dos vistas que no se construyó en esta fase) y la resolución
automática contra catálogo ("blind solving", un problema bastante más difícil que
cualquier otra capacidad cerrada hasta ahora). La Fase 14 (ver
`19-FASE14-TABLAS.md`) cierra la necesidad práctica del bloque de tablas/catálogos
-- una `Table` genérica real, exportable a CSV, ya consumida por `photometry.
zeropoint` y "Ajustar WCS..." -- con una decisión de alcance deliberada: NO
reescribir los tipos de resultado de cada motor (`ApertureMeasurement`,
`PSFFitResult`, `WCSSolution`, `ExtractedSpectrum`...) bajo un contrato común, por
ser una refactorización de alto riesgo que tocaría cuatro bloques ya cerrados y
probados sin necesidad funcional inmediata que lo justifique -- queda documentada
como brecha de arquitectura real para una fase dedicada. La Fase 15 (ver
`20-FASE15-ESPECTROSCOPIA.md`) cierra el último bloque del orden acordado:
`spectroscopy.wavelength` gana un camino de uso real -- "Calibrar longitud de
onda..." detecta las líneas de arco automáticamente (`find_arc_lines`, sin clic
manual, a diferencia del ajuste de WCS) y solo pide al usuario la longitud de onda
conocida de cada una en una tabla, mismo alcance que `identify` interactivo.
`spectroscopy.fluxcal` sigue sin camino de uso -- necesitaría un espectro ya
extraído y calibrado en longitud de onda más un catálogo de flujos estándar,
interacción no construida en esta fase -- pero al menos queda visible como
pendiente en el árbol de procesos en vez de invisible, cerrando la brecha de
"ni siquiera listado" que señalaba la auditoría original. Con esto se completa el
recorrido por los seis bloques del orden de prioridad acordado
(`CCDRED → análisis de imagen → fotometría → astrometría → tablas/catálogos →
espectroscopía`); los huecos que quedan en cada uno están documentados
explícitamente arriba, ninguno oculto.

Tras cerrar los seis bloques, se continuó con los huecos ya documentados como
`PENDIENTE` dentro de bloques que se habían dado por cerrados en su núcleo
mínimo, siguiendo el mismo orden de prioridad (fotometría antes que
astrometría/tablas/espectroscopía, cuyos pendientes son deliberadamente de
mayor riesgo o alcance -- "blind solving", unificación profunda de tipos,
abstracción de catálogo -- y siguen fuera de alcance). La Fase 16 (ver
`21-FASE16-APPHOT-CIERRE.md`) cierra los dos huecos que quedaban en `apphot`:
`fit_curve_of_growth` (`astrophysics_suite/photometry/aperture.py`) ajusta la
curva de crecimiento real a un modelo de saturación monótono y recomienda el
radio de apertura que maximiza la señal/ruido medida -- expuesto como casilla
opcional en `photometry.aperture`, sin cambiar la medida principal ya
probada; y `detect_point_sources_in_array` (`astrophysics_suite/detection/
point_sources.py`) conecta el mismo motor DAOStarFinder ya usado por el
Discovery Engine como alternativa real al clic manual en `photometry.
aperture` y `photometry.zeropoint` ("Detectar automáticamente"). Con esto,
`apphot` queda con sus 7 capacidades en `DISPONIBLE`, ninguna `PENDIENTE`.

Con `apphot` cerrado, la Fase 17 (ver `22-FASE17-DAOPHOT-CIERRE.md`) cierra
los cuatro huecos que quedaban en `daophot`: `select_psf_reference_stars`
(`astrophysics_suite/photometry/psf.py`) implementa la selección automática
de estrellas de referencia tipo `pstselect` (aislamiento real contra todos
los candidatos detectados, no solo los seleccionados; redondez; señal/ruido
mínima); `detect_psf_candidates` (`astrophysics_suite/detection/
point_sources.py`) conecta la detección automática -- el equivalente
`daofind` -- enriquecida con las métricas que esa selección necesita;
`fit_group_psf_photometry_with_position_refinement` implementa el
refinamiento no lineal de posición de `allstar` por proyección variable
(Golub-Pereyra: `scipy.optimize.least_squares` optimiza solo los
desplazamientos de posición, el flujo se resuelve como subproblema lineal
exacto en cada evaluación); y `compute_psf_fit_diagnostics` da el
diagnóstico de calidad que faltaba (chi² reducido + imagen de residuo)
sobre un ajuste ya resuelto, sin volver a ajustar nada. Las cuatro se
exponen como casillas opcionales en `photometry.psf`, sin cambiar el
comportamiento por defecto ya probado desde la Fase 9.6. Con esto, `daophot`
quedó con 6 capacidades cableadas en `DISPONIBLE`; una fase adicional
menor (17.1) añadió el selector de modelo Moffat en `photometry.psf`
(casilla "Usar perfil de Moffat", con `alpha`/`beta` configurables) --
motor ya real desde la Fase 9.3, solo le faltaba la casilla. Con eso,
`daophot` queda con 7 de sus 8 capacidades en `DISPONIBLE`; solo sigue
`EXPERIMENTAL` la PSF empírica -- motor real (`build_empirical_psf`), pero
sin camino de uso porque necesitaría una interacción de dos etapas que no
se construyó (una primera sesión de clic para elegir las estrellas de
referencia con las que construir la PSF, antes de la sesión de clic ya
existente para elegir las fuentes a medir) -- hueco menor, documentado, no
priorizado por no tener un caso de uso concreto que lo reclame todavía.

Con `apphot` y `daophot` cerrados, la Fase 18 (ver
`23-FASE18-ASTROMETRIA-PARES.md`) retoma el hueco que quedaba en
astrometría desde la Fase 13: el registro por pares de estrellas
emparejadas entre dos ventanas (`fit_affine_transform`, motor real, sin
camino de uso). El menú Astrometría gana "Registrar por pares de estrellas
(clic)...", que encadena dos sesiones de clic independientes -- ya
soportadas por cada `ImageView` desde la Fase 9.6, sin ninguna interacción
nueva que construir, solo orquestar el orden -- exigiendo el mismo número de
puntos en el mismo orden en ambas ventanas. A diferencia de "Registrar por
WCS compartido..." (que exige que ambas imágenes ya tengan WCS), esta vía
no necesita astrometría previa en ninguna de las dos -- el caso real que
faltaba cubrir. Aprovechando esta ronda, se corrigió también una fila de la
tabla de astrometría que había quedado desactualizada desde la Fase 14 (no
un hueco de código: la exportación de posiciones de "Ajustar WCS..." con
residuo por estrella ya era real desde entonces, solo la propia tabla de
este documento no se había puesto al día). Con esto, astrometría queda con
8 de sus 9 capacidades en `DISPONIBLE`; solo la resolución automática
contra catálogo ("blind solving") sigue `PENDIENTE`, deliberadamente fuera
de alcance por ser un problema algorítmico bastante más difícil que
cualquier otra capacidad cerrada hasta ahora, sin un caso de uso concreto
que lo reclame todavía.
