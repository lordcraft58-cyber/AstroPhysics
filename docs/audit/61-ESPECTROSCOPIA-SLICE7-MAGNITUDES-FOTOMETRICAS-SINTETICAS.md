# Informe 61 — Espectroscopía slice 7: magnitudes fotométricas sintéticas desde espectro

Continuación de los informes 55-60. Cierra la tarea de tablero **#99 —
"Espectroscopía slice 7: magnitudes fotométricas sintéticas desde
espectro (§50)"**.

## 1. Motor: `astrophysics_suite/spectroscopy/synthetic_photometry.py`

Magnitud AB sintética real: `m_AB = -2.5*log10(f_nu[erg/s/cm^2/Hz]) -
48.60`, la **definición matemática exacta** del sistema AB (Oke & Gunn
1983, ApJS 27, 21) -- una constante de la definición del sistema, no un
valor medido ni aproximado. El flujo efectivo bajo el filtro se calcula
con la fórmula de fotones ponderados estándar (Fukugita et al. 1996, AJ
111, 1748):

```
f_nu_eff = integral(f_nu(lambda) * R(lambda) / lambda dlambda)
           / integral(R(lambda) / lambda dlambda)
```

La conversión `f_lambda -> f_nu` usa `astropy.units.spectral_density`
(evita cualquier error manual de conversión de unidades) -- verificado
numéricamente: un espectro plano de 3631 Jy da `m_AB = 0.0000...` como
exige la propia definición del sistema, y escalar el flujo x100 cambia
la magnitud en exactamente 5.000 (relación de Pogson).

**Nunca extrapola** (`synthetic_effective_f_nu` devuelve `None`) cuando
el espectro dado no cubre por completo el rango real del filtro, ni
cuando el flujo efectivo resultante no es positivo (no hay magnitud real
que dar sobre un flujo neto nulo o negativo).

`relative_magnitude()` da `m_a - m_b` bajo el mismo filtro sin necesitar
ningún punto cero absoluto -- pensado para comparar contra una estrella
de referencia real (p. ej. Vega vía `standard_stars.load_calspec_
spectrum`, Slice 3); el llamador suma aparte la magnitud catalogada real
de la referencia si quiere una magnitud absoluta en el sistema Vega, en
vez de asumirla aquí.

**Nunca llama "magnitud" al resultado de una mera normalización**
(§37/§41, mismo principio que en todo el proyecto): el motor exige flujo
YA calibrado físicamente en erg/s/cm²/Å (la misma convención que produce
`fluxcal.calibrate_flux`, Fase 9.5) -- sobre ADU sin calibrar o un
espectro solo normalizado a continuo=1, el número que devuelve no tiene
significado físico real, y así lo dice explícitamente la documentación
del módulo y el propio diálogo de la GUI.

## 2. Ninguna curva de filtro inventada

Ninguna curva de transmisión de filtro se hardcodea: `load_filter_
curve()` lee siempre un archivo real de dos columnas (longitud de onda
en Å, transmisión de fotones 0-1) -- el mismo formato que exporta el SVO
Filter Profile Service (http://svo2.cab.inta-csic.es/theory/fps/), la
fuente pública estándar de la comunidad. `JOHNSON_COUSINS_FILTERS`/
`SDSS_FILTERS` son catálogos deliberadamente modestos de solo IDENTIDAD
(nombre/banda/longitud de onda central típica, valores de sobra
publicados) -- nunca la forma exacta de una curva, que este módulo no
puede verificar de memoria y que cambiaría el resultado de verdad.
Mismo criterio que `standard_stars.py` (Slice 3) con los espectros de
referencia CALSPEC.

## 3. GUI

`qt_app/spectroscopy/synthetic_photometry_dialog.py` (nuevo, menú
Espectroscopía -> "Magnitud fotométrica sintética..."): exige una
calibración en longitud de onda ya ajustada (mismo requisito que "Medir
velocidad radial..."), botón "Cargar curva de filtro (SVO, .dat)..." que
abre un archivo real, combo de identidad de filtro solo informativo, y
"Calcular magnitud AB" -- con un aviso permanente en el propio diálogo
de que el resultado solo es una magnitud real si el flujo de la ventana
activa ya está calibrado físicamente.

## 4. Validación

| Verificación | Resultado |
|---|---|
| `ruff check` (código nuevo + modificado) | limpio |
| `tests/unit/spectroscopy/test_synthetic_photometry.py` (nuevo, 13 tests) | magnitud AB exacta para 3631 Jy, relación de Pogson exacta, nunca extrapola, rechaza filtro sin área, magnitud relativa recupera una razón de flujo conocida |
| `tests/gui_smoke/test_qt_app_synthetic_photometry_smoke.py` (nuevo, 4 tests) | carga real de archivo de filtro, cálculo real de magnitud, aviso honesto sin filtro cargado, aviso honesto de cobertura incompleta |
| Suite unitaria completa (`pytest tests/ --ignore=tests/gui_smoke`) | **937 passed** (antes del slice: 924 passed) |
| Suite de humo GUI completa (`xvfb-run pytest tests/gui_smoke/`, venv `aps-gui`) | **166 passed** (antes: 162) |
| Motor de extremo a extremo sobre `Vega_1sec_1x1__frame6.fit` real (traza+extracción reales) | corre sin excepciones sobre el flujo ADU extraído -- documentado explícitamente como sin significado físico real (esta cámara no tiene todavía una calibración de flujo absoluta en el taller, ver §5) |

## 5. Limitación real, documentada explícitamente: no hay todavía un camino de GUI para calibrar flujo físicamente

El proceso `spectroscopy.fluxcal` del registro de procesos existe como
motor real (`fluxcal.py`, Fase 9.5/18) pero sigue sin `run=` cableado en
la GUI -- documentado ya en el propio registro como "pendiente de esa
interacción" (necesita elegir un espectro de estrella estándar +
catálogo de flujos, no encaja en el panel de parámetros genérico). Esto
significa que, HOY, ninguna ventana del taller puede llegar a tener un
flujo genuinamente calibrado en erg/s/cm²/Å de principio a fin dentro de
la GUI -- el diálogo de este slice es honesto al respecto (avisa
explícitamente) en vez de fingir que cualquier ventana activa ya lo
está. Cerrar ese camino completo (diálogo de calibración de flujo
absoluta) queda fuera de este slice, documentado aquí para no perderlo.

## 6. Qué queda fuera de este slice

Del encargo original de 79 secciones: diálogo de calibración de flujo
absoluta en la GUI (§5 de este informe), objetos extendidos/nebulosas
(§27), corrección de flexión espectral entre exposiciones (§44),
corrección telúrica real (más allá del aviso de solape del Slice 6,
§46), soporte échelle (§52-54), y el bloque extendido de QC/informe/
reproducibilidad (§63-78).
