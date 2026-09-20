# Informe 71 — Auditoría del encargo completo de espectroscopía (43 secciones)

El usuario pegó el encargo original completo (43 secciones, inspirado
conceptualmente en ISIS de Christian Buil, sin copiar su código). Este
informe audita, sección por sección, qué está hecho de verdad (con
evidencia real: archivo + motor/test), qué está parcial y qué falta --
antes de seguir construyendo a ciegas.

## Resumen ejecutivo

De las 43 secciones, **~24 están completas o casi completas** (motor real
+ tests + validación con Vega real, la mayoría de los slices 1-16 de esta
serie), **~11 están parciales** (el motor existe pero le falta una pieza
concreta: wiring a la GUI, una visualización, o una capacidad específica)
y **~8 son huecos reales confirmados** que no tienen ningún camino de uso
todavía. El hallazgo más importante y repetido (§2, §3, §5, §28): **el
visor 2D nunca dibuja la traza/apertura/cielo sobre la imagen real** --
todo el flujo de trazado→extracción es hoy una caja negra (un clic, y el
resultado aparece en una ventana 1D nueva, sin ver nunca qué región se
usó sobre la imagen original). Es la base de la que dependen varias otras
peticiones (edición manual interactiva de traza/apertura/cielo), así que
es el siguiente slice.

## Tabla sección por sección

| § | Tema | Estado | Evidencia |
|---|---|---|---|
| 1 | Modelo de datos (A-G) + extensiones FITS | **Parcial** | `frame2d.SpectralFrame2D` (data/variance/mask/header) cubre A/B; `spectrum1d_io.py` cubre C/D; `fluxcal.py` cubre E; `continuum.py` cubre F. Falta confirmar detección robusta de BinTableHDU/cubos/WCS preexistente al abrir cualquier FITS ajeno (el cargador genérico de `astrophysics_suite/io/` no se ha auditado específicamente para espectroscopía en este informe). |
| 2 | Detección automática traza 2D + GUI auto/manual/añadir/borrar/recalcular/bloquear | **Parcial** | `trace_spectrum` (polinomio + RMS) y `multiaperture.find_aperture_centers` (auto-detección de picos) existen. **Falta**: spline como alternativa al polinomio, distinción automática puntual/extendida, y toda la GUI de edición (añadir/borrar/recalcular/bloquear traza) -- hoy la traza no es editable tras calcularse. |
| 3 | Extracción 2D→1D (suma/media/ponderada/óptima) siguiendo Y=f(X) | **Parcial** | `extract_sum`/`extract_optimal` SÍ siguen `trace.center_px` columna a columna (no una fila fija) -- correcto. Falta el modo "media" explícito (solo hay suma y óptima) y **la visualización gráfica de los límites de apertura/cielo sobre la imagen** (mismo hueco que §28). |
| 4 | Extracción multiapertura | **Hecho** | `multiaperture.py` (Fase 9.5), `spectroscopy.multiaperture` en el registro, sky subtraction por apertura, `aperture_id` como identificador. |
| 5 | Cielo/sky subtraction (regiones independientes, mostrar sobre la imagen) | **Parcial** | `estimate_sky_background` con `SkyWindow`s y reductores media/mediana/sigma-clip -- motor real. Falta ajuste polinómico suave explícito y, otra vez, mostrar las regiones sobre la imagen 2D. |
| 6 | Píxeles malos/cósmicos/DQ | **Hecho** | `frame2d.PixelFlag`/`build_pixel_mask` (NONFINITE/SATURATED/DEAD/COSMIC_RAY/USER_MASKED), `detect_cosmic_rays` (L.A.Cosmic), `spectroscopy.quality_map` (slice 14) para visualizarlos. Disciplina de "nunca 0 en silencio" verificada en todo `trace.py`. |
| 7 | Preprocesado (bias/dark/flat/bad pixel/cosmic ray, masters con procedencia) | **Hecho (genérico, no específico de espectroscopía)** | `session_pipeline.py`/`ReduceSessionDialog` (Fase 10.1/10.2) ya hacen esto para imagen; `spectroscopy/preprocessing.py` reutiliza `detect_cosmic_rays`. No auditado si el flujo de sesión de LIGHTS se ha probado explícitamente con un frame 2D espectroscópico real de principio a fin. |
| 8 | Calibración λ polinómica de orden configurable | **Hecho** | `wavelength.fit_wavelength_solution(degree=...)`, orden 1-5 soportado, aviso si el orden es excesivo para el número de líneas (a verificar el mensaje exacto). |
| 9 | Calibración con lámpara (Ne/Ar/He/ThAr, tabla PIXEL\|WAVELENGTH\|ID\|RESIDUAL, RMS) | **Hecho** | `line_catalog.py`, `wavelength_fit_dialog.py`, detección de picos + tabla de residuos + RMS total, rechazo manual de líneas. |
| 10 | Identificación automática de líneas con confirmación | **Hecho** | Mismo `wavelength_fit_dialog.py` -- nunca acepta automáticamente, exige confirmación. |
| 11 | MODO REAL vs. MODO SIMULACIÓN (`CALTYPE='SYNTHETIC'`) | **Hecho** | `calibration_provenance.py`: `WavelengthCalibrationRecord.is_synthetic`, `spectrum1d_io.wavelength_header_cards` escribe `CALTYPE='SYNTHETIC'`/`'REAL'` real. Falta confirmar que la GUI muestra literalmente el texto "CALIBRACIÓN SIMULADA" (a verificar en los diálogos). |
| 12 | Calibración predefinida reutilizable (recalcular solo A0) | **Hecho** | `services/spectral_calibration_profiles.py` (slice 3), `reidentify_wavelength_solution` (Fase 15) para recalcular solo el desplazamiento global. |
| 13 | Calibración por estrella de referencia (Balmer) | **Hueco real** | `CalibrationSource.REFERENCE_STAR` existe como VALOR de procedencia (distinción honesta ya modelada), pero **no existe ningún motor que la produzca** -- es un enum sin productor. |
| 14 | Calibración lateral/simultánea (objeto + lámpara en la misma imagen) | **Hecho (motor), parcial (GUI)** | `lateral_calibration.py` (slice 3). No confirmado si la GUI muestra OBJETO/SKY/CALIBRACIÓN superpuestos sobre la misma imagen (mismo hueco de visualización que §2/3/5/28). |
| 15 | Selector de unidades (Å/nm/μm/pixel) + no mostrar "Pixel" si hay WCS | **Parcial** | Los procesos ya cambian la etiqueta del eje X a "Longitud de onda (Å)" cuando hay calibración real (nunca mienten). **Falta** el selector nm/μm y un cambio dinámico en caliente. |
| 16 | WCS espectral real (nunca lineal falso sobre una solución polinómica) | **Hecho** | `spectrum1d_io.py`: WCS lineal real para grado ≤1, convención `-TAB` (Greisen et al. 2006, estándar FITS publicado) para grado ≥2 -- nunca aproxima. Recuperación automática al reabrir confirmada por los propios tests de round-trip. |
| 17 | Respuesta instrumental (separada de la calibración λ) | **Hecho** | `fluxcal.build_sensitivity_function`, `FluxCalibrationDialog` (slice 8) -- proceso explícitamente distinto de la calibración de longitud de onda. |
| 18 | Niveles de calibración de flujo (ADU/relativo/absoluto/densidad) | **Hecho (esencia)** | `flux_bunit` nunca se deja en `"ADU"` cuando el flujo es físico real; `synthetic_photometry.py` nunca llama "absoluta" a una simple normalización. No hay un enum explícito de "nivel" pero la disciplina de nomenclatura se cumple en cada guardado. |
| 19 | Normalización del continuo (RAW vs. NORMALIZED como productos distintos) | **Parcial** | `continuum.py` (polinomio + sigma-clip) -- nunca muta el original. Falta spline y selección manual de regiones de continuo en la GUI. |
| 20 | Base de datos de líneas (elemento/ionización/tipo/referencia) | **Hecho** | `line_catalog.py` (Balmer, Ca II, Na D, nebulares...). |
| 21 | Identificación automática de líneas del objeto | **Hecho** | `object_line_identification.py` (slice 6). |
| 22 | Medidas espectroscópicas (centroide/FWHM/EW/profundidad/SNR) | **Hecho** | `lines.py`, `line_profile_fit.py` (Gaussiana/Voigt, slice 5). |
| 23 | Velocidad radial (Doppler/cross-correlation/heliocéntrica/baricéntrica) | **Hecho** | `radial_velocity.py`/`heliocentric.py` (slice 4) -- RV observada y corregida siempre separadas. |
| 24 | Conversión aire↔vacío | **Hecho el motor, sin conectar a la GUI** | `air_vacuum.py` (Morton 2000, con test dedicado) -- **pero no lo usa ningún consumidor real todavía** (cero referencias fuera de su propio archivo y test). |
| 25 | Comparación con templates (residuo, sin clasificar automáticamente) | **Hueco real** | No existe un flujo dedicado "cargar observado + template, comparar, mostrar residuo, no clasificar". `cross_correlate_radial_velocity` compara contra una plantilla pero solo para RV, no como herramienta de comparación visual general. |
| 26 | Distinción de tipos espectrales, sintéticos marcados como `SYNTHETIC` | **Parcial** | `standard_stars.py` carga espectros CALSPEC reales (nunca inventados). No existe un clasificador de tipo espectral. La disciplina de marcar lo sintético como tal se cumple en todos los motores que generan datos de prueba. |
| 27 | Objetos extendidos/nebulosas | **Hecho** | `extended_extraction.py` (slice 11). |
| 28 | Visor 2D profesional (traza/apertura/cielo/líneas/bad pixels superpuestos) | **Hueco real confirmado** | `ImageView` (`qt_app/mdi/image_window.py`) es un `QGraphicsView` con zoom/pan/stretch (log/sqrt/lineal) real, pero **no dibuja ningún overlay** -- ni traza, ni apertura, ni cielo, ni líneas, ni píxeles malos. Confirmado por inspección directa: cero métodos de overlay en la clase. |
| 29 | Visor 1D interactivo (flujo/continuo/sky/template, selector de unidades, tooltip con λ/flujo/error/SNR) | **Parcial** | `SpectrumView` ya soporta varias series superpuestas y emite `value_hovered` -- pero el tooltip actual solo muestra "X/Y" genéricos (`_on_spectrum_value_hovered` en `main_window.py`), no pixel/λ/flujo/error/SNR desglosados. Sin selector de unidades. |
| 30 | Caídas a cero (el bug original de Vega) | **Hecho** | Corregido en la slice 1 (informe 55) -- contrato `NaN` nunca `0.0` verificado en todo `trace.py` desde entonces. |
| 31 | Informe de control de calidad unificado (semáforo OK/WARNING/ERROR) | **Hueco real** | Los números individuales YA se calculan y se muestran dispersos (RMS de traza en el resumen de `spectroscopy.trace`, RMS de longitud de onda en `wavelength_fit_dialog`, saturación/rayos cósmicos en `quality_map`) pero **no existe un informe unificado** que los junte con un indicador semáforo. |
| 32 | Resolución espectral (R = λ/FWHM) | **Hueco real (pequeño)** | `line_profile_fit.py` ya calcula FWHM real de una línea ajustada -- falta la métrica derivada `R = λ/FWHM` como resultado nombrado. |
| 33 | Generadores sintéticos reutilizables para tests | **Parcial** | Cada archivo de test construye su propio arco/lámpara sintética ad-hoc (numpy directo) -- funciona y está bien probado, pero no existe un módulo público reutilizable (`generate_synthetic_lamp()`, etc.) que la GUI o un pipeline de validación puedan llamar. |
| 34 | Botón "AUTOPROCESS SPECTRUM" (pipeline completo automático) | **Hueco real (grande)** | No existe. Cada paso (bias/dark/flat/traza/cielo/extracción/calibración λ/respuesta/normalización/identificación/QC) tiene su propio motor real y probado por separado, pero ningún botón los encadena. |
| 35 | Modo manual/reset/reprocess sobre cualquier paso automático | **Parcial** | Cada diálogo individual ya permite ajustar sus propios parámetros a mano. Falta la orquestación de nivel superior (§34) sobre la que aplicaría "reprocesar". |
| 36 | Historial de procesamiento (JSON reproducible) | **Parcial** | Cada guardado individual ya escribe procedencia completa en cabeceras FITS (`HISTORY`, `APSWAVE*`, `TELLCORR`, `FLUXCAL`...) -- pero no hay un log JSON unificado de la cadena completa (depende de §34). |
| 37 | Productos con nomenclatura estándar (`object_1D.fits`, `.dat`, `.csv`...) | **Parcial** | `Table.py` ya exporta CSV (Fase 14); cada diálogo guarda FITS con sufijos propios coherentes (`_tellcorr`, `_flexure_corregido`...) pero no el conjunto completo de nombres exactos del encargo. |
| 38 | FITS 1D con cabeceras estándar completas | **Hecho (a falta de auditoría exhaustiva de cada campo)** | `spectrum1d_io.py` ya preserva `OBJECT`/`DATE-OBS`/`EXPTIME` del header original y escribe `BUNIT`/`CTYPE1`/`CUNIT1`/`CRPIX1`/`CRVAL1`/`CDELT1` reales para el caso lineal. |
| 39 | Trazabilidad de cadena completa, nunca sobrescribir en silencio | **Hecho (por diálogo), parcial (cadena completa)** | Cada diálogo pide ruta con `QFileDialog` y nunca sobrescribe el original -- pero no existe la cadena completa nombrada de principio a fin (depende de §34). |
| 40 | Referencia conceptual a ISIS, sin copiar código | **Hecho** | Cumplido en el diseño de toda la serie -- documentación pública como referencia, arquitectura propia. |
| 41 | Principio fundamental (nunca confundir observado/reducido/calibrado/normalizado/sintético) | **Hecho** | Es la disciplina seguida en cada slice de esta serie -- `CALTYPE`, `is_synthetic`, `flux_bunit`, honestidad de procedencia en cada motor. |
| 42 | Panel de estado unificado por objeto (checklist ✓/✗ + rango λ + dispersión + resolución + RMS) | **Hueco real** | No existe. Depende de §31 (QC) + §32 (resolución) + agregación de lo que cada motor ya calcula por separado. |
| 43 | Suite de validación final (G6V + A0V/Vega + lámparas, pipeline completo) | **Parcial** | Existen 984 tests unitarios + 179 de humo GUI reales, y cada slice se validó contra Vega real -- pero no hay UN test de integración nombrado que encadene lámpara sintética → calibración → Vega sintética → extracción → calibración λ → verificación de RMS, como pide el encargo explícitamente. |

## Prioridad de continuación

El hallazgo más repetido (§2, §3, §5, §28) y el que más bloquea al resto
(§35 edición manual depende de poder VER lo que se edita) es el **visor
2D sin overlay**. Es el siguiente slice: dibujar la traza ajustada, los
límites de apertura y las regiones de cielo sobre la imagen 2D real, en
modo solo-lectura primero (visualización), como base para la edición
interactiva en un slice posterior.

Después, por impacto/esfuerzo: §31 (informe de QC unificado, reutiliza
números ya calculados), §32 (resolución espectral, cálculo pequeño sobre
`line_profile_fit` ya existente), §24 (conectar `air_vacuum.py`, ya
construido y probado, a un consumidor real), §13 (calibración por
estrella de referencia, motor nuevo pero acotado).
