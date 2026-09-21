# 50 — Construcción: WCS desde la óptica real, no por descubrimiento

Decisión del usuario, textual: *"El tema WCS en todo el proyecto, en vez
de que sea intentar descubrirlo. Que lo introduzca el usuario en función
de su longitud focal y del tamaño de píxel de su cámara"*, con un
selector de cámaras (empezando por su ZWO ASI533MC Pro) y la focal/
abertura, al estilo del FOV calculator de astronomy.tools.

Es un cambio de filosofía, no solo una función nueva: la escala del
campo pasa de ser algo que el programa intenta adivinar (plate solving
contra un catálogo, con red y con riesgo de fallar) a un dato que el
usuario conoce con certeza y declara.

## Qué se construyó

**`astrophysics_suite/instruments/`** (paquete nuevo):

- `cameras.py` -- `CameraSpec` + catálogo real (ZWO ASI533MC Pro y otras
  siete). Con un aviso de procedencia explícito en el propio módulo:
  son valores de catálogo del fabricante, no medidos por el programa, y
  **la cabecera del archivo del usuario manda sobre ellos**. `find_camera`
  solo empareja por nombre exacto: nunca devuelve "la más parecida",
  porque una geometría de sensor equivocada corrompe el WCS en silencio.
- `optics.py` -- escala de placa, campo, relación focal, límite de Dawes
  y muestreo frente al seeing. La escala se calcula con el arcotangente
  real (`atan(px/focal)`), no con la aproximación lineal: para un píxel
  real da lo mismo, pero no introduce una aproximación gratuita, y el
  test lo comprueba en un caso donde sí difieren (45° exactos).
  **Es la única implementación de la fórmula en todo el proyecto**:
  `plate_solve.estimate_approx_scale_from_header` pasa a importarla en
  vez de repetirla, eliminando una duplicación que ya existía.
- `header.py` -- lee la óptica que declara la cabecera real
  (`INSTRUME`, `XPIXSZ`, `FOCALLEN`, `XBINNING`, `RA`/`DEC`, `OBJECT`) y
  da **prioridad a la cabecera sobre el catálogo interno**, exponiendo la
  discrepancia (`pixel_size_disagreement_um`) cuando la hay. Si falta
  cualquier pieza para la escala, devuelve `None` en vez de suponerla.

**`astrophysics_suite/astrometry/optical_wcs.py`** --
`build_wcs_from_optics` produce un `WCSSolution` TAN real:

- Paridad correcta del cielo: **el este a la izquierda** salvo que la
  imagen esté reflejada (determinante de CD negativo para una imagen
  normal, positivo si hay espejo). Una convención invertida aquí habría
  corrompido toda la identificación de catálogo en silencio, así que se
  verifica explícitamente con datos conocidos.
- `crpix = (ancho/2, alto/2)` en coordenadas 0-based -- exactamente la
  misma convención que ya usan `plate_solve` y `blind_solve`, para que
  las tres soluciones sean intercambiables sin medio píxel de
  desplazamiento.
- La solución queda marcada como **declarada, no ajustada**
  (`n_stars=0`, sin residuales, `is_optical_wcs()`): así ningún informe
  puede leer su RMS de 0" como si fuera un ajuste perfecto contra
  estrellas reales. Es la misma disciplina de procedencia del resto del
  proyecto.

## En la GUI

**Astrometría → "WCS desde la óptica (cámara + focal)..."**, la primera
entrada del menú (antes que los dos plate solvers, que pasan a ser el
camino alternativo).

Selector de cámara, tamaño de píxel, focal, abertura opcional y binning,
con lectura **en vivo** de escala, campo, relación focal, límite de
Dawes y muestreo -- igual que una calculadora de campo. Y tres
comprobaciones honestas que hace de verdad:

1. **Se rellena solo** desde la cabecera real del archivo abierto: con
   los lights de M 31 del usuario reconoce la cámara por `INSTRUME`, y
   trae píxel, focal, binning, RA/Dec y nombre de objeto.
2. **Avisa si la cámara elegida contradice la cabecera** (`⚠ La cabecera
   del archivo dice 3.760 µm por píxel y aquí hay 4.630 µm. La cabecera
   la escribió tu cámara real: créela a ella.`) en vez de sobrescribirla
   en silencio.
3. **Avisa si la geometría de la imagen no es la del sensor** -- y si es
   exactamente la mitad, dice que eso es típico de un demosaico
   SuperPixel/luminancia, que **duplica la escala real**. Ese caso
   concreto es el del propio usuario (cámara OSC), y es justo el error
   que produciría un WCS con el doble de campo del real.

El WCS resultante se guarda por la vía ya existente
(`_remember_wcs_solution`): queda en la ventana y en `SessionState`, así
que lo aprovechan igual el registro por WCS compartido y los informes
científicos.

## Validación con datos reales del usuario

La cabecera real de `Light_M31_300s_0001.fit` confirma el catálogo
**exactamente**:

| dato | cabecera real | catálogo interno |
|---|---|---|
| `INSTRUME` | ZWO ASI533MC Pro | reconocida |
| `XPIXSZ` | 3.75999999 µm | 3.76 µm |
| `NAXIS1×2` | 3008 × 3008 | 3008 × 3008 |
| `FOCALLEN` | 749 mm | (del usuario) |

Resultado real de ese equipo: **1.0355 "/px**, campo **51.9' × 51.9'**,
muestreo de 2.9 px por FWHM de 3" ("bien muestreado"). La escala que
deduce `plate_solve` del mismo header da el mismo 1.0355 "/px --
confirmando que ahora hay una sola implementación y no dos que puedan
divergir.

Verificado además sobre un **XISF real** del mismo campo: 76 claves de
cabecera recuperadas, misma cámara reconocida, misma escala y mismo
campo que por la vía FITS.

Validación visual: captura real del diálogo (relleno automático) y del
aviso cuando se elige una cámara que contradice la cabecera.

## XISF: auditoría completa de paridad

El usuario pidió que *"los xisf se deben poder usar en todo el software
no sólo para abrir fits"*. Auditados todos los puntos de entrada:

- **Lectura: paridad completa.** Todo lector de imagen científica pasa
  por `io/fits_loader.py::load_image` o `io/fits_header_reader.py::
  read_fits_header`, y **ambos despachan XISF** (detectado por extensión
  Y por firma real del archivo). Los únicos dos sitios que abren FITS
  directamente son ese mismo `fits_header_reader` (que ya despacha
  antes) y `reduction/master_frames.py`, que lee el contenedor
  multi-extensión propio del proyecto (`UNCERT`/`NCOMBINE`) que nosotros
  mismos escribimos -- ahí FITS no es una limitación, es el formato del
  archivo que el propio programa generó.
- **Corregido en esta pasada**: el selector de "Patrón de franjas
  maestro" filtraba solo FITS aunque su cargador ya soportaba XISF --
  el único hueco real que quedaba en los diálogos.
- **Lo que NO existe, dicho claramente**: un **escritor** XISF. El
  proyecto lee XISF con un lector propio (escrito desde cero por
  incompatibilidad de licencia, ver cierre 34) pero guarda siempre en
  FITS. Que "Guardar FITS con WCS...", los fotogramas maestros y las
  salidas de reducción produzcan FITS no es un hueco de cableado: es que
  no hay escritor XISF. Escribirlo es un motor nuevo y separado, no una
  conexión pendiente.

## Tests

31 pruebas nuevas, todas contra valores reales o fórmulas cerradas:

- `tests/unit/instruments/test_optics.py` (11): escala contrastada con
  el valor que da cualquier calculadora de campo (0.7756 "/px para
  3.76 µm a 1000 mm), campo de 38.9' de la cámara del usuario,
  arcotangente real, binning, f/ratio y Dawes que **no se inventan** sin
  abertura, clasificación de muestreo, y que el catálogo nunca adivina
  una cámara parecida.
- `tests/unit/instruments/test_header_optics.py` (9): sobre la cabecera
  **literal** de los lights de M 31 del usuario -- incluida la prueba de
  que el catálogo coincide con su cámara real (la que impide un WCS mal
  escalado), que la cabecera gana al catálogo cuando se contradicen, que
  el catálogo solo rellena lo que la cabecera omite, y que una focal
  ausente da `None` en vez de una suposición.
- `tests/unit/astrometry/test_optical_wcs.py` (11): centro exacto,
  escala recuperada, **norte arriba y este a la izquierda**, el espejo
  invirtiendo solo la paridad (no la escala), un píxel cubriendo
  exactamente la escala declarada sobre el cielo, rotación real, campo
  completo de 38.9', ida y vuelta píxel↔cielo, y rechazo de entradas
  físicamente imposibles.
- `tests/gui_smoke/test_qt_app_optical_wcs_smoke.py` (9): el diálogo
  real rellenándose de la cabecera real, la escala y el campo reales en
  pantalla, el aviso al contradecir la cabecera, la detección del
  demosaico SuperPixel, la abertura opcional, el binning, la cámara
  personalizada, y el WCS real llegando a la ventana Y a `SessionState`.

## Validación

| conjunto | comando | resultado |
|---|---|---|
| Unit + integración + regresión | `pytest tests/ --ignore=tests/gui_smoke` (venv `aps-test`) | **726 passed, 21 skipped, 1 xfailed** (antes: 695) |
| GUI smoke completa | `xvfb-run pytest tests/gui_smoke/` (venv `aps-gui`) | **142 passed** (antes: 133) |

## Deliberadamente NO tocado en esta pasada

- **Retirar el plate solving.** Sigue ahí, y debe seguir: es la única
  forma de obtener el centro y la rotación REALES cuando el usuario no
  los sabe, y de verificar una óptica declarada. Lo que cambia es la
  jerarquía: la óptica es ahora el camino primario y el plate solve el
  de verificación/rescate.
- **Que Discovery use la óptica declarada automáticamente.** El pipeline
  genérico sigue con su cadena actual de WCS. Conectarlo es el paso
  siguiente natural (y toca el punto 9 del P0 del usuario: "WCS/Zeropoint
  no se notifican ni persisten adecuadamente"), pero es un cambio en un
  motor ya cerrado y probado: merece su propia pasada con su validación.
- **Escritor XISF.** Ver la auditoría de arriba: motor nuevo, no una
  conexión pendiente.
- **Persistir el equipo como perfil reutilizable.** Hoy el diálogo se
  rellena de la cabecera (que es mejor que una preferencia guardada,
  porque es la verdad de ese archivo concreto). Guardar "mi telescopio
  de 749 mm" como perfil tiene sentido para imágenes sin cabecera
  completa, y encaja con `services/instrument_profiles.py` que ya
  existe -- pero no hacía falta para cerrar esto.

## Cambio de motor

Motor #88 cerrado. El WCS ya se declara desde la óptica real en vez de
adivinarse. El siguiente paso acordado con el usuario es su lista P0,
empezando por cerrar IO/FITS al 100% antes de tocar nada más.
