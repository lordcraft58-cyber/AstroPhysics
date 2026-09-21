# Informe 70 — Espectroscopía slice 16: perfiles de instrumento reales como respaldo de GAIN/RDNOISE

Continuación de los informes 55-69. Tercer motor del bloque §63-78
("base de datos de perfiles de instrumento") -- descubierto al auditar
qué ya existía antes de construir nada nuevo: `services.instrument_
profiles.InstrumentProfileStore` (Fase 10.2, informe 30-31) ya guardaba
`gain_e_per_adu`/`read_noise_e` reales por cámara para la reducción CCD
(`ReduceSessionDialog`), pero la Slice 13 (ruido CCD real en
espectroscopía) solo consultaba la cabecera FITS de la exposición
concreta -- sin ningún respaldo cuando esa cabecera, como el propio
frame real de Vega usado en toda esta serie, no trae `GAIN`/`RDNOISE`.

## 1. El hueco real

Validado en la propia slice 13: `Vega_1sec_1x1__frame6.fit` no tiene
`GAIN` en su cabecera, así que `spectroscopy.trace`/etc. caían siempre al
modelo aproximado `sqrt(ADU)` para ESTE archivo real, aunque el usuario
ya hubiera guardado la ganancia real de su cámara en un perfil de
instrumento para la reducción CCD -- ese conocimiento real nunca llegaba
a los procesos de espectroscopía.

## 2. Cableado (reutiliza `InstrumentProfileStore`, sin cambios en el motor)

- `MainWindow.__init__` gana `instrument_profile_store: InstrumentProfileStore
  | None = None` (mismo patrón ya existente de `preferences`), y pasa
  `profile_store=self.instrument_profile_store` a `build_process_
  registry()`.
- `build_process_registry(*, profile_store=None)` lee los nombres de los
  perfiles YA guardados por el usuario para ofrecerlos como `choices` de
  un nuevo parámetro `instrument_profile` en los cinco procesos de
  trazado/extracción de espectroscopía (`spectroscopy.trace`/
  `multiaperture`/`extended_extraction`/`line`/`line_profile_fit`) --
  por defecto `"(usar cabecera FITS)"`, nunca un perfil elegido en
  silencio.
- `_start_process_worker` rellena `params["_instrument_profiles"]` (los
  perfiles reales, releídos de disco en cada ejecución -- reflejan un
  perfil guardado DESPUÉS de arrancar el taller, aunque la lista de
  `choices` del desplegable, fijada al construir el registro, no se
  actualice hasta reiniciar; limitación real, declarada aquí en vez de
  ocultarla).
- `_uncertainty_adu`: la cabecera de la exposición CONCRETA sigue
  teniendo prioridad siempre; solo cuando no trae `GAIN` real consulta el
  perfil elegido, y lo declara explícitamente en la nota ("... (perfil de
  instrumento «X»)") -- nunca se confunde con un valor medido de esta
  exposición en particular.

## 3. Validación

| Verificación | Resultado |
|---|---|
| `ruff check` (código modificado) | limpio |
| `tests/unit/qt_app/test_registry.py` (+5 tests) | el registro ofrece los perfiles reales guardados como opciones; `_uncertainty_adu` usa el perfil cuando la cabecera no trae `GAIN` real; la cabecera real SIEMPRE gana sobre un perfil elegido; el centinela "(usar cabecera FITS)" se ignora correctamente; `spectroscopy.trace` reporta el perfil usado en el resumen |
| `tests/gui_smoke/test_qt_app_instrument_profile_noise_smoke.py` (nuevo, 1 test) | `MainWindow` con un `InstrumentProfileStore` inyectado (mismo patrón ya usado por `ReduceSessionDialog` en sus propias pruebas) ofrece el perfil real guardado como opción y lo aplica de principio a fin vía clic real |
| Motor de extremo a extremo sobre `Vega_1sec_1x1__frame6.fit` real (sin `GAIN` real, con un perfil real guardado inyectado) | el resumen de `spectroscopy.trace` reporta correctamente "ruido real (GAIN=1.2 e-/ADU, RDNOISE=3 e- (perfil de instrumento «Vega camera (perfil real guardado)»))" -- exactamente el caso real que motivó este slice |
| Suite unitaria completa (`pytest tests/ --ignore=tests/gui_smoke`) | **984 passed** (antes del slice: 979 passed) |
| Suite de humo GUI completa (`xvfb-run pytest tests/gui_smoke/`, venv `aps-gui`) | **179 passed** (antes: 178) |

## 4. Qué queda fuera de este slice

Del bloque §63-78: manejo de calibración por lotes, modo de vigilancia
de directorio, apilado espectral, versionado, modos vista-rápida vs.
reducción científica, informe PDF/HTML, motor de validación física,
separación de API del pipeline, exportación de configuración
reproducible. Y, del resto del encargo de 79 secciones, soporte échelle
(§52-54).
