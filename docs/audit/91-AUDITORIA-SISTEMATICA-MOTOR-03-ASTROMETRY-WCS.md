# 91 — Auditoría sistemática, motor 3/16: Astrometry/WCS

Tercer motor de la fase de cierre sistemático. Astrometry/WCS ya se había
cerrado formalmente (Fase 9.4/13, plate solving con/sin puntero, WCS
desde óptica) y es, de los tres motores auditados hasta ahora, el más
maduro: cada archivo trae hallazgos reales documentados en el propio
código (`strip_wcs_keywords` contra un SIP heredado, `rescale_wcs_for_binning`
contra un error de 14' con `wcs[::2,::2]`, `MIN_STARS_FOR_MEANINGFUL_RMS`
medido con 400 ajustes reales). Aun así, la auditoría contra el checklist
de 20 puntos encontró un hueco real: dos de los seis flujos del menú
Astrometría nunca ofrecían guardar su resultado.

## Mapa del motor (fase previa, sin tocar código)

**Motor científico**: `astrophysics_suite/astrometry/{wcs_fit,plate_solve,
blind_solve,optical_wcs,registration,provenance,pyraf_backend}.py`.
**GUI**: `qt_app/astrometry/{wcs_fit_dialog,plate_solve_dialog,
blind_solve_dialog,optical_wcs_dialog,registration_dialog,
star_pair_registration_dialog}.py`, seis entradas en el menú
"Astrometría" de `main_window.py`.
**Registro de procesos genérico**: ninguna entrada de astrometría vive
ahí -- decisión deliberada y ya documentada (cada flujo necesita estado
propio: puntos marcados a clic, dos ventanas a la vez, consulta SIMBAD),
no un hueco.
**Tests (antes de este informe)**: `tests/unit/astrometry/` -- 7
archivos, 77 tests (3 solo con pyraf real, que no está disponible en
este entorno). GUI: `test_qt_app_astrometry_smoke.py`,
`test_qt_app_plate_solve_smoke.py`, `test_qt_app_blind_plate_solve_smoke.py`,
`test_qt_app_optical_wcs_smoke.py`, `test_qt_app_star_pair_registration_smoke.py`,
`test_qt_app_wcs_fits_copy_smoke.py` (33 tests en total).

Se leyeron los siete archivos del motor científico completos, los seis
diálogos GUI completos, y se verificó con `grep` cada conexión de señal
en `main_window.py` entre un diálogo y su manejador real.

## Hallazgo y cierre

### Dos de los seis flujos nunca ofrecían guardar su resultado

De los seis flujos del menú Astrometría, **cuatro** (resolución
automática con puntero, resolución en ciego, ajuste manual a clic, WCS
desde óptica) ya ofrecían guardar una copia FITS con el WCS y su
procedencia real desde que se cablearon (`_offer_to_save_wcs_fits_copy`,
informes 44-46 y 52-54). Los otros **dos** -- "Registrar por WCS
compartido..." (`RegistrationDialog`, reproyección real vía
`registration.reproject_to_reference`) y "Registrar por pares de
estrellas..." (transformación afín real vía `fit_affine_transform`/
`apply_affine_transform`) -- terminaban siempre en
`main_window.add_image_window(...)` y nada más: el resultado, real y
correcto, vivía solo en una ventana MDI en memoria, exactamente el mismo
patrón de hueco que el informe 90 cerró para "Aplicar calibración..." en
Reducción.

**Corregido**, con procedencia propia para lo que un registro puede
declarar honestamente (no es un ajuste de WCS ni una calibración de
píxeles, así que reutilizar `WCSRecord`/`ReductionRecord` habría sido
forzarlo):

- `astrometry/provenance.py` gana `RegistrationRecord`/
  `build_registration_provenance`/`registration_header_cards` -- mismo
  patrón que `WCSRecord`/`wcs_header_cards`. Para "WCS compartido", el
  WCS de la REFERENCIA se escribe como real en el archivo de salida (no
  es un WCS inventado ni reajustado: tras reproyectar sobre su rejilla,
  ese WCS describe correctamente los píxeles resultantes). Para "pares
  de estrellas" (donde ninguna de las dos imágenes tiene WCS, por
  diseño) no se escribe ningún `CRVAL`/`CD` -- solo el RMS y el modelo
  reales del ajuste afín.
- `RegistrationDialog.computed` pasa de emitir `(datos, título)` a un
  `RegistrationOutcome` real (datos + título + `RegistrationRecord` con
  el WCS de la referencia).
- `main_window._on_registration_computed`/`_on_star_pair_registration_done`
  siguen abriendo la ventana MDI (nada roto) y además llaman a
  `_offer_to_save_registration_fits`: procedencia real, sha256 real de
  referencia/destino cuando sus `source_path` siguen existiendo
  (degradación honesta si no, mismo criterio que el resto del proyecto),
  pregunta y guarda con `QFileDialog`.

Cinco tests nuevos: 3 unitarios (`registration_header_cards` con WCS
heredado real / con solo RMS afín / hashes reales) y 2 de humo GUI (uno
por flujo, guardado real con provenance verificada en el archivo),
además de actualizar los tests existentes que usaban la firma antigua de
`computed` y añadir el `monkeypatch` que ya usan el resto de flujos de
guardado para no bloquear un test que no pretendía probar el guardado.

## Validación con datos reales

Script de validación (no sintético) contra los dos extractos narrowband
reales de M31 del usuario (`dbxtract_HA_registered.fit`/
`dbxtract_OIII.fit`, 2560x2648 float32, ninguno con WCS -- exactamente el
caso de uso real que "Registrar por pares de estrellas..." cubre, el
mismo flujo de combinación Hα/OIII que documenta el módulo): fuentes
reales detectadas en ambos frames (`detect_point_sources_in_array`),
emparejadas por proximidad, ajuste afín real (RMS=4.22 px con 5 pares),
remuestreo real, guardado con procedencia real (sha256 real de ambos
archivos de entrada, RMS/modelo del ajuste) y recarga verificada byte a
byte. Confirma que el fix funciona sobre datos reales de M31, no solo
sobre arrays sintéticos de prueba.

## Qué queda fuera, documentado (no bloquea el cierre)

- **PyRAF/IRAF** (`astrometry/pyraf_backend.py`): mismo tratamiento que
  en Reduction -- backend opcional, correctamente documentado como no
  verificable en este entorno, nunca conectado a la GUI. No se toca.
- **`registration.fit_affine_transform(model="similarity")`**: rama
  real y ya testeada (`tests/unit/astrometry/test_registration.py`),
  pero la GUI (`StarPairConfigDialog`) solo ofrece elegir entre "affine"
  y "similarity" -- ambos casos SÍ están cableados y probados de extremo
  a extremo (el combo ya existía). No es un hueco: se menciona aquí solo
  porque la validación con datos reales de este informe usó "affine".

## Checklist de cierre (20 puntos)

| Punto | Estado |
|---|---|
| Implementación científica real | Sí -- ajuste TAN lineal, plate solving con/sin puntero, WCS desde óptica, registro por WCS/afín, todo propio |
| Entrada definida | Sí -- pares píxel/cielo, imagen+cabecera, o dos `ImageView` con WCS/puntos marcados |
| Salida definida | Sí -- `WCSSolution`/`PlateSolveResult`/`RegistrationOutcome`/`AffineTransform` |
| Tipos coherentes | Sí -- dataclasses tipadas en todo el flujo |
| Unidades correctas | Sí -- grados, arcsec/px, px, consistente en todo el motor |
| Incertidumbres cuando correspondan | Sí -- RMS real por estrella/par en cada ajuste, nunca inventado (WCS óptico declara n_stars=0 explícitamente) |
| Manejo explícito de datos faltantes | Sí -- sin puntero/escala aproximada, `solve_plate` falla con motivo explícito, nunca adivina |
| NOT_AVAILABLE cuando proceda | Sí -- hash de una imagen sin `source_path` real se omite, nunca se inventa |
| Provenance | Sí -- `WCSRecord`/`RegistrationRecord` en los SEIS flujos que guardan a disco (antes solo en cuatro) |
| Errores correctamente gestionados | Sí -- motivos de fallo específicos y accionables en cada resolución, nunca "Error" a secas |
| Funciona independientemente | Sí -- sin GUI, ver `tests/unit/astrometry/` |
| Conectado al motor anterior (Reduction) | Sí -- consume la imagen calibrada real (con o sin recorte, WCS de origen ya eliminado si hubo recorte) |
| Conectado al siguiente (Detection) | Sí -- el WCS resultante alimenta `ImageView.wcs`/`view.fitted_wcs_solution`, ya consumido por fotometría/catálogos |
| GUI funcional | Sí -- seis entradas de menú reales, las seis conectadas a un backend real, ninguna huérfana |
| Guardado de resultados correcto | Sí -- los SEIS flujos escriben a disco tras este informe (antes solo cuatro) |
| Rutas de salida controladas por el usuario | Sí -- `QFileDialog` nativo en los seis |
| Tests unitarios | Sí -- 80 (77 + 3 nuevos) en `tests/unit/astrometry/` |
| Tests de integración | Sí -- consumido end-to-end por Detección/Fotometría/Catálogos (motores posteriores) |
| Test de regresión | N/A directo (sin lector legacy de astrometría que comparar); cubierto por el resto de la suite (1691 passed) |
| Validación con datos reales/controlados | Sí -- Ha/OIII reales de M31, ver arriba |
| Documentación actualizada | Sí -- este informe + comentarios nuevos en el código explicando el hallazgo |
| Ningún placeholder presentado como funcionalidad | Sí -- confirmado, sin excepciones |

## Validación de la suite completa

- `ruff check astrophysics_suite qt_app tests`: limpio.
- Unitaria + integración + regresión: **1691 passed**, 24 skipped (sin
  regresión respecto al informe 90).
- Humo GUI completa: **214 passed** (antes: 212 -- los 2 tests nuevos de
  humo GUI de este informe).

## CHECKPOINT

```
MOTOR: Astrometry/WCS
ESTADO: CERRADO
IMPLEMENTACIÓN: astrophysics_suite/astrometry/{wcs_fit,plate_solve,blind_solve,optical_wcs,registration,provenance}.py
ENTRADA: pares píxel/cielo, imagen+cabecera FITS real, o dos ImageView con WCS/puntos marcados
SALIDA: WCSSolution / PlateSolveResult / RegistrationOutcome / AffineTransform, con RMS/procedencia real
GUI: sí (6 entradas de menú: WCS a clic, resolución con puntero, resolución ciega, WCS desde óptica, registro por WCS compartido, registro por pares -- las 6 conectadas a un backend real)
PROVENANCE: sí (WCSRecord/RegistrationRecord, ahora en los 6 flujos que guardan a disco)
TESTS: 80 unitarios + 35 humo GUI de astrometría (33 previos + 2 nuevos) = 115 tests directamente del motor
TESTS PASADOS: 115 (1691 unit/integración/regresión + 214 humo GUI en conjunto, sin fallos)
TESTS FALLIDOS: 0
VALIDACIÓN REAL: sí (dos extractos narrowband reales de M31, Hα/OIII, registro afín real con RMS=4.22 px, guardado con procedencia y sha256 reales, recargado y verificado)
PROBLEMAS RESTANTES: ninguno bloqueante. Documentado y fuera de alcance: PyRAF/IRAF sigue LIMITADO (correcto, no verificable en este entorno).
CONTRATO HACIA EL SIGUIENTE MOTOR (Detection): ImageView.wcs (astropy.wcs.WCS real, o None si no se resolvió) + view.fitted_wcs_solution (WCSSolution propio, para reproyección/registro posteriores) -- exactamente lo que detection/point_sources.py y los procesos de fotometría ya consumen hoy.
```

## Cambio de motor

Astrometry/WCS re-auditado y cerrado bajo el checklist de 20 puntos, con
un hallazgo real corregido en ambos flujos de registro, testeado y
validado con datos reales de M31. Siguiente en el orden fijo del
usuario: **Detection**.
