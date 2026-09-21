# 105 — CORREGIR: los diálogos de comparación leían la fila cruda del
# CCD, no el espectro real ya extraído

Queja directa y persistente del usuario, repetida palabra por palabra
incluso después de construir el diálogo de clasificación en vivo del
informe 104: *"pero compara el continuo no el espectro"*. Como la queja
seguía igual tras el nuevo diálogo, se descartó que fuera un malentendido
de UI y se releyó el código propio en busca de un fallo real.

## Causa raíz encontrada

Tanto `template_comparison_dialog.py::_on_compare` como el recién
construido `spectral_classification_dialog.py::_update` leían:

```python
flux = view.data[view.data.shape[0] // 2, :]
```

la fila central cruda del fotograma 2D -- sin resta de cielo, sin
extracción óptica (Horne 1986), tal cual sale del sensor. Eso es
exactamente "el continuo" que reportaba el usuario, nunca el espectro
real.

El propio `ImageWindow` (`qt_app/mdi/image_window.py`) ya tiene, desde
antes de esta entrega, un atributo dedicado para evitar justo este
error: `wavelength_calibration_spectrum` -- el espectro real y ya
extraído (óptimo/suma/media, con resta de cielo) sobre el que se ajustó
`fitted_wavelength_solution`, guardado en sincronía en los tres lugares
del código que calibran una ventana (autoprocesar §34, calibración por
estrella de referencia, calibración manual por líneas). Su propio
docstring lo advierte explícitamente: *"para no volver a suponer qué
fila es el espectro"*. Ninguno de los dos diálogos de comparación lo
estaba usando -- por eso comparaban forma de continuo de una sola fila
cruda, no el espectro real, con independencia de lo bien calibrada que
estuviera la longitud de onda.

## Corrección

`template_comparison_dialog.py::_on_compare` y
`spectral_classification_dialog.py::_update` ahora leen
`view.wavelength_calibration_spectrum` en vez de `view.data[fila, :]`,
con un aviso explícito y honesto (nunca un resultado silencioso) cuando
la ventana no lo tiene guardado todavía (p. ej. calibrada a mano sin
pasar por ninguno de los tres flujos reales):

```python
if view.wavelength_calibration_spectrum is None:
    self.result_label.setText(
        f"{view.title} no tiene guardado el espectro real sobre el que "
        "se calibró -- vuelve a calibrar (p. ej. \"Autoprocesar espectro "
        "(§34)\")."
    )
    return
flux = np.asarray(view.wavelength_calibration_spectrum, dtype=np.float64)
```

Reutiliza el mismo atributo ya existente -- no se duplicó lógica de
extracción ni se inventó un nuevo mecanismo.

## Regresión que prueba la corrección

Se construyó un test dedicado en cada diálogo (no solo se ajustaron los
tests existentes a la nueva invariante) que fija deliberadamente
`wavelength_calibration_spectrum` distinto de la fila cruda del `data`
2D (`+5000` de desplazamiento, inconfundible), y comprueba que lo que se
muestra/compara coincide con el espectro real extraído y NO con la fila
cruda:

- `tests/gui_smoke/test_qt_app_spectral_classification_smoke.py::test_spectral_classification_dialog_uses_the_real_extracted_spectrum_not_the_raw_ccd_row`
- `tests/gui_smoke/test_qt_app_template_comparison_smoke.py::test_template_comparison_dialog_uses_the_real_extracted_spectrum_not_the_raw_ccd_row`

Cualquier regresión futura al patrón antiguo (`view.data[fila, :]`)
haría fallar estos dos tests explícitamente.

Los tests de humo preexistentes de ambos diálogos también se
actualizaron para fijar `wavelength_calibration_spectrum` junto con
`fitted_wavelength_solution` -- la misma sincronía que ya exige el
código real (`main_window._on_wavelength_fitted` /
`_on_process_finished`), nunca solo uno de los dos atributos.

## Tests

`pytest tests/unit tests/integration tests/regression -q`: **1795
passed, 24 skipped** (sin cambios -- esta corrección es enteramente de
GUI, no toca `astrophysics_suite/`).

`pytest tests/gui_smoke -q` bajo Xvfb: **218 passed, 1 skipped** (+2
sobre los 216 previos: los dos nuevos tests de regresión dedicados).
