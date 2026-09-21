# 94 — Auditoría sistemática, motor 6/16: Characterization

Sexto motor de la fase de cierre sistemático. A diferencia de Detección
y Rechazo de Artefactos (informes 54 y 87), que ya habían migrado su
última dependencia real de `legacy`, Caracterización seguía delegando
por completo en `legacy...measure_source_quality` -- el motor entero, no
un residuo menor. Esta auditoría cierra esa migración, y de paso destapa
un hallazgo real: parte del código heredado que se iba a migrar era, tal
cual estaba escrito, inalcanzable.

## Mapa del motor (fase previa, sin tocar código)

**Motor científico**: `astrophysics_suite/photometry/quality.py`
(`characterize_point_source`, consumidor de `photometry/aperture.py`
para el flujo real) + `astrophysics_suite/models/characterization.py`
(`CharacterizationResult`, sin cambios en este informe).
**GUI**: ninguna dedicada -- mismo patrón que Detección: se consume
indirectamente a través de `discovery/pipeline.py` (Pase 1: caracteriza
cada detección que sobrevive al filtro morfológico barato; su resultado
alimenta después `artifacts/artifact_screen.py` y `Candidate.flux`/
`Candidate.morphology`).
**Tests (antes de este informe)**: `tests/unit/photometry/test_quality.py`
(8 tests, ya cubrían `characterize_point_source` de extremo a extremo,
pero ninguno fijaba la fórmula exacta contra el original).

## Hallazgo y cierre

### `measure_source_quality` seguía delegando por completo en legacy

Migrada de forma nativa a `photometry/quality.py`, reproduciendo la
MISMA cadena de cálculo (momentos de segundo orden para FWHM/
elipticidad, agudeza por región central 3x3, SNR local, aislamiento por
componentes conexas al 30% del pico) -- mismo patrón que las migraciones
de Detección (informe 54) y del filtro morfológico de Artefactos
(informe 87).

`measure_psf_quality` (la función heredada vecina, mediana de FWHM/
elipticidad sobre varias fuentes) **no se migra**: cero consumidores
reales en `astrophysics_suite`/`qt_app` -- su trabajo ya lo resuelve de
forma nativa `artifacts.artifact_screen.compute_field_statistics`
(misma idea, "referencia de PSF del campo", pero a partir de
`CharacterizationResult` reales). Migrarla habría sido reconstruir algo
ya sustituido, no cerrar un hueco.

### Hallazgo real durante la propia migración: una guarda "muerta" en el original

Al escribir la primera versión nativa, se "simplificó" una comprobación
del original que parecía ser "si no hay señal positiva, devolver NO
DISPONIBLE" -- pero el test de regresión (escrito ANTES de dar la
migración por buena, mismo método que en Detección) detectó una
divergencia real: sobre un recorte totalmente plano, el heredado
**no** devuelve `NO DISPONIBLE`. Investigado a fondo: en el original,
`total` se recalcula a `1.0` tres líneas más abajo de la guarda
(`total = max(np.sum(stamp_pos), 1.0)`), así que `if total <= 0` nunca
puede ser cierto -- la propia asignación anterior a esa comprobación deja
siempre `total` en un valor positivo (un sub-total real, o `1.0` si no
hay señal). Verificado directamente contra el heredado real:

```
$ measure_source_quality(recorte_totalmente_plano, x, y)
state = OBSERVABLE   # no "NO DISPONIBLE"
fwhm_px = None
ellipticity = None
sharpness = None
snr_local = 0.0
```

A diferencia del bug de unidades de FWHM que sí se corrigió en
Detección (`px^4` en vez de `px^2`, un error dimensional real), esto no
es un error de cálculo -- es una guarda que nunca se ejecuta, y el
comportamiento real resultante (`OBSERVABLE` con los campos no medibles
en `None`) ya es exactamente lo que `characterize_point_source` maneja
con honestidad más abajo (`fwhm=None` -> no se construye ninguna
`Quantity` fwhm). **Se conserva tal cual estaba** -- revertir la
"simplificación" y fijar el comportamiento real con un test de
regresión, en vez de corregir en silencio algo que no estaba pidiéndose
corregir.

Doce tests nuevos en `tests/regression/test_quality_matches_legacy.py`
(fuente aislada, elongada, saturada con nivel explícito, saturación
auto-detectada solo para dtype con signo -- verificado que `uint16`,
lo habitual en una cámara real, nunca la dispara sola --, dos fuentes
mezcladas, cerca del borde, cutout demasiado pequeño, y el caso del
campo plano de arriba) prueban la migración campo a campo contra el
original, incluida la guarda inalcanzable.

## Validación con datos reales

Pipeline genérico completo (`run_generic_discovery`, `threshold_sigma=6.0`)
sobre el mismo LIGHT real de M31 sin calibrar de los cierres anteriores:
**365 detecciones, 44 rechazadas, 321 candidatos reales** -- los mismos
números exactos que el cierre de Artifact Rejection (informe 93) sobre
el mismo archivo, lo que confirma que la migración no cambió ningún
resultado real aguas abajo. FWHM/elongación/flujo reales verificados
sobre el primer candidato (FWHM=8.08 px, elongación=1.02, flujo de
banda L=1 024 378 ADU).

## Checklist de cierre (20 puntos)

| Punto | Estado |
|---|---|
| Implementación científica real | Sí -- nativa desde este informe, sin legacy |
| Entrada definida | Sí -- `LoadedImage` + `Detection` ya cribada por Artifact Rejection |
| Salida definida | Sí -- `CharacterizationResult` (fwhm/elongación/flujo/extra) |
| Tipos coherentes | Sí -- `Quantity` tipada en todo el flujo, nunca un float suelto |
| Unidades correctas | Sí -- px, ADU, adimensional según el campo, consistente |
| Incertidumbres cuando correspondan | Sí -- `band_flux` trae error real de `aperture_photometry` (ruido de Poisson) |
| Manejo explícito de datos faltantes | Sí -- cutout demasiado pequeño o sin señal declarado NOT_AVAILABLE, nunca inventado |
| NOT_AVAILABLE cuando proceda | Sí -- `Quantity.not_available` cuando `measure_source_quality` no puede medir |
| Provenance | Sí -- `Provenance.now(engine="photometry.quality", ...)` en cada resultado |
| Errores correctamente gestionados | N/A directo (sin E/S ni red en este motor) |
| Funciona independientemente | Sí -- sin GUI, ver `tests/unit/photometry/test_quality.py` |
| Conectado al motor anterior (Artifact Rejection) | Sí -- mismo `Detection` que ya sobrevivió el gate |
| Conectado al siguiente (Photometry) | Sí -- `band_flux`/`fwhm`/`elongation` alimentan `Candidate.flux`/`Candidate.morphology` y el punto cero fotométrico |
| GUI funcional | N/A -- motor de soporte sin diálogo propio, mismo patrón que Detección |
| Guardado de resultados correcto | N/A -- no produce archivos; su resultado vive en `Candidate`, ya persistido por el motor de Sesión |
| Rutas de salida controladas por el usuario | N/A (mismo motivo) |
| Tests unitarios | Sí -- 8 (sin cambios de número, todos siguen pasando con la migración) |
| Tests de integración | Sí -- consumido end-to-end por Discovery (informe 93 y este, mismos 321 candidatos) |
| Test de regresión | Sí -- 12 nuevos, campo a campo contra legacy, incluida la guarda inalcanzable |
| Validación con datos reales/controlados | Sí -- LIGHT real de M31, ver arriba |
| Documentación actualizada | Sí -- este informe + comentarios nuevos en el código explicando el hallazgo |
| Ningún placeholder presentado como funcionalidad | Sí -- confirmado, sin excepciones |

## Validación de la suite completa

- `ruff check astrophysics_suite tests`: limpio.
- Unitaria + integración + regresión: **1704 passed** (antes: 1692, +12
  tests de regresión nuevos), 24 skipped -- sin regresión.
- Humo GUI: sin cambios de código en `qt_app/` en este informe, no
  requiere nueva corrida (el fix está enteramente en la capa de
  ciencia).

## CHECKPOINT

```
MOTOR: Characterization
ESTADO: CERRADO
IMPLEMENTACIÓN: astrophysics_suite/photometry/quality.py (characterize_point_source, measure_source_quality -- nativa desde este informe)
ENTRADA: LoadedImage + Detection (ya cribada por Artifact Rejection)
SALIDA: CharacterizationResult (fwhm/elongación/band_flux/extra), con Quantity real o NOT_AVAILABLE
GUI: N/A -- motor de soporte, consumido por discovery/pipeline.py
PROVENANCE: sí (Provenance.now por resultado)
TESTS: 8 unitarios + 12 regresión nuevos = 20 tests directos del motor
TESTS PASADOS: 1704 (unit/integración/regresión en conjunto)
TESTS FALLIDOS: 0
VALIDACIÓN REAL: sí (LIGHT real de M31: 365 detectadas, 44 rechazadas, 321 candidatos -- idéntico al informe 93, migración sin cambio de comportamiento real)
PROBLEMAS RESTANTES: ninguno bloqueante. measure_psf_quality no migrada (sin consumidor, superseded por compute_field_statistics) -- documentado, no un hueco.
CONTRATO HACIA EL SIGUIENTE MOTOR (Photometry): CharacterizationResult.band_flux (Quantity con error real) + fwhm/elongation -- exactamente lo que photometry/aperture.py y photometry/calibration.py (punto cero) ya consumen hoy vía Candidate.
```

## Cambio de motor

Characterization cerrado: última delegación real en legacy migrada de
forma nativa, con un hallazgo real (guarda inalcanzable del original)
encontrado por el propio proceso de verificación y conservado tal cual
en vez de corregido en silencio. Validado con datos reales de M31.
Siguiente en el orden fijo del usuario: **Photometry**.
