# AstroPhysics Suite — Fase 14: exportación real de tablas científicas

Quinto bloque del orden de prioridad acordado (`CCDRED → análisis de imagen →
fotometría → astrometría → tablas/catálogos → espectroscopía`). A diferencia de
los bloques anteriores (motor real ya existente, solo faltaba un camino de uso en
la GUI), `13-IRAF-CAPABILITY-MAP.md` §6 señalaba este bloque como una **brecha de
arquitectura**: no existía ningún tipo `Table`/`Source` compartido, y cada motor
(reducción, fotometría, astrometría, espectroscopía) sigue devolviendo su propio
dataclass de resultado local (`ApertureMeasurement`, `PSFFitResult`,
`WCSSolution`, `ExtractedSpectrum`...).

## 1. Decisión de alcance: qué se cierra y qué se deja explícitamente pendiente

Antes de construir nada, conviene decir con precisión qué resuelve esta fase y qué
no, porque las dos lecturas posibles del encargo son muy distintas en riesgo:

- **Lectura A (unificación profunda)**: reescribir `ApertureMeasurement`,
  `PSFFitResult`, `WCSSolution`, `ExtractedSpectrum`... para que hereden o se
  ajusten a un contrato `Measurement`/`Source` común. Esto tocaría los cuatro
  bloques ya cerrados y probados en las Fases 10-13 (309 tests que dependen
  directamente de esos tipos), con riesgo real de regresión, por un beneficio de
  arquitectura sin ninguna necesidad funcional concreta que lo exija hoy.
- **Lectura B (necesidad práctica)**: el encargo, en el fondo, pide poder
  **exportar mediciones reales a una tabla reproducible** -- eso es lo que un
  astrónomo espera poder hacer con los resultados de fotometría/astrometría, no
  necesariamente que el código interno comparta una jerarquía de clases.

Esta fase implementa la Lectura B, deliberadamente, y deja la Lectura A
documentada como brecha de arquitectura real para una fase dedicada -- la misma
disciplina de "menos funcionalidades, pero funcionando de verdad" que ha regido
todo el proyecto: una capacidad real y de bajo riesgo ahora, en vez de un refactor
grande y arriesgado sin necesidad inmediata.

## 2. `astrophysics_suite/tables/table.py` -- `Table`

Tipo de exportación genérico: columnas nombradas (con unidad opcional) + filas de
valores. **No sustituye ningún tipo de resultado existente** -- es una vista que
el llamador arma explícitamente a partir de un resultado real ya calculado (ver
§3), documentado así sin ambigüedad en el docstring del módulo para que nadie lo
confunda con el contrato unificado de la Lectura A.

- `Table.to_csv(path)` / `Table.from_csv(path)`: exportación real a disco, con
  las unidades codificadas en la cabecera (`"ra [deg]"`) y tipado automático al
  releer (entero, flotante o texto, en ese orden de preferencia).
- Validación real: número de columnas y unidades debe coincidir, cada fila debe
  tener la misma aridad que las columnas -- nunca una tabla mal formada
  silenciosa.

8 tests unitarios (`tests/unit/tables/test_table.py`): *roundtrip* real a disco
con tipos mixtos (entero/flotante/texto), cabecera con y sin unidades, archivo
vacío, creación de carpetas de salida que no existían, y los casos de error de
aridad.

## 3. Primeros dos consumidores reales

`ProcessResult` (`qt_app/processes/base.py`) gana un campo opcional
`table: Table | None = None` -- infraestructura reutilizable por cualquier
proceso futuro que produzca datos tabulares, no solo los dos de esta fase:

- **`photometry.zeropoint`** (Fase 12): además del punto cero agregado, ahora
  construye una `Table` con una fila por estrella que sí se emparejó con Gaia
  (columnas: posición de píxel, RA/Dec, magnitud instrumental, magnitud de
  catálogo, separación de emparejamiento) -- las medidas de entrada reales al
  ajuste robusto, no un resultado inventado. (No incluye qué estrellas rechazó
  el sigma-clip final de `fit_zeropoint`, porque esa función no expone ese
  detalle por índice -- documentado así en el comentario del código, una
  limitación real y reconocida, no oculta.)
- **`WCSFitDialog`** (Fase 13): la señal `fitted` pasa de emitir solo
  `WCSSolution` a emitir `(WCSSolution, Table)` -- una fila por estrella marcada,
  con su residuo en segundos de arco. El ajuste de WCS es el caso más claro de
  "tabla de calidad de ajuste" que el encargo pedía explícitamente
  ("exportación de posiciones junto con sus incertidumbres y métricas de
  calidad").

## 4. Mecanismo de exportación en la GUI

`main_window._last_result_table` guarda la última `Table` producida (por
cualquiera de los dos flujos anteriores, o por cualquier proceso futuro que use
`ProcessResult.table`), y "Herramientas → Exportar última tabla a CSV..." la
escribe a donde el usuario elija (`QFileDialog.getSaveFileName`). Un único
mecanismo genérico para ambos flujos, en vez de un botón de exportación
duplicado en cada diálogo.

## 5. Verificación

1 test unitario nuevo en `tests/unit/qt_app/test_registry.py` confirma la
estructura exacta de la tabla que produce `photometry.zeropoint`. 4 tests de humo
GUI nuevos en `tests/gui_smoke/test_qt_app_table_export_smoke.py`:

- Aviso claro cuando no hay ninguna tabla que exportar todavía.
- `photometry.zeropoint` de extremo a extremo (clic real + Gaia mockeada) hasta
  un archivo CSV real en disco, releído y verificado.
- "Ajustar WCS..." de extremo a extremo (clic real + tabla de coordenadas) hasta
  un archivo CSV real, con la columna de residuo verificada presente.

Suite completa verde en ambos entornos tras esta fase: 402 tests en el entorno
con PySide6 (`aps-gui`), 341 en el entorno sin GUI (`aps-test`), más `ruff`
limpio en los 8 archivos nuevos/tocados.

## 6. Qué queda del bloque de tablas/catálogos (documentado, no oculto)

- **Unificación profunda de los tipos de resultado** (Lectura A, §1): deliberada
  y explícitamente no abordada en esta fase, por el riesgo de regresión frente a
  cuatro bloques ya cerrados y probados. Candidata a una fase dedicada de
  consolidación de arquitectura si se decide que hace falta.
- **Abstracción de catálogo con más de un proveedor** (SIMBAD, 2MASS, PS1...):
  no implementada a propósito -- una interfaz "proveedor conectable" con un solo
  proveedor real (Gaia) sería una abstracción prematura sin ningún caso de uso
  concreto que la ejercite (YAGNI). Se construiría cuando exista una necesidad
  real de un segundo catálogo, no antes.
- **Exportación desde otros motores** (fotometría de apertura, PSF, estadísticas
  de imagen, reducción de sesión): `ProcessResult.table` es infraestructura
  reutilizable, pero solo `photometry.zeropoint` y "Ajustar WCS..." la usan hoy
  -- extenderla a los demás procesos es mecánico (armar la `Table` desde su
  resultado real ya calculado) y queda para cuando haya demanda concreta.
