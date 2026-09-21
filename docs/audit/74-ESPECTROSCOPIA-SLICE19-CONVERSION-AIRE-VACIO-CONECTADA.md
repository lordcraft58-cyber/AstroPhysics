# Informe 74 — Espectroscopía slice 19: conexión real de aire↔vacío (§24)

Continuación de los informes 55-73. Tercer slice construido directamente
a partir de la auditoría del informe 71: cierra §24 -- `air_vacuum.py`
(Morton 2000, con test dedicado desde antes de este slice) existía como
motor probado pero sin un solo consumidor real fuera de su propio
archivo y su propio test.

## 1. El hueco real

Todo el catálogo de líneas del proyecto (`line_catalog.SpectralLine.
wavelength_air_angstrom`) se da en AIRE -- misma convención que NIST ASD
por encima de 2000 Å, consistente en todo el proyecto (líneas de
lámpara, líneas de objeto). Ningún consumidor ofrecía nunca el
equivalente en VACÍO, aunque muchas fuentes externas (bases de datos
UV/extragalácticas, comparaciones con literatura moderna) publican
longitudes de onda en vacío -- un usuario que quisiera cotejar una línea
identificada contra una de esas fuentes tenía que convertir a mano.

## 2. `SpectralLine.wavelength_vacuum_angstrom` (nuevo, propiedad real)

```python
@property
def wavelength_vacuum_angstrom(self) -> float:
    return float(air_to_vacuum(self.wavelength_air_angstrom))
```

Conversión real (nunca una aproximación distinta) sobre el dato de
catálogo ya existente -- disponible automáticamente en CUALQUIER
`SpectralLine` del proyecto (líneas de lámpara Ne/Ar/He, Balmer, Ca II,
Na D, líneas nebulares), sin tocar ningún dato ni comportamiento
existente.

## 3. Tres consumidores reales conectados

- **`spectroscopy.identify_lines`** (`registry.py`, `_run_identify_object_lines`):
  la tabla de resultados ahora lleva `catalog_wavelength_air` Y
  `catalog_wavelength_vacuum` (antes solo `catalog_wavelength`, renombrada
  sin cambiar su significado) para cada línea identificada.
- **`RadialVelocityDialog`** (`qt_app/spectroscopy/radial_velocity_dialog.py`):
  la tabla de medición y la tabla exportable (`result_table()`) llevan
  una columna nueva "λ reposo vacío (Å)" junto a la de aire ya existente,
  para cada línea usada en la velocidad radial combinada.
- El catálogo (`line_catalog.py`) queda disponible para cualquier
  consumidor futuro (p. ej. `wavelength_fit_dialog.py`, fuera del alcance
  de este slice) sin ningún trabajo adicional.

Cambio deliberadamente aditivo en ambos sitios: ninguna columna existente
se elimina ni cambia de significado (salvo el renombrado explícito
`catalog_wavelength` -> `catalog_wavelength_air`, sin ningún consumidor
que dependiera del nombre anterior), ninguna física de identificación ni
de velocidad radial se toca.

## 4. Validación

| Verificación | Resultado |
|---|---|
| `ruff check` (código nuevo/modificado) | limpio |
| `tests/unit/spectroscopy/test_line_catalog.py` (+2 tests) | la propiedad coincide exactamente con `air_to_vacuum` real; valor de H-alpha coincide con la referencia bibliográfica ya verificada en `test_air_vacuum.py`; vacío > aire para todo el catálogo real (lámpara + objeto) |
| `tests/unit/qt_app/test_registry.py` (+1 test) | `spectroscopy.identify_lines` reporta ambas columnas (aire/vacío) reales y coherentes para una línea de Balmer real identificada |
| `tests/gui_smoke/test_qt_app_radial_velocity_smoke.py` (extendido, sin tests nuevos) | `RadialVelocityDialog` muestra la columna de vacío real en pantalla y en la tabla exportable |
| Suite unitaria completa (`pytest tests/ --ignore=tests/gui_smoke`) | **997 passed** (antes del slice: 994 passed) |
| Suite de humo GUI completa (`xvfb-run pytest tests/gui_smoke/`, venv `aps-gui`) | **182 passed** (sin cambio -- solo aserciones nuevas en un test existente) |
| Motor de extremo a extremo sobre `Vega_1sec_1x1__frame6.fit` real | reproduce EXACTAMENTE el resultado real ya documentado en el informe 60 (slice 6): 31 desviaciones reales detectadas, 0 coincidencias de catálogo dentro de 3 Å con el eje aproximado sin lámpara real -- resultado honesto sin cambios; la conversión aire->vacío real sobre el catálogo real de objeto (Balmer/Ca II/Na D) da valores físicamente coherentes (vacío siempre > aire, ~1-1.8 Å de separación en el óptico), con H-alpha y Na D2 coincidiendo con las referencias bibliográficas ya usadas |

## 5. Qué queda fuera de este slice

`wavelength_fit_dialog.py` (tabla interactiva/editable de emparejamiento
de líneas de arco) NO se ha tocado -- añadir la columna de vacío ahí
significa modificar un flujo de edición activo ya probado, un riesgo
desproporcionado para el alcance de este slice; el motor
(`SpectralLine.wavelength_vacuum_angstrom`) ya está disponible para
conectarlo ahí en un slice futuro sin trabajo adicional. Del informe 71,
siguen pendientes: edición manual interactiva del overlay 2D
(§2/§3/§5/§35), informe de QC unificado (§31), calibración por estrella
de referencia (§13), botón "AUTOPROCESS SPECTRUM" (§34), y el resto de
huecos reales listados en ese informe.
