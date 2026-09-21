# 38 — Cierre del motor de Fotometría de Apertura

Informe de cierre según el protocolo de 10 fases pedido explícitamente.
Motor único: `photometry/aperture.py` (fotometría de apertura con curva
de crecimiento -- ya real, madura y con GUI propia desde la Fase 16) +
su conexión, hasta ahora inexistente, a la caracterización automática por
fuente (`photometry/quality.py::characterize_point_source`) y de ahí a
`Candidate.flux`.

## FASE 1 — Auditoría

**Implementaciones encontradas.** `photometry/aperture.py` (275
líneas): `aperture_coverage_mask` (cobertura subpíxel), `estimate_local_
sky` (cielo robusto MAD), `aperture_photometry` (apertura múltiple/curva
de crecimiento compartiendo un único cielo local), `fit_curve_of_growth`.
Única implementación, sin duplicados. `legacy/AstroPhysicsSuite_v57_3_
COMMERCIAL.py`: sin fotometría de apertura equivalente -- este motor ya
nació nativo en `astrophysics_suite/`, no es una extracción del legado.

**Wrappers / GUI.** `qt_app/processes/registry.py` (proceso manual
"apphot"): selección de fuente a clic, radio/cielo con valores por
defecto (`radius_px=6.0, sky_r_in=12.0, sky_r_out=18.0`), modelo de
incertidumbre `sqrt(clip(data, 1.0, None))` (Poisson aproximado sobre
los propios datos) -- **la convención de incertidumbre y de radios ya
en producción**, reutilizada sin cambios en este cierre para no acabar
con dos modelos de ruido incompatibles para la misma cámara.

**Duplicados.** Ninguno.

**Funciones muertas encontradas -- esta es la brecha real de este
motor:** `aperture_photometry` tenía **exactamente un llamador de
producción** (el proceso manual `apphot` de la GUI, disparado por clic
del usuario). `photometry/quality.py::characterize_point_source` --el
motor que caracteriza CADA fuente detectada automáticamente durante
Discovery-- nunca la llamaba: `CharacterizationResult.band_flux` llegaba
**siempre vacío** desde producción. `discovery/pipeline.py::run_generic_
discovery` tampoco pasaba `band_flux` al construir cada `Candidate`
(el parámetro `flux=` se omitía en la llamada a `Candidate.create`), así
que **`Candidate.flux` era `{}` en el 100% de los candidatos generados
automáticamente**, con independencia de si la fuente tenía flujo medible
o no.

**GUI ya dormida, no nueva.** `qt_app/candidates/candidate_detail_
widget.py::_section_overview` (línea 190-192) ya tenía, desde antes de
esta ronda:
```python
for band, flux in candidate.flux.items():
    self._kv(form, f"Flujo ({band})", _fmt_quantity(flux))
```
Este bucle nunca se ejecutaba (diccionario siempre vacío) -- código
muerto por falta de dato, no por falta de UI.

**Tests encontrados.** `tests/unit/photometry/test_aperture.py` (10,
reales, sin mocks del propio motor) + `test_psf.py` -- cubren
`aperture.py` de forma aislada, con exactitud verificada contra flujo
inyectado conocido (`assert wide.net_flux == pytest.approx(true_flux,
rel=0.02)`). **Cero tests** ejercían el camino
Characterization -> Candidate.flux, porque ese camino no existía.

**Dependencias reales.** Ninguna nueva: `numpy`, la propia
`aperture_photometry`, `Quantity`/`ValueKind`/`Provenance` (contrato ya
establecido del proyecto).

**Entradas/salidas reales.** Ver Fase 2.

## FASE 2 — Contrato

**Entrada** (`_measure_aperture_flux`, función nueva interna de
`quality.py`): `data: ndarray` (imagen real completa, no un recorte),
`x_px`/`y_px: float` (posición ya conocida de la fuente),
`fwhm_px: float` (FWHM YA medido por `measure_source_quality`
heredado -- nunca una apertura de tamaño arbitrario sin mirar la PSF
real de esta fuente).

**Salida** (`Quantity | None`, insertado en
`CharacterizationResult.band_flux[banda]` para cada banda de la
detección): `value=net_flux` (ADU), `error=net_flux_uncertainty` (ADU,
propagación real de ruido de apertura + incertidumbre del cielo local),
`unit="adu"`, `kind=ValueKind.OBSERVED`, `method="aperture_photometry"`,
`notes=(radio real usado, rango del anillo de cielo, píxeles efectivos)`.

**Radio de apertura:** `max(3.0 * fwhm_px, 3.0)` px -- 3x FWHM captura
`1 - exp(-(3*2.3548)²/2) ≈ 1 - 10⁻¹²` del flujo de un perfil gaussiano
(Howell, *Handbook of CCD Astronomy*, cap. 5): prácticamente el 100% sin
necesitar una curva de crecimiento completa por fuente (coste
computacional -- Discovery caracteriza potencialmente miles de fuentes
por observación). Anillo de cielo `2x`-`3x` ese mismo radio. Se reduce
exactamente a los valores por defecto del proceso manual (6/12/18 px)
cuando el FWHM implica ~6 px de apertura -- misma convención, no una
paralela.

**Incertidumbre.** `sqrt(clip(data, 1.0, None))` -- idéntica al proceso
manual de apertura ya en producción (ver Fase 1), no una aproximación
nueva e incompatible.

**NOT_AVAILABLE / errores.** Sin FWHM medido (`fwhm_quantity is None`,
p. ej. cutout demasiado pequeño) -> `band_flux` queda `{}`, nunca un
radio inventado. Fuente completamente fuera de la imagen (`n_pixels <=
0` tras recortar la cobertura a los límites reales del array) ->
`None`, nunca un flujo fabricado con píxeles inexistentes. Una fuente
cerca del borde pero parcialmente dentro de la imagen SÍ se mide (con
menos píxeles efectivos, pero reales -- `aperture_photometry` ya
recortaba la cobertura a la imagen real antes de esta ronda; verificado,
no solo documentado, en Fase 7).

**Provenance.** Hereda la de `CharacterizationResult` (motor
`photometry.quality`, ya existente) -- no se creó una `Provenance`
separada para el flujo de apertura porque es una medida más dentro del
mismo acto de caracterización de la fuente, igual que FWHM o elongación.

**Quality.** No aplica un nuevo `QualitySummary`: el flujo es una
`Quantity` más dentro de `CharacterizationResult`, sujeta al mismo
`quality_measurement` de estado `OBSERVABLE`/`NOT_AVAILABLE` que ya
gobierna FWHM/elongación.

## FASE 3 — Implementación

**`astrophysics_suite/photometry/quality.py`:** función nueva
`_measure_aperture_flux(data, x_px, y_px, fwhm_px) -> Quantity | None`
(contrato de Fase 2) + wiring en `characterize_point_source`: tras medir
FWHM real, si está disponible, llama a `_measure_aperture_flux` sobre
`loaded_image.legacy_image.data` (la imagen completa, no el recorte que
usa la medida heredada de FWHM) y rellena `band_flux[banda]` para cada
banda de la detección (normalmente una).

**`astrophysics_suite/discovery/pipeline.py`:** una línea en la
construcción de `Candidate` dentro de `run_generic_discovery`:
`flux=reference.characterization.band_flux,` -- el parámetro ya existía
en `Candidate.create`, simplemente nunca se rellenaba desde la ruta de
producción.

No se creó funcionalidad nueva de fotometría: `aperture_photometry`,
`estimate_local_sky`, `aperture_coverage_mask` quedan exactamente como
estaban. No se tocó el proceso manual `apphot` de la GUI ni su modelo de
incertidumbre. No se implementó `band_ratios` (fusión entre bandas de la
misma fuente) ni calibración de punto cero -- explícitamente fuera de
alcance de este cierre (ver "Qué queda").

## FASE 4 — Integración

**Motor anterior -> Motor objetivo:** `characterize_point_source` ya
recibía `loaded_image` (imagen real completa) y `detection.position`
(posición en píxeles de la fuente ya detectada) -- toda la información
necesaria para fotometría de apertura ya llegaba a este motor antes de
esta ronda; no hizo falta tocar `detection/point_sources.py`.

**Motor objetivo -> Motor siguiente:** `discovery/pipeline.py`
(`run_generic_discovery` / `_build_candidate` según el nombre interno) —
`Candidate.flux` pasa a contener el `band_flux` real de la caracterización
del track de referencia, sin pérdida (verificado con
`Candidate.from_dict(candidate.to_dict()) == candidate` en la prueba de
integración).

**Downstream que SIGUE sin consumir este dato -- fuera de alcance
declarado, no un descuido oculto:**
- `anomaly/vector.py` (dimensión fotométrica del vector de anomalía):
  necesitaría un `band_ratios` calibrado entre bandas de la misma
  fuente/época, que a su vez necesita calibración de punto cero
  (`photometry/calibration.py`) para convertir ADU en magnitudes
  comparables -- motor distinto, con su propia auditoría pendiente.
- `evidence/fusion.py` (huérfano, sin llamadores de producción, ver
  auditoría previa de este mismo proyecto): no se tocó.

Ninguno de los dos bloquea el contrato de ESTE motor (`band_flux` en ADU
crudos, con su propia incertidumbre, es una salida completa y honesta en
sí misma); ambos quedan documentados como trabajo futuro de otros
motores.

## FASE 5 — GUI

El bucle `for band, flux in candidate.flux.items(): ...` de
`candidate_detail_widget.py::_section_overview` (línea 190-192) ya
existía -- estaba muerto por falta de dato, no por falta de UI (ver
Fase 1). No se escribió código de interfaz nuevo: se verificó con una
prueba de humo real que, con el dato ahora presente, la fila "Flujo
(banda)" renderiza un valor real (`"... adu"`, no `"NO DISPONIBLE"`)
tras ejecutar un Discovery real de punta a punta y abrir el detalle del
candidato (ver Fase 7).

Progreso/resultado/warnings/errores/estado: heredados sin cambios del
flujo de Discovery ya existente (barra de progreso, resumen de
candidatos) -- este motor no introduce un paso de ejecución nuevo en la
GUI, es una medida más dentro de la caracterización que Discovery ya
ejecutaba.

## FASE 6 — Salidas

**Camino manual (`apphot`, proceso de la GUI, Fase 16, sin cambios en
esta ronda):** ya tiene salida persistente completa -- tabla de
resultados exportable a CSV vía "Exportar última tabla a CSV..."
(`main_window._export_last_table`, ruta elegible, overwrite gestionado
por el diálogo nativo).

**Camino automático (el conectado en esta ronda):** el flujo pasa a
vivir en `Candidate.flux`, en memoria (`SessionState`), y se serializa
sin pérdida (`to_dict`/`from_dict`, verificado por test). **No hay
manera de guardar candidatos/sesión a disco en ningún punto de la
aplicación hoy** -- se comprobó explícitamente (`grep` sobre
`main_window.py` y `services/session_state.py`): existen diálogos de
guardado para FITS con WCS y para tablas CSV de procesos puntuales, pero
ninguno para la lista de `Candidate` que produce Discovery. Esto es un
hueco real, **preexistente a este cierre y no exclusivo de este motor**
(afecta a TODOS los campos de `Candidate`, no solo a `flux`): pertenece
a un motor de persistencia de sesión que este cierre, por mandato
explícito ("no toques ni implementes otros motores"), no puede crear.
Se documenta como **PENDIENTE** explícito, no oculto -- ver Fase 9.

## FASE 7 — Tests

- **Unit (`tests/unit/photometry/test_quality.py`, 4 nuevos sobre 4
  preexistentes = 8):**
  - `test_characterize_point_source_recovers_a_known_injected_flux_
    by_real_aperture_photometry`: flujo inyectado conocido (500 000 ADU,
    perfil gaussiano real) recuperado por el pipeline COMPLETO
    (FITS real en disco -> `load_image` -> `characterize_point_source`)
    con `rel=0.03`, más verificación de `error`, `unit`, `method`,
    `kind` y `notes` -- no `assert result is not None`.
  - `test_characterize_point_source_leaves_band_flux_empty_when_fwhm_
    is_not_available`: reutiliza el escenario de cutout demasiado
    pequeño ya existente y comprueba `band_flux == {}`.
  - `test_characterize_point_source_still_measures_a_real_partial_
    aperture_near_the_edge`: fuente cerca del borde -> flujo real
    positivo con menos píxeles efectivos (no `None`, no un valor
    inventado) -- corrige una suposición inicial mía equivocada (ver
    "Errores encontrados durante el cierre").
  - `test_measure_aperture_flux_returns_none_for_a_source_entirely_
    outside_the_image`: prueba directa de la función interna con una
    posición completamente fuera del array -> `None` real.
- **Integration (`tests/integration/test_generic_discovery_pipeline.py`,
  1 nuevo sobre 13 preexistentes = 14):**
  `test_run_generic_discovery_populates_candidate_flux_from_real_
  aperture_photometry`: Discovery real de punta a punta sobre un FITS
  sintético con 3 fuentes de flujo conocido -> cada `Candidate.flux`
  contiene la banda real con valor/error/unit/method correctos, más
  round-trip de serialización sin pérdida.
- **GUI smoke (`tests/gui_smoke/test_qt_app_candidates_smoke.py`, 1
  nuevo sobre 7 preexistentes = 8):**
  `test_candidate_detail_shows_real_flux_measured_by_aperture_
  photometry`: Discovery real vía la ventana principal (hilo de fondo
  incluido) -> abrir detalle del candidato -> la fila "Flujo (OIII)"
  existe y su valor NO es "NO DISPONIBLE" y contiene "adu".
- **FITS reales:** ver Fase 8.

Ningún test se conforma con `assert result is not None`: cada uno
comprueba el contenido científico (flujo cercano al valor inyectado
conocido, o vacío/`None` cuando corresponde por contrato) y la
transferencia real Characterization -> Candidate (serialización sin
pérdida, GUI que renderiza el valor real).

## FASE 8 — Validación

**Ejecutado de verdad**, no supuesto:

| conjunto | comando | resultado |
|---|---|---|
| Unitarios fotometría | `pytest tests/unit/photometry/` | 24 passed |
| Integración Discovery | `pytest tests/integration/test_generic_discovery_pipeline.py` | 14 passed |
| Suite completa (sin GUI) | `pytest tests/` (venv `aps-test`) | **582 passed, 37 skipped, 1 xfailed** (antes de esta ronda: 577) |
| GUI smoke completa | `xvfb-run pytest tests/gui_smoke/` (venv `aps-gui`) | **106 passed** (antes de esta ronda: 105) |

**Datos utilizados:** FITS sintéticos con estrellas gaussianas reales de
flujo total conocido (unit/integration/GUI), y **píxeles reales** de un
light de M31 del usuario ya debayereado y registrado
(`dbxtract_HA_registered.fit`, 2648×2560 px reales) para la verificación
independiente:

1. Detección real de 15 fuentes puntuales (umbral 8σ) sobre la imagen
   real completa.
2. `characterize_point_source` + medida de flujo de apertura real para
   las 15 -- **15/15 con FWHM real y flujo de apertura real**, cero
   `NOT_AVAILABLE` inesperados.
3. Verificación cruzada por un método de cálculo DISTINTO al del motor
   (máscara binaria por distancia en vez de cobertura subpíxel
   fraccional, calculada directamente en el script de verificación, sin
   llamar a `aperture_photometry`): las 15 medidas coinciden con el
   motor dentro de **0.3%** (`ratio` entre 0.998 y 1.003 en las 15
   fuentes), sobre un rango real de flujo de ~1.2 a ~143 ADU netos.

**Limitaciones (todas documentadas, ninguna oculta):**
- Sin fixture FITS real permanente en el repositorio (mismo motivo que
  en el cierre anterior: tamaño, sin precedente en este proyecto).
- `band_ratios` (fusión fotométrica entre bandas) y la dimensión
  fotométrica de `anomaly/vector.py` siguen sin alcanzar
  `ValueKind.ANOMALOUS` porque necesitan calibración de punto cero --
  motor distinto, fuera de alcance de este cierre (ver Fase 4).
- **Sin salida persistente a disco de `Candidate.flux` (ni de ningún
  otro campo de `Candidate`)** -- gap real, preexistente, de un motor de
  persistencia de sesión que no existe todavía en el proyecto (ver
  Fase 6). Esta es la limitación que impide declarar el cierre
  incondicional (ver Fase 9).
- La incertidumbre de flujo (`sqrt(clip(data,1,None))`) es una
  aproximación de ruido de Poisson sobre los datos ya calibrados en ADU,
  sin separar explícitamente ruido de lectura/ganancia -- la misma
  aproximación que ya usaba el proceso manual antes de esta ronda; no es
  una regresión, pero tampoco un modelo de ruido completo de cámara.

## FASE 9 — Cierre

**Motor: Fotometría de Apertura (conexión automática Characterization ->
Candidate) -- CERRADO.**

- Funciona: sí -- verificado con flujo inyectado conocido (sintético) y
  con contraste independiente sobre píxeles reales de M31 (0.3% de
  acuerdo, 15/15 fuentes).
- Conectado: sí -- Characterization -> Candidate sin pérdida, verificado
  por serialización real y por test de integración de Discovery
  completo.
- GUI funciona: sí -- fila antes muerta ahora renderiza un valor real,
  verificado con prueba de humo sobre la aplicación real (hilo de fondo
  incluido).
- Outputs funcionan: sí -- ver "Actualización" más abajo.
- Provenance funciona: hereda la de `CharacterizationResult`, ya
  probada.
- Tests pasan: 582 (suite completa, antes 577) + 106 GUI (antes 105),
  cero regresiones en esta ronda.
- Validación real realizada: sí, incluida contrastación independiente
  con píxeles reales de M31 (ver Fase 8).

**Actualización (docs/audit/40-CIERRE-MOTOR-PERSISTENCIA-DE-SESION.md).**
En el momento de este informe, "outputs funcionan" se marcó NO para el
camino automático -- no existía ninguna forma de guardar `Candidate.flux`
(ni ningún otro campo de `Candidate`) a disco en la aplicación, así que
este motor se cerró entonces como **REAL PERO LIMITADO**, no CERRADO,
por ese único motivo. El usuario pidió explícitamente cerrar ese hueco
("cierra estos anteriores creando lo que falte"): el cierre 40
(`io/session_export.py::save_session`/`load_session`, cableado en
"Archivo -> Guardar/Abrir sesión...") lo resolvió en la misma sesión de
trabajo, verificado con round-trip real sobre candidatos de M31 con
`band_flux` real producido por ESTE motor. Con esa limitación resuelta,
los siete criterios de la Fase 9 quedan satisfechos y este informe se
corrige a **CERRADO**.

## FASE 10 — Cambio de motor

Informe de cierre entregado. Disponible para pasar al siguiente motor
cuando el usuario lo indique.
