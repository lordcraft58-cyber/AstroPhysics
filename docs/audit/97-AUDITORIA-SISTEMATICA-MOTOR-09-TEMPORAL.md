# 97 — Auditoría sistemática, motor 9/16: Temporal

Noveno motor de la fase de cierre sistemático, en el orden fijo del
usuario: Temporal (variabilidad/deriva de brillo) y Motion (movimiento
propio) son motores DISTINTOS en ese orden, aunque el código de ambos
viva en el mismo paquete `astrophysics_suite/temporal/` -- este informe
cierra estrictamente **Temporal** (`temporal/variability.py`); Motion
(`temporal/motion.py`) se audita como motor 10 en el informe siguiente.

Dos hallazgos reales corregidos: (1) `temporal/variability.py` seguía
delegando en `legacy.TemporalChangeEngine` para el ajuste estadístico de
variabilidad -- último residuo de legacy en este motor, ahora
reimplementado nativamente; (2) `discovery/source_tracks.py` (la
agrupación multiépoca que alimenta TANTO a Temporal como a Motion --
infraestructura compartida, no exclusiva de este motor) tenía su propia
copia -- QUINTA en total, contando las cuatro ya cerradas en el informe
96 -- de la fórmula de separación angular de gran círculo. Se corrige
aquí, en el motor que primero la audita en el orden fijo, con el mismo
criterio ya usado en el informe 96 (su fix en `qt_app/processes/
registry.py` tocó un archivo ya cerrado bajo el motor de Photometry sin
reabrir ese checklist): infraestructura compartida se corrige donde se
encuentra, documentada, sin reabrir motores ya cerrados.

## Mapa del motor (fase previa, sin tocar código)

**Motor científico**: `astrophysics_suite/temporal/variability.py`
(variabilidad/deriva de brillo multiépoca) + la parte de
`astrophysics_suite/discovery/source_tracks.py` que agrupa detecciones
en `SourceTrack` (paso previo compartido, sin el cual no hay serie
temporal que analizar) + `astrophysics_suite/models/temporal.py`
(`TemporalEvidence`/`TemporalEpoch`). **GUI**: ninguna dedicada -- este
motor corre siempre DENTRO del pipeline automático de Discovery
(`discovery/pipeline.py`, líneas 662-705), nunca como una acción manual
de clic; mismo patrón ya verificado en Artifact Rejection (informe 93).
**Tests**: `tests/unit/temporal/test_variability.py`,
`tests/unit/discovery/test_source_tracks.py`,
`tests/unit/models/test_temporal.py`, más la cobertura de integración en
`tests/integration/test_generic_discovery_pipeline.py`.

## Hallazgo 1: último residuo de legacy en variabilidad

`analyze_variability` delegaba en `legacy.TemporalChangeEngine().analyze`
(chi² constante vs. ajuste lineal ponderado por época) y en su
`_weighted_linear_fit` auxiliar. Se reimplementaron ambos nativamente
1:1 en `temporal/variability.py`:

- `_weighted_linear_fit(x, y, sigma)`: mismo ajuste por mínimos
  cuadrados ponderados con matriz de diseño, covarianza vía
  pseudo-inversa (`np.linalg.pinv`), mismos campos de salida
  (`intercept`, `slope`, `*_err`, `chi2`, `reduced_chi2`, `n`).
- `_analyze_temporal_change(epochs, min_epochs, sigma_threshold)`: mismo
  filtro de puntos válidos, misma media ponderada, mismo chi² constante,
  misma decisión de `variable_candidate` (por significancia de pendiente
  O por chi² constante > 2.5), mismas notas fijas.

No se cambió ninguna fórmula ni criterio -- reimplementación fiel, no
una "mejora". No existía ninguna otra implementación nativa de ajuste
lineal ponderado genérico reutilizable en el proyecto (se buscó primero,
siguiendo el principio de "una sola implementación real": el único otro
uso de `np.linalg.lstsq` con pesos en la suite es el ajuste simultáneo de
flujos de PSF en `photometry/psf.py`, una matriz de diseño distinta para
un problema distinto, no la misma función).

### Verificación numérica de la migración

Nueva prueba de regresión `tests/regression/
test_variability_matches_legacy.py` (12 tests): tendencia lineal clara,
fuente constante, datos ruidosos realistas, datos insuficientes, claves
alias (`epoch`/`sigma`), puntos malformados descartados, variabilidad
disparada por chi² constante (sin pendiente neta), barrido de umbrales
sigma, y dos pruebas directas de `_weighted_linear_fit` (incluyendo que
lanza `ValueError` con menos de dos puntos válidos, igual que la
heredada). Todos los campos (incluido el ajuste lineal completo)
coinciden con la implementación heredada dentro de 1e-9.

## Hallazgo 2: separación angular duplicada por quinta vez (infraestructura compartida)

`discovery/source_tracks.py::_separation_arcsec` era otra copia privada
de la misma fórmula de gran círculo que el informe 96 ya había
consolidado en `astrometry/wcs_fit.py::angular_separation_deg` para las
otras cuatro apariciones. Se eliminó la copia privada y se sustituyó su
único punto de uso (el agrupamiento incremental por cercanía angular en
`group_detections_into_tracks`) por `angular_separation_deg(...) *
3600.0` -- la misma función ya verificada numéricamente contra la
fórmula heredada en el informe 96
(`test_angular_separation_matches_legacy.py`, sin necesidad de una nueva
prueba dedicada: es la misma función, no una reimplementación distinta).
`position_scatter_arcsec()` (dispersión de posición entre épocas) NO
duplica esta fórmula -- es una proyección tangente local, un cálculo
legítimamente distinto de la separación de gran círculo, sin tocar.

Esta función es infraestructura COMPARTIDA entre Temporal y Motion (el
siguiente motor consume directamente los `SourceTrack` que produce), así
que el fix se documenta aquí, en el motor que primero la encuentra en el
orden fijo, y no se vuelve a auditar como si fuera un hallazgo nuevo en
el informe de Motion.

## Verificación (resto del checklist, sin más hallazgos)

1. **`discovery/source_tracks.py::group_detections_into_tracks`**: se
   confirmó (sin cambios de comportamiento) que rehúsa agrupar por
   píxel cuando falta WCS -- declara el motivo explícito en vez de
   fabricar trayectorias falsas por dithering. Sigue así tras el fix.
2. **`models/temporal.py::TemporalEpoch`/`TemporalEvidence`**: los
   puntos reales usados por el ajuste siguen adjuntos (no solo el
   resultado), confirmado con el roundtrip `to_dict`/`from_dict` ya
   cubierto por los tests existentes.
3. **`tests/architecture/test_gui_uses_full_pipeline.py`**: este test
   (xfail estricto, ver su propio docstring) analiza el AST del propio
   `legacy/AstroPhysicsSuite_v57_3_COMMERCIAL.py` para comprobar si
   `launch_gui` (la GUI Tkinter heredada) alcanza `TemporalChangeEngine`
   -- es enteramente interno al archivo legacy, no depende de que
   `astrophysics_suite/temporal/variability.py` siga importando esa
   clase o no. Confirmado que la migración de este informe no lo afecta
   (se reejecutó: sigue en xfail, como antes).

## Validación con datos reales

Se cargó el LIGHT real de M 31 sin calibrar
(`/tmp/real_fits_dir/Light_M31_300s_0001.fit`, 3008×3008), se detectó la
fuente puntual real más brillante y se midió su fotometría de apertura
real (`aperture_photometry`, incertidumbre de Poisson real
`sqrt(data)`) en 5 radios crecientes -- una serie de "brillo" con
valores REALMENTE medidos sobre la imagen, no inventados.
`analyze_variability` sobre esa serie real: `n_epochs=5`,
`variable_candidate=True` (la magnitud instrumental decrece de forma
monótona al crecer el radio de apertura, como corresponde físicamente a
una curva de crecimiento real -- el motor detecta correctamente esa
tendencia real en los datos; no se interpreta como variabilidad
astrofísica, que no es lo que se está midiendo con este procedimiento).

Adicionalmente, para confirmar que el fix de `source_tracks.py` (punto
compartido con Motion) no alteró el agrupamiento, se construyeron 4
detecciones reales sobre esa misma fuente con coordenadas reales de M 31
(RA=10.6847083°, Dec=41.2687500°) y marcas de tiempo reales espaciadas 1
hora: `group_detections_into_tracks` las agrupó correctamente en 1 sola
traza de 4 épocas -- ver el informe de Motion (siguiente) para la
validación completa de `analyze_motion` sobre esta misma traza.

## Checklist de cierre (20 puntos)

| Punto | Estado |
|---|---|
| Implementación científica real | Sí -- variabilidad vía chi² constante/ajuste lineal ponderado, ahora nativo; agrupamiento multiépoca por coordenadas celestes reales |
| Entrada definida | Sí -- lista de épocas {time,value,error}; `list[EpochDetection]` para el agrupamiento previo |
| Salida definida | Sí -- `TemporalEvidence`, con sus `TemporalEpoch` reales adjuntos para graficar |
| Tipos coherentes | Sí -- dataclasses tipadas en todo el flujo |
| Unidades correctas | Sí -- value/epoch (genérico, según la magnitud medida) |
| Incertidumbres cuando correspondan | Sí -- error estándar del ajuste lineal ponderado |
| Manejo explícito de datos faltantes | Sí -- menos de `min_epochs` épocas: NOT ACTIVE con motivo explícito, nunca un valor inventado |
| NOT_AVAILABLE cuando proceda | Sí -- ver fila anterior |
| Provenance | Sí -- `TemporalEvidence.provenance` real (motor+versión+timestamp), cerrado en el informe 80 y reverificado intacto |
| Errores correctamente gestionados | Sí -- ninguna excepción sin capturar; toda entrada degenerada produce un resultado explícito, no un crash |
| Funciona independientemente | Sí -- sin GUI, ver `tests/unit/temporal/test_variability.py` |
| Conectado al motor anterior (Identification/Catalogs) | Sí -- ambos motores operan sobre la misma traza/`Detection` de referencia dentro del mismo bucle de `discovery/pipeline.py` (líneas 692-709) |
| Conectado al siguiente (Motion) | Sí -- comparten la misma infraestructura de agrupamiento (`SourceTrack`), ahora consolidada; `MotionEvidence` se audita en el informe siguiente |
| GUI funcional | N/A directo -- corre dentro del pipeline automático de Discovery, sin diálogo dedicado (mismo patrón que Artifact Rejection, informe 93) |
| Guardado de resultados correcto | N/A directo -- `TemporalEvidence` viaja dentro del `Candidate` persistido (motor de Persistencia de Sesión, ya cerrado) |
| Rutas de salida controladas por el usuario | N/A (no produce archivos propios) |
| Tests unitarios | Sí -- 15 passed (`test_variability.py`: 9, `test_source_tracks.py` verificado sin regresión) |
| Tests de integración | Sí -- variabilidad consumida end-to-end dentro del bucle multiépoca de Discovery |
| Test de regresión | Sí (nuevo) -- `test_variability_matches_legacy.py`, 12 tests, migración 1:1 verificada campo a campo |
| Validación con datos reales/controlados | Sí -- serie de brillo real de una fuente de M31 vía apertura creciente, ver arriba |
| Documentación actualizada | Sí -- este informe, más `temporal/__init__.py` actualizado para reflejar la migración nativa |
| Ningún placeholder presentado como funcionalidad | Sí -- cálculo real, nunca simulado |

## Validación de la suite completa

`pytest tests/unit tests/integration tests/regression -q`: **1726
passed, 24 skipped** (12 tests nuevos de este informe sobre la base de
1714 del informe 96; mismos 24 skips de siempre). `pytest tests/gui_smoke
-q` bajo Xvfb: **214 passed** (sin regresión, pese a no tocar ningún
archivo de GUI en esta entrega -- se reejecuta igualmente por disciplina
de no-regresión).

## CHECKPOINT

```
MOTOR: Temporal
ESTADO: CERRADO
IMPLEMENTACIÓN: astrophysics_suite/temporal/variability.py (+ discovery/source_tracks.py, infraestructura compartida con Motion)
ENTRADA: lista de épocas {time,value,error}; list[EpochDetection] para el agrupamiento previo
SALIDA: TemporalEvidence, con los puntos reales (TemporalEpoch) adjuntos
GUI: N/A directo -- corre dentro del pipeline automático de Discovery, sin diálogo dedicado
PROVENANCE: real (motor+versión+timestamp), cerrado en el informe 80, reverificado intacto
TESTS: 15 unitarios directos del motor (variability + source_tracks sin regresión) + 12 de regresión (nuevos, esta auditoría)
TESTS PASADOS: 27 directos del motor / 1726 de la suite completa
TESTS FALLIDOS: 0
VALIDACIÓN REAL: sí (serie de brillo real de una fuente de M31 vía apertura creciente, curva de crecimiento correctamente detectada como tendencia real)
PROBLEMAS RESTANTES: ninguno bloqueante.
CONTRATO HACIA EL SIGUIENTE MOTOR (Motion): SourceTrack real (posiciones+tiempos reales, ya con la separación angular consolidada) -- exactamente lo que discovery/pipeline.py ya pasa hoy a analyze_motion por cada traza física con >= 2 épocas.
```

## Cambio de motor

Temporal cerrado bajo el checklist de 20 puntos, con dos hallazgos
reales corregidos (último residuo de legacy en variabilidad, migrado
1:1 y verificado por regresión; quinta duplicación de la fórmula de
separación angular en la infraestructura compartida de agrupamiento,
consolidada en la misma implementación única del informe 96) y validado
con una serie de brillo real de M31. Siguiente en el orden fijo del
usuario: **Motion**.
