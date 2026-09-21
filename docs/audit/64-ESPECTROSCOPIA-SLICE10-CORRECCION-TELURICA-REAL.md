# Informe 64 — Espectroscopía slice 10: corrección telúrica real (§46)

Continuación de los informes 55-63. Cierra la brecha explícitamente
declarada en `telluric_lines.py` (Slice 6, informe 60) y repetida en el
informe 62 §4: hasta este slice, la única capacidad telúrica del sistema
era identificar solape de bandas conocidas, nunca corregirlas.

## 1. Motor: `astrophysics_suite/spectroscopy/telluric_correction.py`

Física estándar de una atmósfera plano-paralela (profundidad óptica
telúrica escala linealmente con la masa de aire):

- `measure_standard_transmission(wavelength, flux, ...)` normaliza el
  espectro REAL de una estrella estándar telúrica por su propio continuo
  ajustado (reutiliza `continuum.fit_continuum(..., reject="both")`, ya
  probado desde la Fase 9.5), aislando la transmisión atmosférica de la
  forma espectral intrínseca de la estrella -- ninguna profundidad se
  inventa, se mide directamente del espectro dado.
- `correct_telluric_absorption(...)` divide el espectro científico por
  `T_std(λ) ** (X_sci / X_std)` -- la transmisión medida de la estándar
  escalada por la razón de masas de aire real entre las dos exposiciones.

### Disciplina de honestidad: SOLO dentro de bandas catalogadas

La corrección se aplica exclusivamente dentro de las bandas de
`telluric_lines.TELLURIC_BANDS` que la estándar realmente cubre en
longitud de onda -- nunca en todo el rango observado. Fuera de esas
bandas, cualquier "transmisión" medida en el espectro de la estándar es
en realidad una línea fotosférica propia de la estrella (o ruido de su
continuo), no atmósfera real, y aplicarla ahí contaminaría el espectro
científico con features que no le pertenecen. Verificado explícitamente
con un test que inyecta una línea fotosférica profunda de la estándar
fuera de cualquier banda catalogada y confirma que el científico queda
exactamente sin tocar ahí (`corrected_flux == science_flux`,
`correction_factor == 1.0`).

`min_transmission` acota por debajo el divisor -- una transmisión medida
arbitrariamente cerca de cero por ruido del continuo de la estándar no
debe disparar el flujo corregido a un valor arbitrariamente grande.

El resultado (`TelluricCorrectionResult`) siempre devuelve el factor de
corrección real aplicado píxel a píxel y una máscara de qué píxeles se
corrigieron de verdad -- cumpliendo el verbatim del encargo (§46): "nunca
eliminar automáticamente sin mostrar qué corrección se aplicó".

## 2. GUI: `qt_app/spectroscopy/telluric_correction_dialog.py`

Mismo patrón de dos ventanas reales establecido en
`RadialVelocityDialog`/`FluxCalibrationDialog`/`FlexureCorrectionDialog`:
ventana de la estándar telúrica y ventana científica, ambas ya calibradas
en longitud de onda. Masa de aire tomada de `AIRMASS` real de cabecera
cuando existe, o dada a mano -- nunca asumida en `1.0` en silencio. La
tabla de resultado muestra exactamente qué bandas se usaron (nombre,
especie, rango real), y el guardado añade procedencia completa
(`TELLCORR`, `TELLSTD`, `TELLAIRS`, `TELLAIRT`, `TELLNBND`) sin tocar el
registro de calibración en longitud de onda (esta corrección solo toca
flujo, nunca la solución espectral).

## 3. Validación

| Verificación | Resultado |
|---|---|
| `ruff check` (código nuevo) | limpio |
| `tests/unit/spectroscopy/test_telluric_correction.py` (nuevo, 8 tests) | recupera la profundidad inyectada de una banda sintética; corrige de verdad una banda conocida; NUNCA corrige fuera de bandas catalogadas aunque la estándar muestre una línea propia profunda ahí; el exponente de masa de aire escala la corrección; el piso de transmisión mínima acota el divisor; rechaza masas de aire no positivas; sin bandas cubiertas deja el flujo intacto; rechaza formas distintas |
| `tests/gui_smoke/test_qt_app_telluric_correction_smoke.py` (nuevo, 2 tests) | mide y aplica una banda telúrica sintética conocida de principio a fin (incluye guardado real de FITS con `TELLCORR` en cabecera); exige dos ventanas abiertas |
| Motor de extremo a extremo sobre `Vega_1sec_1x1__frame6.fit` real (traza + extracción reales; banda O2 B sintética de profundidad 0.5 inyectada sobre la FORMA/RUIDO real del espectro extraído) | error relativo tras corrección: **0.07%**; píxeles fuera de la banda: corregido == crudo byte a byte |
| Suite unitaria completa (`pytest tests/ --ignore=tests/gui_smoke`) | **954 passed** (antes del slice: 946 passed) |
| Suite de humo GUI completa (`xvfb-run pytest tests/gui_smoke/`, venv `aps-gui`) | **174 passed** (antes: 172) |

## 4. Qué queda fuera de este slice

Del encargo original de 79 secciones: objetos extendidos/nebulosas
(§27), soporte échelle (§52-54), y el bloque extendido de
QC/informe/reproducibilidad (§63-78).
