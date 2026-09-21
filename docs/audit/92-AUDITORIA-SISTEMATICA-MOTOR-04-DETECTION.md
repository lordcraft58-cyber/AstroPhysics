# 92 — Auditoría sistemática, motor 4/16: Detection

Cuarto motor de la fase de cierre sistemático. A diferencia de los tres
motores anteriores (IO/FITS, Reduction, Astrometry/WCS), donde la
auditoría encontró un hallazgo real que corregir, esta auditoría
**no encontró ningún hueco que cerrar** -- Detection ya estaba, de hecho,
al nivel que exige el checklist de 20 puntos. Se documenta igualmente
con el mismo rigor, porque el objetivo de esta fase es verificar de
verdad, no dar nada por bueno sin comprobarlo (la propia lección del
informe 86: "¿seguro que está toda la lista cerrada?").

## Mapa del motor (fase previa, sin tocar código)

**Motor científico**: `astrophysics_suite/detection/{background,finder,
point_sources}.py` -- migrado por completo del monolito legado
(docs/audit/54-CIERRE-DETECTION.md), sin dependencia de legacy en
producción (legacy se conserva únicamente como oráculo de regresión).
**GUI**: sin diálogo propio -- Detection es un motor de soporte que
consumen otros tres directamente: (1) `discovery/pipeline.py` (Pase 1,
vía `services/discovery_service.py` y `NewObservationDialog`), (2)
`main_window._run_with_auto_detected_points` (detección automática para
"Fotometría de apertura", "Punto cero" y "PSF" -- botón "Detectar
automáticamente" en cada uno), (3) `astrometry/plate_solve.py` y
`astrometry/blind_solve.py` (estrellas reales para resolución de placa).
Verificado con `grep` que las tres vías llaman a la función real, no a
ningún envoltorio vacío.
**Registro de procesos genérico**: ninguna entrada -- decisión correcta,
no un hueco (Detection no es un producto terminal que el usuario guarde
por sí solo; construir un diálogo dedicado solo para "ver la lista de
detecciones" sería una capacidad NUEVA, fuera de alcance de esta fase).
**Tests (antes de este informe, sin cambios)**: `tests/unit/detection/
test_point_sources.py` (7), `tests/regression/test_detection_matches_legacy.py`
(9, incluida la rama de reserva sin DAOStarFinder/Background2D),
`tests/regression/test_photutils_compat.py` (5, dos bugs reales de
compatibilidad con photutils >= 2.0 ya corregidos y con regresión
propia), `tests/unit/photometry/test_psf.py` (usa `PSFCandidate`).
GUI: `tests/gui_smoke/test_qt_app_smoke.py::test_psf_auto_detect_selects_isolated_stars_and_skips_close_pair`
ejercita `detect_psf_candidates` de extremo a extremo con estrellas
sintéticas inyectadas (incluida la exclusión de un par demasiado
próximo), no solo la selección de referencias.

## Verificación (sin hallazgos que cerrar)

Se leyeron los tres archivos del motor científico completos y se buscó
explícitamente el patrón de hueco que cerraron los tres informes
anteriores (resultado real sin GUI que lo use, provenance sin rellenar,
rama de código sin test):

1. **Provenance/`input_hashes`**: ya rellenado desde el informe 88 --
   `detect_point_sources` usa el sha256 real que `io.fits_loader` ya
   calculó al cargar la imagen, sin releer el archivo. Verificado con
   datos reales más abajo.
2. **Las dos ramas de reserva tienen test de regresión byte a byte**:
   `_find_point_sources_fallback` (sin DAOStarFinder) y
   `_estimate_background_tiled` (sin `Background2D`) -- casi nunca se
   ejecutan en producción, pero `test_detection_matches_legacy.py` las
   ejercita explícitamente contra la implementación legacy, con
   `pytest.mark.parametrize("use_photutils", [True, False])` para forzar
   ambos caminos de forma determinista.
3. **`_dao_column` (bug real de compatibilidad con photutils >= 2.0,
   columnas `xcentroid`->`x_centroid`)**: regresión propia
   (`test_photutils_compat.py`), verificada con la versión de photutils
   realmente instalada en este entorno (3.0.0).
4. **`detect_psf_candidates`**: sin test unitario dedicado al nivel del
   motor, pero sí ejercitada de extremo a extremo por un test de humo
   GUI real (`test_psf_auto_detect_selects_isolated_stars_and_skips_close_pair`)
   que inyecta estrellas sintéticas de posición conocida y verifica que
   la selección por aislamiento funciona -- lo que exige que
   `detect_psf_candidates` calcule FWHM/elipticidad/separación reales,
   no solo que "devuelva algo". Se considera cobertura suficiente: es el
   mismo criterio de "prueba de humo GUI de extremo a extremo" que ya
   usa el resto del proyecto para caminos consumidos por un solo flujo.
5. **`NewObservationDialog` no expone `fwhm_px`/`threshold_sigma` al
   usuario**: verificado como decisión deliberada y ya documentada en el
   propio docstring del diálogo ("Deliberadamente simple... las opciones
   técnicas del Discovery Engine viven aparte"), no un descuido.

Ninguno de los cinco puntos anteriores requería una corrección.

## Validación con datos reales

Detección real ejecutada contra el LIGHT real de M31 del usuario
(`Light_M31_300s_0001.fit`, 3008x3008, uint16 BZERO/BSCALE, ASI533MC Pro
real, sin calibrar -- una imagen cruda de campo real, no un sintético
limpio): **21 fuentes reales detectadas en 4.04 s** con
`threshold_sigma=6.0` (razonable para un fondo de M31 sin calibrar),
`Detection.method == "DAOStarFinder"` (el camino rápido real, no la
reserva), y `provenance.input_hashes` con el sha256 real del archivo de
origen. Confirma que el motor funciona sobre datos reales de tamaño y
tipo real, con velocidad aceptable y procedencia honesta.

## Checklist de cierre (20 puntos)

| Punto | Estado |
|---|---|
| Implementación científica real | Sí -- DAOStarFinder real + reserva propia verificada, momentos de segundo orden reales para forma |
| Entrada definida | Sí -- `LoadedImage` (con provenance) o array 2D en memoria, según el consumidor |
| Salida definida | Sí -- `Detection`/`PSFCandidate`/tuplas `(x,y,flux)`, según el consumidor |
| Tipos coherentes | Sí -- dataclasses tipadas en todo el flujo |
| Unidades correctas | Sí -- px, ADU, sigma robusta, consistente con el resto del proyecto |
| Incertidumbres cuando correspondan | N/A directo (detección, no medida calibrada); `peak_snr`/`local_snr_median` sí son reales, nunca inventados |
| Manejo explícito de datos faltantes | Sí -- sin `SATURATE` en cabecera, la detección de saturación queda inactiva, nunca inventa un umbral |
| NOT_AVAILABLE cuando proceda | Sí -- sin WCS, `ra_deg`/`dec_deg` quedan `None`, nunca se inventa una posición celeste |
| Provenance | Sí -- `input_hashes` real desde el informe 88, verificado de nuevo aquí con datos reales |
| Errores correctamente gestionados | Sí -- fallo real de DAOStarFinder degrada a la reserva con aviso en el log, nunca una lista vacía silenciosa |
| Funciona independientemente | Sí -- sin GUI, ver `tests/unit/detection/` |
| Conectado al motor anterior (Astrometry/WCS) | Sí -- usa `ImageView.wcs`/cabecera ya resuelta para posición celeste cuando existe |
| Conectado al siguiente (Artifact Rejection) | Sí -- `Detection` alimenta directamente `artifacts/morphology_screen.py` en el pipeline de Discovery |
| GUI funcional | Sí, indirecta -- tres consumidores reales (Discovery, auto-detección en fotometría/PSF, plate solving), los tres probados de extremo a extremo |
| Guardado de resultados correcto | N/A -- Detection no es un producto terminal que se guarde por sí solo; sus consumidores (Candidate, FITS calibrado) ya lo hacen en sus propios motores |
| Rutas de salida controladas por el usuario | N/A (mismo motivo) |
| Tests unitarios | Sí -- 7 en `tests/unit/detection/` + cobertura de `PSFCandidate` en `tests/unit/photometry/test_psf.py` |
| Tests de integración | Sí -- consumido end-to-end por Discovery/Fotometría/Astrometría (motores adyacentes) |
| Test de regresión | Sí -- 9 tests byte a byte contra legacy (incluidas ambas ramas de reserva) + 5 de compatibilidad con photutils |
| Validación con datos reales/controlados | Sí -- LIGHT real de M31 sin calibrar, ver arriba |
| Documentación actualizada | Sí -- este informe (sin cambios de código que documentar aparte) |
| Ningún placeholder presentado como funcionalidad | Sí -- confirmado, sin excepciones |

## Validación de la suite completa

Sin cambios de código en este informe -- se reejecutó la suite relevante
para confirmar el estado antes de cerrar, sin necesidad de una corrida
completa nueva de toda la suite (ya validada íntegra en el informe 91,
sin tocar nada desde entonces):
- `tests/unit/detection/ + tests/regression/test_detection_matches_legacy.py
  + tests/regression/test_photutils_compat.py + tests/unit/photometry/test_psf.py`:
  **46 passed**.
- Humo GUI relevante (`test_qt_app_smoke.py::test_psf_auto_detect_*`):
  ya cubierto por la corrida completa del informe 91 (214 passed).

## CHECKPOINT

```
MOTOR: Detection
ESTADO: CERRADO
IMPLEMENTACIÓN: astrophysics_suite/detection/{background,finder,point_sources}.py
ENTRADA: LoadedImage (con provenance) o array 2D en memoria
SALIDA: Detection / PSFCandidate / (x,y,flux), con provenance real cuando aplica
GUI: indirecta -- consumido por Discovery, auto-detección en fotometría/PSF, y plate solving, los tres reales y probados
PROVENANCE: sí (input_hashes real desde el informe 88)
TESTS: 7 unitarios + 9 regresión legacy + 5 compatibilidad photutils = 21 tests directos del motor
TESTS PASADOS: 46 (incluye tests de PSFCandidate en photometry)
TESTS FALLIDOS: 0
VALIDACIÓN REAL: sí (LIGHT real de M31 sin calibrar, 21 fuentes reales en 4.04s, provenance con sha256 real)
PROBLEMAS RESTANTES: ninguno. Auditoría completa sin hallazgos que corregir -- el motor ya cumplía el checklist de 20 puntos.
CONTRATO HACIA EL SIGUIENTE MOTOR (Artifact Rejection): list[Detection] con MorphologySummary/peak_snr/provenance reales -- exactamente lo que artifacts/morphology_screen.py ya consume hoy en el pipeline de Discovery.
```

## Cambio de motor

Detection re-auditado bajo el checklist de 20 puntos: sin hallazgos que
corregir, validado de nuevo con datos reales de M31. Siguiente en el
orden fijo del usuario: **Artifact Rejection** (ya cerrado bajo el
proceso anterior en el informe 87 -- corresponde re-auditarlo aquí bajo
el checklist de esta fase, como pide el encargo para todos los motores
previamente cerrados).
