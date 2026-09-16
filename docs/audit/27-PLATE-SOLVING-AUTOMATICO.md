# 27 — Plate solving automático real (`solve_plate`)

## 1. Objetivo

Eliminar la dependencia de que el usuario marque a mano parejas de
estrellas para obtener un WCS ("Ajustar WCS (clic + coordenadas)...").
Se añade una resolución astrométrica automática: detecta estrellas reales
en la imagen, las empareja contra Gaia DR3 real, y ajusta un WCS real por
mínimos cuadrados (reutilizando `fit_wcs`, ya existente desde la Fase 13).

## 2. Alcance real (léase antes de asumir "blind solving" completo)

Esto **no** es astrometry.net / ASTAP: no resuelve sin ninguna
información previa contra un índice precalculado de todo el cielo. Eso es
un problema de emparejamiento de patrones geométricos bastante más
difícil, y además exigiría distribuir índices de varios GB, complicando
el empaquetado Windows (Fase 9) sin necesidad.

Lo que sí hace, de verdad, con datos reales:

1. Requiere una **posición aproximada** (RA/Dec) y una **escala
   aproximada** (arcsec/px) — del header FITS (`OBJCTRA`/`OBJCTDEC` o
   `RA`/`DEC`, sexagesimal o decimal; `PIXSCALE`/`SECPIX` o
   `FOCALLEN`+`XPIXSZ`) o introducidas por el usuario en el diálogo.
   Si no hay ninguna disponible, **se informa explícitamente** en vez de
   inventar un WCS (`estimate_approx_pointing_from_header`/
   `estimate_approx_scale_from_header` devuelven `None`).
2. Detecta estrellas reales (`detect_point_sources_in_array`, mismo motor
   DAOStarFinder/legacy que el resto de la aplicación).
3. Consulta Gaia real alrededor del puntero aproximado (mismo
   `query_gaia_neighbors` que usa el resto de catalogación/identificación).
4. Busca la **orientación real** (rotación + posible espejo/paridad) por
   rejilla — sin asumir que el puntero aproximado cae exactamente en el
   centro de la imagen (ver §4, el error puede ser de arcominutos).
5. Empareja 1-a-1 (vecino mutuo) y ajusta un WCS real por mínimos
   cuadrados (`fit_wcs`), con rechazo iterativo sigma-clip (MAD) de
   parejas mal emparejadas (`_robust_fit_wcs`).
6. Valida la solución: número mínimo de estrellas emparejadas, RMS máximo
   del ajuste. Si no se cumple, `success=False` con el motivo exacto —
   nunca se devuelve una solución que no pasa la validación.

Proveedor reportado al usuario:
`"local (rejilla de rotación + emparejamiento Gaia, sin binario/servicio
externo)"` — se decidió no envolver astrometry.net/ASTAP (política del
proyecto de no envolver herramientas de terceros de alto nivel, y este
entorno de desarrollo no tiene salida de red arbitraria para descargar
binarios/índices).

## 3. API

`astrophysics_suite/astrometry/plate_solve.py`:

```python
def solve_plate(
    data: np.ndarray, header: dict, *,
    approx_ra_deg=None, approx_dec_deg=None, approx_scale_arcsec_px=None,
    fwhm_px=3.0, threshold_sigma=5.0, max_stars=40, match_radius_arcsec=4.0,
    rotation_step_deg=2.0, allow_flip=True, min_matched_stars=6,
    max_rms_arcsec=2.0, gaia_mag_limit=16.0, timeout_s=30.0,
    pointing_uncertainty_arcsec=600.0,
) -> PlateSolveResult
```

`PlateSolveResult`: `success`, `solution` (`WCSSolution | None`),
`provider`, `n_detected_stars`, `n_catalog_stars`, `n_matched`, `reason`
(motivo del fallo, o resumen legible si tuvo éxito), `rotation_deg`,
`mirrored`.

GUI: menú **Astrometría → Resolver placa automáticamente...**
(`qt_app/astrometry/plate_solve_dialog.py`, `PlateSolveDialog`) — pide
RA/Dec/escala aproximadas (pre-rellenadas del header si están, siempre
editables), resuelve en un hilo de fondo (`CallableWorker`, consulta Gaia
real), y expone el resultado con mensajes accionables (nunca "Error" a
secas): motivo del fallo + qué hacer (ajustar el puntero/escala, o usar
"Ajustar WCS manualmente..." como alternativa). El manual se mantiene tal
cual, relabeleado como *fallback* explícito.

Tras aceptar, `MainWindow._open_plate_solve_dialog` aplica la solución a
la ventana (`view.fitted_wcs_solution`) y ofrece guardar una copia del
FITS con el WCS escrito en la cabecera real
(`_offer_to_save_wcs_fits_copy`, vía `wcs_solution_to_astropy` +
`save_fits_image`, ya existente desde la Fase 10.1).

## 4. Bug real encontrado y corregido durante el desarrollo

### 4.1 Centroide de detección incompleta desvía la búsqueda de orientación

La primera versión de la rejilla de búsqueda alineaba el CENTROIDE del
catálogo proyectado (con cada hipótesis de rotación/paridad) al
CENTROIDE de las estrellas detectadas, para hacer la búsqueda insensible
a que el puntero aproximado no caiga exactamente en el centro de la
imagen (un error de posición típico de arcominutos, muy superior a la
tolerancia de emparejamiento en píxeles).

Esto asume implícitamente que el centroide de las estrellas
**detectadas** aproxima el centroide del catálogo **proyectado
completo**. Esa asunción se rompe en cuanto la detección es incompleta o
no representativa — algo normal en datos reales (estrellas dobles
próximas que el detector fusiona en una sola fuente, fuentes cerca del
límite de detección, etc.), no un caso raro.

**Reproducción real** (no solo sospecha): con un campo sintético de 35
estrellas inyectadas (mismo generador que el test de humo GUI,
`shape=(220,220)`, `rotation_deg=8.0`, puntero/escala aproximados
**exactos**, es decir el caso más favorable posible), 7 de las 35
estrellas quedaron sin detectar — todas ellas en pares/grupos próximos
(distancia al vecino más cercano entre 3 y 9 px, fusionados por el
detector). El centroide de las 27 estrellas detectadas resultó
`(116.1, 116.4)` px, mientras que el centroide que predice el catálogo
completo es `(128.7, 120.9)` px — un desplazamiento sistemático de más
de 12 px. Con ese desplazamiento, la orientación **correcta**
(rotación=8°, sin espejo) puntuó solo 5 correspondencias en la rejilla
de búsqueda, mientras que una orientación **incorrecta** (espejada,
rotación≈298°) puntuó 16 — la rejilla elegía la orientación equivocada,
y el ajuste final por mínimos cuadrados producía una solución
"plausible" pero con RMS≈4.8" (rechazada por el umbral de validación de
2.0", pero por la razón equivocada: no era ambigüedad real, era un sesgo
sistemático del propio algoritmo de búsqueda).

Verificado paso a paso con un script de depuración (no solo "el test
falla"): se confirmó que la matriz CD de la hipótesis correcta
coincidía exactamente (diferencia 0.0) con la CD verdadera usada para
generar los datos sintéticos, y que el offset recuperado antes de
alinear centroides (`raw_xy`) coincidía exactamente con el offset
verdadero — el error se introducía enteramente en el paso de alineación
por centroide.

### 4.2 Corrección: votación de traslación (tipo Hough), no centroide

Se sustituyó la alineación por centroide por una **votación de
traslación**: para cada hipótesis de rotación/paridad, se calcula, para
cada pareja posible (estrella detectada, estrella de catálogo
proyectada sin trasladar), la traslación que las haría coincidir; se
agrupan esas traslaciones en una rejilla de tamaño `search_tolerance_px`
y se toma la más votada. Las parejas correctas votan todas
(aproximadamente) por la misma traslación; las incorrectas se reparten
casi al azar por todo el rango posible de traslaciones — robusto frente
a una submuestra de detecciones no representativa, sin asumir nada sobre
dónde cae el centro real de la imagen ni sobre qué fracción de estrellas
se detectó.

Archivo: `astrophysics_suite/astrometry/plate_solve.py`,
`_project_catalog_aligned_to_detected` (misma firma pública salvo que
recibe `detected_xy` + `bin_px` en vez de `detected_centroid`).

**Verificación tras la corrección** (mismo caso, sin tocar ningún umbral
de validación): RMS 4.76" → 0.008", rotación recuperada 8.001° (verdad:
8.0°), separación del centro 0.001" (antes indeterminada, al fallar la
validación). Se repitió con 25 combinaciones adicionales de semilla/
rotación/espejo (15 semillas a 8°, 5 a 45° espejado, 5 a 200°) — las 25
convergieron con RMS < 0.01" y rotación/paridad correctas.

## 5. Tests

- `tests/unit/astrometry/test_wcs_fit.py` — 11/11, incluye
  `wcs_solution_to_astropy` (inversa real de `wcs_solution_from_astropy`,
  round-trip numérico + escritura/relectura de un FITS real).
- `tests/unit/astrometry/test_plate_solve.py` — 13/13: recuperación de
  WCS verdadero con puntero/escala aproximados (no exactos); orientación
  espejada; fallos honestos (sin puntero, sin escala, pocas estrellas
  detectadas, Gaia sin fuentes cercanas, puntero muy alejado del real);
  parseo de `estimate_approx_pointing_from_header`/
  `estimate_approx_scale_from_header`.
- `tests/gui_smoke/test_qt_app_plate_solve_smoke.py` — 3/3: resolver y
  aplicar el WCS a la ventana vía el diálogo real (hilo de fondo
  incluido); reportar fallo sin tocar la ventana; guardar una copia del
  FITS con el WCS y verificar, reabriendo con astropy, que el header
  escrito es real y correcto.

Ejecutado en ambos entornos (`aps-test`, sin PySide6, y `aps-gui`, con
PySide6 + Xvfb): suite completa `aps-test` 380 passed / 3 skipped; suite
completa `aps-gui` 468 passed / 2 skipped / 1 xfailed. Sin regresiones.

## 6. Pendiente (no hecho en esta ronda)

- Integración automática de `solve_plate` **dentro** del flujo de
  Discovery (objetivo separado, aún no implementado): al seleccionar
  imágenes para Discovery, si falta WCS, intentar resolución automática
  antes de continuar, con los estados WCS PRESENTE / RESUELTO
  AUTOMÁTICAMENTE / RESUELTO Y VALIDADO / NO DISPONIBLE / FALLIDO / NO
  EJECUTADO visibles en la GUI.
