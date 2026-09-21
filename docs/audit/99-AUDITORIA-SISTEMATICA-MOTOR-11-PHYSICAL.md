# 99 — Auditoría sistemática, motor 11/16: Physical

Undécimo motor de la fase de cierre sistemático. Hallazgo real: a
diferencia de motores anteriores donde solo quedaba un "residuo" de
legacy, aquí el NÚCLEO ENTERO del motor (`infer_physical_parameters` y
`PhysicalConstraintEngine.evaluate`) seguía delegando en el monolito
heredado. Ambos son cálculo puro (física/estadística, sin red), así que
se migraron 1:1 siguiendo el mismo criterio ya aplicado en Characterization
(informe 94) y Temporal (informe 97).

## Mapa del motor (fase previa, sin tocar código)

**Motor científico**: `astrophysics_suite/physics/{inference,
constraints,observables}.py`. **GUI**: ninguna directa -- este motor no
tiene un proceso propio en `qt_app/processes/registry.py`; se alimenta
de lo que SÍ miden Characterization/Photometry (FWHM, razón de bandas,
flujo calibrado) y de la distancia/velocidad que aporte el usuario, y su
salida (`PhysicalInference`/`ConsistencyResult`) alimenta la dimensión
física del `AnomalyVector` en el motor de Anomalía (siguiente-siguiente
en el orden fijo). **Tests**: `tests/unit/physics/` (19 tests).

## Hallazgo: núcleo entero delegado en legacy

- `physics/inference.py::infer_physical_inference` delegaba en
  `legacy.infer_physical_parameters` -- el motor de inferencia física
  completo (razón OIII/Hα observada, tamaño físico por aproximación de
  ángulo pequeño, temperatura post-choque de Rankine-Hugoniot, edad
  dinámica de Sedov-Taylor).
- `physics/constraints.py::evaluate_consistency` delegaba en
  `legacy.PhysicalConstraintEngine.evaluate` -- las dos consistencias
  físicas internas (edad-radio-velocidad de Sedov, temperatura-velocidad
  de choque fuerte) más la comprobación de razón de líneas positiva.

Se reimplementaron ambos 1:1, sin cambiar ninguna fórmula ni criterio:

- `_infer_physical_parameters` (nuevo, en `inference.py`): mismas
  fórmulas exactas (constantes físicas `kB`, `mp`, `mu=0.61`,
  `gamma=5/3` idénticas; mismo coeficiente de Sedov 2/5; misma
  propagación de error por cuadratura relativa). Se detectó y replicó
  además un detalle no obvio: el `json_sanitize` heredado convierte
  NaN/inf a `None` al serializar cada `ParameterEstimate` -- sin
  replicarlo, el diccionario crudo devuelto difería de legacy en ese
  detalle (aunque el `Quantity` final resultante era idéntico, porque
  `infer_physical_inference` ya normalizaba NaN->None por su cuenta).
  Corregido y verificado con la prueba de regresión antes de darlo por
  cerrado -- ver "Errores y correcciones" más abajo.
- `_evaluate_physical_constraints` (nuevo, en `constraints.py`): mismas
  dos comprobaciones de consistencia exactas (mismos coeficientes
  0.4 y 3/16, misma propagación de error, mismo criterio de bandera por
  `min_sigma`), más la comprobación de razón de emisión positiva.

`PhysicalModelRegistry` (heredado) NO se migra: se verificó leyendo el
cuerpo completo de `infer_physical_parameters` que se construye
(`reg = registry or PhysicalModelRegistry()`) pero nunca se consulta
dentro de la función -- parámetro vestigial, y ningún llamador real de
la suite le pasaba nunca un registro propio (confirmado por grep en todo
el árbol). No se migra un artefacto muerto solo por existir en el
original.

### Verificación numérica de la migración

Nueva prueba de regresión `tests/regression/test_physics_matches_legacy.py`
(14 tests): inferencia con fila de resto de supernova completa, con solo
velocidad, con solo tamaño angular, con fila vacía, con flujos
calibrados; con y sin distancia aportada por el usuario; consistencias
con fila físicamente coherente, con fila deliberadamente inconsistente,
con razón de emisión negativa (problema de medida), con espacio de
parámetros vacío, y barrido de umbrales sigma. Todos los campos
(valores, errores, unidades, estado, modelo, bandera, clasificación,
z-score) coinciden con la implementación heredada dentro de 1e-9.

### Errores y correcciones (encontrado durante la propia verificación)

Al escribir la prueba de regresión, el primer intento falló: el campo
`error` de algunos parámetros migrados venía como `NaN` mientras que la
versión heredada devolvía `None` para el mismo caso. Investigado hasta
la causa raíz (`json_sanitize` heredado, invocado dentro de
`ParameterEstimate.asdict()`, convierte cualquier float no finito a
`None` antes de devolver el diccionario) y corregido replicando esa
misma sanitización en `_estimate()` -- mismo patrón de verificación que
ya atrapó una divergencia real en el cierre de Characterization (informe
94): la prueba de regresión hizo su trabajo antes de dar nada por
cerrado.

## Hallazgo relacionado, fuera de alcance (documentado, no corregido aquí)

`astrophysics_suite/anomaly/physical_tension.py::physical_anomaly_quantity`
también llama directamente a `legacy.PhysicalConstraintEngine.evaluate`
(y a `legacy.build_reference_anomaly`), con el MISMO patrón de brecha ya
corregido en `physics/constraints.py` (llama a `.evaluate(row, estimates)`
sin promover los observables medidos al espacio de parámetros). Este
archivo pertenece al paquete `anomaly/`, motor todavía no auditado en el
orden fijo del usuario (Anomaly es el motor 12) -- no se toca aquí,
siguiendo la misma disciplina ya aplicada en informes anteriores de no
adelantar ni reabrir motores fuera de su turno. Queda documentado para
que su propia auditoría lo encuentre como hallazgo real, no como
sorpresa.

## Validación con datos reales

Se cargó el LIGHT real de M 31 sin calibrar
(`/tmp/real_fits_dir/Light_M31_300s_0001.fit`), se detectó la fuente
puntual real más brillante y se midió su FWHM real
(`measure_source_quality`, motor de Characterization ya cerrado):
5.479 px. Con una escala de píxel de referencia (0.5"/px) se obtuvo un
`offset_arcsec` real de 2.739", y con la distancia real y publicada de
M 31 (785 kpc, valor catalogado, no inventado) se ejecutó
`infer_physical_inference`: produjo `offset_pc=10.425 pc` real
(aproximación de ángulo pequeño sobre una medida real). Sin velocidad
medida (no derivable de una sola imagen fotométrica), `evaluate_
consistency` degradó honestamente a 0 comprobaciones evaluadas con el
motivo explícito de cada ausencia (`radius_pc`/`velocity_kms` ausentes),
confirmando que el motor migrado nunca inventa un valor que falta.

## Checklist de cierre (20 puntos)

| Punto | Estado |
|---|---|
| Implementación científica real | Sí -- inferencia (escala física, temperatura de choque, edad de Sedov) y consistencia interna, ambas nativas |
| Entrada definida | Sí -- `row: dict` de observables + `distance_pc`/`distance_err_pc` opcionales |
| Salida definida | Sí -- `PhysicalInference` (parámetros tipados) / `ConsistencyResult` (comprobaciones + no evaluadas) |
| Tipos coherentes | Sí -- `Quantity` tipada en todo el flujo |
| Unidades correctas | Sí -- dex, arcsec, pc, K, yr, flux según el parámetro |
| Incertidumbres cuando correspondan | Sí -- propagación de error real por cuadratura relativa en cada fórmula |
| Manejo explícito de datos faltantes | Sí -- cada observable ausente desactiva solo los modelos que lo necesitan, con motivo explícito |
| NOT_AVAILABLE cuando proceda | Sí -- `physical_tension_quantity` devuelve `Quantity.not_available` con el motivo cuando no hay comprobaciones evaluables |
| Provenance | Sí -- `PhysicalInference.provenance` real (motor+versión+timestamp) |
| Errores correctamente gestionados | Sí -- ninguna excepción sin capturar; toda entrada degenerada produce NOT_AVAILABLE explícito |
| Funciona independientemente | Sí -- sin GUI, ver `tests/unit/physics/` |
| Conectado al motor anterior (Motion) | N/A directo -- Physical no consume `MotionEvidence` en el código actual (ya documentado en el informe 98); consume observables de Characterization/Photometry |
| Conectado al siguiente (Anomaly) | Sí -- `physical_tension_quantity` (ya cableado en `anomaly/physical_tension.py`) alimenta la dimensión física del `AnomalyVector` |
| GUI funcional | N/A directo -- sin proceso propio en el árbol de procesos; alimentado por motores anteriores |
| Guardado de resultados correcto | N/A directo -- `PhysicalInference` viaja dentro del `Candidate` persistido |
| Rutas de salida controladas por el usuario | N/A (no produce archivos propios) |
| Tests unitarios | Sí -- 19 passed |
| Tests de integración | N/A directo en este informe (sin cambio de contrato observable; la conexión real a Anomalía/Evidencia se audita en esos motores) |
| Test de regresión | Sí (nuevo) -- `test_physics_matches_legacy.py`, 14 tests, migración 1:1 verificada campo a campo, incluida una divergencia real encontrada y corregida (NaN vs. None) |
| Validación con datos reales/controlados | Sí -- FWHM real de M31 + distancia real publicada, ver arriba |
| Documentación actualizada | Sí -- este informe |
| Ningún placeholder presentado como funcionalidad | Sí -- cálculo real, nunca simulado |

## Validación de la suite completa

`pytest tests/unit tests/integration tests/regression -q`: **1740
passed, 24 skipped** (14 tests nuevos de este informe sobre la base de
1726 del informe 98; mismos 24 skips de siempre).

## CHECKPOINT

```
MOTOR: Physical
ESTADO: CERRADO
IMPLEMENTACIÓN: astrophysics_suite/physics/{inference,constraints,observables}.py
ENTRADA: row de observables medidos (ratio, offset_arcsec, velocity_kms, radius_pc...) + distancia opcional del usuario
SALIDA: PhysicalInference (parámetros tipados) / ConsistencyResult (comprobaciones + no evaluadas)
GUI: N/A directo -- sin proceso propio, alimentado por Characterization/Photometry
PROVENANCE: real (motor+versión+timestamp)
TESTS: 19 unitarios directos del motor + 14 de regresión (nuevos, esta auditoría)
TESTS PASADOS: 33 directos del motor / 1740 de la suite completa
TESTS FALLIDOS: 0
VALIDACIÓN REAL: sí (FWHM real de una fuente de M31 + distancia real publicada de M31 produce un tamaño físico real; sin velocidad medida, las consistencias degradan honestamente)
PROBLEMAS RESTANTES: ninguno bloqueante en este motor. anomaly/physical_tension.py (motor 12, todavía no auditado) tiene el mismo patrón de brecha ya corregido aquí -- documentado para su propia auditoría, no corregido fuera de turno.
CONTRATO HACIA EL SIGUIENTE MOTOR (Anomaly): PhysicalInference.parameters (Quantity tipada por parámetro) + ConsistencyResult -- ya consumidos hoy por physical_anomaly_quantity en anomaly/physical_tension.py, aunque ese archivo todavía llama a la versión heredada directamente en vez de a evaluate_consistency (ver hallazgo relacionado arriba).
```

## Cambio de motor

Physical cerrado bajo el checklist de 20 puntos: núcleo entero migrado
de legacy a nativo (inferencia + consistencia física), con una prueba de
regresión que además atrapó y corrigió una divergencia real (NaN vs.
None) antes de cerrar. Validado con datos reales de M31. Documentado,
sin corregirlo fuera de turno, un hallazgo relacionado en el motor de
Anomalía (todavía pendiente). Siguiente en el orden fijo del usuario:
**Anomaly**.
