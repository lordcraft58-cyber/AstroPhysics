# 42 — Cierre: Provenance real en TemporalEvidence/MotionEvidence

Informe de cierre según el protocolo de 10 fases pedido explícitamente.
Alcance: `MotionEvidence`/`TemporalEvidence` eran los **únicos** dos
modelos de evidencia de todo el proyecto sin campo `Provenance` --
completar ese contrato, con las mismas garantías que ya tienen
`CharacterizationResult`, `Candidate`, `PlateSolveResult`, etc.

## FASE 1 — Auditoría

`astrophysics_suite/models/temporal.py::TemporalEvidence`/
`MotionEvidence`: sin campo `provenance`. Confirmado con grep: son los
ÚNICOS modelos de evidencia del proyecto en esa situación. La propia
`temporal/motion.py::analyze_motion` lo documentaba explícitamente en
un comentario: *"`MotionEvidence` no tiene todavía campo de
procedencia... mientras tanto, el método y las notas de cada `Quantity`
llevan el motor"* -- y su propio parámetro `pipeline_version` se
descartaba sin usar (`del pipeline_version`) porque no había dónde
ponerlo. `temporal/variability.py::analyze_variability` ni siquiera
tenía el parámetro `pipeline_version`.

**Wrappers/GUI.** Ninguno directo -- ambas funciones se llaman
exclusivamente desde `discovery/pipeline.py` (motor de orquestación),
no hay proceso manual de GUI equivalente.

**Duplicados/funciones muertas.** Ninguno.

**Tests encontrados.** `tests/unit/temporal/test_motion.py` (8),
`test_variability.py` (4), `tests/unit/models/test_temporal.py` (3),
más usos en `tests/unit/anomaly/test_vector.py` y
`tests/unit/evidence/test_chain_builder.py` -- todos construían
`MotionEvidence`/`TemporalEvidence` sin procedencia (no podían, el
campo no existía).

**Dependencias reales.** `Provenance` (ya real, sin cambios). Ninguna
dependencia nueva.

## FASE 2 — Contrato

**Entrada.** `provenance: Provenance` pasa a ser **campo requerido**
(sin valor por defecto) en ambos modelos y en sus `.create()`, igual
que `CharacterizationResult.provenance`/`Candidate.provenance` -- nunca
opcional, para que sea estructuralmente imposible construir una de
estas evidencias sin decir de dónde sale.

**`analyze_motion`/`analyze_variability`.** Ambas construyen
`Provenance.now(pipeline_version=..., engine="temporal.motion"|
"temporal.variability", engine_version="1.0")` **una vez al principio**
y la adjuntan a **todas** las rutas de retorno, incluidas las de
`NOT_AVAILABLE` -- un resultado "no disponible" es tan real como uno
positivo y merece la misma trazabilidad (mismo principio que
`Quantity.not_available` ya aplica a nivel de magnitud individual).

**Serialización.** `to_dict()`/`from_dict()` de ambos modelos incluyen
`"provenance"` como clave **requerida** en `from_dict` (`data
["provenance"]`, sin `.get()` con valor por defecto) -- mismo criterio
que `Candidate`/`CharacterizationResult`: nunca se inventa una
procedencia para datos que no la tengan.

**Errores/NOT_AVAILABLE.** Sin cambios de comportamiento científico --
exactamente los mismos criterios de significancia/residuo/época mínima
que ya existían; el único cambio es que ahora CADA `MotionEvidence`/
`TemporalEvidence` que sale de estas funciones lleva procedencia real.

## FASE 3 — Implementación

`models/temporal.py`: campo `provenance: Provenance` añadido a ambas
clases (después del último campo sin valor por defecto, antes de los
opcionales, para mantener el orden válido de un dataclass), más su
paso por `create()`/`to_dict()`/`from_dict()`.

`temporal/motion.py`: `Provenance.now(...)` construida al principio de
`analyze_motion` (sustituye el `del pipeline_version` + comentario que
explicaba por qué se descartaba), pasada a los 3 puntos de retorno
(`unavailable()` + los dos casos reales: residuo cero y significancia
calculada).

`temporal/variability.py`: `pipeline_version: str = ""` añadido a la
firma (no existía), `ENGINE_VERSION = "1.0"` añadido (no existía,
inconsistente con el resto de motores que sí lo declaran),
`Provenance.now(...)` pasada a los 2 puntos de retorno.

`discovery/pipeline.py`: una línea -- `analyze_variability(...,
pipeline_version=pipeline_version)` (antes no se pasaba; `analyze_
motion` ya lo recibía, simplemente lo tiraba).

No se creó ninguna funcionalidad científica nueva: los criterios de
significancia, residuo mínimo, épocas mínimas, etc. quedan exactamente
iguales.

## FASE 4 — Integración

Contrato ya conectado de extremo a extremo desde antes de este cierre
(`discovery/pipeline.py` ya llamaba a ambas funciones y adjuntaba sus
resultados a `Candidate.motion_evidence`/`temporal_evidence`) -- este
cierre no cambia QUÉ se conecta, sino que la conexión existente ahora
lleva procedencia real en vez de un hueco de contrato. Verificado sin
pérdida vía `Candidate.from_dict(c.to_dict()) == c` en los tests
existentes y nuevos.

## FASE 5-6 — GUI / Salidas

Sin cambios: `candidate_detail_widget.py::_section_temporal_motion` ya
muestra los campos de `MotionEvidence`/`TemporalEvidence` (épocas,
movimiento propio, cambio de brillo) sin depender de `provenance`
directamente -- este cierre no añade una fila nueva a la GUI (la
procedencia de estas dos evidencias no tenía, ni tiene, una
representación visual propia en el detalle del candidato, igual que
`CharacterizationResult.provenance` tampoco la tenía antes de este
proyecto). La persistencia de sesión (cierre 40) ya guarda/recupera
estos campos sin cambios adicionales, verificado en Fase 7.

## FASE 7 — Tests

- **Unit (`tests/unit/temporal/test_motion.py`, 2 nuevos sobre 8
  preexistentes; `test_variability.py`, 2 nuevos sobre 4
  preexistentes):** `pipeline_version` real llega hasta `result.
  provenance.pipeline_version`; procedencia presente y correcta
  también en el camino NOT_AVAILABLE (época única, datos insuficientes)
  -- no solo en el camino feliz.
- **Actualizados (8 tests que ya existían, ahora con `provenance=`
  real en vez de fallar por el nuevo campo requerido):**
  `tests/unit/models/test_temporal.py` (3), `tests/unit/anomaly/
  test_vector.py` (2), `tests/unit/evidence/test_chain_builder.py` (3).
- **Integration (`tests/integration/test_generic_discovery_pipeline.py`,
  extendido, no nuevo):** el test central de agrupación multiépoca ya
  producía `Candidate` reales con `motion_evidence`/`temporal_evidence`
  -- se le añadió `pipeline_version="v-multi-epoch-test"` a la llamada
  y aserciones de que `motion_evidence.provenance`/`temporal_evidence.
  provenance` lo llevan de verdad, con el motor correcto.
- **FITS reales:** ver Fase 8.

Ningún test se conforma con `assert result is not None`: cada uno
comprueba que la procedencia real (motor, versión de pipeline) llega
hasta el resultado final, incluido el camino "no disponible".

## FASE 8 — Validación

**Ejecutado de verdad**, no supuesto:

| conjunto | comando | resultado |
|---|---|---|
| Unitarios temporal | `pytest tests/unit/temporal/` | 16 passed |
| Suite completa (sin GUI) | `pytest tests/` (venv `aps-test`) | **597 passed, 37 skipped, 1 xfailed** (antes: 593) |
| GUI smoke completa | `xvfb-run pytest tests/gui_smoke/` (venv `aps-gui`) | **110 passed** (sin cambios, ninguna prueba GUI nueva en este cierre) |

**Datos utilizados:** trazas sintéticas reales (unit/integración), y
**3 lights reales de M31** (`Light_M31_300s_0001/0002/0003.fit`, Bayer
RGGB real, WCS SIP real, `DATE-OBS` real con 5 minutos de separación
entre tomas) para la verificación de extremo a extremo:

1. Discovery real completo (demosaico + detección + caracterización +
   agrupación multiépoca + movimiento/variabilidad) sobre las 3 épocas
   reales -> 46 candidatos reales, 39 con `motion_evidence`/`temporal_
   evidence` real (>= 2 épocas emparejadas).
2. Los 39 candidatos con evidencia temporal/de movimiento llevan
   `provenance.engine`/`provenance.pipeline_version` reales y
   correctos -- verificado programáticamente, no solo inspeccionado a
   ojo.
3. Tiempo total: 7.7s para las 3 imágenes reales completas (3008×3008,
   demosaico incluido) -- sin regresión de rendimiento perceptible.

**Limitaciones:** ninguna nueva introducida por este cierre. La
procedencia de `TemporalEvidence`/`MotionEvidence` no tiene
representación visual propia en la GUI (mismo estado que `Characterization
Result.provenance`, que tampoco la tiene) -- consistente con el resto
del proyecto, no una carencia de este cierre en particular.

## FASE 9 — Cierre

**Motor: Provenance en TemporalEvidence/MotionEvidence -- CERRADO.**

- Funciona: sí -- verificado con datos sintéticos y con 3 épocas
  reales de M31.
- Conectado: sí -- el contrato ya estaba conectado de extremo a
  extremo; ahora lleva procedencia real en cada tramo.
- GUI funciona: sin cambios necesarios (ver Fase 5-6) -- no hay
  regresión, confirmado con la suite de humo completa.
- Outputs funcionan: sí -- la persistencia de sesión (cierre 40)
  guarda/recupera estos campos sin pérdida, verificado.
- Provenance funciona: sí -- literalmente el objeto de este cierre.
- Tests pasan: 597 (suite completa, antes 593) + 110 GUI (sin cambios),
  cero regresiones.
- Validación real realizada: sí, incluidas 3 épocas reales de M31.

Sin limitaciones que impidan el cierre incondicional -- a diferencia de
los cierres 38/39 (que dependían de un motor de persistencia que no
existía todavía), este cierre no depende de ningún otro motor pendiente.

## FASE 10 — Cambio de motor

Informe de cierre entregado. Disponible para pasar al siguiente motor
cuando el usuario lo indique.
