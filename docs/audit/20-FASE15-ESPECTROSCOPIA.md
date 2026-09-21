# AstroPhysics Suite — Fase 15: calibración en longitud de onda real

Sexto y último bloque del orden de prioridad acordado (`CCDRED → análisis de
imagen → fotometría → astrometría → tablas/catálogos → espectroscopía`). El
motor de `astrophysics_suite/spectroscopy/` resultó ser más completo de lo que
sugería la documentación de la Fase 9.6 (extracción óptima de Horne, función de
sensibilidad, corrección de extinción atmosférica, todo real), pero la GUI era
puramente demostrativa en todo lo que exponía, y `spectroscopy.wavelength` no
tenía ningún camino de uso -- listado en el árbol de procesos sin `run=`.

## 1. Por qué la detección de líneas no necesita clic (a diferencia del WCS)

En el ajuste de WCS (Fase 13), la posición de cada estrella hay que marcarla a
mano porque el taller no tiene ningún criterio para decidir "esto es una
estrella de referencia" sin que el usuario lo señale. En la calibración de
longitud de onda la situación es distinta: `find_arc_lines` ya localiza picos
reales de forma completamente automática (fondo local robusto + umbral de
significancia + centroide subpíxel por parábola de 3 píxeles) -- lo que el
taller **no puede** adivinar es a qué longitud de onda conocida corresponde
cada pico detectado (eso depende de qué lámpara de calibración se usó, algo que
solo el usuario sabe). Por eso el flujo de esta fase detecta automáticamente y
solo pide al usuario rellenar una tabla de longitudes de onda -- mismo alcance
que `identify` interactivo de IRAF, ni más ni menos.

## 2. "Calibrar longitud de onda..." (`qt_app/spectroscopy/wavelength_fit_dialog.py`)

Nuevo menú de nivel superior "Espectroscopía". El flujo:

1. Al pulsar "Calibrar longitud de onda (detectar líneas)...", el taller toma
   la fila central de la imagen activa como espectro de arco 1D -- misma
   convención ya usada por `spectroscopy.continuum` desde la Fase 9.6, para no
   introducir una segunda forma distinta de tratar "una fila como espectro".
2. `find_arc_lines` real detecta los picos automáticamente. Si detecta menos de
   2 líneas, el taller lo dice explícitamente en la barra de estado en vez de
   abrir un diálogo vacío.
3. Se abre `WavelengthFitDialog`: una tabla con una fila por línea detectada
   (píxel y amplitud de solo lectura, longitud de onda editable) + el grado del
   polinomio a ajustar.
4. "Ajustar solución" llama a `fit_wavelength_solution` real (sin ningún
   cambio) y reporta el RMS del ajuste.
5. La `WavelengthSolution` resultante se guarda en
   `ImageView.fitted_wavelength_solution` (mismo patrón que
   `fitted_wcs_solution` de la Fase 13) -- infraestructura para que un futuro
   consumidor (p. ej. aplicar la solución a una traza ya extraída) no tenga que
   volver a ajustar nada.

Igual que el ajuste de WCS, el cálculo opera solo sobre las pocas líneas
detectadas (nunca sobre la imagen completa), así que corre de forma síncrona --
no hace falta hilo de fondo.

## 3. Tabla exportable (reutiliza la Fase 14 sin cambios)

`WavelengthFitDialog.fitted` emite `(WavelengthSolution, Table)` -- una fila por
línea, con su residuo -- usando el mismo tipo `Table` de la Fase 14 y el mismo
mecanismo genérico "Herramientas → Exportar última tabla a CSV..." que ya
servía a `photometry.zeropoint` y a "Ajustar WCS...". Ningún código de
exportación nuevo: la infraestructura de la Fase 14 se reutiliza tal cual,
confirmando que sí era genérica de verdad, no solo aparentemente.

## 4. Limpieza del árbol de procesos (deuda pendiente de fases anteriores)

Al retirar `spectroscopy.wavelength` del árbol (reemplazado por el diálogo
dedicado, mismo criterio que `imtools.arithmetic` o los fotogramas maestros de
`ccdred`), se encontró que las entradas `astrometry.wcs_fit` y
`astrometry.registration` habían quedado **listadas como "(pendiente)" en el
árbol de procesos desde la Fase 13**, a pesar de que ambas ya tenían un camino
de uso real desde esa misma fase (los diálogos del menú Astrometría) -- una
inconsistencia real que contradecía la propia disciplina del proyecto ("el
explorador de procesos debe reflejar el estado verdad"). Esta fase las retira
también, con el mismo comentario explicativo que ya usan las demás capacidades
resueltas por diálogo dedicado.

Al hacerlo, el árbol de procesos se quedó sin ninguna entrada `PENDIENTE` en
absoluto -- una señal genuinamente buena (todo lo cableable con el patrón
actual ya está cableado), pero que dejaba sin sentido la prueba
`test_unwired_processes_have_no_run_and_are_flagged` (que exige que exista al
menos una entrada pendiente correctamente marcada, como guardia contra ocultar
huecos). Se resolvió añadiendo `spectroscopy.fluxcal` como entrada pendiente
explícita -- una capacidad real (función de sensibilidad + calibración de
flujo, `fluxcal.py`) que **nunca había aparecido en el árbol en absoluto**
según la auditoría original, ni siquiera como pendiente. Añadirla cierra la
prueba de forma honesta (una capacidad real que de verdad falta, no un relleno
artificial) y corrige una brecha de visibilidad real que señalaba
`13-IRAF-CAPABILITY-MAP.md` desde el principio de la Fase 10.

## 5. Verificación

4 tests de humo GUI nuevos en `tests/gui_smoke/test_qt_app_wavelength_smoke.py`:
detección + ajuste de extremo a extremo contra datos sintéticos con líneas de
mercurio reales de referencia (4046.6, 4358.3, 5460.7, 5769.6 Å), verificando
que la solución ajustada predice correctamente una longitud de onda intermedia
(no solo reproduce los puntos de entrada); aviso claro cuando hay menos de 2
líneas detectadas; aviso sin imagen activa; exportación real a CSV a través del
mecanismo de la Fase 14. 1 test unitario actualizado en
`tests/unit/qt_app/test_registry.py` (categorías del árbol sin "Astrometría").

Suite completa verde en ambos entornos tras esta fase: 406 tests en el entorno
con PySide6 (`aps-gui`), 341 en el entorno sin GUI (`aps-test`), más `ruff`
limpio en los 6 archivos nuevos/tocados.

## 6. Qué queda del bloque de espectroscopía (documentado, no oculto)

- **`spectroscopy.fluxcal`**: motor real, ahora visible en el árbol como
  pendiente, sin camino de uso todavía -- necesitaría un espectro ya extraído
  y calibrado en longitud de onda (encadenando trazado + calibración de esta
  fase) más un catálogo de flujos estándar.
- **Trazado/extracción/continuo** (`spectroscopy.trace`, `spectroscopy.
  continuum`): siguen `EXPERIMENTAL`, con el mismo recorte de alcance
  explícito de la Fase 9.6 (fila central tratada como espectro, tira repetida
  en vez de un espectro real) -- sin un widget de gráfico 1D dedicado, esto no
  cambia.
- **Extracción multi-apertura por lote, medición de líneas individuales,
  combinación de espectros de varias exposiciones, tipo `Spectrum` compartido**:
  no abordados, mismo estado que señalaba la auditoría original.

## 7. Cierre del recorrido por los seis bloques

Con esta fase se completa el recorrido por el orden de prioridad acordado
explícitamente al principio: `CCDRED → análisis de imagen → fotometría →
astrometría → tablas/catálogos → espectroscopía`. Cada bloque cerrado tiene su
propio documento de fase (`14` a `20`) y su fila correspondiente en
`13-IRAF-CAPABILITY-MAP.md`, con los huecos que quedan en cada uno documentados
explícitamente, nunca ocultos -- la misma disciplina de honestidad epistémica
que rige el resto del proyecto, aplicada aquí a la propia gestión del alcance
del encargo.
