# AstroPhysics Suite — Fase 6 (Slice 1): Primera Extracción Real

Continuación de `06-FASE5-TESTS-DE-REGRESION.md`. La Fase 6 completa ("extraer los motores de `analyze_pair_core`/`launch_gui` hacia los paquetes objetivo, función por función") es, con diferencia, la fase más grande del plan -- realistamente abarca muchas iteraciones futuras, no una sola sesión. Este documento cubre deliberadamente **un primer corte vertical delgado**: `io/` (carga real de imágenes) y `detection/` (detección de fuentes puntuales), de extremo a extremo, con tests reales. Es la plantilla que las siguientes extracciones (astrometría, fotometría, física, anomalías, ...) deben seguir -- no un intento de mover todo el monolito de golpe, que el propio plan (`02-...`, sección 5) prohíbe explícitamente ("nunca big bang").

## 1. Patrón de migración: strangler fig, no reescritura

`astrophysics_suite/io/fits_loader.py` y `astrophysics_suite/detection/point_sources.py` **delegan el algoritmo** en el código heredado ya probado (`load_fits`, `sha256_file`, `estimate_background`, `detect_point_sources`, `enrich_star_rows`) y añaden únicamente la traducción a los contratos tipados de la Fase 4. No se reimplementó la lectura de FITS ni DAOStarFinder desde cero.

Esto es intencional, no un atajo: reimplementar el manejo de cubos 3D/4D, WCS, memmap y las heurísticas de photutils desde cero, en una sesión, sin el corpus de casos reales que ya cubre el código heredado, habría sido el tipo exacto de riesgo que la auditoría (Fase 1) pide evitar -- y además habría vuelto a crear dos implementaciones paralelas del mismo algoritmo, el problema central que toda esta reingeniería existe para resolver (Fase 1, sección 6). El objetivo de esta fase es **dar a la lógica correcta un hogar con el contrato correcto**, no reescribir lo que ya funciona.

Para que esto sea posible de forma limpia, se añadió `legacy/__init__.py`, convirtiendo `legacy/` en un paquete Python importable normalmente (`from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import ...`) en vez de depender del truco de carga dinámica que usan los tests (`tests/conftest.py`, necesario porque el nombre de archivo con número de versión no es importable como módulo suelto). Es una dependencia de una sola dirección, documentada explícitamente en el docstring del paquete: `astrophysics_suite/` puede depender de `legacy/` durante la migración; nada fuera de `astrophysics_suite/` debería depender de `legacy/` a largo plazo, y esta dependencia se retira módulo a módulo según avanza la Fase 6.

## 2. `io/fits_loader.py`

```python
load_image(path, *, band, role="science") -> LoadedImage
build_observation(images: list[tuple[path, band]], *, observation_id, target_name, ...) -> (Observation, dict[path, LoadedImage])
```

`LoadedImage` lleva el `ImageRef` tipado (Fase 4) **y** el `FitsImage` heredado (`.data`, `.header`, `.wcs`, `.pixel_to_world`) como manija transicional explícita: motores todavía no migrados (como `detection/point_sources.py`, ver §3) necesitan los píxeles reales y el WCS, no solo la metadata. El propio docstring de `LoadedImage` advierte que ese campo no debe filtrarse a `models/` ni a ningún contrato de la Fase 4 -- es una herramienta de migración, no parte del esquema final.

`ImageRef.sha256`/`pixel_scale_arcsec`/`has_wcs` se rellenan con datos reales (`sha256_file`, `FitsImage.pixel_scale_arcsec`, `FitsImage.wcs is not None`), no con valores de relleno -- cerrando el hueco que la Fase 4 dejó explícito (los modelos existían, pero nada los construía todavía a partir de un archivo real).

## 3. `detection/point_sources.py`

```python
detect_point_sources(loaded_image: LoadedImage, *, observation_id, band, fwhm_px=3.0, threshold_sigma=5.0, max_sources=3000) -> list[Detection]
```

Encadena tres funciones heredadas ya probadas -- `estimate_background` → `detect_point_sources` (contrato Nx3 fijado en la Fase 3) → `enrich_star_rows` (FWHM/elipticidad reales por fuente, vía momentos de segundo orden, no inventados) -- y traduce cada fila enriquecida a un `Detection` con `SkyPosition` (con RA/Dec real si hay WCS, `None` si no -- nunca inventado) y `MorphologySummary`.

**Conversión de convención de forma, documentada porque es exactamente la clase de error que motivó esta auditoría (Fase 1, sección 3.3):** `enrich_star_rows` devuelve `ellipticity = 1 - sqrt(l2/l1)` (heredado); `MorphologySummary.elongation` (Fase 4) sigue la convención `sqrt(l1/l2)` ya usada por `detect_discovery_sources` en el propio código heredado. La conversión correcta es `elongation = 1 / (1 - ellipticity)`. Se implementó, se comentó explícitamente en el código (`_elongation_from_legacy_ellipticity`), y se verificó con un test que confirma `elongation >= 1.0` (circular = 1.0, nunca por debajo) sobre fuentes sintéticas reales -- mezclar estas dos convenciones sin convertir habría sido, literalmente, otro `bg.background` vs. `Background.bkg`.

`MorphologySummary.compactness` usa `sharpness_index` (relación núcleo/anillo de flujo, ya calculada por `enrich_star_rows` a partir de píxeles reales) en vez de inventar una métrica nueva.

## 4. Verificación

8 tests nuevos (`tests/unit/io/`, `tests/unit/detection/`), todos contra datos **reales**, no simulados a nivel de mock: FITS sintéticos escritos con `_write_minimal_fits_2d`, estrellas inyectadas con posición conocida, y aserciones sobre las posiciones recuperadas (no solo "no lanza excepción"). Incluye verificación de roundtrip de serialización real (`Detection.from_dict(d.to_dict()) == d`) sobre objetos producidos por el pipeline real, no construidos a mano como en los tests unitarios de la Fase 4.

Suite completa tras esta fase: **69 tests pasan + 1 xfail esperado** (Python 3.12 + tkinter + Xvfb); **67 pasan + 1 skip (sin tkinter) + 1 xfail** (Python 3.11 sin GUI). Sin regresiones en ninguno de los 61 tests de las Fases 3-5.

## 5. Qué queda -- el resto de la Fase 6

Este slice cubre dos motores de nueve. El resto sigue el mismo patrón (delegar el algoritmo heredado, tipar la salida, test end-to-end con datos sintéticos reales), en este orden de dependencia natural:

1. **Artifact Rejection** -- generalizar `_label_discovery_morphology` (hoy umbrales fijos en código, ver Fase 1 §6.3/§13.9) a reglas explícitas sobre `Detection`, produciendo `ArtifactCheck`.
2. **Identification** (`catalogs/`) -- unificar `query_gaia_sources` y `crossmatch_gaia_safe` (hoy dos implementaciones con formatos de retorno distintos, Fase 4 §7 nota 3) en un único cliente Gaia, más SIMBAD, produciendo `CatalogMatch`/`CatalogQuery` y el `IdentificationState` único.
3. **Characterization** (`photometry/`, `astrometry/`) -- el grupo de funciones ya casi listo señalado en la Fase 2 §5.4 (`measure_source_quality`, `measure_psf_quality`, `absolute_photometric_calibration`, `apply_atmospheric_extinction`, `extract_radial_profile`), envueltas para producir `CharacterizationResult`.
4. **Physical** (`physics/`) -- `infer_physical_parameters`, `GridManager`/`ShockGrid`, `ModelComparisonEngine` → `PhysicalInference`. Es el motor más denso científicamente; requiere más cuidado y probablemente más de un slice.
5. **Anomaly** (`anomaly/`) -- `PhysicalConstraintEngine`, `SpatialTrendAnomalyEngine` → `AnomalyVector`.
6. **Temporal** (`temporal/`) -- `measure_proper_motion`, `TemporalChangeEngine` → `TemporalEvidence`/`MotionEvidence`.
7. **Evidence** (`evidence/`) -- generalizar `DiscoveryEvidenceEngine` para consumir las salidas tipadas de todos los motores anteriores → `EvidenceChain`.

Solo cuando estos siete estén poblados tiene sentido la Fase 7 (fusionar los tres pipelines de descubrimiento en una única ruta `Observation → Candidate`, Fase 1 §6) -- intentarla antes sería fusionar motores que todavía no hablan el mismo idioma tipado.
