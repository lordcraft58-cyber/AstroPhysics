# Informe 76 — Espectroscopía slice 21: calibración por estrella de referencia (§13)

Continuación de los informes 55-75. Quinto slice construido directamente
a partir de la auditoría del informe 71: cierra §13 -- `CalibrationSource.
REFERENCE_STAR` existía como valor del enum en `calibration_provenance.py`
desde antes de este slice (con sus avisos de honestidad ya codificados en
`build_wavelength_provenance`), pero ningún motor real lo producía
todavía.

## 1. El hueco real

Sin una lámpara de calibración real disponible, un usuario con una
estrella de tipo espectral conocido (p. ej. una estándar A0V como Vega,
con Balmer en absorción) no tenía ninguna forma de obtener una
calibración en longitud de onda -- aunque el modelo de datos del
proyecto ya distinguía explícitamente este caso (`REFERENCE_STAR`) de
una calibración de lámpara real o sintética.

## 2. `astrophysics_suite/spectroscopy/reference_star_calibration.py` (nuevo)

`calibrate_from_reference_star(pixel, flux, continuum, catalog, ...)` --
reutiliza TRES motores ya reales y ya probados, sin duplicar ninguno:

1. `object_line_identification.detect_object_lines` (detección real de
   dos pasadas con signo, absorción Y emisión) -- aquí en espacio de
   PÍXEL en vez de longitud de onda, porque la calibración todavía no
   existe; la función es unidad-agnóstica (solo usa el espaciado real
   entre puntos), así que esto es reutilización directa, documentada
   como tal en el docstring del módulo.
2. `line_catalog.match_lines_to_catalog` -- mismo motor que ya usa el
   flujo de lámpara de arco (`wavelength_fit_dialog.py`), aquí contra un
   catálogo de OBJETO (Balmer, Ca II, Na D...) en vez de uno de lámpara.
3. `wavelength.fit_wavelength_solution` -- mismo ajuste final que
   cualquier otra calibración del proyecto.

Devuelve siempre el `WavelengthCalibrationRecord` COMPLETO (con
`source=CalibrationSource.REFERENCE_STAR` y `reference_object` ya
puesto), nunca solo la solución desnuda, para que el aviso obligatorio
de `build_wavelength_provenance` -- "la posición de una línea estelar
depende también de velocidad radial y ensanchamiento, no solo de la
óptica" -- nunca se pueda perder aguas abajo. Lanza `ValueError`
honesto (nunca `None` silencioso) si ninguna línea real detectada llega
a emparejarse, o si las que sí lo hacen no bastan para el grado pedido.

## 3. `spectroscopy.reference_star_calibration` (nuevo proceso, `registry.py`)

Misma convención de fila central que "Calibrar longitud de onda..."
(`_open_wavelength_fit_flow`) -- sin picking, opera sobre toda la fila
central de una vez. `reference_object` se lee del `OBJECT` REAL de la
cabecera FITS si lo tiene (`header.get("OBJECT")`); sin él, un
marcador de posición honesto explícito ("objeto sin nombre en la
cabecera FITS") en vez de inventar un nombre de estrella -- no existe
ningún tipo de parámetro de texto libre en el contrato genérico de
`ParameterSpec` (solo float/int/bool/choice), así que ampliar ese
contrato solo para este campo habría sido un cambio mucho más amplio y
arriesgado que leer un dato que la propia cabecera FITS ya suele traer.

Nuevo artefacto `wavelength_calibration_record`/`wavelength_calibration_
spectrum` en `ProcessResult.artifacts`, con su manejo correspondiente en
`main_window._on_process_finished` (mismo patrón que `zeropoint_fit`):
aplica `view.fitted_wavelength_solution`/`view.wavelength_calibration_
record`/`view.wavelength_calibration_spectrum`, dejando "Guardar espectro
calibrado..." y "Medir velocidad radial..." funcionando exactamente
igual que tras una calibración de lámpara.

## 4. Validación

| Verificación | Resultado |
|---|---|
| `ruff check` (código nuevo/modificado) | limpio |
| `tests/unit/spectroscopy/test_reference_star_calibration.py` (nuevo, 5 tests) | recupera una dispersión conocida a partir de líneas de Balmer sintéticas reales con una dispersión aproximada errónea en un 1%; el registro de procedencia avisa de "estrella de referencia" y NUNCA de "SIMULADA" (hay evidencia real detrás); rechaza `reference_object` vacío; falla honestamente sin ninguna línea real ni con muy pocas coincidencias para el grado pedido |
| `tests/unit/qt_app/test_registry.py` (+3 tests) | aplica una calibración provisional real con el `OBJECT` real de la cabecera; cae al marcador honesto sin cabecera real; falla con `ValueError` sobre un continuo puro sin ninguna línea real |
| `tests/gui_smoke/test_qt_app_reference_star_calibration_smoke.py` (nuevo, 1 test) | tras ejecutar el proceso, `view.fitted_wavelength_solution`/`view.wavelength_calibration_record`/`view.wavelength_calibration_spectrum` quedan aplicados exactamente igual que tras "Calibrar longitud de onda..." |
| Suite unitaria completa (`pytest tests/ --ignore=tests/gui_smoke`) | **1019 passed** (antes del slice: 1011 passed) |
| Suite de humo GUI completa (`xvfb-run pytest tests/gui_smoke/`, venv `aps-gui`) | **184 passed** (antes: 183) |
| Motor de extremo a extremo sobre `Vega_1sec_1x1__frame6.fit` real (vía `qt_app.processes.registry`, misma traza real ya validada en slices anteriores) | `OBJECT` real de la cabecera ("Vega") leído y usado correctamente como `reference_object`; con la misma dispersión de referencia aproximada ya documentada en el informe 60 (1.4 Å/px, sin lámpara real en los datos adjuntados) y una tolerancia realista (5 Å), el motor falla LIMPIAMENTE con `ValueError` -- 0 de 18 detecciones reales coincide dentro de esa tolerancia -- **mismo resultado honesto ya aceptado y documentado en el informe 60 para el motor de identificación de líneas de objeto sobre este mismo archivo**: sin una lámpara real, una calibración precisa no siempre es posible, y el motor debe decirlo, nunca inventar una coincidencia |

## 5. Qué queda fuera de este slice

No se ha construido ningún diálogo interactivo de confirmación línea a
línea (al estilo `WavelengthFitDialog`) para este flujo -- el proceso
usa los mismos parámetros explícitos (dispersión/origen aproximados,
tolerancia, catálogo) que ya exige el resto del taller como su propia
"etapa de confirmación" (§10), en vez de una tabla editable dedicada;
añadir esa tabla interactiva queda fuera del alcance mínimo de este
slice. Del informe 71, siguen pendientes: edición manual interactiva
del overlay 2D (§2/§3/§5/§35) y botón "AUTOPROCESS SPECTRUM" (§34).
