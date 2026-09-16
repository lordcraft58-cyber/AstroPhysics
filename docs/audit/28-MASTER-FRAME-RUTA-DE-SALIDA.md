# 28 — Guardado de fotogramas maestros en ruta elegida

## 1. Problema real reportado

"Construir fotograma maestro" combinaba bias/dark/flat correctamente,
pero el resultado solo quedaba en el estado en memoria de
`MasterFrameLibrary` -- nunca se escribía a disco, no había forma de
elegir dónde guardarlo, y se perdía al cerrar la aplicación.

## 2. Cambios

### 2.1 `astrophysics_suite/reduction/master_frames.py`: `save_master_frame`/`load_master_frame`

Un `MasterFrame` no es solo `data`: `uncertainty` (incertidumbre real
por píxel) se propaga de verdad en `calibration.py` al restar/dividir
por un maestro (`apply_calibration`), y `n_combined` documenta cuántos
fotogramas se combinaron. Guardar solo `data` y, al releer, rellenar
`uncertainty` con ceros inventados habría falseado esa propagación de
errores -- exactamente la clase de dato inventado que el encargo prohíbe.

`save_master_frame(path, frame)` escribe un FITS real de 3 HDUs:
primario (`data`, con cabecera `MASTKIND`/`NFRAMES`/`EXPTIME`/`FILTER`),
extensión `UNCERT` (incertidumbre real) y extensión `NCOMBINE` (nº de
fotogramas combinados por píxel). `load_master_frame(path)` es la
inversa real -- y si el FITS no tiene esa forma exacta (no fue guardado
por esta función), lo rechaza con un `ValueError` explícito en vez de
aceptarlo con datos fabricados.

### 2.2 `qt_app/reduction/build_master_frame_dialog.py`

Nuevo campo "Carpeta/archivo de salida" + botón "Examinar..." (abre un
`QFileDialog.getSaveFileName` real). El nombre propuesto se deriva de
"Nombre" + la última carpeta usada, pero deja de actualizarse en cuanto
el usuario edita la ruta a mano. Se añade `.fits` automáticamente si
falta la extensión. Si el archivo ya existe, se pide confirmación
(`QMessageBox.question`, por defecto "No") antes de sobrescribir.

El botón ahora se llama "Combinar y guardar": tras combinar en el hilo
de fondo (sin cambios ahí), escribe el FITS real con
`save_master_frame` y solo entonces registra el maestro en
`MasterFrameLibrary` -- con su ruta real, nunca solo en memoria. Si la
escritura falla (permiso denegado, disco lleno...), se muestra el error
real y NO se registra en la biblioteca ni se cierra el diálogo -- el
usuario puede corregir la ruta y reintentar.

### 2.3 `services/app_preferences.py` (nuevo)

Recuerda la última carpeta de salida usada, entre construcciones y entre
sesiones -- mismo patrón ya establecido por
`services/instrument_profiles.py` (un único JSON bajo
`~/.astrophysics_suite/`, sin base de datos).

### 2.4 `qt_app/reduction/master_frame_library.py`

`NamedMasterFrame` gana `path: str | None` y `saved_at: datetime | None`
-- la biblioteca sigue siendo en memoria (no una base de datos), pero
ahora sabe si una entrada tiene un archivo real detrás y cuál.

### 2.5 "Cargar fotograma maestro..." (nuevo, menú Reducción)

`qt_app/main_window.py`: abre un FITS ya guardado
(`load_master_frame`), propone un nombre (editable) derivado del
archivo, y lo registra en la biblioteca con su ruta real -- así es como
un maestro guardado en una sesión anterior se "reutiliza en sesiones
posteriores": reabriendo el archivo real, no con un índice propio
persistido aparte (deliberado, para no introducir una base de datos que
el encargo pide explícitamente evitar).

## 3. Verificación real (no solo "no lanza")

- Bias/Dark/Flat construidos y guardados en una ruta elegida por el
  test (no una ruta interna fija); el archivo existe de verdad en disco
  tras `_on_combine`.
- Dark: `exposure_s` sobrevive guardar + reabrir con `load_master_frame`.
- Confirmación de sobrescritura: con "No", el archivo existente
  (verificado con un contenido centinela) queda intacto y el maestro NO
  se registra en la biblioteca; con "Yes", se sobrescribe de verdad.
- Reutilización entre sesiones: un `MainWindow` NUEVO (biblioteca vacía)
  carga el FITS guardado por el primero vía "Cargar fotograma
  maestro...", y el resultado se usa de verdad en una calibración real
  (`ApplyCalibrationDialog`) cuyo resultado numérico coincide con lo
  esperado -- no solo "aparece en la lista".

## 4. Tests

`tests/unit/reduction/test_master_frames.py` (+5): round-trip completo
data/uncertainty/n_combined; exposición de dark preservada; rechazo de
un FITS que no es un maestro guardado por esta función;
`overwrite=False` falla si el archivo ya existe.

`tests/unit/services/test_app_preferences.py` (nuevo, 4 tests).

`tests/gui_smoke/test_qt_app_reduction_smoke.py` (+4, y 2 existentes
extendidos con la ruta de salida real): exposición de dark tras
recarga; confirmación de sobrescritura (No no toca el archivo, Yes sí);
recarga de un maestro guardado en un `MainWindow` nuevo, usado en una
calibración real de extremo a extremo.

Suite completa sin regresiones en ambos entornos (aps-test: 396
passed/3 skipped; aps-gui: 483 passed/2 skipped/1 xfailed).

## 5. Pendiente (no hecho en esta ronda)

- El resto de operaciones que producen archivos (FITS calibrados/
  registrados de sesión, tablas CSV, etc.) no se ha tocado en esta
  ronda -- varias ya tenían su propio selector de ruta desde fases
  anteriores (p. ej. `ReduceSessionDialog`); una revisión sistemática de
  cuáles aún guardan a una ruta fija queda para el objetivo 6 del
  encargo, no abordado todavía.
