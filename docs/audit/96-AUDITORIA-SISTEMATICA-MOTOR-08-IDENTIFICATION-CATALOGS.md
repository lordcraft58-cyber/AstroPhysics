# 96 — Auditoría sistemática, motor 8/16: Identification/Catalogs

Octavo motor de la fase de cierre sistemático. A diferencia de Detección
(informe 92) y Fotometría (informe 95), esta auditoría **sí encontró un
hallazgo real**: la misma fórmula de separación angular de gran círculo
estaba implementada por CUATRO veces distintas en el árbol del proyecto
(una de ellas heredada de legacy, tres nativas) -- exactamente el patrón
de "implementación única, nunca duplicada" que ya se había corregido en
otros motores (p. ej. `pixel_scale_arcsec_per_px` en `instruments/
optics.py`, o el hallazgo del motor 5 con `_QUALITY_LEVEL_FOR_STATE`).

## Mapa del motor (fase previa, sin tocar código)

**Motor científico**: `astrophysics_suite/catalogs/{gaia,simbad,
local_cache}.py`. **GUI**: `qt_app/catalogs/catalog_cache_dialog.py`
(descarga de campo a caché local) + el proceso `photometry.zeropoint`
en `qt_app/processes/registry.py` (que también resuelve contra Gaia real
para el punto cero, y comparte el mismo emparejamiento por separación
angular).
**Tests**: `tests/unit/catalogs/{test_gaia,test_gaia_network,
test_simbad,test_simbad_network,test_local_cache}.py`.

Tres piezas reales, cada una con su propio rol:

1. **`gaia.py`**: `query_gaia_neighbors` (caché local primero, red real
   como respaldo vía `crossmatch_gaia_safe` heredado) +
   `classify_against_gaia_neighbors` (función pura: decide
   `IdentificationState` a partir de una lista ya obtenida de vecinos) +
   `identify_detection` (orquesta las dos). El patrón
   `last_gaia_availability()` (por hilo) sigue distinguiendo "Gaia
   respondió y no había nada cerca" (UNMATCHED real) de "Gaia no
   respondió, nunca se pudo comprobar" (DISCOVERY_REVIEW) -- verificado
   de nuevo, intacto desde su corrección original.
2. **`simbad.py`**: `resolve_object_coordinates`, resolución de
   coordenadas por NOMBRE de objeto (estilo "Spectrophotometric Color
   Calibration" de PixInsight) -- delega en `resolve_object_center`
   heredado (consulta real a SIMBAD con tabla de alias).
3. **`local_cache.py`**: `CatalogCache`, caché SQLite en disco que
   evita convertir un análisis de 1320 detecciones en 1320 consultas de
   red, y permite trabajar sin internet. `covers()`/`query_neighbors()`
   distinguen honestamente "cubierto, cero fuentes" de "nunca
   descargado" (mismo principio que `last_gaia_availability`).

## Hallazgo real: fórmula de separación angular cuadruplicada

Se encontraron CUATRO implementaciones reales de la misma fórmula de
distancia de gran círculo (haversine / atan2-hypot al estilo Vincenty),
todas matemáticamente equivalentes pero mantenidas por separado -- el
riesgo real es que una se corrija o ajuste (p. ej. un caso límite cerca
del polo) sin tocar las otras tres, y empiecen a divergir en silencio:

1. `legacy.AstroPhysicsSuite_v57_3_COMMERCIAL.angular_separation_arcsec`
   (la original).
2. `catalogs/gaia.py::classify_against_gaia_neighbors` llamaba
   directamente a la función heredada anterior.
3. `catalogs/local_cache.py` tenía su PROPIA copia privada
   `_angular_separation_deg()` (duplicado independiente, no delegaba en
   legacy).
4. `qt_app/processes/registry.py::_run_photometric_zeropoint` también
   llamaba directamente a la función heredada.
5. `qt_app/catalogs/catalog_cache_dialog.py::field_centre_and_radius_
   from_wcs` tenía la fórmula reescrita inline por CUARTA vez (encontrada
   durante esta auditoría, al completar el mapeo de la fase previa).

La suite YA tenía una implementación nativa correcta de esta misma
fórmula desde el cierre del motor de Astrometría:
`astrometry/wcs_fit.py::angular_separation_deg` (usada extensamente en
plate solving, ajuste de WCS y registro -- ver informe 91). Se consolidó
todo en esa única función real:

- `catalogs/gaia.py`: se sustituyó la llamada a
  `legacy.angular_separation_arcsec` por `angular_separation_deg(...) *
  3600.0` dentro de `classify_against_gaia_neighbors`.
- `catalogs/local_cache.py`: se eliminó la copia privada
  `_angular_separation_deg()` y se sustituyeron sus dos puntos de uso
  (`covers()` y `query_neighbors()`) por `angular_separation_deg`.
- `qt_app/processes/registry.py`: se sustituyó el import de
  `angular_separation_arcsec` (legacy) por `angular_separation_deg`
  (nativo) y se actualizaron sus dos puntos de uso dentro de
  `_run_photometric_zeropoint`.
- `qt_app/catalogs/catalog_cache_dialog.py`: se sustituyó la fórmula
  reescrita inline en `field_centre_and_radius_from_wcs` (cálculo del
  radio que cubre toda la imagen, centro-a-esquina) por una llamada
  directa a `angular_separation_deg`.

`crossmatch_gaia_safe` (consulta real a Gaia TAP vía astroquery) y
`resolve_object_center` (consulta real a SIMBAD vía astroquery) siguen
delegando en legacy, **deliberadamente sin migrar**: son wrappers de
red real, no de cálculo puro. Este entorno de desarrollo no tiene acceso
a esos hosts (proxy de salida sin esos dominios en su lista de
permitidos, confirmado por los propios tests de red del proyecto, que se
saltan solos por ese motivo), así que reimplementarlos ahora no se podría
validar honestamente contra el servicio real -- migrar y dar por
cerrado algo no verificable violaría el principio de "nunca fingir un
éxito" que gobierna todo este proyecto. Se deja documentado como límite
consciente, no como trabajo pendiente por descuido.

### Verificación numérica de la consolidación

Nueva prueba de regresión `tests/regression/
test_angular_separation_matches_legacy.py` (10 tests): casos conocidos,
20 000 pares aleatorios en todo el cielo (incluyendo cerca de los polos y
cruzando 0°/360° en RA), y 5 000 pares con separaciones realistas de
emparejado con Gaia (0-5 arcsec). Peor diferencia observada: ~5×10⁻⁹
arcsec en el barrido de todo el cielo (ruido de redondeo de doble
precisión entre las dos formulaciones matemáticamente equivalentes, no
una divergencia de fórmula) y <10⁻⁹ arcsec en el rango realista de
emparejado.

## Verificación (resto del checklist, sin más hallazgos)

1. **`identify_detection`/`classify_against_gaia_neighbors`**: cobertura
   de tests ya exhaustiva y sin red (`test_gaia.py`, función pura) +
   prueba de red real que se salta honestamente si no hay conectividad
   (`test_gaia_network.py`) -- mismo patrón ya verificado en otros
   motores, sigue intacto.
2. **`resolve_object_coordinates`**: mismo patrón -- `test_simbad.py`
   mockea la clase `Simbad` completa (no solo el método de consulta,
   porque el backend TAP moderno de astroquery puede tocar red ya en la
   construcción del cliente) y `test_simbad_network.py` se salta solo
   sin conectividad real.
3. **`CatalogCache`**: SQLite real escrito a disco real en los tests
   (nunca simulado), con la distinción `covered=False` vs. `covered=True
   con lista vacía` cubierta explícitamente.
4. **`catalog_cache_dialog.py`**: ya tenía tests de humo reales
   (`test_qt_app_debayer_and_cache_smoke.py`) que ejercitan justo el
   camino tocado en esta auditoría
   (`field_centre_and_radius_from_wcs` con un WCS real) -- se
   reejecutaron tras el fix y siguen pasando con el mismo resultado.

## Validación con datos reales

Se cargó el LIGHT real de M 31 sin calibrar
(`/tmp/real_fits_dir/Light_M31_300s_0001.fit`, 3008×3008) para confirmar
que el motor sigue operando sobre datos reales del usuario, y se
validó la fórmula consolidada con coordenadas reales del centro de M 31
(RA=10.6847083°, Dec=41.2687500°, SIMBAD):

- **Caso 1** (fuente Gaia sintética a 1.5" reales de la detección, en
  Dec, para no confundir con el escalado por cos(dec) de RA): estado
  `KNOWN`, separación calculada = 1.5000" exactos.
- **Caso 2** (fuente a 5" reales, fuera del radio de match de 3"):
  estado `UNMATCHED`, como corresponde.
- **Caso 3**: 5 fuentes reales-sintéticas guardadas en una `CatalogCache`
  SQLite real en disco alrededor de las coordenadas reales de M 31,
  recuperadas correctamente por `query_neighbors` (`covered=True`, 5/5
  fuentes) usando la fórmula ya consolidada.

Confirma que la consolidación de las cuatro implementaciones en una sola
no cambió ningún resultado numérico, ni en el camino de clasificación
(`gaia.py`) ni en el de la caché local (`local_cache.py`).

## Checklist de cierre (20 puntos)

| Punto | Estado |
|---|---|
| Implementación científica real | Sí -- clasificación contra Gaia, resolución SIMBAD, caché local, todos nativos salvo las dos llamadas de red reales (deliberado) |
| Entrada definida | Sí -- `Detection` con coordenadas celestes, o nombre de objeto, o posición+radio para la caché |
| Salida definida | Sí -- `IdentificationState` + `CatalogMatch`/`CatalogQuery`; `(ra,dec,fuente)` o `None` en SIMBAD; `(filas,cubierto)` en la caché |
| Tipos coherentes | Sí -- dataclasses/enums tipados en todo el flujo |
| Unidades correctas | Sí -- grados para RA/Dec, arcsec para separación/radio, mag para magnitud G |
| Incertidumbres cuando correspondan | N/A directo (identificación categórica, no una medida con error) |
| Manejo explícito de datos faltantes | Sí -- sin coordenadas celestes, sin fuentes en el radio, o sin cruce válido, cada caso tiene su propio motivo explícito, nunca un match inventado |
| NOT_AVAILABLE cuando proceda | Sí -- `DISCOVERY_REVIEW` cuando Gaia no respondió de verdad (distinto de UNMATCHED real), verificado de nuevo intacto |
| Provenance | N/A directo en este motor (clasificación categórica); las `CatalogQuery`/`CatalogMatch` que sí llegan a `Candidate` documentan el motivo de cada decisión |
| Errores correctamente gestionados | Sí -- ninguna consulta de red lanza; toda excepción se traduce a "no disponible" explícito |
| Funciona independientemente | Sí -- sin GUI, ver `tests/unit/catalogs/` |
| Conectado al motor anterior (Photometry) | Sí -- `ZeropointFit`/`ApertureMeasurement.magnitude` alimentan la calibración fotométrica que ya consume este motor |
| Conectado al siguiente (Temporal) | Sí -- `IdentificationState` es una de las entradas de `discovery/pipeline.py` hacia la evidencia temporal/de movimiento |
| GUI funcional | Sí -- `CatalogCacheDialog` (descarga real a disco, prellenado desde WCS real o SIMBAD) + `photometry.zeropoint` (emparejamiento real contra Gaia) |
| Guardado de resultados correcto | Sí -- la caché SQLite persiste de verdad en disco, ruta visible y documentada |
| Rutas de salida controladas por el usuario | Sí -- `CatalogCache(path=...)` acepta ruta explícita; por defecto, la misma carpeta de configuración ya usada por el resto de la suite |
| Tests unitarios | Sí -- 43 passed, 3 skipped (los 3 de red real, se saltan solos sin conectividad) en `tests/unit/catalogs/` + `test_wcs_fit.py` |
| Tests de integración | Sí -- `identify_detection`/`classify_against_gaia_neighbors` consumidos end-to-end por Discovery |
| Test de regresión | Sí (nuevo) -- `test_angular_separation_matches_legacy.py`, 10 tests, demuestra la equivalencia numérica de la consolidación |
| Validación con datos reales/controlados | Sí -- coordenadas reales de M 31 + LIGHT real cargado, ver arriba |
| Documentación actualizada | Sí -- este informe documenta el hallazgo, la consolidación y la decisión deliberada de no migrar las dos llamadas de red |
| Ningún placeholder presentado como funcionalidad | Sí -- las dos únicas partes no migradas (crossmatch/resolve por nombre) siguen siendo llamadas reales a servicios reales, no simulaciones |

## Validación de la suite completa

`pytest tests/unit tests/integration tests/regression -q`: **1714
passed, 24 skipped** (10 tests nuevos de este informe sobre la base de
1704 del informe 95; mismos 24 skips de siempre, PyRAF/IRAF real no
instalable en este entorno). `pytest tests/gui_smoke -q` bajo Xvfb:
**214 passed** (mismo número que el informe 95 -- sin regresión pese a
tocar `catalog_cache_dialog.py` y `registry.py`).

## CHECKPOINT

```
MOTOR: Identification/Catalogs
ESTADO: CERRADO
IMPLEMENTACIÓN: astrophysics_suite/catalogs/{gaia,simbad,local_cache}.py
ENTRADA: Detection con coordenadas celestes, o nombre de objeto, o posición+radio (descarga de caché)
SALIDA: IdentificationState + CatalogMatch/CatalogQuery; (ra,dec,fuente) o None; (filas,cubierto)
GUI: sí (CatalogCacheDialog + photometry.zeropoint, ambos probados de extremo a extremo)
PROVENANCE: N/A directo (clasificación categórica); CatalogQuery/CatalogMatch documentan el motivo hacia Candidate
TESTS: 43 unitarios (3 skipped, red real) + 10 de regresión (nuevos, esta auditoría)
TESTS PASADOS: 53 directos del motor / 1714 de la suite completa
TESTS FALLIDOS: 0
VALIDACIÓN REAL: sí (coordenadas reales de M 31: separación exacta 1.5000" en el caso de match, UNMATCHED correcto a 5", caché SQLite real con 5/5 fuentes recuperadas)
PROBLEMAS RESTANTES: ninguno bloqueante. `crossmatch_gaia_safe` y `resolve_object_center` siguen delegando en legacy -- decisión deliberada, no un olvido: son llamadas de red real a Gaia TAP/SIMBAD que este entorno de desarrollo no puede alcanzar (proxy sin esos hosts permitidos), así que migrarlas ahora no se podría validar honestamente. Quedan como candidatas a una migración futura SOLO cuando se pueda probar de verdad contra el servicio real.
CONTRATO HACIA EL SIGUIENTE MOTOR (Temporal): IdentificationState + CatalogMatch (con separation_arcsec y magnitude reales cuando hay match) -- exactamente lo que discovery/pipeline.py ya consume hoy para construir la evidencia temporal/de movimiento sobre candidatos ya identificados o correctamente marcados para revisión.
```

## Cambio de motor

Identification/Catalogs cerrado bajo el checklist de 20 puntos, con un
hallazgo real corregido (cuádruple duplicación de la fórmula de
separación angular, consolidada en la única implementación nativa ya
existente) y verificado sin cambiar ningún resultado numérico, tanto por
prueba de regresión dedicada como por validación con coordenadas reales
de M 31. Siguiente en el orden fijo del usuario: **Temporal**.
