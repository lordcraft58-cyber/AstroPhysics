# Informe 83 — Espectroscopía slice 28: comparación con plantilla de referencia (§25)

Continuación del informe 82. Nota de auditoría antes de empezar: al
revisar el resto de huecos del informe 71 se confirmó que **§33
(generador sintético público reutilizable)** y **§43 (test de
integración con nombre propio, extremo a extremo)** YA estaban
completos de una fase anterior (`astrophysics_suite/spectroscopy/
synthetic_lamp.py` y `tests/integration/test_wavelength_calibration_
pipeline.py`, ambos citando literalmente "§33"/"§43" en su docstring) --
no eran huecos reales, corrige el resumen de cierre anterior.

## Diseño (§25)

- `astrophysics_suite/spectroscopy/template_comparison.py` (nuevo
  módulo, numpy puro): `compare_to_template(observed_wavelength,
  observed_flux, template_wavelength, template_flux, *, normalize)` --
  interpola la plantilla REAL sobre el eje real del observado (`NaN`
  fuera del rango real de la plantilla, nunca extrapolada), calcula el
  residuo punto a punto, y reporta `overlap_fraction` (fracción real de
  solape) para que el llamador pueda avisar si la comparación es poco
  significativa. `normalize="median"` (por defecto) reescala cada
  espectro por su propia mediana real sobre el solape -- compara la
  FORMA aunque los niveles de flujo absolutos difieran (p. ej. ADU
  crudo contra un espectro ya calibrado en flujo); `normalize="none"`
  compara los valores tal cual. Lanza `ValueError` honesto si la
  plantilla no solapa en absoluto con el observado.
- Deliberadamente NUNCA clasifica ni sugiere un tipo espectral (§25/§26
  siguen unidos por la misma razón real: sin una biblioteca de
  plantillas por tipo espectral REAL de la que generalizar, cualquier
  "coincidencia" automática sería una clasificación inventada). La
  "plantilla" es CUALQUIER espectro 1D real que el usuario elija --
  otra observación propia, una estándar, un archivo de otro programa --
  nunca un catálogo interno inventado.
- `qt_app/spectroscopy/template_comparison_dialog.py` (nuevo diálogo,
  menú Espectroscopía → "Comparar con plantilla de referencia..."):
  elige la ventana observada (ya calibrada en longitud de onda, misma
  convención de fila central que el resto de diálogos de
  espectroscopía) y carga la plantilla de un FITS 1D real
  (`spectrum1d_io.load_spectrum1d_fits`, el mismo formato que ya
  produce "Guardar espectro calibrado..."). Al comparar, abre una
  ventana de espectro nueva con tres curvas reales (observado,
  plantilla, residuo) y avisa en el registro si el solape real es bajo
  (<50%) -- nunca oculta que la comparación puede no ser significativa.

## Validación

- `ruff check`: limpio en los cuatro archivos nuevos/tocados.
- `tests/unit/spectroscopy/test_template_comparison.py` (nuevo, 8
  tests): residuo ~0 con la plantilla idéntica; normalización por
  mediana cancela un factor de escala constante; `normalize="none"`
  conserva la diferencia aditiva real; `NaN` real fuera del rango de una
  plantilla más estrecha; rechazo honesto sin solape en absoluto,
  formas distintas, normalización desconocida, y plantilla con menos de
  dos puntos.
- `tests/gui_smoke/test_qt_app_template_comparison_smoke.py` (nuevo, 2
  tests): flujo real de calibración + guardado + comparación contra el
  mismo espectro guardado (residuo ~0, solape 100% real, abre
  exactamente una ventana nueva); aviso real al intentar comparar sin
  haber elegido plantilla todavía.
- Suite unitaria completa: **1063 passed** (antes: 1055).
- Suite de humo GUI completa: **193 passed** (antes: 191).
- Validación real sobre `Vega_1sec_1x1__frame6.fit`: traza + extracción
  real, guardada dos veces como FITS 1D real y comparada consigo misma
  tras un ciclo completo de guardado/relectura -- solape real 100%,
  residuo máximo real 0 (exacto, como debe ser comparando un espectro
  real contra sí mismo a través del mismo formato FITS que usa el resto
  del taller).

## Qué queda del informe 71

Solo §2 (edición interactiva de traza/apertura/cielo sobre el overlay
del slice 17) sigue siendo un hueco real y grande. §1/§7/§11/§14/§18/§26
son verificaciones/auditorías menores de menor prioridad -- §26
(clasificador de tipo espectral) sigue de baja viabilidad real sin una
biblioteca de plantillas verificada (mismo motivo documentado arriba
para §25).
