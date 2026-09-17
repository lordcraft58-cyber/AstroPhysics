# 41 — Investigación del motor de Fotometría PSF: PENDIENTE (no cerrado, código revertido)

Informe según el protocolo de 10 fases pedido explícitamente. Motor
candidato: `photometry/psf.py` (ajuste gaussiano de fuente única como
contraste real e independiente al flujo de apertura ya conectado en el
cierre 38). **Resultado: PENDIENTE, no CERRADO ni REAL PERO LIMITADO.**
Todo el código de conexión (`quality.py`, `discovery/pipeline.py`,
`models/candidate.py`, GUI, tests) se implementó, se probó con datos
sintéticos, y se **revirtió por completo** tras encontrar una
discrepancia real y no resuelta al validar con píxeles reales de M31 --
ningún cambio de este intento quedó en el repositorio.

## FASE 1 — Auditoría

`photometry/psf.py` (449 líneas): `fit_group_psf_photometry`,
`fit_group_psf_photometry_with_position_refinement`,
`compute_psf_fit_diagnostics`, `select_psf_reference_stars`,
`build_empirical_psf`, modelos `GaussianPSF`/`MoffatPSF`/`EmpiricalPSF`
-- real, maduro, con proceso manual en GUI (`qt_app/processes/
registry.py::_run_psf_photometry`, Fases 17/19) y tests unitarios
propios (`tests/unit/photometry/test_psf.py`) que usan exclusivamente
estrellas gaussianas **aisladas sobre fondo plano**. Cero llamadores
desde `characterize_point_source`/Discovery automático -- mismo perfil
que aperture/calibración antes de sus cierres.

## FASE 2 — Contrato (el que se implementó y luego se revirtió)

`_measure_psf_flux(data, x_px, y_px, fwhm_px) -> tuple[Quantity,
Quantity | None] | None` en `photometry/quality.py`: ajuste de un
`GaussianPSF` de fuente única (sigma derivado del mismo FWHM ya medido,
`fit_half_size = 3x FWHM`, `fit_sky=True`), devolviendo flujo PSF +
chi² reducido (`compute_psf_fit_diagnostics`). Se añadieron
`Candidate.psf_flux`/`psf_fit_reduced_chi2` (contrato mínimo necesario
para que el resultado llegara al candidato) y una fila en
`candidate_detail_widget.py`.

## FASE 3 — Implementación

Implementado exactamente como en Fase 2, siguiendo el mismo patrón que
`_measure_aperture_flux` (Fase 38). **Lint limpio, 3 tests unitarios
nuevos pasaron a la primera** con estrellas gaussianas sintéticas
puras: flujo recuperado a <1% del valor inyectado, chi² reducido < 1
para un perfil que sí es gaussiano, y un chi² marcadamente mayor (>10x)
para un perfil deliberadamente no gaussiano (top-hat) -- el mecanismo
en sí funciona correctamente cuando el modelo coincide con los datos.

## FASE 4-6 — Integración/GUI/Salidas

Conectado exactamente igual que el cierre 38 (misma disciplina de
"cambios mínimos de contrato"): `Candidate.psf_flux`/
`psf_fit_reduced_chi2`, fila nueva en el detalle del candidato. GUI
verificada con humo real (Discovery completo -> fila renderiza un
valor). Hasta este punto, indistinguible en rigor de los tres cierres
anteriores de esta sesión.

## FASE 7-8 — Tests y Validación: AQUÍ SE ENCONTRÓ EL PROBLEMA REAL

Integración sintética (8/8 pruebas pasaron, incluida GUI): sobre
campos limpios (fondo plano, fuente gaussiana aislada, sin estructura
extendida real), PSF y apertura coinciden dentro de 5-10%, exactamente
lo esperado.

**Validación con píxeles reales de M31** (mismo archivo que los
cierres 38/39, `dbxtract_HA_registered.fit`) -- la comprobación
obligatoria antes de declarar cualquier cierre -- reveló un problema
real, no supuesto:

1. **Primer síntoma:** sobre fuentes reales de M31, el flujo PSF
   discrepaba de la apertura por factores de 3x a >100x, y en dos de
   tres fuentes probadas el ajuste devolvía **flujo negativo** -- una
   fuente real, claramente detectada y brillante, "midiendo" un flujo
   negativo es una señal inequívoca de que algo está mal, no ruido de
   medición.

2. **Causa raíz nº1, encontrada y confirmada:** `fit_group_psf_
   photometry(..., fit_sky=True)` absorbe el cielo local con **una
   única constante** por caja de ajuste. Inspeccionando los píxeles
   reales alrededor de una de las fuentes fallidas, el "cielo" real no
   es plano: hay un gradiente real y sustancial (la emisión Hα difusa
   de M31 varía de forma continua incluso dentro de una caja de
   25×25 px). Un modelo de cielo constante frente a un fondo con
   pendiente real produce, con mínimos cuadrados ponderados, una
   amplitud de fuente sesgada -- en el caso peor, negativa. Confirmado
   con un experimento controlado (`diag29`, `diag30` en el scratchpad de
   la sesión): restar primero un cielo local robusto (`estimate_local_
   sky`, el mismo método MAD-clip por anillo que ya usa con éxito la
   apertura) y ajustar con `fit_sky=False` elimina los flujos
   negativos.

3. **Causa raíz nº2, encontrada pero NO resuelta dentro de este
   intento:** incluso tras corregir el cielo (Pase 2), el flujo PSF
   siguió siendo sistemáticamente MENOR que la apertura por un factor
   de ~2 a ~12x en las fuentes reales de M31 probadas (`diag30`).
   Inspeccionando el perfil radial real de una fuente (`diag31`): el
   valor por encima del fondo a un radio de varios FWHM sigue siendo
   real y no despreciable -- compatible con que la apertura (que suma
   TODO lo que hay dentro de un radio de 3xFWHM, venga de donde venga)
   esté integrando flujo real de estructura difusa circundante
   (nebulosidad Hα real de M31, no ruido) que un ajuste de PSF
   compacta, por diseño, deliberadamente NO le atribuye a la fuente
   puntual. **No se ha determinado con la rigurosidad que este
   proyecto exige cuál de las dos cantidades -- o ninguna -- es "la
   correcta" para esta imagen en particular**, ni si la magnitud de la
   discrepancia observada es la esperada físicamente o sigue
   apuntando a un problema adicional no identificado (p. ej., si el
   propio FWHM heredado de `measure_source_quality` está sistemáticamente
   sesgado en campos con estructura difusa real, cosa que no se
   descartó).

**Ningún test sintético de este intento -- ni los que ya existían en
`test_psf.py`, ni los 3 que yo mismo añadí -- ejercita esta situación**
(fondo con gradiente real, fuente embebida en estructura extendida
real): todos usan fondo perfectamente plano. Esa es la brecha real de
cobertura que la validación con FITS reales existe para encontrar, y la
encontró.

## FASE 9 — Cierre: PENDIENTE

**Motor: Fotometría PSF -- PENDIENTE.** No se marca CERRADO ni REAL
PERO LIMITADO: a diferencia de las limitaciones honestas y acotadas de
los cierres 38-40 (una salida que faltaba, una dimensión que no se
podía calcular sin otro motor), aquí el propio **contenido científico
del flujo PSF es de fiabilidad no establecida** sobre campos con
estructura difusa real como M31 -- justo el tipo de campo que esta
aplicación existe para analizar. Publicarlo como si fuera una medida
de confianza equivalente al flujo de apertura, con la evidencia
disponible hoy, habría sido exactamente el "falso éxito" que este
proyecto prohíbe explícitamente.

**Decisión tomada: revertir todo el código de este intento** (`git
checkout --` sobre los 7 archivos tocados) en vez de dejarlo a medias
o marcado como limitado. El repositorio queda exactamente como al
cierre del motor de Persistencia de Sesión (commit `6018dc9`); la
suite completa se confirmó de nuevo en verde (593 passed, 37 skipped,
1 xfailed) tras el revert, sin ningún resto de este intento.

**Qué haría falta para cerrar esto de verdad en una ronda futura**
(no intentado aquí, para no ampliar el alcance de una conexión que ya
resultó más profunda de lo esperado):
- Un modelo de cielo local no constante para el ajuste PSF (p. ej. un
  plano o una superficie de bajo orden ajustada dentro de la misma caja,
  o restar un cielo robusto por anillo como ya hace la apertura antes
  de pasar los datos al ajuste -- el fix parcial de la causa raíz nº1
  ya apunta en esa dirección).
- Una decisión explícita, informada por alguien con criterio científico
  sobre el campo concreto (o el propio usuario), de qué cantidad es la
  que se quiere: flujo del punto fuente aislado de su entorno (lo que
  da PSF), o flujo total dentro de una apertura fija incluyendo
  estructura circundante real (lo que da apertura) -- ambas son
  medidas reales y legítimas, pero de cosas distintas, y esta ronda no
  tenía mandato para tomar esa decisión de diseño científico por su
  cuenta.
- Validación real adicional en campos de estrellas de campo aisladas
  (lejos del disco de M31) para confirmar que, en el régimen donde SÍ
  se espera acuerdo, el motor lo cumple también con píxeles reales (no
  solo sintéticos) -- no se llegó a probar por quedar bloqueado en el
  hallazgo anterior.

## FASE 10 — Cambio de motor

Sin cierre que entregar (por diseño: PENDIENTE, código revertido).
Continuando la evaluación de prioridad para el siguiente motor, tal
como pidió el usuario ("sigue evaluando sin parar").
