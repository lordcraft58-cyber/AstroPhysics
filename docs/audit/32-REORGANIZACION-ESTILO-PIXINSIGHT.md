# 32 — Reorganización de la ventana principal al estilo PixInsight

Pedido explícito: "organiza más la ventana gráfica al estilo pixinsight,
sin modificar el apartado artístico" -- cambios de disposición/
organización de la interfaz, nunca de color/tema (`qt_app/theme.py` no
se ha tocado en esta ronda).

## 1. Barra de herramientas principal (nueva)

`QToolBar` ya tenía su estilo definido en `theme.py` (`QToolBar { ... }`)
desde hace fases, pero nunca se había usado -- infraestructura preparada
y sin cablear, el mismo tipo de hallazgo que ya se corrigió antes en
este proyecto para otros casos. `MainWindow._build_toolbar` la añade
ahora, con las acciones más frecuentes como iconos (mismos `QAction` que
ya existían para los menús, nunca duplicados): Abrir FITS, Nueva
observación, Cancelar análisis, Resolver placa automáticamente,
Construir fotograma maestro, Aplicar calibración, Alternar STF. Los
iconos son los pictogramas estándar de Qt/el sistema
(`QStyle.StandardPixmap`) -- ninguna decisión de diseño propia, y se
puede ocultar/mostrar desde Vista como cualquier barra de Qt real
(`toggleViewAction()`).

## 2. Lectura de píxel ("Readout") en la barra de estado (nueva)

Rasgo característico de PixInsight: posición + valor ADU real bajo el
cursor, en tiempo real. `ImageView` gana la señal `pixel_hovered` (con
seguimiento de ratón activado, `setMouseTracking(True)`) y
`MainWindow` un `QLabel` permanente en la barra de estado que la
muestra. Nunca inventa un valor: si el cursor cae fuera de los límites
de la imagen, muestra "--" explícitamente (`nan`, nunca un `0` u otro
valor fabricado).

## 3. Disposición de paneles (sin cambios estructurales)

La disposición ya existente (Explorador de procesos a la izquierda,
Propiedades+Candidatos tabificados a la derecha, Consola abajo, área
MDI central) ya se aproximaba razonablemente a un layout habitual de
PixInsight (Process Explorer / inspector de parámetros / Process
Console) -- no se ha reordenado, solo completado con lo que faltaba
(barra de herramientas y lectura de píxel).

## 4. Verificación real

Capturas de pantalla reales (no solo aserciones) confirmando: la barra
de herramientas se renderiza con los iconos esperados bajo el menú, y
la lectura de píxel se actualiza correctamente al mover el ratón sobre
una imagen real cargada. El tema oscuro es idéntico al de antes (ningún
archivo de `theme.py` tocado).

## 5. Tests

`tests/gui_smoke/test_qt_app_smoke.py` (+2): la barra de herramientas
expone las acciones esperadas (con icono real, no vacío) y se puede
ocultar/mostrar; la lectura de píxel refleja el valor real bajo el
cursor (derivado de la posición de escena realmente resuelta por la
vista, no de una correspondencia widget↔escena asumida) y muestra "--"
fuera de los límites de la imagen.

Suite completa sin regresiones (aps-test: 408 passed/4 skipped; aps-gui:
507 passed/3 skipped/1 xfailed).
