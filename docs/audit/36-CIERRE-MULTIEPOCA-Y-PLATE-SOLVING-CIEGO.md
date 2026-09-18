# 36 — Cierre P0: multiépoca real en Discovery + plate solving ciego

## 1. Objetivo

Continuación directa de la fase de cierre iniciada en `cacac21` (P0.1:
`artifact_screen`, `physics/observables`, `physics/constraints`,
`anomaly/vector`, `evidence/chain_builder`). Tres piezas, en orden:

1. **P0.2** — agrupación multiépoca real (`discovery/source_tracks.py`)
   y motor de movimiento (`temporal/motion.py`).
2. **P0.3** — cablear TODO lo anterior en `discovery/pipeline.py`, que
   hasta este punto seguía produciendo un `Candidate` por detección
   cruda por imagen, nunca por fuente física real.
3. **Plate solving ciego** (`astrometry/blind_solve.py`) — la petición
   explícita del usuario: resolver WCS sin ninguna coordenada previa,
   "como hacen todos los programas".

## 2. P0.2 — `source_tracks.py` + `motion.py`

`group_detections_into_tracks` agrupa detecciones de varias épocas en
una `SourceTrack` por coordenadas celestes reales (nunca por píxel: el
dithering entre tomas mueve la misma fuente a píxeles distintos). Sin
WCS, se declara explícitamente en vez de emparejar por píxel.

`analyze_motion` ajusta una trayectoria lineal real por mínimos
cuadrados usando el tiempo real de cada época (`DATE-OBS`), no la resta
ingenua primera-menos-última. La incertidumbre sale del residuo real del
ajuste (o de un RMS de registro externo con menos de 3 épocas).

**Caso límite encontrado y corregido durante la verificación**: una
trayectoria perfectamente lineal (exactamente lo que hace un asteroide
real en un intervalo corto) da residuo de ajuste EXACTAMENTE cero. La
primera versión interpretaba eso como "no se mueve" — error científico:
significa que no hay forma de estimar la incertidumbre sin una
referencia externa, no que el objeto esté quieto. Corregido: se reporta
el desplazamiento medido sin inventar una barra de error,
`moving_source_candidate` queda en `False` por "significancia no
demostrable" (explícito en las notas), y con un RMS de registro real
aportado, la significancia SÍ se calcula.

## 3. P0.3 — cablear todo en `discovery/pipeline.py`

Reestructurado `run_generic_discovery` en tres fases:

1. **Por imagen**: demosaico → WCS → detección → filtro morfológico
   barato (solo descarta lo más extremo: elongación ≥ 8, área ≤ 2 px) →
   caracterización real → estadística de campo
   (`compute_field_statistics`) → cribado REAL de artefactos
   (`artifacts/artifact_screen.screen_detection`, con los 7 detectores
   reales: saturación, ruido, traza, píxel caliente, rayo cósmico y PSF
   defectuosa contra la PSF del campo, error de registro en multiépoca).
   Este cribado es ahora el gate autoritativo antes de Candidate — el
   filtro morfológico barato nunca rechaza algo que el cribado real
   habría aceptado.
2. **Entre imágenes**: agrupación multiépoca POR BANDA (bandas distintas
   de la misma toma, p. ej. Hα y OIII, nunca se funden en una traza: no
   son épocas de lo mismo).
3. **Por traza física**: variabilidad (`temporal/variability`, usando
   `peak_adu`/`noise_adu` como proxy instrumental de brillo — NO es
   flujo calibrado, la fotometría de apertura/PSF todavía no está
   conectada a `Characterization`, ver §6) + movimiento
   (`temporal/motion`) cuando hay ≥ 2 épocas, identificación una sola
   vez sobre la época de referencia, `AnomalyVector`, `EvidenceChain`, y
   UN candidato (antes: uno por época).

`Candidate` gana el campo `evidence_chain` (con roundtrip probado).
`identification_state` alcanza ahora `MOVING_SOURCE_CANDIDATE`/
`TRANSIENT_CANDIDATE`/`KNOWN_VARIANT` cuando el motor correspondiente
concluye algo real — antes solo `KNOWN`/`UNMATCHED`/`DISCOVERY_REVIEW`
eran alcanzables en producción. `ANOMALOUS` y la tensión física quedan
`NOT_AVAILABLE` de forma honesta en el modo genérico: requieren
calibración fotométrica (flujo esperado por banda) y distancia/velocidad
que Discovery genérico no tiene de dónde sacar por fuente — no se fuerza
su activación sin datos reales.

### 3.1. Bug real encontrado ejecutando el pipeline multiépoca de verdad

`detect_point_sources()` etiquetaba cada detección con un
`detection_id` de componente conexa LOCAL a su imagen (`det_id`, que se
reinicia en cada llamada). Dos imágenes de la misma `Observation` con el
mismo número de fuentes producían `detection_id` idénticos. Invisible
antes (cada detección se convertía en `Candidate` al vuelo, sin
indexarse); en cuanto P0.3 empezó a indexar por `detection_id` para
reconstruir el `Candidate` tras agrupar por traza, la segunda imagen
sobrescribía en silencio a la primera. Corregido con un parámetro
`image_index` opcional que hace el id único en toda la `Observation`
(retrocompatible: sin él, se conserva el formato anterior). Dos tests de
regresión reproducen la colisión y confirman la corrección
(`tests/unit/detection/test_point_sources.py`).

### 3.2. Verificación de extremo a extremo

**Sintética** (`tests/integration/test_generic_discovery_pipeline.py::
test_run_generic_discovery_groups_multi_epoch_detections_into_one_candidate_per_physical_source`):
3 imágenes con WCS + `DATE-OBS` reales, una fuente fija y otra que se
desplaza 1 px/época. De 6 detecciones crudas salen exactamente 2
candidatos. La fija NO se declara en movimiento (jitter de centroide
real, 1.24σ); la que se mueve sí (529σ), con `MotionEvidence` y
`EvidenceChain` reales adjuntos.

**Real** — ejecutado sobre los 3 lights reales de M 31 del usuario (OSC,
Bayer RGGB, WCS real):

| magnitud | valor |
|---|---|
| detecciones crudas (3 épocas) | 1320 |
| rechazadas por artefacto real | 144 |
| **candidatos (trazas físicas)** | **583** |
| trazas con las 3 épocas | 215 |
| trazas con 2 épocas | 163 |
| trazas de 1 época | 205 |
| candidatos `MOVING_SOURCE_CANDIDATE` | 1 (7.62σ) |
| tiempo total | 7.5 s |

Sin agrupar, el resultado habría sido ~1176 candidatos (uno por
detección superviviente al cribado) — la deduplicación 3x que
`source_tracks.py` documentaba como el problema a resolver queda
confirmada con datos reales, no simulados.

Las 11 pruebas de integración preexistentes (imagen única, dos bandas,
plate solving con puntero, debayering, WCS ya presente) pasan sin
modificar — la reestructuración es un no-op de comportamiento para
observaciones de una sola época, como debía ser.

## 4. Plate solving ciego (`astrometry/blind_solve.py`)

`plate_solve.solve_plate` (Fase 27) siempre requirió un puntero
aproximado (header o SIMBAD). El usuario pidió explícitamente lo
contrario: "se tiene que poder hacer, todos los programas pueden".

### 4.1. Cómo funciona (mismo principio que astrometry.net/ASTAP)

1. **Código invariante de 4 estrellas**: para 4 puntos cualesquiera, se
   toma el par más separado (A, B) como referencia de un marco local
   (rotación + escala + traslación que lleva A al origen y B a (1, 0));
   los otros dos puntos, expresados en ese marco, dan 4 números
   invariantes a la orientación/escala/posición original — solo
   dependen de la FORMA del grupo. El orden C/D se canonicaliza (`Cx <=
   Dx`) y se prueban las dos asignaciones posibles de A/B, quedándose
   con el código lexicográficamente menor — así el mismo grupo físico
   da siempre el mismo código sin importar en qué orden llegaron los
   puntos ni quién los detectó primero.
2. **Índice de asterismos** del catálogo de referencia disponible
   (`catalogs/local_cache.CatalogCache.all_rows()`, método nuevo: TODO
   lo descargado, sin importar la posición) — un asterismo por estrella
   (ella + sus 3 vecinas más próximas, proyectadas al plano tangente
   local centrado en ella misma).
3. **Mismo índice sobre las estrellas detectadas** en la imagen,
   directamente en píxeles (ya euclídeos, sin proyección).
4. **Emparejamiento** por vecino más cercano en el espacio de códigos
   (KD-tree). Cada coincidencia da 4 correspondencias
   (píxel, cielo) directas, sin ambigüedad de orden.
5. **Semilla + verificación real**: cada candidato se reduce a un
   puntero/escala semilla vía `fit_wcs` (ya probado) sobre esos 4
   puntos, y esa semilla se entrega ÍNTEGRA a `plate_solve.solve_plate`
   — la misma rejilla de rotación, ajuste robusto sigma-clip y
   validación de RMS/mínimo de estrellas que protege la resolución con
   puntero. Un asterismo falso casi nunca sobrevive esa segunda pasada.

### 4.2. Por qué esto no es "inventar" una solución

Sigue haciendo falta un catálogo de referencia real — normalmente la
caché local ya descargada. Sin ninguna descarga previa, se declara
explícitamente ("sin catálogo de referencia local disponible") y no se
intenta nada — nunca golpea Gaia a ciegas sobre "todo el cielo" (miles
de consultas sin límite razonable).

### 4.3. Integración en Discovery

`_ensure_wcs` ahora, cuando no hay WCS: intenta el camino con puntero
(header/SIMBAD) si hay uno disponible; si falla o no hay ninguno,
intenta resolución ciega contra la caché local (`WCS_STATE_BLIND_
RESOLVED`, nuevo, distinto de `WCS_STATE_AUTO_RESOLVED` para que quede
claro en la GUI de dónde vino el WCS); solo si ambos fallan, se declara
`WCS_STATE_SOLVE_FAILED` con el motivo de los dos intentos. La barra de
estado de `qt_app/main_window.py` distingue ahora "resuelto con
puntero" de "resuelto en ciego".

### 4.4. Verificación

Sintética, catálogo de referencia disperso en un campo bastante más
amplio (400 estrellas en ~0.6°×0.6°) que el campo de la imagen
(512×512 px a 1.2"/px ≈ 0.17°×0.17°, ~24 estrellas reales en común):
recuperado el CRVAL real a **0.002"**, la rotación real a **0.001°**,
RMS del ajuste final **0.038"**, con 24/24 estrellas emparejadas. Test
de **no-falso-positivo** dedicado: con un catálogo de una zona del cielo
sin relación real con la imagen, el resolutor falla honestamente (no
produce ninguna solución) — la comprobación que de verdad importa contra
la epistemia prohibida por el encargo ("resultados inventados").

Sobre los `dbxtract_OIII.fit`/`dbxtract_HA_registered.fit` reales del
usuario (sin RA/DEC, sin OBJCTRA/OBJCTDEC, sin WCS, sin nombre de objeto
en el header — el caso "sin coordenadas" real, no hipotético):
`detect_point_sources_in_array` encuentra 77 y 104 fuentes puntuales
reales respectivamente, así que el resolutor ciego SÍ tiene con qué
trabajar en cuanto haya un catálogo de referencia real disponible (Gaia
en vivo o una descarga previa a la caché local) — no se pudo verificar
el resultado final sobre estos dos archivos concretos en este entorno
por no tener acceso de red real a Gaia, la misma limitación que ya
afecta a cualquier función de este proyecto que consulte Gaia aquí.

## 5. Brecha de tests cerrada de paso

Al retomar el trabajo se encontró que `cacac21` (P0.1) había añadido 6
módulos nuevos (1107 líneas: `artifact_screen.py`,
`physics/observables.py`, `physics/constraints.py`, `anomaly/vector.py`,
`evidence/chain_builder.py`, extensión de `photometry/quality.py`) sin
ningún test propio. Cerrada con 57 tests nuevos sobre comportamiento
real; de paso se encontró que el z-score correcto para una edad
autoconsistente en `physics/constraints.py` es `None` (incertidumbre no
computable), no `0.0` como se había asumido al escribir el primer
intento del test.

## 6. Qué queda (no incluido en esta ronda)

- **Fotometría real en Characterization**: `band_flux`/`band_ratios`
  siguen vacíos en la ruta de producción genérica — `AnomalyVector`
  fotométrico/espectral y `ANOMALOUS` no son alcanzables sin conectar
  `photometry/aperture.py`/`photometry/psf.py` a `characterize_point_
  source`. El proxy `peak_adu` para variabilidad (§3) es un paso
  intermedio honesto, no un sustituto.
- **Anomalía espacial por población** (§13 del encargo original): sin
  motor conectado, la dimensión `spatial` de `AnomalyVector` sigue
  `NOT_AVAILABLE` en toda la ruta de producción.
- **Provenance en `MotionEvidence`/`TemporalEvidence`**: ninguno de los
  dos modelos tiene todavía un campo de procedencia estructurado; el
  método/notas de cada `Quantity` cubre parcialmente ese hueco pero no
  es lo mismo.
- **`anomaly/physical_tension.py`**: motor anterior (con soporte de
  comparación contra referencia externa) que ya NO se invoca desde
  producción — `anomaly/vector.py` usa `physics/constraints.py`, no
  este módulo. Candidato a eliminar o a fusionar su capacidad de
  referencia externa en `physics/constraints.py`.
- **P2 completo**: espectroscopía y calibración de flujo conectadas al
  Discovery Engine, contratos de resultado compartidos, IA (modelo real
  con procedencia o `NOT_AVAILABLE` explícito).
- El informe final de dos tablas (motor↔implementación↔conexión↔test y
  función real no conectada) que pedía el encargo de cierre, cubriendo
  los 21 motores -- este documento cubre solo lo tocado en esta ronda.

## 7. Suites

`tests/unit/discovery/test_source_tracks.py` (8), `tests/unit/temporal/
test_motion.py` (8), `tests/unit/artifacts/test_artifact_screen.py`
(17), `tests/unit/physics/test_observables.py` (9), `tests/unit/physics/
test_constraints.py` (6), `tests/unit/anomaly/test_vector.py` (12),
`tests/unit/evidence/test_chain_builder.py` (11), `tests/unit/
astrometry/test_blind_solve.py` (11), `tests/unit/catalogs/
test_local_cache.py` (+4 sobre `all_rows`), `tests/unit/detection/
test_point_sources.py` (+2, colisión de `detection_id`), `tests/unit/
photometry/test_quality.py` (+2), `tests/unit/models/test_candidate.py`
(+2, `evidence_chain`), más las pruebas de integración de extremo a
extremo ya citadas.

Suite completa: **573 passed, 36 skipped, 1 xfailed** (pytest, entorno
`aps-test`) + **102 passed** (smoke GUI, `aps-gui` bajo Xvfb) — sin
ninguna regresión sobre el estado anterior a esta ronda.
