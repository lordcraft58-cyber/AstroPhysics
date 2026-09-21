# AstroPhysics Suite — Fase 17: cierre del bloque `daophot`

Con `apphot` cerrado en la Fase 16, esta fase retoma los cuatro huecos que
`13-IRAF-CAPABILITY-MAP.md` documentaba como `PENDIENTE` en `daophot`:
selección automática de estrellas de referencia (`pstselect`), detección
automática conectada a `photometry.psf` (`daofind`), refinamiento no lineal
de posición (`allstar`), y diagnóstico de calidad de ajuste. El núcleo del
bloque (ajuste simultáneo con desmezclado, tres modelos de PSF) ya era real
desde la Fase 9.3 -- lo que faltaba era automatizar la selección de
referencias y cerrar el ciclo iterativo de refinamiento/diagnóstico que
`allstar`/`nstar` añaden sobre `daophot` básico.

## 1. Selección automática de estrellas PSF (`pstselect`)

`select_psf_reference_stars` (`astrophysics_suite/photometry/psf.py`) aplica
los tres criterios reales de una buena estrella de referencia para PSF:

- **Aislamiento**: se rechaza cualquier candidato con otro candidato --
  pase o no el resto de criterios -- a menos de `min_separation_px`. Un
  vecino débil, aunque no sea seleccionable él mismo, sigue contaminando la
  PSF empírica apilada o el ajuste simultáneo si cae dentro de la caja de
  ajuste.
- **Redondez**: se rechaza cualquier candidato con elipticidad por encima
  de `max_ellipticity` -- una fuente alargada es más probable que sea un
  blend sin resolver o un objeto extendido que una estrella real.
- **Señal/ruido**: se rechaza cualquier candidato con S/N de pico por
  debajo de `min_snr` -- una referencia ruidosa arrastra ese ruido a la PSF
  que se construye a partir de ella.

Nunca inventa una selección cuando ninguna fuente cumple los tres criterios
a la vez -- devuelve una lista vacía, que la GUI reporta explícitamente en
vez de abrir una selección vacía.

## 2. Detección automática conectada (`daofind`)

`detect_psf_candidates` (`astrophysics_suite/detection/point_sources.py`)
reutiliza el mismo motor DAOStarFinder que ya usaba `detect_point_sources`
(Discovery Engine) y `detect_point_sources_in_array` (Fase 16), pero
enriquecido vía `enrich_star_rows` (momentos de segundo orden reales) con
las métricas que `select_psf_reference_stars` necesita -- FWHM, elipticidad,
nitidez, S/N de pico -- que `detect_point_sources_in_array` no calcula (esa
función solo da posición y flujo bruto, suficiente para "haz clic por mí"
pero no para juzgar si una fuente es una buena referencia). Sin cabecera
FITS real disponible en este camino (array en memoria), la detección de
saturación de `enrich_star_rows` queda inactiva -- documentado explícitamente
en el docstring, no se inventa un valor de `SATURATE`.

## 3. Refinamiento no lineal de posición (`allstar`)

`fit_group_psf_photometry_with_position_refinement` extiende
`fit_group_psf_photometry` (que fijaba las posiciones, límite de alcance
documentado explícitamente desde la Fase 9.3) resolviendo el problema no
lineal por **proyección variable** (Golub-Pereyra): `scipy.optimize.
least_squares` optimiza únicamente los 2 desplazamientos `(dx, dy)` de cada
fuente respecto a su posición inicial; en cada evaluación, el flujo (y el
cielo local) de todas las fuentes se resuelve como el mismo subproblema
lineal exacto que ya resolvía `fit_group_psf_photometry` de forma cerrada.
Así el optimizador no lineal nunca necesita más de 2 parámetros por fuente,
y cada evaluación sigue siendo el óptimo lineal global para esa posición --
mucho más estable que optimizar flujo y posición conjuntamente de forma no
lineal. La caja de píxeles del ajuste se fija una sola vez a partir de las
posiciones iniciales (más el margen de desplazamiento máximo permitido), no
en cada iteración, para que el vector de residuos tenga tamaño constante.

Verificado con una estrella sintética en posición subpíxel conocida y una
adivinanza inicial deliberadamente descentrada (~1.8 px de error): el
refinamiento recupera la posición real dentro de 0.15 px y mejora el flujo
recuperado frente a dejar la posición fija en la adivinanza inicial.

## 4. Diagnóstico de calidad de ajuste

`compute_psf_fit_diagnostics` no vuelve a ajustar nada -- toma un resultado
ya resuelto (de `fit_group_psf_photometry` o su variante con refinamiento) y
reconstruye el modelo para compararlo con los datos reales: chi² reducido
(equivalente al `CHI` que reporta `nstar`/`allstar` -- ~1 indica que el
modelo de PSF explica los residuos dentro del ruido esperado) e imagen de
residuo (datos - modelo) recortada a la caja de ajuste, para inspección
visual de estructura sistemática que un modelo insuficiente (p. ej.
Gaussiana para un perfil con colas más pesadas) no captura. El nivel de
cielo no viaja en `PSFFitResult` (para no cambiar ese contrato ya usado en
cuatro sitios) -- se recupera aquí con un ajuste lineal de 1 parámetro
(media ponderada por varianza inversa del residuo tras restar solo el
modelo de fuentes), la misma cantidad que ya resolvió el ajuste original
como parte del mismo sistema lineal.

Verificado comparando el chi² reducido de un modelo Gaussiano con el sigma
correcto (≈1) frente a un modelo deliberadamente mal ajustado (sigma 2.5x
mayor que el real): el chi² reducido del modelo incorrecto es más de 3
veces mayor -- el diagnóstico realmente distingue un buen ajuste de uno
malo, no solo devuelve un número.

## 5. Cableado en `photometry.psf`

Cuatro casillas opcionales nuevas, todas desactivadas por defecto (el
comportamiento ya probado desde la Fase 9.6 no cambia):

- **"Refinar posición (allstar)"** + "Desplazamiento máximo permitido" ->
  `fit_group_psf_photometry_with_position_refinement` en vez de
  `fit_group_psf_photometry`.
- **"Diagnóstico de ajuste (chi², residuo)"** -> añade el chi² reducido al
  registro y abre la imagen de residuo en una ventana nueva.
- **"Detectar automáticamente (pstselect)"** + los parámetros de detección
  y de selección (aislamiento, elipticidad máxima, S/N mínima, máximo de
  estrellas) -> `MainWindow._run_with_auto_detected_points` (Fase 16) gana
  una rama específica para `photometry.psf`: en vez de tomar las N fuentes
  más brillantes (como `photometry.aperture`/`zeropoint`), aplica
  `detect_psf_candidates` + `select_psf_reference_stars` -- una estrella de
  referencia para PSF necesita estar aislada, no simplemente ser brillante.

`photometry.psf` también gana una `Table` exportable (x, y, flujo,
incertidumbre) -- una fila por fuente, siempre, reutilizando sin cambios el
mecanismo genérico de la Fase 14.

## 6. Verificación

Motor: `tests/unit/photometry/test_psf.py` (11 pruebas nuevas --
refinamiento de posición recupera la posición real desde una adivinanza
descentrada y mejora el flujo frente a posición fija; diagnóstico da chi²
reducido ≈1 para el modelo correcto y lo dispara para uno incorrecto;
`select_psf_reference_stars` rechaza vecinos cercanos, fuentes alargadas y
de baja S/N, ordena por brillo y respeta el máximo) y
`tests/unit/detection/test_point_sources.py` cubre `detect_psf_candidates`
indirectamente vía las pruebas de selección.

GUI: `tests/unit/qt_app/test_registry.py` (3 pruebas -- refinamiento
converge a la posición real vía `process.run`, diagnóstico añade la imagen
de residuo como `output_data` y la línea de chi² al registro, la tabla se
devuelve siempre) y `tests/gui_smoke/test_qt_app_smoke.py` (2 pruebas de
humo con `QApplication`/hilo de fondo reales -- selección automática
pstselect distingue dos estrellas aisladas de un par pegado que debe
quedar fuera; refinamiento + diagnóstico de extremo a extremo vía un clic
real deliberadamente descentrado, verificando que la posición reportada
converge a la real y que se abre la ventana de residuo).

Suite completa verde en ambos entornos tras esta fase: 431 tests en el
entorno con PySide6 (`aps-gui`, +15 sobre la Fase 16), 361 en el entorno sin
GUI (`aps-test`, +15), más `ruff --select F,E9` limpio en los 7
archivos nuevos/tocados.

## 7. Qué queda (ninguno bloqueante para `daophot`)

Con esta fase, 6 de las 8 capacidades de la tabla de `daophot` en
`13-IRAF-CAPABILITY-MAP.md` quedan en `DISPONIBLE`. Las 2 restantes
(modelo Moffat, PSF empírica) siguen `EXPERIMENTAL` -- motores reales
(`MoffatPSF`, `build_empirical_psf`), pero la GUI sigue fija en el modelo
Gaussiano; exponer un selector de modelo en `photometry.psf` es una
extensión de UI pequeña, no un motor por construir, y queda documentada
para cuando haya un caso de uso concreto que la reclame (un campo con
seeing marcadamente no gaussiano). No bloquea el cierre del bloque.

Con `apphot` y `daophot` cerrados, los pendientes reales que quedan en todo
el proyecto son los que ya estaban deliberadamente fuera de alcance desde
las Fases 13-15: registro por pares de estrellas emparejadas entre dos
ventanas, resolución automática contra catálogo ("blind solving"),
unificación profunda de tipos de resultado, abstracción de catálogo con más
de un proveedor, y las extensiones de espectroscopía (`spectroscopy.
fluxcal` sin camino de uso, extracción multi-apertura, medición de líneas,
combinación de espectros, tipo `Spectrum` compartido) -- todos de mayor
riesgo o alcance que los ya cerrados, y documentados explícitamente en cada
fase correspondiente.
