# 102 — CONSTRUIR: Importar plantilla de referencia desde texto (λ, flujo)

Encargo directo del usuario: convertir un espectro de referencia real
que trajo en un archivo de texto (`N3000-01996.SSP`, estrella G6 V, dos
columnas longitud de onda/flujo -- formato típico de una biblioteca
espectral externa) en algo utilizable como plantilla en "Comparación con
plantilla de referencia" (informe 101).

## Qué se construyó

Dos funciones nuevas en `spectrum1d_io.py`, cero motores científicos
nuevos:

- `import_ascii_spectrum(path)`: lee un archivo de texto genérico de dos
  columnas (longitud de onda en Å, flujo) -- cualquier línea que no
  empiece por dos números reales se trata como cabecera y se descarta
  del array, pero la primera de esas líneas se devuelve tal cual (nunca
  se pierde en silencio el metadato real de origen, p. ej. el
  identificador del objeto). Exige longitud de onda estrictamente
  creciente -- un archivo desordenado o corrupto falla de forma
  honesta, nunca se reordena en silencio.
- `save_reference_template_fits(path, wavelength, flux, ...)`: escribe
  esos datos como FITS 1D con WCS `WAVE-TAB` EXACTO (misma convención
  -TAB ya usada por `wavelength_header_cards` para una calibración
  polinómica, §16 -- tabla de búsqueda real, nunca una recta aproximada
  que introduciría un error que el archivo de texto no tenía).
  Deliberadamente SIN `CALTYPE`/`APSWAVSR`: esas tarjetas describen la
  procedencia de una calibración hecha por ESTE taller
  (`calibration_provenance.py`), y una plantilla importada de fuera no
  pasó por ninguna -- ponérselas sería una procedencia falsa.

Releíble después sin cambios por `load_spectrum1d_fits`, que ya existía
(informe 100/101).

## GUI

"Comparación con plantilla de referencia..." tiene ahora, junto a
"Elegir plantilla (FITS 1D)...", el botón **"Importar plantilla desde
texto (λ, flujo)..."**: elige el archivo de texto directamente, sin
tener que convertirlo a mano primero. Internamente usa
`import_ascii_spectrum` y deja los datos ya listos para comparar --
convertir a FITS en disco es opcional (`save_reference_template_fits`),
solo hace falta si se quiere reutilizar la plantilla fuera de esta
sesión o en otro programa.

## Validación con el archivo real del usuario

`N3000-01996.SSP` (600 puntos, 3700.00-4698.33 Å, paso ~1.667 Å, cabecera
`*SpHdr* N3000-01996,7.103218,34.47361,5.550`): importado y convertido a
FITS real, ida y vuelta exacta verificada (`load_spectrum1d_fits` tras
`save_reference_template_fits` reproduce longitud de onda y flujo sin
pérdida). Entregado al usuario como
`N3000-01996_G6V_template.fits`, listo para "Elegir plantilla (FITS 1D)..."
sin pasos intermedios.

## Tests

- `tests/unit/spectroscopy/test_spectrum1d_io.py`: +7 (importa datos
  reales, conserva la cabecera, ignora líneas en blanco, rechaza menos
  de dos filas reales, rechaza longitud de onda no creciente en vez de
  reordenar, ida y vuelta exacta a FITS, nunca una procedencia de
  calibración falsa, rechaza formas no coincidentes).
- `tests/gui_smoke/test_qt_app_template_comparison_smoke.py`: +1
  (importa una plantilla de texto real end-to-end y compara con una
  ventana observada real).

`pytest tests/unit tests/integration tests/regression -q`: **1778
passed, 25 skipped** (7 nuevos sobre la base de 1771 del informe 101).
`pytest tests/gui_smoke -q` bajo Xvfb: **222 passed** (1 nuevo sobre
221).
