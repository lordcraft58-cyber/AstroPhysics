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
| Aritmética entre imágenes con propagación de error (+ − × ÷, unidades, máscaras) | Real, `imtools/arithmetic.py:23` (`UncertainImage`) | `tests/unit/imtools/test_arithmetic.py` | Proceso `imtools.arithmetic` listado, **sin `run=`** (necesita una vista de selección de dos imágenes que la GUI no tiene) | **PENDIENTE** |
| Eliminación de rayos cósmicos (L.A.Cosmic real: Laplaciano submuestreado, imagen de estructura fina, doble umbral, crecimiento de máscara, iterativo) | Real, `imtools/cosmic_rays.py:71` | `tests/unit/imtools/test_cosmic_rays.py` | Proceso `imtools.cosmic_rays`, cableado | **DISPONIBLE** |
| S/N por imagen a partir del modelo de ruido CCD | Real, `UncertainImage.from_counts`/`.snr()` (`arithmetic.py:50/150`) | ídem | Reutilizado internamente por otros procesos, sin panel propio | **DISPONIBLE** (como bloque interno) |
| Estadística/histograma de imagen completa como utilidad genérica reutilizable | No existe un módulo dedicado (cada motor calcula lo que necesita internamente, p. ej. STF en `qt_app/mdi/stf.py`) | — | — | **PENDIENTE** |
| Máscaras/regiones/recortes genéricos (no ligados a una apertura fotométrica ni al recorte de overscan) | No existe como utilidad independiente | — | — | **PENDIENTE** |
| Normalización de imagen genérica | Solo existe dentro de `build_master_flat` (normalización a mediana 1.0); no hay utilidad genérica | `tests/unit/reduction/test_master_frames.py` | — | **PENDIENTE** (como utilidad genérica) |

---

## 3. `apphot` — fotometría de apertura

| Capacidad | Estado actual | Test | GUI | Estado final |
|---|---|---|---|---|
| Detección de fuentes (DAOStarFinder real, no un placeholder) | Real, `detection/point_sources.py:47` (`detect_point_sources`) | `tests/unit/detection/test_point_sources.py` | Usado por el Discovery Engine; no expuesto como paso previo interactivo de `photometry.aperture` | **EXPERIMENTAL** (existe, pero desconectado del flujo interactivo de fotometría) |
| Centroidado (momento de segundo orden), FWHM, elipticidad, nitidez | Real, `_legacy_enrich_star_rows` vía `detection/point_sources.py` | ídem | ídem | **DISPONIBLE** (como motor) |
| Máscara de cobertura de apertura subpíxel (interior/exterior analítico, borde sobremuestreado) | Real, `photometry/aperture.py:17` (`aperture_coverage_mask`) | `tests/unit/photometry/test_aperture.py` | Proceso `photometry.aperture`, cableado | **DISPONIBLE** |
| Estimación de cielo en anillo con rechazo iterativo sigma-clip (MAD) | Real, `aperture.py:73` (`estimate_local_sky`) | ídem | ídem | **DISPONIBLE** |
| Fotometría multi-radio (curva de crecimiento cruda), flujo neto, error propagado, magnitud instrumental | Real, `aperture.py:145` (`aperture_photometry`) | ídem | ídem, pero **fijo en el centro de la imagen**, sin selección de fuente por clic ni por detección automática | **EXPERIMENTAL** (motor real, interacción de la GUI recortada) |
| Ajuste real de curva de crecimiento / radio óptimo | No implementado (se devuelven las medidas por radio, sin ajuste ni recomendación de radio óptimo) | — | — | **PENDIENTE** |
| Calibración fotométrica (punto cero resuelto contra estrellas estándar/catálogo) | No implementada -- el punto cero es una constante fija que introduce el usuario, nunca ajustada contra datos | — | — | **PENDIENTE** (ver honestidad epistémica: el proceso lo declara así en su propia descripción, no se presenta como calibración validada) |

---

## 4. `daophot` — fotometría PSF

| Capacidad | Estado actual | Test | GUI | Estado final |
|---|---|---|---|---|
| Modelo PSF Gaussiano elíptico | Real, `photometry/psf.py:31` (`GaussianPSF`) | `tests/unit/photometry/test_psf.py` | Expuesto en `photometry.psf` | **DISPONIBLE** |
| Modelo PSF Moffat (colas realistas) | Real, `psf.py:56` (`MoffatPSF`) | ídem | Motor listo, **GUI fija en Gaussiano** (`registry.py:79`) | **EXPERIMENTAL** (motor disponible, no seleccionable desde la GUI) |
| PSF empírica (apilado de estrellas de referencia, recentrado subpíxel, sobremuestreo) | Real, `psf.py:83/102` (`build_empirical_psf`) | ídem | Motor listo, **no expuesto en la GUI** | **EXPERIMENTAL** (motor disponible, no seleccionable desde la GUI) |
| Selección automática de estrellas PSF (equivalente a `pstselect`: aislamiento/redondez/nitidez) | No implementada -- las posiciones de referencia las da el llamador | — | — | **PENDIENTE** |
| Detección automática de fuentes previa a PSF (equivalente a `daofind`) | Reutiliza el mismo `detect_point_sources` genérico de apphot -- no hay ningún criterio afinado para candidatura PSF (redondez/nitidez) | `tests/unit/detection/test_point_sources.py` | No conectado a `photometry.psf` (la selección hoy es 100% manual por clic) | **PENDIENTE** (como paso `daofind`-específico) |
| Ajuste PSF simultáneo multi-fuente con desmezclado (`group`+`psf`+`nstar` real) | Real, `psf.py:164` (`fit_group_psf_photometry`) -- matriz de diseño con una columna por fuente + término de cielo, ponderado por sigma inverso, incertidumbre por covarianza | ídem | Proceso `photometry.psf`, cableado, selección de posiciones a clic (Fase 9.6 §8) | **DISPONIBLE** |
| Refinamiento no lineal de posición iterativo (`allstar`) | No implementado -- posiciones fijas, documentado explícitamente como límite de alcance en el propio código (`psf.py:189-192`) | — | — | **PENDIENTE** |
| Diagnóstico de calidad de ajuste (chi, residuos, imagen de residuo por `nstar`) | No implementado -- `PSFFitResult` solo devuelve flujo + incertidumbre | — | — | **PENDIENTE** |

---

## 5. Astrometría (equivalente propio de las partes relevantes de `astcat`/registro de imágenes)

| Capacidad | Estado actual | Test | GUI | Estado final |
|---|---|---|---|---|
| Proyección tangencial (TAN) pixel↔cielo, ambas direcciones | Real, `astrometry/wcs_fit.py:24/37` | `tests/unit/astrometry/test_wcs_fit.py` | — | **DISPONIBLE** (como motor) |
| Separación angular (gran círculo, fórmula haversine) | Real, `wcs_fit.py:57` | ídem | — | **DISPONIBLE** |
| Ajuste WCS lineal (matriz CD) desde pares pixel↔cielo, con residuo por estrella y RMS | Real, `wcs_fit.py:91` (`fit_wcs`) -- **deliberadamente sin términos SIP/TPV de orden superior**, documentado como límite de alcance | ídem | Proceso `astrometry.wcs_fit` listado, **sin `run=`** | **PENDIENTE** (motor real, sin camino de uso) |
| Registro/alineación afín o de similitud entre dos imágenes desde estrellas emparejadas, con RMS de residuo | Real, `astrometry/registration.py:31` (`fit_affine_transform`) | `tests/unit/astrometry/test_registration.py` | Proceso `astrometry.registration` listado, **sin `run=`** | **PENDIENTE** (motor real, sin camino de uso) |
| Remuestreo/reproyección de una imagen a la solución WCS de otra | Real, `registration.py:87/115` (`apply_affine_transform`, `reproject_to_reference`) | ídem | — | **DISPONIBLE** (como motor) |
| Emparejamiento automático uno-a-uno contra catálogo de referencia (Gaia) | Real, pero vive en `catalogs/gaia.py`, no orquestado junto a `fit_wcs` -- no existe una función única "detectar -> consultar Gaia -> emparejar -> ajustar WCS" | ver §6 | Sin camino de uso desde `astrometry.wcs_fit` | **PENDIENTE** (como flujo integrado) |
| Comunicación honesta de problemas de WCS (nunca inventa coordenadas) | Real y verificado: `detection/point_sources.py:78-81` deja `ra_deg`/`dec_deg` en `None` sin WCS válido; `catalogs/gaia.py:39-44` cae explícitamente a `DISCOVERY_REVIEW` con motivo `"sin coordenadas celestes (sin WCS válido)"` | `docs/audit/09-FASE7-DISCOVERY-ENGINE.md` (verificado end-to-end) | — | **DISPONIBLE** |
| Exportación de posiciones con incertidumbre y métricas de calidad | Parcial: `WCSSolution` sí expone `residuals_arcsec`/`rms_residual_arcsec`; no hay una exportación tabular dedicada (ligado al vacío de "tablas", §6) | — | — | **PENDIENTE** (como exportación) |

---

## 6. Tablas, coordenadas y catálogos (equivalente propio de `astcat`)

| Capacidad | Estado actual | Test | GUI | Estado final |
|---|---|---|---|---|
| Consulta seguraante red a Gaia (nunca lanza, degrada a lista vacía) | Real, `catalogs/gaia.py:19` (`query_gaia_neighbors`) | — | Usado por el Discovery Engine | **DISPONIBLE** |
| Clasificación por vecino más cercano contra Gaia (`KNOWN`/`UNMATCHED`/`DISCOVERY_REVIEW`) | Real, `gaia.py:32` (`classify_against_gaia_neighbors`) | — | ídem | **DISPONIBLE** |
| Abstracción de catálogo genérica (proveedor conectable: SIMBAD, 2MASS, PS1...) | No existe -- solo Gaia, acoplado directamente | — | — | **PENDIENTE** |
| Tipo de dato `Table`/`SourceCatalog` compartido entre motores | No existe -- cada motor devuelve su propia lista de dataclasses local (`ApertureMeasurement`, `PSFFitResult`, `Detection`...), sin contrato común | — | — | **PENDIENTE** -- brecha de arquitectura real, no solo de funcionalidad (ver nota abajo) |
| Exportación de tablas científicas reproducibles (CSV/FITS-table) | No implementada para ningún motor de fotometría/astrometría | — | — | **PENDIENTE** |

**Nota de arquitectura**: el encargo pide contratos `Measurement`/`Source`/`PhotometryResult`/
`AstrometricResult`/`Spectrum`/`Table` unificados. Hoy existen (Fase 4) `Quantity`,
`Provenance`, `Observation`/`ImageRef`, `Detection`, `Candidate` y toda la cadena de
evidencia del Discovery Engine -- pero reducción/fotometría/astrometría/espectroscopía
cada una reinventa su propio dataclass de resultado local
(`MasterFrame`, `ApertureMeasurement`, `PSFFitResult`, `WCSSolution`,
`ExtractedSpectrum`...) sin heredar de un contrato común. Es una brecha real y
deliberadamente señalada aquí para una fase de consolidación posterior -- no se toca
en la Fase 10.1 (que se centra en cerrar `ccdred`), pero debe abordarse antes de que
"tablas y catálogos" pueda considerarse `DISPONIBLE` en sentido pleno.

---

## 7. `onedspec`/`twodspec`/`apextract` — espectroscopía

| Capacidad | Estado actual | Test | GUI | Estado final |
|---|---|---|---|---|
| Trazado de apertura (centroide ponderado por flujo columna a columna + ajuste polinómico sigma-clip) | Real, `spectroscopy/trace.py:29` (`trace_spectrum`) | `tests/unit/spectroscopy/test_trace.py` | Proceso `spectroscopy.trace`, cableado (clic para el centro inicial) | **EXPERIMENTAL** (el resultado se visualiza como una franja repetida, no un espectro real -- documentado así explícitamente por falta de un widget de gráfico 1D) |
| Extracción por suma simple con fondo de ventanas laterales | Real, `trace.py:117` (`extract_sum`) | ídem | Disponible como método del mismo proceso `spectroscopy.trace` | **EXPERIMENTAL** (mismo motivo que arriba) |
| Extracción óptima ponderada por varianza (Horne 1986) | Real, `trace.py:147` (`extract_optimal`) | ídem | ídem | **EXPERIMENTAL** (mismo motivo) |
| Detección de líneas de arco (fondo local robusto + umbral + centroide subpíxel parabólico) | Real, `spectroscopy/wavelength.py:22` (`find_arc_lines`) | `tests/unit/spectroscopy/test_wavelength.py` | — | **DISPONIBLE** (como motor) |
| Solución de longitud de onda (ajuste polinómico, RMS + residuo por línea) | Real, `wavelength.py:70` (`fit_wavelength_solution`) | ídem | Proceso `spectroscopy.wavelength` listado, **sin `run=`** (necesita una lista de líneas de referencia que la GUI no ofrece aún) | **PENDIENTE** (motor real, sin camino de uso) |
| Transferencia de solución por correlación cruzada (`reidentify`, solo traslación) | Real, `wavelength.py:92` (`reidentify_wavelength_solution`) | ídem | — | **DISPONIBLE** (como motor) |
| Corrección de extinción atmosférica + dos fórmulas de masa de aire | Real, `spectroscopy/fluxcal.py:14/29/38` | `tests/unit/spectroscopy/test_fluxcal.py` | — | **DISPONIBLE** (como motor) |
| Función de sensibilidad desde estrella estándar (`sensfunc`) + calibración de flujo (`calibrate`) | Real, `fluxcal.py:67/110` | ídem | **Sin ningún `ProcessDefinition`** -- no aparece ni como pendiente en el árbol | **PENDIENTE** (motor real, ni siquiera listado) |
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
| Análisis de imagen | 3 | 0 | 3 | Cubre lo esencial (aritmética con error, L.A.Cosmic real); faltan utilidades genéricas de inspección |
| `apphot` | 3 | 2 | 2 | Motor sólido; selección de fuente en la GUI sigue fija al centro |
| `daophot` | 2 | 2 | 4 | Núcleo real (deblending simultáneo, tres modelos PSF); falta selección/refinamiento/diagnóstico automáticos |
| Astrometría | 4 | 0 | 4 | Motores sólidos y honestos ante fallos de WCS; **ninguno wireado en la GUI todavía** |
| Tablas/catálogos | 2 | 0 | 3 | Solo Gaia; sin contrato `Table`/`Source` compartido -- brecha de arquitectura real |
| Espectroscopía | 5 | 4 | 5 | Motor más completo de lo esperado (Horne, sensfunc, extinción); GUI puramente demostrativa en todo lo que expone |

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
`PENDIENTE` -- y el siguiente bloque a abrir, según el orden acordado, es análisis de
imagen (estadística/histograma genérico, máscaras/regiones/recortes independientes
de fotometría u overscan, normalización genérica).
