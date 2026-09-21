# AstroPhysics Suite — Fase 18: registro por pares de estrellas emparejadas

Con `apphot` y `daophot` cerrados (Fases 16-17), esta fase retoma el hueco
que quedaba documentado en astrometría desde la Fase 13: `fit_affine_
transform` (`astrophysics_suite/astrometry/registration.py`) era real y
estaba probado, pero sin ningún camino de uso desde la GUI -- necesitaba
seleccionar pares de estrellas emparejadas entre dos ventanas MDI a la vez,
una interacción que la Fase 13 dejó explícitamente fuera de alcance.

## 1. Por qué hacía falta además de "Registrar por WCS compartido..."

"Registrar por WCS compartido..." (Fase 13) exige que **ambas** imágenes ya
tengan una solución astrométrica -- cargada del FITS o recién ajustada a
mano. Esa vía no sirve para el caso, igual de real, de dos exposiciones sin
astrometría en absoluto (p. ej. dos tomas de banda estrecha del mismo campo
que solo hace falta alinear entre sí, sin coordenadas celestes de por
medio) -- exactamente el caso que resuelve `geomap`/`geotran` interactivo de
IRAF sin pasar por WCS. El registro por pares de estrellas cierra ese hueco:
no necesita WCS en ninguna de las dos imágenes, solo que el usuario pueda
señalar la misma estrella en ambas.

## 2. "Registrar por pares de estrellas (clic)..." (menú Astrometría)

Nuevo diálogo de configuración (`qt_app/astrometry/
star_pair_registration_dialog.py::StarPairConfigDialog`) -- deliberadamente
pequeño: solo elige la ventana de referencia, la ventana a transformar, el
modelo (`affine` con 6 parámetros libres, o `similarity` con 4 -- ambos ya
reales en el motor desde antes de esta fase) y cuántos pares se van a
marcar. La selección de posiciones en sí no encaja en un formulario, así
que al aceptar el diálogo, `MainWindow` toma el control (mismo patrón que
"Ajustar WCS..." y "Calibrar longitud de onda..."):

1. Inicia una sesión de clic en la ventana de **referencia** pidiendo
   exactamente N puntos.
2. Al completarse, inicia una segunda sesión de clic en la ventana
   **objetivo**, pidiendo el mismo número de puntos, en el mismo orden
   (misma estrella señalada en el mismo orden en ambas ventanas -- el único
   requisito real del método, igual que `geomap` interactivo).
3. Si el número de puntos no coincide entre las dos ventanas, se informa en
   la barra de estado y no se ejecuta nada -- nunca se completa un
   emparejamiento a medias inventando un punto que falta.
4. Con ambos conjuntos de puntos, `fit_affine_transform` ajusta la
   transformación real y `apply_affine_transform` remuestrea la imagen
   objetivo sobre la rejilla de la referencia, en un hilo de fondo
   (`CallableWorker`, igual que "Registrar por WCS compartido...").

Ninguna de las dos sesiones de clic necesitó código de interacción nuevo:
cada `ImageView` ya soportaba clic-para-marcar de forma independiente desde
la Fase 9.6 -- encadenar dos sesiones en dos ventanas distintas fue pura
orquestación en `MainWindow`, sin tocar `ImageView`.

## 3. Convención de dirección de la transformación

`fit_affine_transform(reference_xy, target_xy)` ajusta `target_xy = matrix
@ reference_xy + offset` (verificado contra `tests/unit/astrometry/
test_registration.py`, no adivinado). Para remuestrear la imagen objetivo
**sobre la rejilla de la imagen de referencia**, el ajuste se llama con los
puntos de la ventana objetivo en el papel `reference_xy` (el sistema donde
viven los datos de entrada) y los puntos de la ventana de referencia en el
papel `target_xy` (la rejilla de salida deseada) -- documentado en un
comentario en el propio código, para que la convención no dependa de
memorizar el docstring del motor cada vez que se lea esta llamada.

## 4. Verificación

`tests/gui_smoke/test_qt_app_star_pair_registration_smoke.py` (3 pruebas
nuevas, `QApplication`/hilo de fondo reales): flujo completo de extremo a
extremo con dos ventanas reales, clic real en cada una (una traslación
conocida entre ambas), verificando que la imagen resultante tiene los picos
de las estrellas alineados exactamente en las posiciones reales de la
imagen de referencia (no solo que el proceso "no lanza"); aviso claro
cuando se marcan menos de 3 pares en la ventana de referencia; aviso claro
sin una segunda imagen abierta.

Suite completa verde en ambos entornos tras esta fase: 434 tests en el
entorno con PySide6 (`aps-gui`, +3 sobre la Fase 17), 361 en el entorno sin
GUI (`aps-test`, sin cambio -- la prueba nueva requiere PySide6 y se salta
ahí), más `ruff --select F,E9` limpio en los 3 archivos nuevos/tocados.

## 5. Qué queda (fuera de alcance, no bloqueante)

Con esta fase, astrometría queda con 8 de sus 9 capacidades en
`DISPONIBLE`. Solo sigue `PENDIENTE`, deliberadamente, la resolución
automática contra catálogo ("blind solving": detectar fuentes, consultar
Gaia, y encontrar la correspondencia y el WCS sin ninguna posición inicial
dada por el usuario) -- un problema algorítmico bastante más difícil que
cualquier otra capacidad cerrada hasta ahora (normalmente resuelto con
técnicas de coincidencia de patrones geométricos tipo *astrometry.net*, no
con mínimos cuadrados directos), sin un caso de uso concreto en este
proyecto que lo reclame todavía.
