# Fix: no se podían abrir imágenes FITS de 3+ dimensiones

## 1. Síntoma reportado

"Tampoco deja abrir imágenes de 3 dimensiones" -- un cubo FITS (p. ej.
una serie temporal, un RGB, o cualquier NAXIS>2) simplemente no se podía
abrir desde "Archivo → Abrir FITS...".

## 2. Diagnóstico

`legacy.AstroPhysicsSuite_v57_3_COMMERCIAL.load_fits` ya tenía, por
diseño deliberado documentado en su propio código (`AmbiguousCubeError`,
línea 1562), la política de **nunca** elegir un plano de un cubo 3D/4D
por su cuenta -- una decisión de honestidad epistémica correcta (elegir
"el plano 0" en silencio podría analizar un canal equivocado sin que
nada lo delate). Con `plane=None` (su valor por defecto) y
`allow_first_plane=False` (también por defecto), cualquier FITS con
`NAXIS > 2` lanza `AmbiguousCubeError`.

El problema real no estaba en `load_fits` (que se comporta como debe),
sino en que **nada en la capa por encima exponía una forma de indicar el
plano**:

- `astrophysics_suite/io/fits_loader.py::load_image` llamaba a
  `load_fits(path)` sin ningún parámetro adicional -- no exponía
  `plane=` en absoluto.
- `qt_app/main_window.py::open_fits` capturaba `AmbiguousCubeError` con
  el mismo `except Exception` genérico que cualquier otro fallo de
  carga, y solo mostraba el mensaje de la excepción en un
  `QMessageBox.critical` -- sin ningún camino para que el usuario
  indicara el plano y reintentara.

Resultado: un FITS 3D/4D era, en la práctica, imposible de abrir desde
la GUI, aunque el motor de carga ya sabía perfectamente cómo hacerlo si
alguien le daba el índice.

## 3. Corrección

Sin cambiar la política de `load_fits` (sigue sin elegir un plano en
silencio):

- `astrophysics_suite/io/fits_loader.py::load_image` gana un parámetro
  `plane` opcional, que pasa tal cual a `load_fits`.
- Nueva función `probe_fits_shape(path)` -- lee solo el header (sin
  cargar píxeles) para obtener la forma completa del cubo, que la GUI
  necesita para construir el selector de plano sin tener que parsear el
  mensaje de la excepción.
- `qt_app/io/cube_plane_dialog.py` (nuevo): `CubePlaneDialog` -- un
  `QSpinBox` por cada eje sobrante (`ndim - 2`), acotado al tamaño real
  de ese eje, mostrando la forma completa del cubo. El usuario confirma
  explícitamente; no hay ningún valor por defecto que se aplique sin que
  el usuario pulse "Aceptar".
- `qt_app/main_window.py::open_fits`: primer intento sin `plane` (igual
  que antes); si lanza `AmbiguousCubeError`, se inspecciona la forma real
  con `probe_fits_shape` y se abre `CubePlaneDialog`; si el usuario
  confirma, se reintenta `load_image(..., plane=...)`. Si cancela, no se
  abre ninguna ventana (igual que cancelar cualquier otra selección en el
  taller) -- no es un error, es una decisión del usuario. El título de la
  ventana resultante indica el plano elegido y la forma original del
  cubo (p. ej. `cubo_HA.fits [plano (3,) de (5, 24, 24)]`), para que
  nunca quede ambiguo qué se está viendo.

## 4. Tests

- `tests/unit/io/test_fits_loader.py` (5 pruebas nuevas): confirma que
  `AmbiguousCubeError` se sigue lanzando sin `plane` (la política
  correcta no cambió); `load_image(path, plane=N)` selecciona la
  rebanada 2D correcta para un cubo 3D; `plane=(i, j)` para un cubo 4D;
  `probe_fits_shape` da la forma real sin cargar píxeles, para cubos y
  para FITS 2D normales.
- `tests/gui_smoke/test_qt_app_smoke.py` (2 pruebas nuevas, con
  `QApplication` real): flujo completo -- abrir un cubo 3D real,
  confirmar/elegir plano en `CubePlaneDialog`, verificar que la ventana
  abierta contiene exactamente la rebanada 2D correcta (comparación
  `np.testing.assert_array_equal` contra el cubo original, no solo "no
  lanza"); cancelar el diálogo no abre ninguna ventana.

Suite completa verde en ambos entornos: 373 tests en `aps-test` (+5),
450 en `aps-gui` (+2), `ruff --select F,E9` limpio en los 5 archivos
nuevos/tocados.

## 5. Alcance

Esto resuelve **abrir** un cubo FITS y ver la rebanada 2D elegida --
suficiente para inspeccionar y usar cualquier proceso del taller sobre
ese plano, exactamente igual que sobre cualquier otra imagen 2D. No
añade selección de plano dentro de "Nueva observación" (Discovery) ni de
"Reducir sesión de LIGHTS..." -- si esos flujos necesitan aceptar cubos
3D/4D en el futuro, necesitarán el mismo patrón (capturar
`AmbiguousCubeError`, pedir el plano) aplicado en sus propios puntos de
carga; no se ha hecho aquí para no ampliar el alcance de este fix más
allá del síntoma reportado.
