# Informe 67 — Espectroscopía slice 13: ruido CCD real (ADU↔electrón) en trazado/extracción interactivos

Continuación de los informes 55-66. Mismo patrón del slice 12
(saturación): un motor real y correcto para la física ya existía
(`imtools.cosmic_rays._noise_model`, usado internamente por L.A.Cosmic),
pero toda la parte interactiva de espectroscopía seguía usando la
aproximación `sqrt(ADU)` sin ninguna posibilidad de usar la ganancia/
ruido de lectura reales del instrumento cuando la cabecera FITS los trae.

## 1. Por qué `sqrt(ADU)` es una aproximación, no el ruido real

El ruido de disparo (Poisson) actúa sobre ELECTRONES reales detectados,
no sobre cuentas ADU -- `sqrt(ADU)` solo es exacto si la ganancia del
instrumento es exactamente 1 e-/ADU y no hay ruido de lectura, algo que
casi ninguna cámara real cumple. La fórmula correcta (misma disciplina
CCD estándar que ya usa `L.A.Cosmic` en este proyecto):

```
señal_e = ADU · ganancia          (electrones reales detectados)
ruido_e = sqrt(señal_e + ruido_lectura_e²)
ruido_ADU = ruido_e / ganancia
```

Este proyecto ya lo hacía bien en un solo sitio (`imtools.cosmic_rays.
_noise_model`, con parámetros `gain_e_per_adu`/`read_noise_e` que la GUI
de `imtools.cosmic_removal` ya expone), pero cada proceso interactivo de
espectroscopía (`spectroscopy.trace`, `multiaperture`,
`extended_extraction`, `line`, `line_profile_fit`) construía su propia
incertidumbre con `np.sqrt(np.clip(data, 1.0, None))` -- la aproximación
burda, sin ninguna forma de usar `GAIN`/`RDNOISE` reales aunque
estuvieran en la cabecera.

## 2. `astrophysics_suite/imtools/ccd_noise.py` (nuevo)

`ccd_noise_adu(data_adu, *, gain_e_per_adu, read_noise_e=0.0)` -- la
fórmula de arriba, extraída de `cosmic_rays._noise_model` a un módulo
público y reutilizable (dirección de dependencia correcta:
`spectroscopy` ya depende de `imtools`, nunca al revés).
`cosmic_rays._noise_model` se refactorizó para llamar a esta función
compartida en vez de duplicar la fórmula -- **ninguna magnitud física se
mide dos veces por dos vías distintas**, misma disciplina que
`multiaperture.py`.

## 3. `qt_app/processes/registry.py` -- `_uncertainty_adu`

Helper nuevo, mismo patrón que `_saturation_mask_from_header` (slice
12): lee `header['GAIN']`/`header['RDNOISE']` reales; si `GAIN` no es un
valor real y positivo, cae al modelo aproximado `sqrt(ADU)` de siempre
(nunca se inventa una ganancia). Cableado en los cinco procesos
interactivos de espectroscopía que antes calculaban su propia
incertidumbre a mano: `spectroscopy.trace`, `spectroscopy.multiaperture`,
`spectroscopy.extended_extraction`, `spectroscopy.line`,
`spectroscopy.line_profile_fit`. El resumen de cada proceso declara
explícitamente qué modelo se usó ("ruido real (GAIN=... e-/ADU[, RDNOISE=...
e-])" o "ruido Poisson aproximado (sin GAIN real)") -- nunca aparenta una
precisión que no tiene.

Los tres procesos de FOTOMETRÍA (`photometry.aperture`, `photometry.
zeropoint`, `photometry.psf`) quedan **fuera de este slice**: ya declaran
explícitamente en su propia descripción de la GUI que usan el modelo
aproximado "mientras el taller no importa la incertidumbre real de
calibración" -- tocar ese motor ya cerrado (informes 16/38-42) queda
fuera del alcance de "terminar espectroscopía".

## 4. Validación

| Verificación | Resultado |
|---|---|
| `ruff check` (código nuevo/modificado) | limpio |
| `tests/unit/imtools/test_cosmic_rays.py` (sin cambios, 7 tests) | sigue en verde tras el refactor -- confirma que `_noise_model` produce exactamente el mismo resultado llamando a la función compartida |
| `tests/unit/imtools/test_ccd_noise.py` (nuevo, 6 tests) | coincide con el cálculo manual Poisson+lectura; el caso límite gain=1/ruido=0 coincide exactamente con `sqrt(ADU)`; mayor ganancia reduce el ruido en ADU; señal negativa se recorta a 0 antes del término Poisson; rechaza ganancia no positiva y ruido de lectura negativo |
| `tests/unit/qt_app/test_registry.py` (+5 tests) | `_uncertainty_adu` cae a `sqrt(ADU)` sin `GAIN` real (ausente, no numérico, o negativo); usa la fórmula real con `GAIN`+`RDNOISE`; usa la fórmula real con solo `GAIN` (`RDNOISE` por defecto 0); `spectroscopy.trace` reporta cuál modelo se usó en ambos casos |
| Motor de extremo a extremo sobre `Vega_1sec_1x1__frame6.fit` real | el frame real **no trae `GAIN`/`RDNOISE`** en su cabecera -- confirmado que cae correctamente al modelo aproximado tal cual llega; con `GAIN=1.2`/`RDNOISE=3.0` inyectados (representativo de una cámara astronómica real de ganancia baja), la incertidumbre real difiere de la aproximada (16.31 vs. 17.65 ADU de media en una región de fondo real) y `spectroscopy.trace` lo reporta de principio a fin en su resumen |
| Suite unitaria completa (`pytest tests/ --ignore=tests/gui_smoke`) | **976 passed** (antes del slice: 965 passed) |
| Suite de humo GUI completa (`xvfb-run pytest tests/gui_smoke/`, venv `aps-gui`) | **176 passed** (sin cambios -- wiring interno, ninguna prueba de GUI nueva) |

## 5. Qué queda fuera de este slice

Del bloque §63-78: manejo de calibración por lotes, modo de vigilancia
de directorio, apilado espectral, versionado, base de datos de perfiles
de instrumento, modos vista-rápida vs. reducción científica, comparación
antes/después, informe PDF/HTML, motor de validación física, separación
de API del pipeline, exportación de configuración reproducible. Y, del
resto del encargo de 79 secciones, soporte échelle (§52-54).
