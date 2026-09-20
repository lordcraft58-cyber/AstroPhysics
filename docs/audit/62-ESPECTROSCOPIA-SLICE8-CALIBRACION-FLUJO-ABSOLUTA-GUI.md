# Informe 62 — Espectroscopía slice 8: GUI de calibración de flujo absoluta

Continuación de los informes 55-61. Cierra la tarea de tablero **#100 —
"Espectroscopía slice 8: GUI de calibración de flujo absoluta (§48)"**,
y con ella el hueco explícito documentado en el informe 61 §5: hasta este
slice, `spectroscopy.fluxcal` era un motor real sin ningún camino de GUI
para llegar a usarlo.

## 1. Diálogo: `qt_app/spectroscopy/flux_calibration_dialog.py`

Sobre `astrophysics_suite.spectroscopy.fluxcal` (ya existente y probado
desde la Fase 9.5/18, sin cambios en el motor mismo). Dos ventanas reales,
ambas ya calibradas en longitud de onda: la de la estrella estándar
(cuentas) y la científica a calibrar.

- La referencia física de la estándar se carga SIEMPRE de un archivo
  CALSPEC real (`standard_stars.load_calspec_spectrum`, Slice 3) -- nunca
  inventada. El combo de identidad de estrella (`CALSPEC_STANDARD_STARS`)
  es solo informativo/de procedencia, igual que en `synthetic_photometry_
  dialog.py`.
- La masa de aire se toma de la cabecera real (`AIRMASS`) cuando existe
  (verificado con la prueba de humo: `airmass_spin` se rellena solo con el
  valor real de la cabecera), o el usuario la da a mano -- nunca se asume
  `1.0` en silencio.
- Conversión ADU -> cuentas/s exige `EXPTIME`/`EXPOSURE` REAL de la
  cabecera -- si no está, el diálogo falla con un mensaje claro en vez de
  asumir un tiempo de exposición de 1 s.
- Ajusta la función de sensibilidad real (`build_sensitivity_function`) y
  la muestra en una tabla exportable (longitud de onda, sensibilidad
  medida, sensibilidad ajustada) -- las curvas visibles que pide el
  encargo (§48).
- Aplica la sensibilidad a la ventana científica (`calibrate_flux`) y
  guarda el resultado como FITS 1D real con procedencia completa
  (`FLUXCAL`, `STDSTAR`, `STDFILE`, `SENSDEG`, `AIRMASS`, `EXTCOEF`) --
  nunca sobrescribe el original.

## 2. Hallazgo real corregido: `BUNIT` se pisaba en silencio a `"ADU"`

Al escribir el primer FITS calibrado de prueba, `header_out["BUNIT"]`
salía `"ADU"` a pesar de haber pasado explícitamente `"erg/s/cm2/
Angstrom"` en el `header` del llamador. Causa raíz real en
`spectrum1d_io.save_spectrum1d_fits` (código ya existente desde la
slice 2, informe 56): `wavelength_header_cards()` fijaba
`cards["BUNIT"] = "ADU"` de forma incondicional, y ese diccionario se
aplicaba SIEMPRE DESPUÉS del `header` del llamador -- así que cualquier
`BUNIT` real que el llamador diera quedaba pisado en silencio. Un flujo
ya calibrado físicamente por `fluxcal.calibrate_flux` se habría guardado
etiquetado como si fueran cuentas crudas, sin ningún aviso.

Corregido añadiendo un parámetro real `flux_bunit: str = "ADU"` a
`wavelength_header_cards()`/`save_spectrum1d_fits()` (aditivo, el valor
por defecto preserva exactamente el comportamiento anterior para los
usos ya existentes de escritura de espectros calibrados en longitud de
onda pero NO en flujo físico) -- el diálogo de este slice es el primer
llamador real que pasa `flux_bunit="erg/s/cm2/Angstrom"`. 2 tests de
regresión nuevos en `test_spectrum1d_io.py` (uno confirma el valor por
defecto, otro reproduce exactamente el hallazgo: pasar `BUNIT` dentro de
`header` NO basta, hace falta `flux_bunit`).

## 3. Validación

| Verificación | Resultado |
|---|---|
| `ruff check` (código nuevo + modificado) | limpio |
| `tests/unit/spectroscopy/test_spectrum1d_io.py` (+2 tests, 12 en total) | valor por defecto ADU preservado, `flux_bunit` nunca pisado |
| `tests/gui_smoke/test_qt_app_flux_calibration_smoke.py` (nuevo, 3 tests) | recupera un flujo de referencia real conocido a través de una respuesta instrumental sintética conocida (error relativo mediano <10% en el núcleo del rango), exige EXPTIME real, avisa sin referencia cargada |
| Suite unitaria completa (`pytest tests/ --ignore=tests/gui_smoke`) | **939 passed** (antes del slice: 937 passed) |
| Suite de humo GUI completa (`xvfb-run pytest tests/gui_smoke/`, venv `aps-gui`) | **169 passed** (antes: 166) |
| Motor de extremo a extremo sobre `Vega_1sec_1x1__frame6.fit` real (traza+extracción reales, referencia sintética de ley de potencias solo para la prueba) | corre sin excepciones; `BUNIT` guardado correctamente como `erg/s/cm2/Angstrom`, no `ADU` |

## 4. Qué queda fuera de este slice

Del encargo original de 79 secciones: objetos extendidos/nebulosas (§27),
corrección de flexión espectral entre exposiciones (§44), corrección
telúrica real -- más allá del aviso de solape del Slice 6 (§46), soporte
échelle (§52-54), y el bloque extendido de QC/informe/reproducibilidad
(§63-78).
