# 47 — Construcción: motor de combinación/apilado de espectros 1D

Siguiente motor de la expansión de espectroscopía (docs/audit/13-...
§7, 45-..., 46-...), elegido por el mismo criterio que el de medición de
líneas: autocontenido (módulo nuevo, no toca ningún motor ya cerrado) y
de valor científico real directo -- combinar varias exposiciones del
mismo objeto mejora la señal/ruido, exactamente el motivo por el que
existe `scombine` en IRAF.

## Qué se construyó

`astrophysics_suite/spectroscopy/combine.py` -- `combine_spectra(
wavelengths, fluxes, flux_uncertainties=None, *, reference_wavelength=None,
method="median", sigma_clip=3.0, max_iters=5) -> CombinedSpectrum`,
equivalente propio de `scombine`:

- Remuestrea cada espectro de entrada (interpolación lineal) sobre una
  malla de longitud de onda común -- por defecto la del primer espectro,
  igual que `scombine` sin malla explícita.
- **Nunca extrapola**: un espectro de entrada solo contribuye en los
  puntos de la malla común que caen dentro de su propio rango real. Un
  punto sin ningún espectro que lo cubra queda en `NaN`, nunca en 0 ni
  en un valor inventado.
- Combina por `"mean"` o `"median"`, con rechazo real de atípicos
  (rayos cósmicos residuales de una sola exposición) por sigma-clipping
  robusto (MAD), cuando hay al menos 3 espectros con dato real en ese
  punto -- mismo algoritmo que ya usan `fit_continuum`/`trace_spectrum`.
- Propagación de error: con `flux_uncertainties` dadas y `method="mean"`,
  media ponderada por varianza inversa con propagación formal
  (`σ_combinada = 1/√(Σ 1/σᵢ²)`, verificado contra la fórmula cerrada).
  En cualquier otro caso, la incertidumbre combinada se estima de la
  dispersión muestral real entre espectros (`std/√n`) -- nunca inventada,
  pero tampoco disponible con un único espectro contribuyendo en ese
  punto (`NaN` honesto, no una incertidumbre fabricada de la nada).
- `n_combined`/`n_rejected` por punto, para que se pueda ver exactamente
  cuántas exposiciones sustentan cada parte del resultado.

Mismo principio de arrays sueltos que `trace.py`/`wavelength.py`/
`continuum.py`/`lines.py`, sin tipo `Spectrum` unificado (pieza de
arquitectura mayor y separada, sigue documentada aparte).

## Cableado en la GUI

Diálogo dedicado **Espectroscopía → "Combinar espectros..."**
(`qt_app/spectroscopy/combine_spectra_dialog.py`), mismo patrón que
"Registrar por WCS compartido..." (`RegistrationDialog`): combinar
necesita elegir varias ventanas MDI (dos o más), no encaja en el árbol
de procesos genérico que opera sobre una sola imagen activa. Lista con
checkboxes de las ventanas abiertas; cada una se trata como espectro 1D
por la fila central, **usando la calibración en longitud de onda real de
la ventana si ya se ajustó una** (`view.fitted_wavelength_solution`,
persistida desde "Calibrar longitud de onda...") o el eje de píxeles si
no -- y **rechaza explícitamente mezclar ventanas calibradas con no
calibradas** en vez de combinar longitudes de onda reales con índices de
píxel en silencio (harían falso "solape" o falta total de solape según
los rangos numéricos, un resultado sin sentido sin ningún error visible).
Selector de método (mediana/media) y umbral de sigma-clip. El resultado
se abre como una ventana nueva (tira 1D repetida, misma limitación ya
documentada para `spectroscopy.trace`: sin visor de espectros 1D
dedicado) y su tabla completa (longitud de onda, flujo, incertidumbre,
`n_combined`, `n_rejected`) queda exportable a CSV -- mismo mecanismo que
el resto de tablas del taller.

## Tests

- `tests/unit/spectroscopy/test_spectral_combine.py` (10 tests):
  media ponderada verificada contra la fórmula cerrada de varianza
  inversa; rechazo real de un pico de rayo cósmico inyectado en una sola
  exposición (verificado que se excluye y que el resultado se acerca al
  valor real, no solo "no lanza excepción"); mismo caso sin sigma-clip
  para confirmar que el atípico SÍ contamina la media cuando el rechazo
  está desactivado (contraste explícito); nunca extrapola más allá del
  rango propio de cada espectro; incertidumbre por dispersión muestral
  cuando no hay `flux_uncertainties`; `NaN` honesto con un solo espectro
  contribuyendo; validaciones de forma/monotonía/método.
  (Nombrado `test_spectral_combine.py`, no `test_combine.py`, para no
  chocar con el `tests/unit/reduction/test_combine.py` ya existente --
  pytest sin paquetes con `__init__.py` no tolera basenames duplicados.)
- `tests/integration/test_spectroscopy_combine_pipeline.py` (1 test):
  tres exposiciones 2D sintéticas independientes del mismo objeto
  (mismo continuo y línea reales, tres realizaciones de ruido distintas)
  -- cadena real completa `trace -> extract -> wavelength -> combine ->
  continuum -> measure_line` por exposición y sobre el resultado
  combinado; compara el error relativo de `integrated_flux` de
  `measure_line` entre una sola exposición y las tres combinadas --
  confirma una mejora real y sustancial de señal/ruido (no marginal),
  que es la razón de ser completa de este motor, no solo que la función
  "no lanza excepción". Sin sigma-clip en esta prueba a propósito (el
  rechazo ya tiene su prueba dedicada) para aislar la mejora de S/N del
  ruido estadístico propio de rechazar con muestras de tamaño 3.
- `tests/gui_smoke/test_qt_app_spectroscopy_combine_smoke.py` (3 tests):
  flujo completo del diálogo contra ventanas MDI reales (combinación
  real de dos ventanas, verificación de que rechaza mezclar calibración
  en longitud de onda, y el aviso al abrir el menú con menos de dos
  imágenes).

## Corrección durante el desarrollo

La primera versión de la prueba de integración exigía que las tres
exposiciones contribuyeran siempre a los 240 puntos combinados
(`n_combined == 3` en todos), con sigma-clip activado. Falló de forma
intermitente: con solo 3 muestras por punto, el sigma robusto (MAD) es
estadísticamente inestable -- una simulación numérica confirmó una tasa
real de rechazo espurio de ruido gaussiano puro de ~11% por punto con
n=3 (bajando gradualmente, no de forma abrupta, hasta ~2% con n=20; no
es un fallo de una sola implementación, es una propiedad conocida del
sigma-clip por MAD con muestras pequeñas, el mismo algoritmo que ya usan
`fit_continuum`/`trace_spectrum` sobre cientos de puntos donde este
efecto es invisible). La corrección real no fue "ajustar el umbral hasta
que pasara": la prueba de rechazo de atípicos ya existe por separado
(`test_spectral_combine.py`, con 6-8 espectros y comprobando solo la
columna con el pico inyectado, nunca "todas las demás columnas"); la
prueba de mejora de S/N no necesita sigma-clip para demostrar su punto,
así que se desactivó ahí (`sigma_clip=None`) -- aislando cada prueba de
lo que realmente valida, en vez de mezclar dos propiedades estadísticas
distintas en una sola aserción frágil.

También se detectó una colisión de nombre de módulo de test
(`tests/unit/reduction/test_combine.py` ya existía, para combinar
fotogramas CCD) al ejecutar la suite completa por primera vez --
corregido renombrando el archivo nuevo a `test_spectral_combine.py`.

## Validación

| conjunto | comando | resultado |
|---|---|---|
| Unit + integración + regresión | `pytest tests/ --ignore=tests/gui_smoke` (venv `aps-test`) | **685 passed, 21 skipped, 1 xfailed** (antes: 674) |
| GUI smoke completa | `xvfb-run pytest tests/gui_smoke/` (venv `aps-gui`) | **121 passed** (antes: 118) |

## Deliberadamente NO tocado en esta pasada

- **Visor de espectros 1D dedicado.** Misma limitación ya documentada
  para `spectroscopy.trace`/`spectroscopy.continuum`/`spectroscopy.line`
  desde la Fase 9.5 -- un widget de gráfico 1D real es una pieza de UI
  mayor y separada.
- **Alineación por correlación cruzada antes de combinar** (para
  exposiciones con un desplazamiento en longitud de onda real entre
  sí, p. ej. por flexión instrumental entre exposiciones). `scombine`
  real de IRAF asume las entradas ya alineadas o remuestreadas a una
  base común -- este motor sigue esa misma asunción explícitamente
  (interpolación sobre la malla de referencia, sin buscar un
  desplazamiento óptimo). Añadir esa alineación es una capacidad nueva y
  separada (emparentada con `reidentify`), no parte de "combinar
  espectros ya en la misma base".
- **Extracción multi-apertura, tipo `Spectrum` unificado.** Siguen como
  PENDIENTE documentado en `docs/audit/13-...` §7, sin resolver aquí.

## Cambio de motor

Motor #85 cerrado. Disponible para el siguiente motor según criterio
propio de prioridad, sobre el mismo backlog documentado en los informes
45-47 (artefactos DONUT/GRADIENT, cableado de `spectroscopy.fluxcal` --
bloqueado por falta de catálogo de flujos estándar externo --,
extracción multi-apertura, tipo `Spectrum` unificado, u otras brechas
todavía abiertas).
