# Informe 85 — Espectroscopía slice 30: cierre de la auditoría menor final (§1/§7/§11/§14/§18)

Continuación del informe 84. Cierra los cinco puntos menores de baja
prioridad que quedaban abiertos del informe 71 tras el slice 29, más una
confirmación explícita sobre §26.

## §18 — sin cambio de código

La propia tabla de auditoría del informe 71 ya marcaba §18 como "Hecho
(esencia)" antes de este slice. Revisado de nuevo: sigue siendo cierto,
no se necesita ningún cambio. Se documenta aquí solo para dejar
constancia explícita del cierre, sin inventar trabajo que no hacía falta.

## §1 — robustez del lector genérico de FITS ante extensiones no-imagen

`_first_image_hdu_index` (`astrophysics_suite/io/fits_reader.py`), la
función real que usa `load_fits` para encontrar la HDU con la imagen,
ya comprobaba `getattr(hdu, "is_image", False) and hdu.header.get(
"NAXIS", 0) >= 2` -- lógica correcta para saltar una HDU primaria vacía
o una extensión de tabla real (p. ej. un registro de órdenes de un
echelle) y encontrar la imagen 2D real. No tenía ninguna prueba
específica que lo demostrara.

- **Diseño**: sin cambio de código fuente -- solo cobertura de prueba
  nueva, la corrección más honesta cuando la lógica ya es correcta.
- `tests/unit/io/test_fits_loader.py` (+1 test):
  `test_load_fits_skips_a_non_image_extension_to_find_the_real_2d_frame`
  construye un FITS real con HDU primaria vacía + extensión de tabla +
  extensión de imagen, y comprueba que `load_fits` encuentra la imagen
  real (`hdu_index == 2`), nunca la tabla ni la primaria vacía.
- Validación real sobre `Vega_1sec_1x1__frame6.fit`: `load_fits` (el
  lector genérico real de la GUI) abre el fotograma espectroscópico real
  de Vega sin ninguna transformación especial (`shape=(1039, 1391)`,
  `hdu_index=0`).

## §7 — integración real reducción CCD → preprocesado espectroscópico → traza/extracción

Hasta ahora `preprocess_spectroscopic_frame` (bias/dark/flat/píxeles
defectuosos/rayos cósmicos) y `trace_spectrum`/`extract_sum`/
`extract_optimal` solo se probaban por separado. Nada demostraba que
componen de verdad tal como afirma el propio docstring de
`preprocessing.py`.

- **Diseño**: sin cambio de código fuente -- son motores ya construidos
  y ya probados por separado; lo que faltaba era la prueba de
  integración que demuestra la composición real.
- `tests/integration/test_reduction_spectroscopy_pipeline.py` (nuevo,
  2 tests):
  - `test_preprocessed_mask_really_protects_the_extraction_from_a_real_cosmic_ray`:
    inyecta un rayo cósmico real en un fotograma sintético, comprueba
    que `preprocess_spectroscopic_frame` lo marca en la máscara real, y
    que pasar esa máscara a `extract_sum` protege de verdad la columna
    contaminada frente a no pasarla -- comparado contra un valor de
    referencia real (extracción limpia del mismo fotograma sin el rayo
    cósmico inyectado, con tolerancia absoluta+relativa, en vez de
    comparar contra una columna vecina en continuo dominado por ruido de
    Poisson, que resultó ser una comparación frágil).
  - `test_full_reduction_and_extraction_chain_recovers_the_true_wavelength_solution`:
    bias+flat real → traza → extracción óptima → detección de líneas →
    ajuste de solución de longitud de onda, y comprueba que la solución
    recuperada coincide con la real (`atol=1.5` Å) -- la cadena completa
    no degrada lo que ya probaba `test_wavelength_calibration_pipeline.py`
    (§43) por separado.

## §11 — avisos reales de procedencia de calibración visibles en la GUI

`build_wavelength_provenance` (`calibration_provenance.py`) ya generaba
avisos reales (p. ej. pocas líneas usadas respecto al grado del
polinomio) para cualquier calibración, sintética o real, pero
`main_window._on_wavelength_fitted` nunca los leía ni los mostraba --
quedaban solo en el registro de operaciones si alguien miraba el log con
atención.

Se descartó deliberadamente la lectura alternativa de "hacer alcanzable
desde la GUI el aviso de calibración SINTÉTICA": una calibración
sintética es solo para pruebas internas y no debe poder dispararse desde
la GUI real por diseño -- no es un hueco real. El hueco real es la clase
general de avisos que ya aplican también a calibraciones reales
(`LAMP_REAL`) y no llegaban al usuario.

- **Diseño**:
  - `qt_app/main_window.py`: `_on_wavelength_fitted` ahora construye la
    procedencia real (`build_wavelength_provenance(record)`) cuando hay
    un `record`, registra cada aviso real en el log con `logger.warning`,
    y añade un recuento real de avisos al mensaje de la barra de estado
    (p. ej. "-- 1 aviso(s), ver registro de operaciones.") -- nunca
    inventa avisos que la procedencia real no generó.
- `tests/gui_smoke/test_qt_app_wavelength_smoke.py` (+2 tests):
  - `test_wavelength_fitted_surfaces_real_provenance_warnings`: un
    `WavelengthCalibrationRecord` real con pocas líneas respecto al
    grado dispara un aviso real de procedencia -- aparece en el log
    (nivel AVISO) y en la barra de estado.
  - `test_wavelength_fitted_without_real_warnings_stays_silent_about_them`:
    una calibración real sin motivo de aviso no muestra ninguno
    (honestidad: nunca mostrar un aviso que no corresponde a una
    condición real).

## §14 — canal de calibración lateral/simultánea integrado en la corrección de flexión

`lateral_calibration.py` (`extract_lateral_calibration_spectrum`,
`LateralCalibrationWindow`) ya existía como motor aislado y probado,
pero "Corrección de flexión espectral entre exposiciones..."
(`flexure_correction_dialog.py`) solo medía el desplazamiento usando la
fila central del objeto -- nunca ofrecía usar un canal de calibración
lateral real, pese a que el propio docstring de `lateral_calibration.py`
lo mencionaba como su caso de uso principal.

- **Diseño**:
  - `qt_app/spectroscopy/trace_overlay_data.py`: nuevo campo
    `TraceOverlay.calibration_windows` (misma geometría que
    `SkyWindow`) para dibujar la región real del canal de calibración,
    distinta de OBJETO/CIELO.
  - `qt_app/mdi/image_window.py`: color propio (`#c77dff`) para las
    regiones de calibración en `_draw_trace_overlay_item`; nuevo método
    público `set_calibration_windows(trace, windows)` que añade/
    reemplaza esas regiones sobre el overlay ya dibujado (o crea uno
    mínimo con la traza real ya conocida si todavía no había ninguno).
  - `qt_app/spectroscopy/flexure_correction_dialog.py`: casilla nueva
    "Usar canal de calibración lateral/simultánea (§14)" + controles de
    desplazamiento/semiancho reales. `_spectrum_for_view` reutiliza
    literalmente `view.trace_edit_context` (la MISMA traza ya calculada,
    slice 29 -- nunca retraza) y llama a
    `extract_lateral_calibration_spectrum` con la ventana real indicada;
    si la vista no tiene traza todavía, error honesto en vez de
    silenciar el fallo; si el canal no tiene ninguna medida real en esa
    ventana, error honesto en vez de medir un desplazamiento sobre ruido.
    Decisión deliberada y documentada con un comentario explícito: el
    producto GUARDADO (`_on_save`) sigue siendo siempre el espectro real
    del OBJETO (fila central), nunca el canal de calibración, aunque ese
    canal se haya usado para MEDIR el desplazamiento -- lo que se
    persiste es la ciencia con la longitud de onda ya corregida, no el
    canal auxiliar.
- `tests/gui_smoke/test_qt_app_trace_overlay_smoke.py` (+2 tests):
  `set_calibration_windows` añade una tercera región real distinguible
  sin perder las de cielo ya dibujadas; crea un overlay mínimo real
  cuando todavía no había ninguno.
- `tests/gui_smoke/test_qt_app_lateral_calibration_smoke.py` (nuevo,
  2 tests): mide un desplazamiento real conocido (3.0 px) usando el
  canal de calibración de dos fotogramas sintéticos trazados de verdad
  vía el registro de procesos, con `shift_px` recuperado dentro de
  ±0.6 px del valor real inyectado, y comprueba que la región real queda
  dibujada en ambas vistas; y que exigir el canal sin una traza real
  previa falla con un mensaje honesto en vez de intentar medir sobre
  datos inexistentes.

## Validación consolidada

- `ruff check astrophysics_suite qt_app tests`: limpio.
- Suite unitaria completa: **1070 passed** (antes: 1067).
- Suite de humo GUI completa: **202 passed** (antes: 196).
- Validación real sobre `Vega_1sec_1x1__frame6.fit` para cada punto
  aplicable (§1, §7 vía los motores ya validados en informes previos);
  §11 y §14 son funcionalidades de interacción GUI/dependientes de un
  canal de calibración lateral real que Vega no tiene, así que se
  validaron con datos sintéticos con desplazamiento conocido, como
  corresponde.

## Cierre del informe 71

Con este slice se cierran los cinco puntos menores que quedaban
abiertos (§1, §7, §11, §14, §18) tras el informe 84. Solo queda §26
(clasificador de tipo espectral), deliberadamente no construido por baja
viabilidad real sin una biblioteca de plantillas verificada -- mismo
límite ya documentado para §25 en el informe 83 y confirmado sin cambios
en este slice. La auditoría de 43 secciones del informe 71 queda cerrada
en su totalidad, salvo esa única limitación documentada y deliberada.
