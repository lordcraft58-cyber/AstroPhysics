# Informe 68 — Espectroscopía slice 14: visualización de mapa de calidad 2D

Continuación de los informes 55-67. Primer motor del bloque §63-78
("QC/diagnóstico") que no queda ya cubierto por las slices 12/13
(saturación, ruido CCD real) -- concretamente, "visualización de mapa de
calidad 2D".

## 1. El hueco real

Desde las slices 12/13, `spectroscopy.trace`/`multiaperture`/
`extended_extraction` ya excluyen píxeles reales (no finitos, saturados
según `SATURATE` real) de cualquier medida, y lo declaran en el resumen
del proceso ("N píxel(es) saturado(s) excluido(s)"). Pero ese resumen es
solo un RECUENTO en texto -- el usuario no podía ver DÓNDE están esos
píxeles en la imagen, ni distinguir un puñado disperso de un
cluster que invalida toda una columna de la traza.

## 2. `qt_app/processes/registry.py` -- `spectroscopy.quality_map`

Proceso nuevo, sin ninguna física nueva: reutiliza exactamente
`frame2d.build_pixel_mask` (motor ya probado desde el informe 55) con el
mismo `SATURATE` real de cabecera que ya usa `_saturation_mask_from_
header` desde la slice 12, y opcionalmente `imtools.cosmic_rays.detect_
cosmic_rays` (ya probado, Fase 9.1) si se activa "Detectar también rayos
cósmicos reales". El resultado (`PixelFlag` combinado bit a bit, `0` =
bueno) se abre como una imagen nueva -- visible directamente en el
visor con el mismo control de stretch/colormap que cualquier otra
imagen del taller, en vez de solo un número en el resumen.

El resumen y el registro declaran el desglose real por motivo
(`NONFINITE`/`SATURATED`/`COSMIC_RAY`) y, cuando se activa la detección
de rayos cósmicos sin `GAIN` real en la cabecera, lo dice explícitamente
("GAIN aproximado=1.0 e-/ADU (sin GAIN real en la cabecera)") -- el
mismo principio de honestidad epistémica de siempre: nunca presentar un
resultado calculado con un valor asumido como si fuera preciso.

## 3. Validación

| Verificación | Resultado |
|---|---|
| `ruff check` (código nuevo) | limpio |
| `tests/unit/qt_app/test_registry.py` (+3 tests) | marca solo NaN/Inf reales sin `SATURATE` real; marca píxeles saturados reales con `SATURATE` real y lo declara en el registro; la detección de rayos cósmicos solo se activa si se pide explícitamente |
| `tests/gui_smoke/test_qt_app_quality_map_smoke.py` (nuevo, 2 tests) | abre una ventana nueva con los píxeles reales marcados de principio a fin; confirma que el proceso no requiere ningún clic (va directo al hilo de fondo) |
| Motor de extremo a extremo sobre `Vega_1sec_1x1__frame6.fit` real | sin `SATURATE`/`GAIN` reales (el caso real de este archivo): 0 píxeles marcados, coincide exactamente con `np.count_nonzero(~np.isfinite(data))` del frame real (0); con `SATURATE=45000` inyectado: 215 píxeles marcados, coincide exactamente con el recuento ya validado en la slice 12; con detección de rayos cósmicos activada (`GAIN` aproximado, sin valor real en la cabecera, declarado como tal): 23365 píxeles adicionales -- un recordatorio real de que el recuento de rayos cósmicos depende de la ganancia asumida cuando no hay una real, justo lo que el mensaje de aviso existe para comunicar |
| Suite unitaria completa (`pytest tests/ --ignore=tests/gui_smoke`) | **979 passed** (antes del slice: 976 passed) |
| Suite de humo GUI completa (`xvfb-run pytest tests/gui_smoke/`, venv `aps-gui`) | **178 passed** (antes: 176) |

## 4. Qué queda fuera de este slice

Del bloque §63-78: manejo de calibración por lotes, modo de vigilancia
de directorio, apilado espectral, versionado, base de datos de perfiles
de instrumento, modos vista-rápida vs. reducción científica, comparación
antes/después, informe PDF/HTML, motor de validación física, separación
de API del pipeline, exportación de configuración reproducible. Y, del
resto del encargo de 79 secciones, soporte échelle (§52-54).
