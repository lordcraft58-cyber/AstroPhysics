# 29 — Tutorial guiado de primer arranque

## 1. Objetivo

Un recorrido interactivo real por la interfaz -- nunca un PDF, nunca un
README aparte -- que resalta controles REALES de `MainWindow` (nunca
controles inventados), aparece la primera vez que se abre la aplicación,
y se puede reabrir en cualquier momento.

## 2. Arquitectura

`qt_app/tutorial/tutorial_overlay.py`:

- `TutorialStep`: `title` + cuatro campos de texto (`what_it_does`,
  `when_to_use`, `what_it_needs`, `what_it_produces` -- QUÉ HACE/CUÁNDO
  USARLO/QUÉ NECESITA/QUÉ PRODUCE) + `target`, una función que recibe el
  `MainWindow` real y devuelve el `QRect` (en sus coordenadas) del
  control a resaltar, o `None` para un paso sin control concreto
  (bienvenida/cierre). Que el "target" sea una función, no una
  referencia fija, es deliberado: si algún día un control cambia de
  sitio o no está visible, el paso simplemente no resalta nada en vez de
  señalar un lugar equivocado.
- `TutorialOverlay`: una capa (`QWidget` translúcido, hijo de
  `MainWindow`, del tamaño de su cliente) con un panel contextual
  (título, los cuatro campos, contador "Paso X de 12",
  Atrás/Siguiente/Saltar) y un "hueco" real sobre el control resaltado.

`qt_app/tutorial/tutorial_steps.py`: los 12 pasos reales pedidos
(Bienvenida, Explorador de procesos, Abrir FITS, Visualización,
Reducción, Astrometría, Fotometría, Espectroscopía, Discovery,
Candidatos, Exportación, Final), cada uno con su `target` real:
`_menu_target`/`_widget_target`/`_dock_target` resuelven la geometría
real de un menú, un widget o un dock (elevando su pestaña si está
tabificado, p. ej. CANDIDATOS con PROPIEDADES) contra el `MainWindow`
actual -- no hay ningún control inventado en ninguno de los 12 pasos.

`MainWindow` expone ahora como atributos (antes eran variables locales
de `_build_menu`/`_build_docks`) los menús y docks que el tutorial
necesita señalar: `file_menu`, `tools_menu`, `reduction_menu`,
`astrometry_menu`, `spectroscopy_menu`, `discovery_menu`,
`explorer_dock`, `properties_dock`, `console_dock`, `candidates_dock`.

## 3. "Aparece solo la primera vez" -- diseño real, no una promesa vacía

Una sola preferencia persistida (`services/app_preferences.py`, mismo
JSON bajo `~/.astrophysics_suite/` ya usado por
`instrument_profiles.py`): `tutorial_show_on_startup` (por defecto
`"true"` si nunca se fijó). `MainWindow.maybe_show_tutorial_on_startup()`
lo comprueba y abre el tutorial si es `"true"`; al completarlo o
saltarlo, se fija a `"false"`. El usuario puede reactivarlo en cualquier
momento con la casilla "Ayuda -> Mostrar tutorial al iniciar"
(`QAction` marcable, sincronizada con la preferencia). "Ayuda ->
Tutorial guiado" siempre lo reabre manualmente, sin tocar esa
preferencia.

**Decisión deliberada:** `maybe_show_tutorial_on_startup()` NO se llama
desde `MainWindow.__init__` -- se llama explícitamente desde el punto
de entrada real (`qt_app/__main__.py`, tras `window.show()`). Así,
construir un `MainWindow()` (como hacen las más de 80 pruebas de humo
GUI ya existentes) nunca dispara una ventana emergente por sí solo; el
efecto secundario de "mostrar algo la primera vez" vive en el arranque
real de la aplicación, no en el constructor del widget.

## 4. Bug real encontrado y corregido durante el desarrollo

El paso "Candidatos" necesita elevar su pestaña (tabificada con
"Propiedades") para resaltar la de verdad visible. Elevar un
`QDockWidget` reordena el apilamiento interno de `QMainWindow`, y dejaba
la propia capa del tutorial (y su panel) por DEBAJO del dock recién
elevado -- confirmado con una captura real (`window.grab()`): el panel
de texto desaparecía por completo a partir de ese paso, aunque su
geometría calculada era correcta (verificado imprimiéndola).
**Corregido** reafirmando `self.raise_()` en cada paso, no solo al
abrir el tutorial.

Corregido eso, apareció un segundo problema real: el "hueco" sobre el
dispositivo resaltado (antes implementado pintando todo y luego
"borrando" esa región con `QPainter.CompositionMode_Clear`) dejaba de
revelar el contenido real del control en cuanto la capa del tutorial
pasaba a estar POR ENCIMA de él en el apilamiento (el hueco se veía
negro sólido, no el contenido real) -- verificado con capturas antes y
después. `CompositionMode_Clear` solo limpia el búfer de la propia capa;
no repinta lo que hay detrás. **Corregido** de raíz: en vez de
pintar-y-borrar, se recorta la región del hueco con `QRegion` y nunca se
pinta ahí -- al ser una capa translúcida, lo no pintado queda realmente
transparente, revelando el control real sin trucos de composición.
Verificado visualmente (capturas de pantalla reales) para los 12 pasos,
incluido el caso del dock tabificado.

## 5. Tests

`tests/gui_smoke/test_qt_app_tutorial_smoke.py` (6 tests):
- Los 12 pasos, contra una ventana real, resuelven un rectángulo real y
  no vacío (pasos con control) o `None` explícito (bienvenida/cierre).
- Prueba obligatoria L: aparece en el primer arranque (preferencia sin
  fijar).
- Prueba obligatoria M: tras completarlo (recorrido real hasta
  "Finalizar"), un `MainWindow` nuevo con la misma preferencia
  persistida no lo muestra solo.
- Prueba obligatoria N: aunque la preferencia esté en `"false"`, "Ayuda
  -> Tutorial guiado" siempre lo reabre, desde el paso 1.
- Saltar también marca la preferencia; navegación Atrás/Siguiente
  verificada.
- La casilla "Mostrar tutorial al iniciar" escribe de verdad la
  preferencia al activarla/desactivarla.

Verificación visual adicional (no solo aserciones): capturas de pantalla
reales (`window.grab()`) de los 12 pasos contra una ventana real de
1440x920 bajo Xvfb, incluido el caso del dock tabificado antes y
después de la corrección del §4.

Suite completa sin regresiones (aps-test: 396 passed/3 skipped; aps-gui:
489 passed/2 skipped/1 xfailed).

## 6. Pendiente (no hecho en esta ronda)

- El tutorial no se adapta a un layout de docks distinto del que trae la
  aplicación por defecto (docks flotantes o movidos por el usuario): en
  ese caso, un paso puede no resaltar nada (`target` devuelve `None` con
  seguridad, nunca un lugar equivocado) en vez de encontrar el control
  donde esté. No se ha implementado seguimiento de docks reordenados.
