# 55 — Espectroscopía, slice 1: nunca un flujo inventado

## Alcance de este informe

El usuario pidió una reingeniería profunda del módulo de espectroscopía
inspirada conceptualmente en ISIS (Christian Buil), con 79 secciones:
modelo de datos, trazas multiapertura, cielo, píxeles malos/rayos
cósmicos, preprocesado por lotes, calibración de longitud de onda
(lámpara, sintética, predefinida, por estrella de referencia, lateral),
WCS espectral, respuesta instrumental, calibración de flujo,
normalización, base de datos de líneas, medidas espectroscópicas,
velocidad radial, aire/vacío, comparación con plantillas, objetos
extendidos, visores 2D/1D, control de calidad, resolución espectral,
generadores sintéticos, pipeline automático + modo manual, historial de
procesamiento, productos FITS, trazabilidad completa, corrección de
drift, calibración lateral, líneas telúricas, extinción atmosférica,
CALSPEC, magnitudes fotométricas, rectificación geométrica, soporte
échelle y fusión de órdenes, propagación de incertidumbres/covarianza,
resampling, cross-correlation, RV multi-línea, correcciones
baricéntrica/heliocéntrica, ajustes Gaussian/Voigt, diagnóstico de
calidad 2D, saturación/gain/read-noise, monitorización de directorio,
apilado espectral, versionado, base de datos de instrumentos, quick
look vs. reducción científica, informes PDF/HTML, motor de validación
física, API interna separada de la GUI, y reproducibilidad vía
configuración exportable.

**Eso es, de manera realista, muchas semanas de trabajo de ingeniería
de software científico -- no una sola sesión.** Intentar "completarlo"
todo de un golpe habría significado una de dos cosas, ambas
inaceptables para este proyecto: escribir miles de líneas sin validar
de verdad y llamarlas "hecho" (exactamente la deshonestidad epistémica
que el propio encargo prohíbe explícitamente en su punto 41), o recortar
el alcance en silencio sin decirlo. Ninguna de las dos.

**Lo que se hace aquí es la Slice 1**: la base de datos (§1 parcial) y
el arreglo del defecto real y concreto que el usuario señaló con
evidencia (§30, "caídas a cero") -- verificado, diagnosticado hasta la
causa raíz exacta, y corregido con rigor sobre los 4 archivos FITS
reales que el usuario adjuntó. Las secciones restantes (calibración de
longitud de onda con lámpara real §8-16, respuesta instrumental §17,
normalización de continuo dedicada §19 -- ya existe una versión básica
en `continuum.py`, base de datos de líneas §20 -- ya existe una versión
en `lines.py`, velocidad radial §23, échelle §52-53, telúricas §46,
extinción §47, informes §75, etc.) quedan **pendientes y enumeradas al
final**, para continuar motor a motor con el mismo rigor que el resto de
este proyecto.

## El hallazgo real: `flux[col] = 0.0` nunca sobrescrito

**Síntoma reportado por el usuario**: profundas depresiones verticales
que llegan casi a cero en los espectros de Vega.

**Causa raíz, encontrada por auditoría de código y confirmada con los 4
archivos FITS reales adjuntados** (`Vega_1sec_1x1__frame6.fit`,
`veg_stacked.fits`, `T-CrB_900sec_1x1__frame6.fit`, `T-CrB.fits`):

`astrophysics_suite/spectroscopy/trace.py::extract_sum`/`extract_optimal`
inicializaban `flux = np.zeros(n_columns)` y, en varias rutas, dejaban
ese `0.0` sin sobrescribir:

- `extract_sum`: ninguna, pero el fondo se restaba de una suma cuyo
  número de píxeles reales podía ser distinto del nominal sin decirlo.
- `extract_optimal`: `if lo < 0 or hi > height: continue` (la apertura
  no cabía entera cerca de un borde) y `if denominator <= 0: continue`
  (perfil/varianza degenerados en esa columna) dejaban la columna en
  `flux[col] = 0.0` -- **un valor de flujo perfectamente creíble para
  cualquier consumidor posterior**.

El consumidor real es `qt_app/spectroscopy/spectrum_view.py`, cuyo
`_build_path` **ya estaba preparado** para abrir un hueco real en el
trazado ante cualquier punto no finito (`NaN`/`Inf`) -- pero nunca
recibía uno: recibía un `0.0` con apariencia de dato real, que se
dibujaba como una caída vertical profunda hasta el eje. Productor y
consumidor tenían contratos incompatibles: uno prometía nunca inventar
un cero, el otro lo producía sin darse cuenta.

Además, un segundo defecto relacionado: `trace_spectrum` no tenía
ningún concepto de píxel inválido. Un solo `NaN` dentro de la ventana de
búsqueda contaminaba `total_weight` a `NaN` -- y como `NaN <= 0` es
`False` en Python/numpy, el guardia que debía saltar esa columna nunca
se disparaba. El `NaN` se propagaba a `current_center`, y la columna
siguiente reventaba con `ValueError: cannot convert float NaN to
integer` al intentar redondear un centro ya contaminado. Con datos
reales (una cámara real tiene píxeles muertos, y la máscara de
saturación puede introducir `NaN`), esto no era un caso de esquina
teórico.

## Auditoría con los 4 archivos reales

| Archivo | Forma | Píxeles `== 0` (todo el frame) |
|---|---|---|
| `Vega_1sec_1x1__frame6.fit` (crudo, 16 bits) | 1039×1391 | 1397 |
| `veg_stacked.fits` (apilado Siril, 10 subs) | 1039×1391 | 1038 |
| `T-CrB_900sec_1x1__frame6.fit` (crudo, 16 bits) | 1039×1391 | 1522 |
| `T-CrB.fits` (apilado Siril) | 1039×1391 | 797 381 (55 % del frame) |

Los 1397 píxeles muertos reales del frame de Vega crudo incluían **27
dentro de la propia banda espacial de la traza** -- exactamente el tipo
de evidencia que el motor de extracción, sin ningún concepto de
"píxel malo", trataba como flujo real.

**Hallazgo adicional, no anticipado**: la traza en `T-CrB.fits`
(apilado) da un RMS de **12.99 px** con los parámetros por defecto,
frente a 0.08-0.11 px en los otros tres archivos -- señal real de que la
posición inicial supuesta (fila 602, la misma que funciona para Vega)
no corresponde a una traza limpia en ese apilado concreto (más de la
mitad del frame es literalmente cero, compatible con un desalineamiento
fuerte entre subexposiciones durante el apilado). Esto no es un defecto
del motor de trazado -- es precisamente el tipo de aviso que
`TraceResult.n_columns_used_for_fit` ya expone, y que un futuro QC
(§31/§76, pendiente) debería convertir en un `CALIBRATION WARNING`
visible en vez de dejarlo enterrado en un número.

## Lo hecho

### 1. `astrophysics_suite/spectroscopy/frame2d.py` (nuevo)

Modelo de datos (§1 parcial): `PixelFlag` (`NONFINITE`, `SATURATED`,
`DEAD`, `COSMIC_RAY`, `USER_MASKED`, combinables a nivel de bits),
`build_pixel_mask()` (nunca infiere un defecto de los propios valores
salvo `NONFINITE`, que no es una opción; `SATURATED` solo con
`saturate_adu` real; `DEAD`/`COSMIC_RAY`/`USER_MASKED` solo con máscara
aportada), `SpectralFrame2D` (imagen 2D + varianza/máscara/cabecera
opcionales, `.uncertainty` = `None` real si no hay varianza, nunca un
valor inventado).

### 2. `astrophysics_suite/spectroscopy/trace.py` (reescrito)

- `trace_spectrum`: acepta `mask`; excluye SIEMPRE los no finitos del
  centroide (con o sin máscara externa) -- ya no puede reventar por un
  NaN. `TraceResult` gana `n_columns_used_for_fit` (cuántas columnas
  sostienen de verdad el ajuste).
- `estimate_sky_background` (antes `_background_per_column`, privada):
  regiones de cielo EXPLÍCITAS (`SkyWindow`, §5) en vez de un único
  desplazamiento simétrico; reductor seleccionable (`median`/`mean`/
  `sigma_clip`); consciente de la máscara; si ninguna ventana aporta un
  solo píxel utilizable, la columna queda `valid=False` y `level=NaN`
  -- nunca `0.0`.
- `extract_sum`/`extract_optimal`: **`flux`/`flux_uncertainty` son
  `NaN` en cualquier columna que no se pudo medir, nunca `0.0`**. Cada
  `ExtractedSpectrum` gana `valid`, `n_pixels_used`, `n_pixels_rejected`
  y el `SkyEstimate` usado -- trazabilidad real de cuánta apertura
  contribuyó a cada punto. Una apertura parcialmente enmascarada (un
  píxel muerto real dentro de la ventana) se renormaliza por la
  fracción de apertura realmente medida, en vez de aparecer más tenue
  solo por tener un píxel menos.

### 3. Callers actualizados

`multiaperture.py` y `qt_app/processes/registry.py` (el flujo real de
la GUI, `spectroscopy.trace`/`spectroscopy.multiaperture` en el taller
de procesos) migrados a la nueva firma; las medianas de S/N y de flujo
que se muestran en el registro/tabla usan ahora `nanmedian`, para no
dejar que una columna inválida arrastre la estadística hacia abajo por
la puerta de atrás.

## Validación

**Sintética** (`tests/unit/spectroscopy/test_trace.py`, 13 pruebas): un
NaN en la ventana de búsqueda ya no revienta el trazado; una apertura
que cae fuera de la imagen queda `NaN`+`valid=False`, nunca `0.0`; una
apertura parcialmente enmascarada se renormaliza; una columna
totalmente enmascarada queda inválida sin afectar a sus vecinas; el
cielo sin píxeles utilizables queda `NaN`, nunca `0.0`; el reductor
`sigma_clip` rechaza un resto de fuente real contaminando una ventana de
cielo. `tests/unit/spectroscopy/test_frame2d.py` (13 pruebas): un 0
válido nunca se marca malo; NaN/Inf siempre se marcan sin configuración;
la saturación queda inactiva sin un `SATURATE` real; nada se infiere sin
evidencia aportada.

**Real, los 4 archivos del usuario**: ninguna de las 8 combinaciones
(4 archivos × 2 métodos de extracción) produce un solo `flux == 0.0` en
una columna inválida -- el único `0.0` que aparece (`veg_stacked`,
1 columna) está en una columna **válida**, donde absolutamente todos los
píxeles de entrada (apertura y las dos ventanas de cielo) son
literalmente `0.0` sin enmascarar: el borde de recorte de la
alineación de Siril, un caso real de "0 válido" -- exactamente la
distinción que pedía el punto 6 del encargo, y que el motor ahora
respeta en vez de arbitrarla.

Suite completa tras el cierre de esta slice: **786 pasadas, 24
saltadas, 1 xfailed** (`aps-test`, +29 sobre el cierre anterior de
Detection) y **149 pasadas** de humo GUI (`aps-gui`, sin cambios: no se
tocó ninguna pantalla). `ruff` limpio.

## Checklist de la slice

| Fase | Estado |
|---|---|
| IMPLEMENTACIÓN | `frame2d.py` (nuevo) + `trace.py` (reescrito) |
| CONTRATO | `PixelFlag`, `SpectralFrame2D`, `SkyWindow`/`SkyEstimate`, `ExtractedSpectrum.valid/n_pixels_used/n_pixels_rejected` |
| GUI | `spectroscopy.trace`/`spectroscopy.multiaperture` migrados sin cambiar su interfaz visible; el visor ya sabía dibujar huecos NaN (`test_qt_app_spectrum_view_smoke.py`, sin cambios) |
| PROVENANCE | cada `ExtractedSpectrum` sabe cuántos píxeles reales contribuyeron a cada punto y de dónde salió el cielo |
| UNIT TEST | `test_trace.py` (13) + `test_frame2d.py` (13), todas nuevas o actualizadas |
| FITS REAL | los 4 archivos del usuario -- ver tabla arriba |
| CERRADO (esta slice) | sí |

## Pendiente -- el resto del encargo, motor a motor

Explícitamente NO abordado en esta slice, para continuar con el mismo
rigor (no una lista de promesas, una lista de trabajo futuro real):

- **Rayos cósmicos (§6)**: `imtools/cosmic_rays.py` ya existe (L.A.Cosmic
  real, probado, usado en reducción) y es reutilizable directamente
  como paso de preprocesado 2D antes de `trace_spectrum` -- integrarlo
  explícitamente en el flujo de espectroscopía (hoy solo se usa en
  `reduction/`) es la primera pieza pendiente, no una reescritura.
- **Calibración de longitud de onda con lámpara real (§8-16)**: existe
  `wavelength.py` con detección de picos y ajuste polinómico -- falta
  el catálogo de líneas por lámpara (Ne/Ar/He/HeNeAr/ThAr), el modo
  simulación marcado explícitamente (`CALTYPE='SYNTHETIC'`), la
  reutilización de una solución instrumental previa y la calibración
  lateral/simultánea.
- **WCS espectral real (§16)**: escribir `CTYPE1='WAVE'` con la solución
  real (lineal o no) al FITS, y recuperarlo al reabrir.
- **Respuesta instrumental y calibración de flujo (§17-18)**: no existe
  todavía; `fluxcal.py` tiene un esqueleto bloqueado por falta de
  catálogo de estrellas estándar (ya anotado en informes anteriores).
- **Base de líneas + medidas avanzadas (§20-22, §62)**: `lines.py` ya
  mide EW/FWHM/profundidad de una línea dada su posición; falta la
  base de datos catalogada por elemento/ionización y la identificación
  automática tras calibrar.
- **Velocidad radial (§23, §58-61)**: no existe todavía.
- **Aire/vacío (§24)**: no existe todavía.
- **Objetos extendidos/multi-región (§27)**: `multiaperture.py` ya
  soporta varias trazas; falta el modo "región espacial ancha sin PSF
  puntual" para nebulosas.
- **Échelle (§52-53), telúricas (§46), extinción (§47), CALSPEC (§49),
  magnitudes (§50), rectificación geométrica (§51), resampling con
  metadatos de correlación (§55-57), pipeline automático con checklist
  visible (§34, §73), historial JSON reproducible (§36, §78), informe
  PDF/HTML (§75), base de datos de instrumentos (§71), quick look
  marcado explícitamente (§72)**: no existen todavía.

El orden de continuación natural, dado lo ya cerrado en este proyecto:
cielo con rayos cósmicos integrados → calibración de longitud de onda
con lámpara real y WCS espectral → respuesta instrumental → base de
líneas + medidas → el resto, motor a motor, con el mismo protocolo que
ya cerró IO/FITS, Reducción, Astrometría y Detección.
