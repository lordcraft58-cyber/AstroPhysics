# Informe 60 — Espectroscopía slice 6: identificación automática de líneas de objeto + base de datos de líneas telúricas

Continuación de los informes 55-59. Cierra la tarea de tablero **#98 —
"Espectroscopía slice 6: identificación automática de líneas de objeto +
líneas telúricas (§21/§22/§46)"**.

## 1. Identificación automática de líneas de objeto tras calibrar (§21, §22)

`astrophysics_suite/spectroscopy/object_line_identification.py` (nuevo).

A diferencia de la lámpara de arco (`wavelength.match_lines_to_catalog`,
que solo dispone de una dispersión APROXIMADA para predecir dónde caería
cada línea), aquí el espectro YA está calibrado en longitud de onda de
verdad -- el emparejamiento es directo por posición real, sin necesidad de
predecir nada.

- **`detect_object_lines()`**: detecta desviaciones reales del continuo,
  emisión Y absorción en la misma pasada, reutilizando `wavelength.
  find_arc_lines` (ya probado). **Hallazgo real corregido durante la
  construcción**: la primera versión aplicaba el detector sobre
  `abs(residuo)` en una única pasada para capturar ambos signos a la vez --
  pero el valor absoluto de un ruido gaussiano real es una distribución
  semi-normal (siempre >= 0), y el umbral `min_snr` de `find_arc_lines`
  (basado en la MAD del propio array de entrada) deja de corresponder a
  sigmas reales del ruido original bajo esa transformación: en la práctica
  disparaba falsos positivos muy por encima de lo que `min_snr=5.0`
  promete (confirmado con datos sintéticos de puro ruido). Corregido a DOS
  pasadas reales (residuo tal cual + residuo negado), cada una preservando
  la estadística gaussiana correcta -- verificado después: **0 falsos
  positivos en 50 ensayos** de puro ruido al umbral por defecto (antes de
  la corrección, fallaba con cierta frecuencia).
- **`identify_object_lines_in_spectrum()`**: para cada detección real,
  sugiere la línea de catálogo más cercana dentro de una tolerancia --
  **solo sugerencias** (§10/§21, mismo principio que en toda la suite):
  nunca se acepta nada automáticamente. Cada `ObjectLineMatch` lleva:
  - `confidence`: cercanía a la posición del catálogo (no una probabilidad).
  - `line_type_agrees`: si el signo real detectado (absorción/emisión)
    concuerda con el tipo catalogado de la línea -- `False` AVISA de una
    coincidencia de posición cuya naturaleza no encaja, sin descartarla:
    el llamador decide.
  - `telluric_overlap`: la banda telúrica real que solapa esa longitud de
    onda, o `None` -- ver §2.

## 2. Base de datos de líneas telúricas (§46)

`astrophysics_suite/spectroscopy/telluric_lines.py` (nuevo). Catálogo
modesto de bandas O2/H2O bien documentadas (O2 B ~6867-6884 Å, O2 A
~7594-7621 Å, y tres complejos de H2O) -- representadas como BANDAS
(rango de longitud de onda), no líneas individuales: a la resolución
típica de un espectrógrafo de aficionado, la absorción telúrica es un
complejo de muchas líneas mezcladas, no una línea aislada, así que una
banda es más honesta que fingir una posición de línea única.

Verbatim del encargo (§46), cumplido literalmente: *"nunca eliminar
automáticamente sin mostrar qué corrección se aplicó"* -- este módulo
**solo identifica solape** (`find_telluric_overlap()`/`bands_overlapping_
range()`). Ninguna corrección o sustracción telúrica se implementa
todavía (eso exigiría un espectro de estrella estándar telúrica, fuera de
este slice) -- ninguna profundidad numérica se inventa tampoco: `strength`
es descriptivo (`"strong"`/`"moderate"`), no una constante de catálogo
(la profundidad real depende de la masa de aire y la humedad de cada
observación concreta).

## 3. GUI

Nuevo proceso `spectroscopy.identify_lines` ("Identificar líneas
automáticamente", menú de procesos -> Espectroscopía) -- sin picking
(opera sobre toda la fila central calibrada de una vez): exige que la
ventana activa ya tenga una calibración en longitud de onda ajustada
(mismo requisito que "Medir velocidad radial..."), elige un conjunto de
líneas (Balmer/Ca II H&K/Na D/nebulares/todas), y muestra tabla + gráfica
con una banda etiquetada por cada línea identificada -- coloreada según su
estado: ámbar normal, ámbar-oscuro si solapa una banda telúrica, roja si
el tipo (absorción/emisión) no concuerda. `main_window._start_process_
worker` gana un nuevo parámetro especial reutilizable, `_wavelength_
solution`, mismo mecanismo que `_header`/`_wcs` ya existentes.

## 4. Validación

| Verificación | Resultado |
|---|---|
| `ruff check` (código nuevo + modificado) | limpio |
| `tests/unit/spectroscopy/test_object_line_identification.py` (nuevo, 12 tests) | detecta ambos signos, nunca inventa una línea sin evidencia, avisa de desacuerdo de tipo sin descartar, marca solape telúrico real, nunca falso positivo sobre puro ruido (verificado con 50 semillas) |
| `tests/unit/spectroscopy/test_telluric_lines.py` (nuevo, 8 tests) | catálogo modesto/ordenado, sin profundidades inventadas, solape inclusivo en los bordes |
| `tests/gui_smoke/test_qt_app_identify_lines_smoke.py` (nuevo, 3 tests) | flujo completo con líneas reales, fallo honesto sin calibración, cero coincidencias reportado sin fingir nada |
| Suite unitaria completa (`pytest tests/ --ignore=tests/gui_smoke`) | **924 passed** (antes del slice: 904 passed) |
| Suite de humo GUI completa (`xvfb-run pytest tests/gui_smoke/`, venv `aps-gui`) | **162 passed** (antes: 159) |
| Identificación real sobre `Vega_1sec_1x1__frame6.fit` (traza+extracción+continuo reales, eje aproximado marcado como tal) | corre sin excepciones: 31 desviaciones reales detectadas, 0 coincidencias de catálogo dentro de 3 Å -- resultado honesto sobre datos reales sin calibración de lámpara todavía, no forzado |

## 5. Qué queda fuera de este slice

Del encargo original de 79 secciones: objetos extendidos/nebulosas (§27),
corrección de flexión espectral entre exposiciones (§44), corrección/
sustracción telúrica real (más allá del aviso de solape de este slice,
§46), magnitudes fotométricas desde espectro (§50), soporte échelle
(§52-54), y el bloque extendido de QC/informe/reproducibilidad (§63-78).
