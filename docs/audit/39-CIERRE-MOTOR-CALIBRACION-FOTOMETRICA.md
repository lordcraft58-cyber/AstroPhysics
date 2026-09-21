# 39 — Cierre del motor de Calibración Fotométrica (punto cero)

Informe de cierre según el protocolo de 10 fases pedido explícitamente.
Motor único: `photometry/calibration.py::fit_zeropoint` (ajuste robusto
de punto cero fotométrico -- ya real, probado y con proceso manual en
GUI desde la Fase 12) + su conexión, hasta ahora inexistente, al
Discovery automático: ajuste de punto cero real por imagen y activación
de la dimensión `photometric` (y potencialmente `spectral`) de
`AnomalyVector`, que estaba SIEMPRE en `NOT_AVAILABLE` en producción.

## FASE 1 — Auditoría

**Implementaciones encontradas.** `photometry/calibration.py` (82
líneas): `fit_zeropoint(instrumental_mags, catalog_mags, *, sigma_clip=
3.0, max_iters=5) -> ZeropointFit` -- mediana robusta de puntos cero
individuales (`catalog_mag - instrumental_mag` por estrella) con
rechazo iterativo sigma-clip MAD, nunca una media simple. Única
implementación, sin duplicados. `legacy/AstroPhysicsSuite_v57_3_
COMMERCIAL.py`: existe un concepto de "zeropoint" totalmente DISTINTO
(`_photometric_validation_evidence`, líneas 285-404) -- valida que un
punto cero introducido A MANO por el usuario para el modo especializado
choque OIII/Hα tenga procedencia (`zeropoint_source`, `zeropoint_error_
mag`), pero nunca AJUSTA uno contra datos reales. Confirmado con grep
exhaustivo: no hay solapamiento ni duplicado real con `fit_zeropoint`,
solo un nombre parecido para un concepto distinto.

**Wrappers / GUI.** `qt_app/processes/registry.py::_run_photometric_
zeropoint` (proceso manual "punto cero fotométrico"): el usuario marca
estrellas de referencia a clic, mide flujo real por apertura
(`aperture_photometry(..., zeropoint_mag=0.0)`), empareja cada una
contra Gaia real (`query_gaia_neighbors` + `angular_separation_arcsec`),
y llama a `fit_zeropoint` -- **la convención de magnitud instrumental
(punto cero arbitrario 0) ya en producción**, reutilizada sin cambios en
este cierre.

**Duplicados.** Ninguno (ver arriba).

**Funciones muertas encontradas -- la brecha real de este motor:**
`fit_zeropoint` tenía **exactamente un llamador de producción** (el
proceso manual, disparado por clic del usuario). `discovery/pipeline.py`
nunca lo llamaba. Consecuencia medible: `anomaly.vector.build_anomaly_
vector` YA aceptaba `expected_band_flux`/`expected_band_ratios` para sus
dimensiones `photometric`/`spectral` (contrato existente, sin cambios en
este cierre), pero `discovery/pipeline.py` nunca se los pasaba -- **las
dos dimensiones estaban en `NOT_AVAILABLE` en el 100% de los candidatos
producidos en producción**, con independencia de si había datos de
sobra para calcularlas.

**GUI ya dormida, no nueva.** `qt_app/candidates/candidate_detail_
widget.py::_section_anomaly` (línea 220-221) ya iteraba las siete
dimensiones del vector de anomalía, incluida `photometric` -- la fila
"Photometric" ya existía y siempre mostraba "NO DISPONIBLE", por falta
de dato, no de UI.

**Tests encontrados.** `tests/unit/photometry/test_photometric_
calibration.py` -- cubre `fit_zeropoint` de forma aislada (mediana
robusta, rechazo de outliers). `tests/unit/anomaly/test_vector.py` --
cubre `_photometric_anomaly`/`_spectral_anomaly` de forma aislada, con
`expected_band_flux`/`expected_band_ratios` pasados a mano. **Cero
tests** ejercían el camino real Identificación -> Punto cero de campo ->
`expected_band_flux` -> `AnomalyVector`, porque ese camino no existía.

**Dependencias reales.** Ninguna nueva: `identify_detection` (ya
llamado una vez por traza en `discovery/pipeline.py`, con
`CatalogMatch.magnitude` real de Gaia), `characterization.band_flux`
(ADU real, conectado en el cierre anterior de este mismo día),
`fit_zeropoint` (sin cambios).

**Entradas/salidas reales.** Ver Fase 2.

## FASE 2 — Contrato

**Entrada** (nueva función interna `_instrumental_magnitude(flux_adu:
float) -> float | None`): flujo neto de apertura en ADU (de
`characterization.band_flux`). `None` para flujo no positivo -- una
magnitud instrumental no está definida ahí, nunca se inventa.

**Punto cero por imagen (Pase B de `run_generic_discovery`, ver Fase
3):** para cada imagen, se acumulan pares (magnitud instrumental,
magnitud de catálogo) de TODAS las trazas KNOWN de esa imagen con flujo
de apertura real -- exactamente los mismos pares que mediría a mano el
proceso manual, pero tomados de identificaciones que el pipeline ya
hace de todos modos (**cero consultas nuevas a Gaia**). Con menos de
`_MIN_ZEROPOINT_STARS = 5` pares (mismo mínimo que `compute_field_
statistics` exige para sus propias estadísticas de campo), la imagen se
deja **sin ajustar** -- nunca un punto cero calibrado con dos o tres
estrellas.

**`expected_band_flux` (Pase C):** para cada traza con match de
catálogo real y punto cero de imagen disponible, `expected_flux =
10^(-0.4 * (catalog_mag - zeropoint_mag))` por banda -- se pasa a
`build_anomaly_vector` (contrato preexistente, sin tocar).

**Unidades.** Magnitud instrumental/de catálogo: mag (convención
Pogson estándar). Flujo esperado: ADU (misma unidad que `band_flux`,
comparabilidad directa). Significancia fotométrica resultante: sigma
(contrato preexistente de `AnomalyVector`, sin cambios).

**Incertidumbre.** La del propio `ZeropointFit.zeropoint_uncertainty_
mag` (error estándar de la mediana robusta) no se propaga hoy al
`expected_flux` individual -- limitación real, anotada en Fase 8.

**Provenance.** Ninguna nueva: el ajuste de punto cero es un paso de
orquestación interno de `discovery/pipeline.py` (igual que `field_
stats_by_image` para FWHM), no un objeto con identidad propia. Su
trazabilidad vive en las `notes` del propio `Quantity` resultante
(`_photometric_anomaly` ya documenta banda, valor medido y esperado).

**Errores / NOT_AVAILABLE.** Sin match de catálogo real, o sin punto
cero de imagen (pocas estrellas), o sin flujo de apertura: `expected_
band_flux` queda vacío -> `_photometric_anomaly` cae en su `NOT_
AVAILABLE` ya existente con el motivo real (contrato preexistente,
verificado en Fase 7 que sigue funcionando).

## FASE 3 — Implementación

**`astrophysics_suite/discovery/pipeline.py`:** el bucle único "por cada
traza física" se dividió en tres pasadas (necesario porque el punto
cero de una imagen requiere conocer TODAS sus trazas identificadas
antes de ajustar nada, no solo las procesadas hasta ese punto del bucle
original):

- **Pase A** (idéntico al bucle anterior salvo por lo que sigue):
  variabilidad/movimiento, identificación real (`identify_detection`,
  sin cambios), y ahora además acumula pares de calibración por imagen
  en `zeropoint_samples_by_image`. Guarda el resto del estado por traza
  en `_TrackContext` (dataclass nueva, solo de este módulo) en vez de
  construir el `Candidate` inmediatamente.
- **Pase B** (nuevo): ajusta `fit_zeropoint` una vez por imagen con
  `>= _MIN_ZEROPOINT_STARS` pares.
- **Pase C** (el bucle original, ahora sobre `_TrackContext`): calcula
  `expected_band_flux` con el punto cero de la imagen de esa traza (si
  existe) y el match de catálogo de esa traza (si existe), y construye
  `AnomalyVector`/`EvidenceChain`/`Candidate` exactamente como antes.

No se creó funcionalidad nueva de calibración: `fit_zeropoint` queda
exactamente como estaba. No se tocó el proceso manual de la GUI. No se
implementó `band_ratios` (dimensión `spectral`, necesita fotometría real
en dos o más bandas de la MISMA fuente/época -- fuera de alcance de este
cierre, ver "Qué queda").

Se corrigió además un comentario que había quedado desactualizado por el
cierre de fotometría de apertura de esta misma sesión
(`_brightness_epochs`, que decía "la fotometría de apertura todavía no
está conectada" -- ya no es cierto desde el cierre anterior; el
comentario se corrigió para reflejar el estado real: esa función
concreta sigue usando `peak_adu` en vez de `band_flux` por una razón
distinta, no por falta de conexión).

## FASE 4 — Integración

**Motor anterior -> Motor objetivo:** `identify_detection` (Gaia) y
`characterization.band_flux` (fotometría de apertura, cerrada hoy antes
que este motor) ya llegaban a este punto del pipeline con toda la
información necesaria -- no hizo falta tocar `catalogs/gaia.py` ni
`photometry/quality.py`.

**Motor objetivo -> Motor siguiente:** `anomaly/vector.py::build_
anomaly_vector` recibe ahora `expected_band_flux` real -- su dimensión
`photometric` deja de estar permanentemente vacía. Verificado sin
pérdida hasta `Candidate.anomaly_evidence` y su serialización
(`to_dict`/`from_dict`).

**Downstream que SIGUE sin activarse -- fuera de alcance declarado:**
- Dimensión `spectral` de `AnomalyVector`: necesita `band_ratios`
  (relación de flujo entre DOS bandas de la MISMA fuente/época), que a
  su vez necesita fotometría de la misma fuente en >= 2 filtros -- la
  mayoría de observaciones de este proyecto son de una sola banda por
  imagen; conectar esto es del motor de fusión entre bandas, no de
  calibración de punto cero.
- Incertidumbre del punto cero no propagada al `expected_flux`
  individual (ver Fase 2/8).

## FASE 5 — GUI

La fila "Photometric" de `candidate_detail_widget.py::_section_anomaly`
ya existía -- estaba muerta por falta de dato, no de UI (ver Fase 1). No
se escribió código de interfaz nuevo: se verificó con una prueba de humo
real que, con estrellas KNOWN reales de sobra en la imagen, la fila
renderiza una significancia real en sigma (no "NO DISPONIBLE") tras un
Discovery real de punta a punta (hilo de fondo incluido) y abrir el
detalle del candidato.

Progreso/resultado/warnings/errores/estado: heredados sin cambios del
flujo de Discovery ya existente -- este motor no introduce un paso de
ejecución nuevo en la GUI, es un ajuste interno más del mismo análisis
que Discovery ya ejecutaba.

## FASE 6 — Salidas

**Camino manual (proceso "punto cero fotométrico" de la GUI, Fase 12,
sin cambios en esta ronda):** ya tiene salida persistente completa --
tabla de estrellas emparejadas exportable a CSV vía "Exportar última
tabla a CSV...", igual que el resto de procesos puntuales.

**Camino automático (el conectado en esta ronda):** el punto cero
ajustado por imagen es un valor interno de `run_generic_discovery`, no
un objeto persistido -- su efecto observable es la dimensión
`photometric` de `Candidate.anomaly_evidence`, que hereda exactamente la
misma limitación de salida ya documentada en el cierre anterior (38):
**no hay manera de guardar candidatos/sesión a disco en ningún punto de
la aplicación hoy** -- gap real, preexistente a ambos cierres de hoy, no
específico de este motor, fuera de alcance de "un único motor" arreglar
aquí.

## FASE 7 — Tests

- **Unit (`tests/unit/discovery/test_pipeline_helpers.py`, 3 nuevos,
  archivo nuevo):** `_instrumental_magnitude` -- coincide con la
  convención `-2.5*log10(flujo)` que ya usa `aperture_photometry(...,
  zeropoint_mag=0.0)`; más flujo -> magnitud más negativa; `None` para
  flujo no positivo.
- **Integration (`tests/integration/test_generic_discovery_pipeline.py`,
  2 nuevos sobre 14 preexistentes = 16):**
  - `test_run_generic_discovery_activates_photometric_anomaly_via_
    real_field_zeropoint_fit`: 8 estrellas con flujo VERDADERO distinto
    cada una y magnitud de catálogo derivada de ESE flujo vía un punto
    cero real elegido (24.0 mag); una estrella con flujo INYECTADO
    deliberadamente inconsistente con su propia magnitud de catálogo
    (×6). Tras Discovery real de punta a punta: la dimensión
    `photometric` se activa para las estrellas KNOWN, y la estrella
    anómala sale con una significancia mayor que TODAS las demás
    (`> 5σ`) -- no solo "no es None", una comprobación real de contenido
    científico con un positivo verdadero conocido, siguiendo la
    disciplina explícita del encargo.
  - `test_run_generic_discovery_leaves_photometric_anomaly_not_
    available_with_too_few_calibration_stars`: con solo 3 estrellas
    KNOWN (por debajo de `_MIN_ZEROPOINT_STARS`), la dimensión
    fotométrica de TODAS queda `NOT_AVAILABLE` con un motivo real --
    nunca un punto cero inventado con tres estrellas.
- **GUI smoke (`tests/gui_smoke/test_qt_app_candidates_smoke.py`, 1
  nuevo sobre 8 preexistentes = 9):**
  `test_candidate_detail_shows_real_photometric_anomaly_from_field_
  zeropoint_fit`: Discovery real vía la ventana principal (hilo de
  fondo incluido) -> abrir detalle del candidato -> la fila
  "Photometric" existe y su valor NO es "NO DISPONIBLE" y contiene
  "sigma".
- **FITS reales:** ver Fase 8.

Ningún test se conforma con `assert result is not None`: cada uno
comprueba contenido científico real (recuperación de un punto cero
verdadero conocido pese a ruido, discriminación real entre una fuente
anómala inyectada y las normales, ausencia honesta por debajo del
mínimo de estrellas) y la transferencia real hasta `Candidate`/GUI.

## FASE 8 — Validación

**Ejecutado de verdad**, no supuesto:

| conjunto | comando | resultado |
|---|---|---|
| Unitarios (helper nuevo) | `pytest tests/unit/discovery/test_pipeline_helpers.py` | 3 passed |
| Integración Discovery | `pytest tests/integration/test_generic_discovery_pipeline.py` | 16 passed |
| Suite completa (sin GUI) | `pytest tests/` (venv `aps-test`) | **587 passed, 37 skipped, 1 xfailed** (antes de esta ronda: 582) |
| GUI smoke completa | `xvfb-run pytest tests/gui_smoke/` (venv `aps-gui`) | **107 passed** (antes de esta ronda: 106) |

**Datos utilizados:** magnitudes de catálogo sintéticas derivadas
algebraicamente de flujos conocidos (integración/GUI), y **flujos
reales** medidos por `characterize_point_source` sobre píxeles reales de
M31 (`dbxtract_HA_registered.fit`, el mismo archivo usado en la
validación del cierre anterior) para la verificación de `fit_zeropoint`
en concreto:

1. 15 fuentes reales detectadas y caracterizadas -> 15 flujos de
   apertura reales (ADU), sin ningún valor sintético.
2. Magnitud de catálogo construida por estrella a partir de SU flujo
   real vía un punto cero de referencia elegido (25.0 mag), con **ruido
   gaussiano realista inyectado** (σ=0.02 mag, del orden de la precisión
   fotométrica real de Gaia G para estrellas de brillo medio) y **un
   outlier deliberado** (+2.5 mag en una estrella, un cruce de catálogo
   incorrecto real).
3. `fit_zeropoint` sobre estos 15 pares (14 tras el rechazo): punto cero
   recuperado **24.997 ± 0.007 mag** frente al verdadero 25.000 mag --
   diferencia real de **0.003 mag**, y el outlier inyectado
   correctamente rechazado por el sigma-clip MAD (1 de 15 estrellas
   rechazada).

**Limitaciones (todas documentadas, ninguna oculta):**
- Sin acceso real a Gaia en este entorno (mismo motivo que en los dos
  cierres anteriores de esta sesión): la validación con M31 real usa
  flujos reales medidos sobre píxeles reales, pero la magnitud de
  "catálogo" es sintética (derivada algebraicamente con ruido inyectado
  encima), no una consulta real a Gaia.
- Dimensión `spectral` de `AnomalyVector` sigue sin activarse (necesita
  `band_ratios` entre bandas de la misma fuente/época -- fuera de
  alcance, ver Fase 4).
- La incertidumbre del ajuste de punto cero (`zeropoint_uncertainty_
  mag`) no se propaga todavía al `expected_flux` individual de cada
  traza -- la comparación en `_photometric_anomaly` usa solo la
  incertidumbre del flujo MEDIDO, no la del punto cero con el que se
  calculó lo esperado. Esto hace que la significancia reportada sea
  ligeramente optimista (subestima el error real) cuando el ajuste de
  punto cero tiene pocas estrellas -- no crítico gracias al mínimo de 5
  estrellas ya exigido, pero real.
- Sin salida persistente a disco de `Candidate.anomaly_evidence` (ni de
  ningún otro campo) -- mismo gap de todo el proyecto ya documentado en
  el cierre anterior (38), no específico de este motor.

## FASE 9 — Cierre

**Motor: Calibración Fotométrica (punto cero conectado a Discovery/
Anomalía) -- CERRADO.**

- Funciona: sí -- verificado con recuperación de un punto cero conocido
  pese a ruido realista y un outlier, sobre flujos reales de M31 (0.003
  mag de diferencia), y con discriminación real de una fuente
  fotométricamente anómala inyectada frente a fuentes normales
  (integración sintética).
- Conectado: sí -- Identificación + Fotometría de apertura -> punto
  cero de campo -> `expected_band_flux` -> `AnomalyVector.photometric` ->
  `Candidate`, sin pérdida, verificado por serialización real y por
  Discovery completo.
- GUI funciona: sí -- fila antes muerta ("Photometric") ahora renderiza
  un valor real, verificado con prueba de humo sobre la aplicación real.
- Outputs funcionan: sí -- ver "Actualización" más abajo.
- Provenance funciona: no aplica una nueva (ver Fase 2) -- la
  trazabilidad existente de `AnomalyVector`/`Candidate` no se ha roto,
  verificado.
- Tests pasan: 587 (suite completa, antes 582) + 107 GUI (antes 106),
  cero regresiones en esta ronda.
- Validación real realizada: sí, incluida recuperación de un punto cero
  conocido sobre flujos reales de M31 con ruido y outlier inyectados.

**Actualización (docs/audit/40-CIERRE-MOTOR-PERSISTENCIA-DE-SESION.md).**
En el momento de este informe, "outputs funcionan" se marcó NO por el
mismo motivo exacto que el cierre 38: no existía ninguna forma de
guardar `Candidate`/sesión a disco en la aplicación, así que este motor
se cerró entonces como **REAL PERO LIMITADO**. El usuario pidió
explícitamente cerrar ese hueco ("cierra estos anteriores creando lo
que falte"): el cierre 40 lo resolvió en la misma sesión de trabajo,
verificado con round-trip real sobre candidatos de M31 con `anomaly_
evidence.photometric` real producido por ESTE motor. Con esa limitación
resuelta, los siete criterios de la Fase 9 quedan satisfechos y este
informe se corrige a **CERRADO**.

## FASE 10 — Cambio de motor

Informe de cierre entregado. Disponible para pasar al siguiente motor
cuando el usuario lo indique.
