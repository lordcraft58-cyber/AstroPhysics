# 54 — Cierre de Detection

Cuarto motor de la lista del usuario, tras Astrometría/WCS (informe 53).
La auditoría encontró un solo hueco arquitectónico -- el motor entero
seguía viviendo en el monolito legado -- y migrarlo con rigor destapó un
**bug numérico real**, presente desde siempre, que ninguna comparación
sintética podía ver por sí sola.

## 1. El Detection Engine entero delegaba en el monolito legado

**El hueco**: `astrophysics_suite/detection/point_sources.py` era una
capa de traducción a `Detection`/`SkyPosition`/`MorphologySummary` (Fase
4) por encima de tres funciones importadas directamente de
`legacy.AstroPhysicsSuite_v57_3_COMMERCIAL`: `estimate_background`,
`detect_point_sources` (DAOStarFinder + reserva en Python puro) y
`enrich_star_rows` (métricas locales por fuente). El propio
`detection/__init__.py` lo declaraba: *"Delega el algoritmo de detección
... en el código heredado ya probado"*.

**Lo hecho**: tres módulos nuevos, con el mismo criterio que ya cerró
IO/FITS (informe 51):

- `astrophysics_suite/detection/background.py` -- `Background`,
  `estimate_background()`. `Background2D` de `photutils` como algoritmo
  primario (dependencia dura del producto, `photutils>=1.13` pinada en
  `requirements-app.txt`/`requirements-test.txt`), con una reserva en
  Python puro (mosaico + estadística robusta + interpolación de spline)
  para cuando `Background2D` falla en tiempo real sobre datos
  concretos -- no por ausencia del paquete, que aquí no es una
  posibilidad real.
- `astrophysics_suite/detection/finder.py` -- `find_point_sources()`
  (DAOStarFinder primario, con el mismo manejo de alias de columnas por
  versión que el original: `photutils >= 1.13` renombró
  `xcentroid`→`x_centroid`, verificado con la versión 3.0.0 realmente
  instalada) y `enrich_detections()` (momentos de segundo orden →
  `EnrichedSource`, una dataclass tipada en vez de los diccionarios de
  claves sueltas del original).
- `point_sources.py` pasa a importar solo de estos dos módulos. Cero
  referencias a `legacy` en todo el paquete `detection/`.

**Lo que autoriza el cambio**: `tests/regression/
test_detection_matches_legacy.py` compara ambas implementaciones campo a
campo -- fondo, RMS, fuentes detectadas, métricas por fuente -- incluidas
las dos ramas de reserva (sin `Background2D`, sin `DAOStarFinder`) que
la mayoría de ejecuciones nunca recorre. Diez pruebas, coincidencia
exacta salvo el punto 2.

## 2. La fórmula de FWHM de `enrich_star_rows` nunca fue un FWHM

Esto no salió de la auditoría de arquitectura: salió de validar el
motor migrado contra el LIGHT real de M 31 y encontrar que el 100% de
las 152 fuentes detectadas tenían un FWHM "estelar" de decenas de
píxeles (mediana 54 px = 56" -- una estrella del tamaño de la Luna
llena).

**La causa raíz**: `enrich_star_rows` calcula los autovalores `l1`, `l2`
de la matriz de momentos de segundo orden (varianzas, en px²) y luego:

```python
fwhm = 2.354820045 * math.sqrt(l1 * l2)          # legacy -- INCORRECTO
```

`l1 * l2` tiene unidades de **px⁴** (varianza al cuadrado), no px². Para
convertir a un FWHM real hace falta la RAÍZ CUARTA de `l1*l2` (la media
geométrica de `sqrt(l1)` y `sqrt(l2)`, cada una ya en píxeles), no la
raíz cuadrada:

```python
fwhm = 2.354820045 * math.sqrt(math.sqrt(l1 * l2))   # corregido
```

La prueba de que esto es real, no una preferencia de estilo: el
**mismo archivo legacy** ya tenía la fórmula CORRECTA escrita en otro
sitio -- el filtro de forma interno del propio detector de reserva
(`_detect_point_sources_legacy`, ahora `_find_point_sources_fallback`)
calcula `fwhm_major = 2.3548*sqrt(l1)` y `fwhm_minor = 2.3548*sqrt(l2)`
por separado, correctamente. El error estaba solo en el paso de
enriquecimiento que se reporta después -- una inconsistencia interna del
propio código original, no una interpretación distinta.

**Verificado con una gaussiana sintética de sigma REALMENTE conocido**
(`test_enrich_detections_fwhm_matches_a_known_sigma_gaussian`):

| sigma real | FWHM teórico (2.3548·σ) | FWHM legacy medido | ratio |
|---|---|---|---|
| 1.5 px | 3.53 px | 5.30 px | 1.50× |
| 2.0 px | 4.71 px | 9.42 px | 2.00× |
| 3.0 px | 7.06 px | 21.15 px | 2.99× |
| 4.0 px | 9.42 px | 36.30 px | 3.85× |

La inflación **crece con el propio tamaño real de la fuente** -- no es
un offset fijo que un usuario pudiera restar mentalmente. Con la fórmula
corregida, el FWHM medido coincide con el teórico dentro del 5% en los
cuatro casos.

**Impacto real, corriente abajo** (por qué esto merecía arreglarse, no
solo documentarse):

- `Detection.morphology.fwhm_px` y `.area_px` (`point_sources.py`) se
  calculan a partir de este valor -- todo consumidor de `Detection`
  heredaba la inflación.
- `artifacts/artifact_screen.py` usa `fwhm`/`median_fwhm_px` para
  distinguir un píxel caliente (FWHM casi nulo) de una PSF estelar real,
  y una fuente "más afilada que la PSF" como posible rayo cósmico -- con
  la inflación creciendo con el tamaño real, la comparación relativa
  quedaba sistemáticamente distorsionada.
- `physics/observables.py` multiplica `fwhm_px * pixel_scale_arcsec`
  para reportar un tamaño angular -- un valor directamente expuesto,
  ahora honesto.

`photometry/psf.py` (fotometría PSF) **no** se ve afectado: calcula su
propio FWHM de forma independiente, como ya declaraba su propio
docstring (*"momentos 2D reales, independiente de `enrich_star_rows`"*),
confirmado por auditoría (ninguna referencia cruzada).

**Divergencia deliberada de legacy, documentada donde corresponde**:
igual que el informe 51 documentó explícitamente sus dos diferencias
frente al lector legacy, este informe documenta esta única diferencia.
El propio test de paridad (`test_enrich_detections_matches_legacy_row_by_row`)
no compara `fwhm_px` por igualdad -- demuestra la relación exacta
`fwhm_corregido = 2.3548·sqrt(fwhm_legacy / 2.3548)`, es decir: "es la
misma fórmula, con la raíz que faltaba", no un valor inventado.
`sharpness_index` y `quality` (que dependen de `fwhm_px` para sus radios
de apertura y su umbral de borde) tampoco se comparan por igualdad, por
la misma razón.

## Validación con datos reales

LIGHT de M 31 (300 s, ASI533MC Pro, 3008×3008, sin bias/dark/flat -- el
mismo conjunto de motores anteriores), `fwhm_px=3.0, threshold_sigma=5.0`:

| Comprobación | Antes del arreglo | Después |
|---|---|---|
| Fondo (bkg/rms) migrado vs. legacy | idéntico | idéntico |
| Fuentes detectadas (posición/flujo) | idéntico (152) | idéntico (152) |
| FWHM mediana de las fuentes | 54.3 px (56.2") | 15.2 px (15.7") |
| Fuentes con FWHM < 8 px | 0 de 152 | 8 de 45 (parámetros por defecto) |

El residuo por encima del FWHM ideal (seeing-limited, un par de
píxeles a esta escala) es coherente con estar analizando un LIGHT
**crudo, sin reducir** -- sin bias/dark/flat, sin corrección de cielo:
exactamente el trabajo de los motores 1-2 (IO/FITS, Reduction) ya
cerrados, no de Detection. Repitiendo la misma detección sobre el mismo
LIGHT tras `reduction.sky.fit_sky_background` (aplanado de cielo real),
la mediana baja más, a 12.0 px -- en la dirección correcta. Separar qué
de esas fuentes son estrellas reales y qué son artefactos o núcleo de
M 31 es precisamente el trabajo de los motores siguientes en el orden
del usuario (Artefactos, Caracterización), no de este.

## Checklist del motor

| Fase | Estado |
|---|---|
| IMPLEMENTACIÓN | `detection/background.py` + `detection/finder.py`, sin legacy |
| CONTRATO | `Background`, `EnrichedSource` (dataclasses tipadas, ya no dicts) |
| GUI | sin diálogo propio -- motor de backend consumido por Discovery y por "detectar automáticamente" en fotometría/PSF (sin cambios de contrato externo) |
| SALIDA | `Detection` (Fase 4), sin cambios de forma; `fwhm_px`/`area_px` ahora correctos |
| PROVENANCE | `detect_point_sources()` sigue adjuntando `Provenance` real (motor/versión) |
| UNIT TEST | `tests/unit/detection/test_point_sources.py` (6, ya existentes, todos verdes) |
| REGRESSION TEST | `tests/regression/test_detection_matches_legacy.py` (10, nuevas) |
| FITS REAL | LIGHT de M 31 -- ver tabla arriba |
| CERRADO | sí |

Suite completa tras el cierre: **767 pasadas, 24 saltadas, 1 xfailed**
(`aps-test`, +10 sobre el cierre anterior) y **149 pasadas** de humo GUI
(`aps-gui`, sin cambios: Detection no tiene diálogo propio). `ruff`
limpio.

## Lo que sigue abierto en este motor

- **Ningún consumidor pasaba `input_hashes`** a la `Provenance` de
  `detect_point_sources()` -- mismo hueco ya anotado en los informes 52
  y 53, no específico de este motor.
- **La clasificación `quality` ("ok"/"edge"/"low_snr"/"saturated")**
  sigue siendo un diagnóstico LOCAL por fuente, no un veredicto de
  "es una estrella real" -- eso es, deliberadamente, el trabajo del
  motor de Artefactos (siguiente en el orden del usuario).
