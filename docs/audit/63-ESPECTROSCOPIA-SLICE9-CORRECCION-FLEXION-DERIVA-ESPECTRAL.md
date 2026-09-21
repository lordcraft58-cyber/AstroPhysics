# Informe 63 — Espectroscopía slice 9: corrección de flexión/deriva espectral entre exposiciones

Continuación de los informes 55-62. Cierra la tarea de tablero **#101 —
"Espectroscopía slice 9: corrección de flexión/deriva espectral entre
exposiciones (§44)"**.

## 1. Motivación (§44)

Entre exposiciones consecutivas de la misma configuración instrumental
(el mismo arco no se repite antes de cada exposición científica, o el
instrumento deriva por flexión mecánica/térmica a lo largo de la noche),
la solución de longitud de onda ajustada sobre un arco de referencia deja
de ser exacta: el espectro completo se desplaza unos pocos píxeles sin
que cambie la forma (dispersión) de la calibración. Recalcular el
polinomio completo por cada exposición es innecesario y más frágil que
recuperar solo ese desplazamiento global.

## 2. Motor: `astrophysics_suite/spectroscopy/flexure_correction.py`

- `measure_flexure_shift(reference_solution, reference_spectrum,
  new_spectrum, *, reference_wavelength, max_shift_px=50)` reutiliza
  directamente `wavelength.reidentify_wavelength_solution` (Fase 15, ya
  probado) para recuperar el desplazamiento global real por correlación
  cruzada -- **nunca** reajusta el polinomio completo.
- Convierte ese desplazamiento a las tres unidades que pide el encargo:
  `shift_px`, `shift_angstrom` (usando la dispersión LOCAL real de la
  solución original en `reference_wavelength`, por diferencia finita
  centrada sobre la propia solución invertida numéricamente -- nunca una
  dispersión media global asumida) y `shift_velocity_km_s` (reutilizando
  `radial_velocity.velocity_from_wavelength_shift` de la Slice 4, misma
  convención Doppler clásica en todo el proyecto).
- `reference_solution` debe ser la solución "base" (`reference_pixel_
  shift == 0`); el desplazamiento medido REEMPLAZA cualquier
  `reference_pixel_shift` previo en vez de acumularse con él -- documentado
  explícitamente en el docstring: para una serie larga de exposiciones,
  comparar siempre contra la exposición de referencia original evita
  acumular error de encadenar exposición-a-exposición.

### Hallazgo real corregido durante la construcción

La primera versión calculaba `shift_px = shifted_solution.
reference_pixel_shift - reference_solution.reference_pixel_shift`, que
conflaciona los marcos de referencia cuando `reference_solution.
reference_pixel_shift` ya es distinto de cero. `reidentify_wavelength_
solution` **reemplaza** el desplazamiento, no lo acumula -- así que la
resta era conceptualmente incorrecta. Simplificado a usar directamente
`shifted_solution.reference_pixel_shift`, con la precondición documentada
en el docstring en vez de intentar manejar el encadenamiento.

## 3. GUI: `qt_app/spectroscopy/flexure_correction_dialog.py`

Diálogo dedicado (menú Espectroscopía → "Corrección de flexión entre
exposiciones..."), mismo patrón de dos ventanas reales establecido en
`RadialVelocityDialog`/`FluxCalibrationDialog`:

- Ventana de REFERENCIA (ya calibrada, `fitted_wavelength_solution` +
  `wavelength_calibration_record` reales) y ventana NUEVA (misma
  configuración instrumental, sin necesitar su propia calibración).
- `reference_wavelength_spin` se rellena solo con la mediana real de
  longitud de onda de la ventana de referencia.
- Rechaza explícitamente anchos distintos (`"anchos distintos"`) en vez
  de dejar que la correlación cruzada falle con un error interno opaco.
- Al guardar, el registro de calibración se marca SIEMPRE con
  `offset_only_reidentified=True` (mismo campo honesto de procedencia de
  la Slice 3/§12): nunca se presenta un desplazamiento global recalculado
  como si fuera una calibración recién medida por líneas.
- Guarda el resultado como FITS 1D real (`save_spectrum1d_fits`, sin
  `flux_bunit` -- la corrección de flexión no toca el flujo, solo la
  solución de longitud de onda, así que el `BUNIT` por defecto `"ADU"` es
  correcto aquí).

## 4. Validación

| Verificación | Resultado |
|---|---|
| `ruff check` (código nuevo) | limpio |
| `tests/unit/spectroscopy/test_flexure_correction.py` (nuevo, 7 tests) | recupera un desplazamiento sintético conocido dentro de la precisión ya establecida de `reidentify_wavelength_solution`; Δλ coherente con la dispersión local real; Δv coherente con la fórmula Doppler clásica; desplazamiento nulo da ~0; la forma del polinomio nunca cambia; rechaza formas distintas |
| `tests/gui_smoke/test_qt_app_flexure_correction_smoke.py` (nuevo, 3 tests) | mide y aplica un desplazamiento sintético conocido de principio a fin (incluye guardado real de FITS y verificación de `offset_only_reidentified=True`); rechaza anchos distintos; exige dos ventanas abiertas |
| Motor de extremo a extremo sobre `Vega_1sec_1x1__frame6.fit` real (traza + extracción reales; desplazamiento de 2.4 px inyectado sobre el espectro real por interpolación) | desplazamiento medido: 2.330 px (error 0.07 px); control sin desplazamiento: 0.000 px exacto |
| Suite unitaria completa (`pytest tests/ --ignore=tests/gui_smoke`) | **946 passed** (antes del slice: 939 passed) |
| Suite de humo GUI completa (`xvfb-run pytest tests/gui_smoke/`, venv `aps-gui`) | **172 passed** (antes: 169) |

La validación sobre datos reales de Vega confirma una precisión bastante
mejor (0.07 px) que la observada con arcos sintéticos de tres líneas
aisladas (Slice 3/9, ~0.3-0.5 px) -- consistente con que un espectro
estelar real con múltiples líneas de absorción a lo largo de todo el
rango aporta mucha más señal a la correlación cruzada que unas pocas
líneas de arco puntuales.

### Error de test corregido (no del motor)

Durante la primera ejecución de la prueba de humo GUI,
`test_flexure_correction_dialog_rejects_mismatched_widths` fallaba por un
error en el propio test: generaba una imagen "estrecha" de 500 px de
ancho reutilizando las líneas por defecto `(200.0, 500.0, 800.0)`, y la
línea en 800 cae fuera de un array de 500 elementos, produciendo un
`ValueError` de broadcasting antes de siquiera llegar al diálogo.
Corregido pasando líneas explícitas que caben dentro del ancho reducido
(`(100.0, 250.0, 400.0)`); no había ningún defecto en el código de
producción.

## 5. Qué queda fuera de este slice

Del encargo original de 79 secciones: objetos extendidos/nebulosas
(§27), corrección telúrica real -- más allá del aviso de solape del
Slice 6 (§46), soporte échelle (§52-54), y el bloque extendido de
QC/informe/reproducibilidad (§63-78).
