# Informe 73 — Espectroscopía slice 18: resolución espectral real R=λ/FWHM (§32)

Continuación de los informes 55-72. Segundo slice construido directamente
a partir de la auditoría del informe 71: cierra §32 ("Hueco real
(pequeño)"), el error explícito que el encargo pide evitar --
"No confundir dispersión: Å/pixel con resolución: Å FWHM" -- y evita
duplicar por segunda vez la misma matemática de dispersión local que ya
existía en `flexure_correction.py` (Slice 9).

## 1. El hueco real

"Ajuste de perfil de línea (Gaussiana/Voigt)" (`spectroscopy.line_profile_fit`)
siempre trabajaba enteramente en espacio de píxel: el centro y el FWHM
ajustados se reportaban en píxeles de la fila central, nunca convertidos a
Å ni usados para calcular un poder resolutivo real, aunque la imagen
tuviera ya una calibración en longitud de onda real ajustada
(`_wavelength_solution`, poblada por `main_window` desde
`view.fitted_wavelength_solution`).

## 2. `wavelength.local_dispersion_at_pixel` (nuevo, público)

```python
def local_dispersion_at_pixel(solution: WavelengthSolution, pixel: float, *, delta: float = 0.5) -> float:
```

Dispersión real (dλ/dpíxel) de una solución en un píxel concreto, por
diferencia finita centrada evaluando la propia solución -- nunca una
dispersión media global asumida (`CDELT1` solo describe bien un ajuste
de grado ≤1; para un polinomio de grado superior la dispersión real varía
a lo largo del eje, confirmado con un test dedicado sobre una solución
cuadrática).

Esta matemática ya existía, duplicada en privado, como
`flexure_correction._local_dispersion_angstrom_per_px` (Slice 9, que
además invierte longitud de onda -> píxel antes de evaluarla, un paso
que sigue siendo específico de ese motor). Se ha refactorizado
`flexure_correction.py` para que delegue en la nueva función pública en
vez de reimplementar la diferencia finita por segunda vez -- misma
disciplina que unificó `ccd_noise_adu` en el Slice 13. Los 15 tests
existentes de `test_flexure_correction.py` siguen pasando sin cambios,
confirmando que el refactor no alteró ningún resultado.

## 3. `line_profile_fit.spectral_resolution` (nuevo)

```python
def spectral_resolution(center_wavelength_angstrom: float, fwhm_angstrom: float) -> float:
    return center_wavelength_angstrom / fwhm_angstrom
```

`R = λ/FWHM`, exigiendo explícitamente que ambos argumentos estén en Å
reales (nunca en píxeles) y sean positivos -- rechaza con `ValueError`
cualquier llamada degenerada en vez de devolver un número sin sentido
físico.

## 4. Cableado en `_run_line_profile_fit_central_row` (`registry.py`)

Tras el ajuste Gaussiano/Voigt real (sin cambios en su lógica ni en su
comportamiento cuando no hay calibración), se añade una conversión
posterior SOLO si `params["_wavelength_solution"]` es real:

1. Dispersión local real en el píxel del centro ajustado
   (`local_dispersion_at_pixel`).
2. Centro real en Å (`solution.pixel_to_wavelength(...)`).
3. FWHM real en Å (`|FWHM_px * dispersión_local|`).
4. `R = spectral_resolution(...)`.

Sin calibración, se informa honestamente en el registro de operaciones
que la resolución no está disponible -- nunca se asume una dispersión
inventada. La tabla de resultados siempre lleva las tres columnas
nuevas (`center_wavelength_angstrom`, `fwhm_angstrom`, `resolution`),
con `NaN` real (no una cadena vacía ni un cero) cuando no hay
calibración, para que un consumidor programático de la tabla nunca
reciba un valor fabricado.

## 5. Validación

| Verificación | Resultado |
|---|---|
| `ruff check` (código nuevo/modificado) | limpio |
| `tests/unit/spectroscopy/test_wavelength.py` (+2 tests) | `local_dispersion_at_pixel` recupera la dispersión lineal conocida en cualquier píxel; sobre una solución cuadrática real, la dispersión local difiere correctamente entre los dos extremos del rango (creciente, valor exacto en cada extremo) |
| `tests/unit/spectroscopy/test_line_profile_fit.py` (+3 tests) | `spectral_resolution` calcula R=λ/FWHM correctamente; rechaza FWHM y longitud de onda no positivos |
| `tests/unit/qt_app/test_registry.py` (+2 tests) | sin calibración: el resumen no menciona λ, el registro de operaciones dice explícitamente "no disponible", las 3 columnas nuevas son `NaN`; con una solución de dispersión lineal conocida (2.0 Å/px): centro/FWHM/R reales coinciden con el valor esperado analíticamente |
| `tests/unit/spectroscopy/test_flexure_correction.py` (sin cambios, 15 tests) | siguen pasando tras el refactor de `_local_dispersion_angstrom_per_px` para delegar en la nueva función pública -- confirma que el refactor no alteró ningún resultado |
| Motor de extremo a extremo sobre `Vega_1sec_1x1__frame6.fit` real | traza/extracción reales (igual que en la validación del Slice 5) localizan la absorción real más fuerte en la columna 555 (mínimo real del residuo, no asumido); el ajuste Gaussiano real converge (FWHM=5.818 px, significancia=532σ); con una solución de dispersión de referencia declarada (1.6 Å/px, misma aproximación ya usada y documentada en `valida_wavelength_real.py` por no haber lámpara de arco real en los datos adjuntados), la línea real cae en λ≈5087.2 Å, FWHM≈9.309 Å, R≈546 -- un valor de resolución físicamente razonable para este tipo de instrumento |
| Suite unitaria completa (`pytest tests/ --ignore=tests/gui_smoke`) | **994 passed** (antes del slice: 987 passed) |

No se han modificado tests de humo GUI en este slice: no hay ninguna
superficie de interfaz nueva, solo texto adicional en el resumen/registro
de operaciones de un proceso ya existente y tres columnas nuevas en su
tabla de resultados -- ambos ya cubiertos por los tests unitarios
directos sobre `process.run(...)`.

## 6. Qué queda fuera de este slice

Del informe 71, siguen pendientes: edición manual interactiva del
overlay 2D (§2/§3/§5/§35), informe de QC unificado (§31), conexión de
`air_vacuum.py` (ya construido, sin usar todavía) a un consumidor real
(§24), calibración por estrella de referencia (§13), botón "AUTOPROCESS
SPECTRUM" (§34), y el resto de huecos reales listados en ese informe.
