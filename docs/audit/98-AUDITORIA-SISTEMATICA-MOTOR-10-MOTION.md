# 98 — Auditoría sistemática, motor 10/16: Motion

Décimo motor de la fase de cierre sistemático. A diferencia de Temporal
(informe 97, mismo paquete `astrophysics_suite/temporal/` pero motor
distinto en el orden fijo del usuario), esta auditoría **no encontró
ningún hallazgo que corregir**: `temporal/motion.py` ya era nativo desde
su construcción original (tarea histórica "P0.2 -- Motor de tracks
multiépoca + motion.py con tests reales"), sin ninguna delegación en
legacy y sin la fórmula de separación angular duplicada que sí se
encontró (y ya se corrigió, como infraestructura compartida) en
`discovery/source_tracks.py` durante el cierre de Temporal.

## Mapa del motor (fase previa, sin tocar código)

**Motor científico**: `astrophysics_suite/temporal/motion.py`
(`analyze_motion`) + la parte de `models/temporal.py` que le
corresponde (`MotionEpoch`/`MotionEvidence`). Consume directamente el
`SourceTrack` que produce `discovery/source_tracks.py` (mismo
agrupamiento multiépoca ya auditado y consolidado en el informe 97 --
infraestructura compartida con Temporal, no se vuelve a auditar aquí
como si fuera nueva). **GUI**: ninguna dedicada -- corre siempre dentro
del pipeline automático de Discovery (`discovery/pipeline.py`, línea
705), mismo patrón que Temporal. **Tests**:
`tests/unit/temporal/test_motion.py` (11 tests).

## Verificación (sin hallazgos que cerrar)

1. **Sin residuo de legacy**: `motion.py` no importa nada de
   `legacy.AstroPhysicsSuite_v57_3_COMMERCIAL` -- confirmado por
   inspección directa de sus imports (`core.enums`, `core.provenance`,
   `core.quantity`, `discovery.source_tracks`, `models.temporal`, además
   de `math`/`numpy`). Nunca hubo una versión heredada de este ajuste de
   trayectoria: se construyó nativo desde el principio.
2. **Sin fórmula duplicada**: los desplazamientos que usa
   (`x_arcsec`/`y_arcsec` vía `math.cos(math.radians(mean_dec))`) son
   una proyección al plano tangente local para un ajuste lineal por
   mínimos cuadrados -- un cálculo legítimamente distinto de la
   separación de gran círculo que sí estaba duplicada en otros puntos
   del proyecto (informes 96 y 97). No hay nada que consolidar aquí.
3. **La regla de los 3 puntos (ya documentada en el propio módulo,
   reverificada intacta)**: con menos de `MIN_EPOCHS_FOR_RESIDUAL=3`
   posiciones no hay residuo del ajuste, así que sin un
   `registration_rms_arcsec` externo no se puede distinguir movimiento
   real de error de registro -- el motor lo declara `NOT_AVAILABLE` con
   el motivo explícito, nunca asume ausencia de movimiento. Con residuo
   exactamente cero (trayectoria perfectamente lineal, posible con
   ruido real bajo) se reporta el desplazamiento MEDIDO sin barra de
   error inventada, y `moving_source_candidate=False` por falta de
   significancia demostrable, NO por ausencia de desplazamiento -- la
   diferencia queda escrita en las notas del propio `Quantity`.
4. **`registration_rms_arcsec` no se threadea desde
   `discovery/pipeline.py`**: confirmado (de nuevo, ya lo hizo el
   informe 97) que es una decisión correcta, no un cable suelto --
   Discovery automático no tiene un RMS de registro fiable disponible
   (el registro real por WCS compartido es un flujo manual aparte, con
   su propio `RegistrationRecord`). El parámetro existe para cuando SÍ
   se conoce (p. ej. una futura integración con el flujo manual de
   registro), y su ausencia hoy degrada honestamente.
5. **Conexión real al resto del pipeline**: `MotionEvidence.
   moving_source_candidate` es justo lo que
   `discovery/pipeline.py::_upgrade_identification_state` (líneas
   507-525) usa para reclasificar una traza como
   `IdentificationState.MOVING_SOURCE_CANDIDATE` -- con prioridad sobre
   la variabilidad (un objeto que se desplaza es más específico que uno
   que solo cambia de brillo), y solo cuando el motor concluyó algo real
   (`moving_source_candidate=True`), nunca por la mera presencia de un
   objeto `MotionEvidence` con menos épocas de las necesarias. Desde
   ahí, el `IdentificationState` resultante alimenta directamente
   Anomalía/Evidencia (`anomaly/vector.py`, `evidence/chain_builder.py`)
   -- el motor de Physical (siguiente en el orden fijo del usuario)
   opera sobre parámetros físicos inferidos por separado (fotometría/
   espectroscopía), no consume `MotionEvidence` directamente; se deja
   documentado aquí con honestidad en vez de forzar un contrato de datos
   que el código no tiene.

## Validación con datos reales

Reutiliza la validación ya ejecutada durante el cierre de Temporal
(informe 97, misma corrida): 4 detecciones reales construidas sobre la
fuente puntual real más brillante del LIGHT de M 31
(`/tmp/real_fits_dir/Light_M31_300s_0001.fit`), con coordenadas reales
de M 31 (RA=10.6847083°, Dec=41.2687500°) y marcas de tiempo reales
espaciadas 1 hora, con un movimiento propio de prueba INYECTADO de
0.05"/hora en Dec:

- `group_detections_into_tracks` agrupó las 4 detecciones en 1 sola
  traza real de 4 épocas.
- `analyze_motion` sobre esa traza recuperó el movimiento inyectado con
  exactitud: `pm_total=0.0500"/h` (el valor exacto inyectado),
  `moving_source_candidate=True` (correctamente significativo con 4
  épocas y residuo bajo).

Confirma que el motor mide correctamente sobre datos derivados de una
fuente real y coordenadas reales, con el residuo/incertidumbre
calculados del ajuste real, no de un valor fijo.

## Checklist de cierre (20 puntos)

| Punto | Estado |
|---|---|
| Implementación científica real | Sí -- ajuste lineal por mínimos cuadrados con tiempo real por época, residuo real, significancia real |
| Entrada definida | Sí -- `SourceTrack` con posiciones celestes y tiempos reales |
| Salida definida | Sí -- `MotionEvidence` (pm_total/pm_ra/pm_dec con incertidumbre, moving_source_candidate, épocas reales) |
| Tipos coherentes | Sí -- dataclasses tipadas en todo el flujo |
| Unidades correctas | Sí -- arcsec/hour |
| Incertidumbres cuando correspondan | Sí -- del residuo real del ajuste, con los grados de libertad correctos; combinada en cuadratura con el RMS de registro cuando se conoce |
| Manejo explícito de datos faltantes | Sí -- menos de 2 posiciones, alguna época sin tiempo real, intervalo cero, menos de 3 épocas sin RMS de registro externo, residuo cero: cada caso con su motivo explícito |
| NOT_AVAILABLE cuando proceda | Sí -- ver fila anterior, con `Quantity.not_available` real, nunca un cero disfrazado de medida |
| Provenance | Sí -- `MotionEvidence.provenance` real (motor+versión+timestamp), cerrado en el informe 80, reverificado intacto |
| Errores correctamente gestionados | Sí -- ninguna excepción sin capturar; toda entrada degenerada produce un resultado explícito |
| Funciona independientemente | Sí -- sin GUI, ver `tests/unit/temporal/test_motion.py` |
| Conectado al motor anterior (Temporal) | Sí -- comparten el mismo `SourceTrack` (infraestructura de agrupamiento consolidada en el informe 97) |
| Conectado al siguiente (Physical) | Parcial, documentado con honestidad: `MotionEvidence` alimenta directamente `IdentificationState` (vía `_upgrade_identification_state`) y de ahí Anomalía/Evidencia; Physical no consume `MotionEvidence` directamente en el código actual -- ver punto 5 arriba |
| GUI funcional | N/A directo -- corre dentro del pipeline automático de Discovery, sin diálogo dedicado (mismo patrón que Temporal) |
| Guardado de resultados correcto | N/A directo -- `MotionEvidence` viaja dentro del `Candidate` persistido (motor de Persistencia de Sesión, ya cerrado) |
| Rutas de salida controladas por el usuario | N/A (no produce archivos propios) |
| Tests unitarios | Sí -- 11 passed |
| Tests de integración | Sí -- consumido end-to-end dentro del bucle multiépoca de Discovery (`n_epochs_used == 3` en el test de integración ya existente) |
| Test de regresión | N/A directo -- nunca hubo una versión heredada que comparar (motor nativo desde su construcción original) |
| Validación con datos reales/controlados | Sí -- movimiento inyectado recuperado con exactitud sobre coordenadas reales de M31, ver arriba |
| Documentación actualizada | Sí -- este informe |
| Ningún placeholder presentado como funcionalidad | Sí -- ajuste real, nunca simulado |

## Validación de la suite completa

Sin cambios de código en este informe -- se reejecutaron los tests
directos del motor para confirmar el estado antes de cerrar (11
passed); la suite completa ya está validada íntegra desde el informe 97
(1726 passed, 24 skipped unit/integración/regresión; 214 passed humo
GUI), sin tocar nada desde entonces.

## CHECKPOINT

```
MOTOR: Motion
ESTADO: CERRADO
IMPLEMENTACIÓN: astrophysics_suite/temporal/motion.py
ENTRADA: SourceTrack con posiciones celestes y tiempos reales (>= 2 épocas)
SALIDA: MotionEvidence (pm_total/pm_ra/pm_dec con incertidumbre real, moving_source_candidate, épocas reales)
GUI: N/A directo -- corre dentro del pipeline automático de Discovery, sin diálogo dedicado
PROVENANCE: real (motor+versión+timestamp), cerrado en el informe 80, reverificado intacto
TESTS: 11 unitarios directos del motor
TESTS PASADOS: 11 directos del motor / 1726 de la suite completa (sin cambios en esta entrega)
TESTS FALLIDOS: 0
VALIDACIÓN REAL: sí (movimiento propio inyectado de 0.05"/h recuperado con exactitud sobre una traza real de 4 épocas construida sobre una fuente real de M31)
PROBLEMAS RESTANTES: ninguno bloqueante. registration_rms_arcsec sigue sin threading desde discovery/pipeline.py -- decisión correcta y ya documentada (informes 97 y este), no un cable suelto.
CONTRATO HACIA EL SIGUIENTE MOTOR (Physical): MotionEvidence real alimenta IdentificationState (MOVING_SOURCE_CANDIDATE) que consume Anomalía/Evidencia; Physical, en el código actual, opera sobre parámetros físicos inferidos por separado (fotometría/espectroscopía) sin consumir MotionEvidence directamente -- documentado con honestidad, no forzado.
```

## Cambio de motor

Motion cerrado bajo el checklist de 20 puntos: sin hallazgos que
corregir -- motor nativo desde su construcción original, sin
duplicación ni delegación en legacy, con su regla de significancia (3
épocas mínimas para tener residuo real) ya correctamente documentada y
reverificada intacta. Validado con movimiento propio inyectado
recuperado con exactitud sobre una traza real derivada de M31.
Siguiente en el orden fijo del usuario: **Physical**.
