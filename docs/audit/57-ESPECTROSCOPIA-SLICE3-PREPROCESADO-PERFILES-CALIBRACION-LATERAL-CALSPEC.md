# Informe 57 — Espectroscopía slice 3: preprocesado con rayos cósmicos integrados, perfiles de instrumento reutilizables, calibración lateral/simultánea y biblioteca CALSPEC

Continuación de los informes 55 (modelo de datos + fin del cero silencioso) y
56 (calibración en longitud de onda). Cierra la tarea de tablero
**#95 — "Espectroscopía slice 3: rayos cósmicos integrados + calibración
lateral/predefinida + CALSPEC"**, cuatro piezas del encargo original de 79
secciones que quedaban pendientes tras el informe 56: §7 (preprocesado
completo), §12 (perfiles de instrumento reutilizables), §14/§45 (calibración
lateral/simultánea) y §49 (biblioteca de estándares al estilo CALSPEC).

## 1. Preprocesado espectroscópico con rayos cósmicos integrados (§7)

`astrophysics_suite/spectroscopy/preprocessing.py` (nuevo) —
`preprocess_spectroscopic_frame()` orquesta la cadena fija que pide el
encargo, **RAW → BIAS → DARK → FLAT → MÁSCARA DE PÍXELES DEFECTUOSOS →
LIMPIEZA DE RAYOS CÓSMICOS → 2D CIENTÍFICA**, componiendo motores YA
probados en vez de reimplementarlos:

- `reduction.calibration.calibrate_frame` — bias/dark/flat/máscara de
  píxeles defectuosos y propagación de varianza (ya usado y probado desde
  el motor de Reducción, informe 52).
- `imtools.cosmic_rays.detect_cosmic_rays` — L.A.Cosmic, ya usado y
  probado en `reduction/`.

El resultado es un `SpectralFrame2D` (del informe 55) con la `PixelFlag.
COSMIC_RAY` fijada donde corresponda. **Por defecto los píxeles de rayo
cósmico se marcan pero NO se interpolan** (`apply_cosmic_ray_interpolation=
False`): el valor bruto (inflado) se conserva y solo la máscara cambia, para
no perder información real por una interpolación que el usuario no pidió
explícitamente. Si se activa la interpolación, el bit de máscara sigue
puesto -- nunca se borra el rastro de que ese píxel fue sustituido.

**Validado con datos reales**: sobre `Vega_1sec_1x1__frame6.fit` (la
exposición cruda real del usuario), el preprocesado corre de extremo a
extremo sin excepciones, la máscara resultante alimenta directamente
`trace_spectrum`/`extract_sum` del slice 1 (traza con RMS=0.03 px, 837/1391
columnas usadas en el ajuste), y **solo 2 de 1391 columnas quedan
inválidas** (marcadas `NaN`, nunca `0.0`).

**Hallazgo real, no un fallo del código**: una columna extraída (columna 0,
el borde del sensor) da flujo neto exactamente `0.0` -- investigado a
propósito porque el propio principio del encargo es "nunca 0.0 silencioso".
La inspección de los 13 píxeles de esa columna muestra que son
**genuinamente 0.0 en el dato crudo** (borde del sensor Atik, sin máscara de
píxel muerto real disponible para esta cámara) y el cielo estimado ahí
también es 0.0 -- el sistema hace exactamente lo correcto: no inventa un
píxel muerto que no puede confirmar (mismo principio de `frame2d.py`: un
0.0 real nunca se marca malo automáticamente), y reporta el cálculo honesto
de "0.0 de entrada real → 0.0 de salida real", que es un caso categóricamente
distinto del bug original (columna sin evidencia usable rellenada con 0.0
en vez de `NaN`). Documentado aquí en vez de "arreglado" porque no hay nada
que arreglar: es una propiedad real del borde de este sensor concreto.

7 tests unitarios nuevos (`tests/unit/spectroscopy/test_preprocessing.py`):
posiciones reales de rayos cósmicos inyectados, no-interpolación por
defecto, interpolación explícita opcional, detección desactivable con
recuento honesto de cero, aplicación real de bias/flat, propagación de
varianza no inventada, saturación marcada solo con un `SATURATE` real.

## 2. Perfiles de calibración espectral reutilizables (§12)

`services/spectral_calibration_profiles.py` (nuevo) -- mismo patrón que
`services/instrument_profiles.py` (Fase 10.2): JSON bajo el directorio de
configuración del usuario, en la capa de servicios porque tocar disco no es
responsabilidad del motor científico.

- `SpectralCalibrationProfile`: coeficientes, grado, RMS, desplazamiento de
  referencia, nº de líneas usadas/rechazadas, lámpara, y opcionalmente el
  **espectro de lámpara original** (para poder recalcular solo el
  desplazamiento más adelante).
- `profile_from_record()`: empaqueta una `WavelengthCalibrationRecord` ya
  validada como perfil -- **rechaza explícitamente guardar una calibración
  `SYNTHETIC`** como perfil de instrumento (presentar una calibración de
  prueba como si fuera una solución validada sería exactamente la mentira
  que prohíbe el encargo).
- `SpectralCalibrationProfile.to_record()`: reutiliza la solución **tal
  cual**, marcada `CalibrationSource.REUSED_INSTRUMENTAL` -- nunca como si
  se acabara de medir en la observación actual.
- `reidentify_profile_offset()`: recalcula **solo el desplazamiento global
  A0** por correlación cruzada (reutiliza `wavelength.
  reidentify_wavelength_solution`, ya probado desde la Fase 15) contra el
  espectro de lámpara guardado en el perfil -- **nunca un reajuste completo
  de la forma del polinomio sin nueva evidencia de líneas**, tal como pide
  el encargo verbatim ("Permitir recalcular únicamente el desplazamiento
  global A0... indicar claramente que un cambio temporal/mecánico del
  instrumento puede desplazar el espectro").

Para que ese aviso sea automático y no dependa de que nadie se acuerde de
escribirlo, `WavelengthCalibrationRecord` (en `calibration_provenance.py`)
gana un campo nuevo, aditivo, `offset_only_reidentified: bool = False`;
`build_wavelength_provenance` añade el aviso de deriva mecánica/térmica
solo cuando ese campo es `True` -- una reutilización tal cual (`to_record()`,
sin recalcular nada) NO dispara ningún aviso nuevo, y el test ya existente
`test_reused_instrumental_source_is_measured` (que espera
`warnings == ()` para un `REUSED_INSTRUMENTAL` liso) sigue pasando sin
tocarlo: el aviso es específico del caso que de verdad lo necesita.

**GUI** (`qt_app/spectroscopy/wavelength_fit_dialog.py`): nueva fila
"Perfil de instrumento" con un combo de perfiles guardados y dos botones,
"Usar tal cual" y "Recalcular solo offset (A0)", más un botón "Guardar como
perfil..." junto a "Ajustar solución" (solo disponible tras un ajuste real
por líneas, nunca sobre una solución ya reutilizada de otro perfil). El
flujo completo -- ajustar con líneas reales, guardar como perfil, y
reutilizarlo desde una segunda y tercera ventana sin repetir la
identificación de líneas -- tiene una prueba de humo GUI de extremo a
extremo (`test_save_use_and_reidentify_a_spectral_calibration_profile`).

8 tests unitarios nuevos (`tests/unit/services/test_spectral_calibration_
profiles.py`): guardado/recuperación con espectro de referencia, rechazo de
calibraciones sintéticas, reutilización tal cual sin aviso espontáneo,
recuperación del desplazamiento real por correlación cruzada (con el
desplazamiento verdadero conocido de antemano), aviso de deriva mecánica,
fallo honesto sin espectro de referencia guardado, y rechazo de un perfil
de otra configuración de instrumento (nº de píxeles distinto).

## 3. Calibración lateral/simultánea (§14, §45)

`astrophysics_suite/spectroscopy/lateral_calibration.py` (nuevo) --
extracción de una lámpara de calibración registrada en la MISMA imagen 2D
que el objeto (un canal de fibra de calibración simultánea, o parte de la
rendija iluminada por la lámpara junto al objeto), en una región espacial
paralela a la traza del objeto pero independiente de ella.

Geométricamente es la misma idea que `trace.SkyWindow` (`offset_px`/
`half_width_px` respecto al centro de la traza en cada columna, siguiendo
su curvatura -- la lámpara lateral comparte óptica con el objeto), pero
`extract_lateral_calibration_spectrum()` **no resta cielo**: la señal de la
lámpara no es fondo a eliminar, es la propia señal de interés. Mismo
contrato de "nunca cero silencioso" que el resto del slice 1: una columna
sin evidencia usable queda `flux=NaN`, `valid=False`; sin `uncertainty`
dado, `flux_uncertainty` queda `NaN` en vez de inventar un error.

7 tests unitarios nuevos (`tests/unit/spectroscopy/test_lateral_
calibration.py`): separa la señal de la lámpara de la del objeto (no las
mezcla), sigue la curvatura de la traza, ventana fuera de la imagen →
inválida no cero, ventana totalmente enmascarada → inválida no cero,
incertidumbre `NaN` sin dato real de varianza, forma incompatible lanza
error, método etiquetado correctamente.

Validado end-to-end sobre `Vega_1sec_1x1__frame6.fit` real (ver script de
validación): la extracción lateral corre sin excepciones sobre la traza
real detectada, con 1391/1391 columnas válidas para una ventana bien
dentro de la imagen.

## 4. Biblioteca de estándares espectrofotométricos al estilo CALSPEC (§49)

`astrophysics_suite/spectroscopy/standard_stars.py` (nuevo). Disciplina
idéntica a `line_catalog.py` (informe 56): **catálogo deliberadamente
modesto** de solo 6 estrellas cuyo papel como patrón CALSPEC está de sobra
documentado (Vega, Sirius, y los enanas blancas DA G191-B2B/GD71/GD153/
HZ43, todos patrones CALSPEC primarios o históricos bien establecidos) --
mejor una lista corta y verificada que una larga con alguna clasificación
sin confirmar.

**Ningún valor de flujo se inventa ni se hardcodea** -- el catálogo solo da
identidad (nombre/alias/tipo espectral/por qué se usa), nunca números de
flujo. El espectro de referencia real (longitud de onda + flujo físico)
se lee siempre de un archivo CALSPEC real descargado de STScI mediante
`load_calspec_spectrum()`, que implementa el formato público y estable que
documenta STScI (tabla binaria con columnas `WAVELENGTH`/`FLUX`, más
`STATERROR` si el archivo la trae) -- ese `(wavelength, flux)` real
alimenta directamente `fluxcal.build_sensitivity_function()` (ya
implementado y probado, Fase 9.5/18), sin duplicar ni reinventar la
función de sensibilidad.

Se dejó fuera deliberadamente cualquier coordenada o nombre de archivo
CALSPEC con versión concreta (p. ej. `_stis_008.fits`): esos sufijos de
versión cambian con las actualizaciones periódicas de STScI y afirmarlos
de memoria sin poder verificarlos sería precisamente el tipo de dato
inventado que prohíbe el encargo. Las coordenadas, si hacen falta, se
resuelven contra SIMBAD con el motor ya existente (Fase "resolución de
coordenadas por nombre de objeto").

7 tests unitarios nuevos (`tests/unit/spectroscopy/test_standard_
stars.py`): catálogo modesto y sin campos de flujo, búsqueda por
nombre/alias, `None` en vez de "el más parecido" para una estrella
desconocida, lectura real de un archivo con la forma CALSPEC documentada
(con y sin columna de error), y error claro para un archivo sin columnas
reconocibles.

## 5. Validación

| Verificación | Resultado |
|---|---|
| `ruff check` (código nuevo + modificado) | limpio |
| Suite unitaria completa (`pytest tests/ --ignore=tests/gui_smoke`) | **862 passed**, 24 skipped, 1 xfailed (antes del slice: 757 passed) |
| Suite de humo GUI completa (`xvfb-run pytest tests/gui_smoke/`, venv `aps-gui`) | **153 passed** (antes: 142) |
| Preprocesado + traza + extracción + calibración lateral sobre `Vega_1sec_1x1__frame6.fit` real | corre de extremo a extremo, traza RMS=0.03 px, 2/1391 columnas inválidas (nunca `0.0`), hallazgo del borde de sensor documentado arriba |

## 6. Qué queda fuera de este slice

Del encargo original de 79 secciones, siguen pendientes para slices
futuros (no bloquean el cierre de esta pieza concreta): identificación
automática de líneas de objeto + ajuste Gaussiano/Voigt (§21-22/§62),
velocidad radial multi-línea y correcciones heliocéntricas/baricéntricas
(§23/§58-61), objetos extendidos/nebulosas (§27), corrección de flexión
espectral entre exposiciones (§44), base de datos de líneas telúricas
(§46), magnitudes fotométricas desde espectro (§50), soporte échelle
(§52-54), y el bloque extendido de QC/informe/reproducibilidad (§63-78).
