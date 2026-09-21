# 37 — Cierre del motor de Resolución Astrométrica Automática (Plate Solving)

Informe de cierre según el protocolo de 10 fases pedido explícitamente.
Motor único: `astrometry/plate_solve.py` (con puntero aproximado) +
`astrometry/blind_solve.py` (ciego, sin puntero) -- dos caminos de
entrada al mismo motor conceptual, comparten verificación real.

## FASE 1 — Auditoría

**Implementaciones encontradas.** `plate_solve.py` (con puntero) y
`blind_solve.py` (ciego): únicas, sin duplicados. `legacy/AstroPhysicsSuite_
v57_3_COMMERCIAL.py`: grep exhaustivo de `solve_plate|plate_solve|blind_
solve` y de patrones de resolución astrométrica -- **cero** resultados.
No hay implementación heredada que migrar ni duplicar.

**Dependencia compartida, fuera de alcance de este motor** (usada
también por Ajuste Manual de WCS y por Registro, así que su API pública
no se toca): `astrometry/wcs_fit.py` (`fit_wcs`, `gnomonic_project`/
`deproject`, `WCSSolution`, `wcs_solution_to_astropy`,
`rescale_wcs_for_binning`, `angular_separation_deg`).

**GUI.** `qt_app/astrometry/plate_solve_dialog.py` (camino con puntero):
completo antes de esta ronda -- RA/Dec/escala editables con prellenado
desde header, botón SIMBAD, resolución en hilo de fondo, guardado real a
disco con ruta elegible y overwrite (`_offer_to_save_wcs_fits_copy` en
`qt_app/main_window.py`). **El camino ciego no tenía diálogo ni entrada
de menú** -- solo se ejecutaba automáticamente dentro de Discovery.

**Tests encontrados.** `tests/unit/astrometry/test_plate_solve.py`
(pointed) y `test_blind_solve.py` (11, ciego) -- ambos reales, sin mocks
del propio motor. `tests/gui_smoke/test_qt_app_plate_solve_smoke.py` (6,
incluido guardar-y-reabrir-con-astropy real) -- **solo el camino con
puntero**. `tests/integration/test_generic_discovery_pipeline.py` --
ambos caminos cableados en Discovery. Ninguno usaba píxeles de un FITS
real del usuario para plate solving específicamente.

**Dependencias reales.** `detect_point_sources_in_array`
(`detection/point_sources.py`), `query_gaia_neighbors`
(`catalogs/gaia.py`, con caché local primero), `CatalogCache`
(`catalogs/local_cache.py`), `fit_wcs`/`gnomonic_project`/`gnomonic_
deproject`/`WCSSolution` (`astrometry/wcs_fit.py`).

**Entradas/salidas reales.** Ver Fase 2.

**Brechas reales encontradas:** ni `PlateSolveResult` ni `WCSSolution`
llevaban `Provenance` -- inconsistente con `Detection`,
`CharacterizationResult`, `MotionEvidence`... que sí la llevan. Ninguna
de las dos funciones públicas aceptaba `pipeline_version`.

## FASE 2 — Contrato

**Entrada** (`solve_plate`, con puntero): `data: ndarray` (imagen 2D
real), `header: dict`, `approx_ra_deg`/`approx_dec_deg`/
`approx_scale_arcsec_px: float | None`, parámetros de detección/ajuste/
validación (`fwhm_px`, `threshold_sigma`, `max_stars`,
`match_radius_arcsec`, `rotation_step_deg`, `allow_flip`,
`min_matched_stars`, `max_rms_arcsec`, `gaia_mag_limit`, `timeout_s`,
`pointing_uncertainty_arcsec`), **nuevo** `pipeline_version: str = ""`.

**Entrada** (`solve_plate_blind`, ciego): `data`, `header`,
`catalog_rows: list[dict]` (obligatorio -- típicamente
`CatalogCache("gaia").all_rows()`), parámetros propios de asterismos
(`k_neighbors`, `code_tolerance`, `max_candidates_tried`,
`max_image_stars`, `max_catalog_stars`, `seed_pointing_uncertainty_
arcsec`), **nuevo** `pipeline_version: str = ""`, y
`**solve_plate_kwargs` reenviado a la verificación interna.

**Salida** (`PlateSolveResult`, ambos caminos): `success: bool`,
`solution: WCSSolution | None` (`crval_deg` grados, `crpix_px` px,
`cd_matrix_deg_per_px` grados/px, `residuals_arcsec`,
`rms_residual_arcsec`, `n_stars`), `provider: str`,
`n_detected_stars`/`n_catalog_stars`/`n_matched: int`, `reason: str`
(siempre legible), `rotation_deg`/`mirrored`, **nuevo**
`provenance: Provenance | None`.

**Unidades.** RA/Dec grados decimales; escala arcsec/px; CD grados/px;
residuales y RMS en arcsec; rotación en grados [0,360).

**Incertidumbre.** `rms_residual_arcsec`/`residuals_arcsec` (no es un
`Quantity`: es la calidad de un ajuste geométrico, no una magnitud
escalar con error).

**Quality.** No hay `QualitySummary` (este motor no emite `Candidate`);
el equivalente es `success`/`reason` con umbrales explícitos.

**Provenance.** `Provenance.now(pipeline_version=..., engine="astrometry.
plate_solve"|"astrometry.blind_solve", engine_version="1.0")` --
adjuntada SIEMPRE, éxito o fallo (un intento fallido también es
procedencia real).

**Errores.** Nunca lanza por un motivo esperado (sin estrellas, sin
catálogo, RMS alto, timeout) -- todo vuelve como `success=False` +
`reason`. Confirmado en la auditoría: ninguna excepción de programación
sin capturar en la ruta pública.

**NOT_AVAILABLE.** Equivalente: `success=False` + `reason` explícito --
ya cumplido en ambos caminos antes de esta ronda.

## FASE 3 — Implementación

Único cambio de contrato: `provenance` añadido a `PlateSolveResult`.
Implementado con un envoltorio delgado (`solve_plate`/`solve_plate_
blind` públicas llaman a un núcleo privado `_solve_plate_core`/
`_solve_plate_blind_core` y adjuntan `Provenance` con
`dataclasses.replace()` sobre el resultado) -- evita tocar los 10 y 7
puntos de retorno de cada función respectivamente, cero riesgo de
olvidar uno. El camino ciego etiqueta el resultado FINAL con su propio
motor (`astrometry.blind_solve`), no con el del intento interno de
verificación (`astrometry.plate_solve`) que reutiliza -- son procedencias
distintas y no deben confundirse. `pipeline_version` se hiló hasta
`discovery/pipeline.py` (`_ensure_wcs`/`_try_blind_solve`), que ya lo
recibía para el resto de motores.

No se creó ninguna funcionalidad nueva de detección/emparejamiento/
ajuste -- ambos algoritmos quedan exactamente como en la ronda anterior.

## FASE 4 — Integración

`discovery/pipeline.py::_ensure_wcs` (motor anterior: demosaico +
detección de puntero desde header/SIMBAD; motor siguiente: detección de
fuentes puntuales, identificación Gaia, todo lo que depende de WCS)
intenta primero el camino con puntero si hay uno disponible; si falla o
no hay ninguno, intenta el camino ciego contra la caché local; solo si
ambos fallan, se declara `WCS_STATE_SOLVE_FAILED` con el motivo de los
dos intentos. Ya integrado en la ronda anterior, reconfirmado aquí sin
cambios de comportamiento (las 13 pruebas de integración existentes
siguen en verde).

## FASE 5 — GUI

**Camino con puntero:** ya completo antes de esta ronda.

**Camino ciego (nuevo):** `qt_app/astrometry/blind_solve_dialog.py`
(`BlindPlateSolveDialog`) -- sin campos de RA/Dec/escala (no hacen
falta), muestra el estado real de la caché local
(`CatalogCache.describe()`), resuelve en hilo de fondo
(`CallableWorker`, mismo patrón que el diálogo con puntero), y expone
`result_solution()`/`result_table()` igual que `PlateSolveDialog` -- así
`main_window._offer_to_save_wcs_fits_copy` (guardado a disco) se
reutiliza sin ningún cambio. Entrada de menú nueva: "Astrometría ->
Resolver placa en ciego (sin puntero)...", junto a la existente.

La GUI muestra: progreso (mensaje de estado durante la resolución en
hilo de fondo), resultado (estrellas detectadas/catalogadas/emparejadas,
rotación, proveedor), warnings (aviso de ambigüedad cuando la segunda
mejor orientación queda cerca de la elegida, heredado de `solve_plate`),
errores (motivo explícito, nunca "Error" a secas, con sugerencias de qué
hacer), estado (habilitación de botones Resolver/Aceptar según fase) y
archivos producidos (ruta real tras guardar).

## FASE 6 — Salidas

Reutiliza `_offer_to_save_wcs_fits_copy` (ya existente, sin cambios):
ruta elegible (`QFileDialog.getSaveFileName`, con nombre por defecto
`<original>_wcs.fits`), overwrite gestionado por el diálogo nativo del
sistema, cabecera original preservada + WCS fusionado
(`wcs_solution_to_astropy(...).to_header()`), error de escritura real
mostrado con `QMessageBox.critical` (nunca silencioso). Provenance del
propio `PlateSolveResult` vive en el objeto Python del resultado
(consumible por quien orqueste la resolución, p. ej. Discovery, que ya
la recibe); no se escribe todavía como tarjetas FITS propias en la
cabecera guardada -- limitación real, anotada en "Qué queda".

Verificado reabriendo el archivo guardado con astropy en el test de
humo GUI (ver Fase 7).

## FASE 7 — Tests

- **Unit:** `test_plate_solve.py` (13) + `test_blind_solve.py` (11) +
  4 nuevos de provenance (2 por camino, éxito y fallo) = **28**.
- **Integration:** `test_generic_discovery_pipeline.py` -- ambos
  caminos cableados en Discovery end-to-end con FITS sintéticos reales
  (WCS real, DATE-OBS real).
- **Regresión:** `test_local_cache.py::test_all_rows_*` (4) protege la
  columna SQL ambigua corregida la ronda anterior;
  `test_solve_plate_blind_does_not_false_positive_on_an_unrelated_
  catalog` protege la garantía epistémica central del motor (nunca
  fabricar una solución) -- la regresión más grave posible aquí.
- **GUI smoke:** `test_qt_app_plate_solve_smoke.py` (6, con puntero,
  preexistente) + `test_qt_app_blind_plate_solve_smoke.py` (3, nuevo:
  resolver-y-aplicar, fallar-sin-catálogo, guardar-y-reabrir-con-
  astropy) = **9**, ambos caminos con el mismo rigor.
- **FITS reales:** ver Fase 8 -- verificado con píxeles reales del
  usuario, no comprometido como fixture permanente (ver limitación).

Ningún test se conforma con `assert result is not None`: cada uno
verifica separación angular real en arcsec contra un valor verdadero
conocido (sintético o derivado del propio WCS SIP-real del archivo),
RMS del ajuste, número de estrellas emparejadas, o el contenido legible
del mensaje de error.

## FASE 8 — Validación

**Ejecutado de verdad**, no supuesto:

| conjunto | comando | resultado |
|---|---|---|
| Unitarios astrometría | `pytest tests/unit/astrometry/` | 64 passed, 3 skipped (no relacionados) |
| Suite completa (sin GUI) | `pytest tests/` (venv `aps-test`) | **577 passed, 37 skipped, 1 xfailed** |
| GUI smoke completa | `xvfb-run pytest tests/gui_smoke/` (venv `aps-gui`) | **105 passed** |

**Datos utilizados:** FITS sintéticos con estrellas gaussianas reales +
ruido real inyectado (unit/integration/GUI), y **píxeles reales** del
light M31 del usuario (`Light_M31_300s_0001.fit`, Bayer RGGB real, WCS
SIP real) para la verificación de Fase 7:

1. Debayer real (SuperPixel) del campo completo (3008×3008 -> 1504×1504).
2. Detección real de 390 fuentes en el campo completo -> catálogo de
   referencia construido con sus posiciones de cielo REALES (SIP-aware,
   `astropy.wcs.WCS.all_pix2world`, no simuladas).
3. Recorte de 700×700 px en torno al `CRPIX` real (donde el SIP es más
   preciso) -- la "imagen a resolver", con 40 estrellas detectadas.
4. `solve_plate_blind` (mockeando solo el punto de red de Gaia hacia el
   catálogo así construido, mismo patrón que el resto del proyecto sin
   acceso real a internet): **éxito al primer asterismo probado**, 34/40
   estrellas emparejadas, RMS=0.21", separación real frente al centro
   verdadero (recalculado independientemente vía SIP): **0.385 arcsec**.

Un primer intento de este mismo script dio 1676" de discrepancia -- caza
y corrección de un bug real, pero en el SCRIPT DE PRUEBA (olvidé sumar
el origen del recorte al evaluar la posición "verdadera" con el WCS de
la imagen completa), no en el motor; documentado para que quede
constancia de que se verificó, no se asumió.

**Limitaciones:**
- Sin acceso real a Gaia en este entorno (confirmado en toda la sesión):
  la verificación con FITS reales mockea la consulta de red hacia el
  catálogo construido a partir del propio WCS SIP real del archivo, no
  hacia Gaia en vivo. Es una limitación del ENTORNO de pruebas, no del
  motor -- el mismo mecanismo (`query_gaia_neighbors`, caché local
  primero) es el que usa toda la aplicación.
- La verificación con FITS reales NO quedó como fixture pytest
  permanente: el archivo (18 MB) no tiene precedente de commitearse al
  repositorio (que hoy pesa ~20 MB en total, todos los tests existentes
  generan FITS sintéticos programáticamente) y vive en el scratchpad de
  esta sesión, no en el repositorio. Decisión pendiente del usuario si
  se quiere una fixture real permanente (cambio de política del
  proyecto, no una limitación técnica del motor).
- `WCSSolution`/`wcs_fit.fit_wcs` no modelan SIP (documentado como
  alcance deliberado desde antes de esta ronda) -- el camino ciego
  recupera correctamente el puntero/rotación/escala LINEAL incluso
  sobre datos con SIP real (demostrado: 0.385" cerca de CRPIX, donde el
  SIP es más preciso), pero un WCS guardado por este motor sobre un
  campo muy amplio con distorsión SIP fuerte tendría más error hacia
  los bordes que el WCS original del instrumento.
- Provenance no se escribe todavía como tarjetas FITS en el header
  guardado (vive en el objeto `PlateSolveResult` en memoria).

## FASE 9 — Cierre

**Motor: Resolución Astrométrica Automática (Plate Solving, con puntero
+ ciego) -- CERRADO.**

- Funciona: ambos caminos, verificado con sintéticos y con píxeles
  reales del usuario.
- Conectado: Discovery (`_ensure_wcs`) intenta ambos caminos en orden
  antes de rendirse; sin pérdida de información entre motores
  (confirmado en la ronda anterior y reconfirmado aquí).
- GUI funciona: ambos caminos tienen diálogo, entrada de menú, y guardan
  a disco -- verificado con pruebas de humo reales, no solo "abre sin
  excepción".
- Outputs funcionan: ruta elegible, overwrite gestionado, metadata
  original preservada, verificado reabriendo con astropy.
- Provenance funciona: ambos caminos la adjuntan siempre, éxito o
  fallo, con el motor y la versión de pipeline reales.
- Tests pasan: 577 (suite completa) + 105 (GUI bajo Xvfb), cero
  regresiones.
- Validación real realizada: ver Fase 8, incluida verificación con
  datos reales del usuario.

Limitaciones anotadas (no bloquean el cierre, son alcance conocido, no
carencias ocultas): sin SIP en el ajuste propio; sin fixture FITS real
permanente; provenance no persistida en el header FITS guardado.

## FASE 10 — Cambio de motor

Informe de cierre entregado. Disponible para pasar al siguiente motor
cuando el usuario lo indique.
