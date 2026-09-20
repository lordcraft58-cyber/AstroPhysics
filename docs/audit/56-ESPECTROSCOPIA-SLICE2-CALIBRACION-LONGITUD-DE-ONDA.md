# 56 — Espectroscopía, slice 2: calibración de longitud de onda real

Continuación del informe 55 (slice 1: modelo de datos + fin de las
"caídas a cero" en la extracción). Esta slice cierra el bloque central
de calibración de longitud de onda del encargo original: §8-13
(polinomio configurable, lámparas, modo simulación explícito,
reutilización de solución, calibración por estrella de referencia),
§16 (WCS espectral real), §20-21 (catálogo de líneas + identificación
sugerida con confirmación), §24 (aire/vacío), y §33 (generadores
sintéticos de lámpara para pruebas).

## Lo hecho

### 1. `calibration_provenance.py` -- nunca una calibración inventada presentada como real (§11/§41)

`CalibrationSource` (`LAMP_REAL`/`REUSED_INSTRUMENTAL`/`REFERENCE_STAR`/
`SYNTHETIC`) + `WavelengthCalibrationRecord` + `build_wavelength_provenance()`,
mismo patrón que ya cerró `astrometry/provenance.py` y
`reduction/provenance.py`. Cada fuente avisa de lo que de verdad no
sabe: `SYNTHETIC` siempre avisa "CALIBRACIÓN SIMULADA"; `REFERENCE_STAR`
siempre avisa de que la posición de una línea estelar depende también
de velocidad radial y ensanchamiento, no solo de la óptica.

**Medido, no supuesto** (`MIN_LINES_PER_DEGREE`): con exactamente
`grado + 1` líneas (el mínimo que admite `fit_wavelength_solution`), el
ajuste interpola esos puntos exactamente y el RMS declarado no mide
nada fuera de ellos. Verificado por simulación (grado 3, 0.15 px de
error real de centroide, dispersión ~1.4 Å/px, 300 ajustes):

| n líneas | RMS declarado | error real en el centro | ratio |
|---|---|---|---|
| 4 (=grado+1) | 0.00000 Å | 1.7208 Å | ~10⁹× |
| 6 | 0.52547 Å | 0.7423 Å | 1.41× |
| 8 | 0.71013 Å | 0.5759 Å | 0.81× |
| 20 | 1.10746 Å | 0.3048 Å | 0.28× |

De ahí el aviso: con `n <= grado*2` líneas, el RMS declarado no es
representativo.

### 2. `line_catalog.py` -- catálogos públicos reales, nunca inventados (§9/§20)

Líneas de lámpara Ne/Ar/He (+ `HeNeAr` como unión) y líneas de
objeto (Balmer, Ca II H&K, Na D1/D2, nebulares `[O III]`/`[N II]`/
`[S II]`) -- todos datos físicos públicos (NIST Atomic Spectra
Database, y exactamente los valores del propio encargo para las
líneas de objeto), nunca código ni interfaz de ISIS ni de ningún otro
programa. `match_lines_to_catalog()` sugiere correspondencias pico↔catálogo
bajo una dispersión aproximada dada por el llamador -- nunca aplica la
solución por sí sola (§10: *"Debe existir una etapa de confirmación. No
aceptar automáticamente una identificación dudosa"*).

### 3. `air_vacuum.py` -- conversión estándar publicada (§24)

Morton (2000, ApJS 130, 403). Verificado contra los valores de
referencia ampliamente citados: Hα 6562.8 Å aire → 6564.61 Å vacío;
Na D2 5889.95 Å aire → 5891.58 Å vacío. Round-trip aire→vacío→aire
exacto a 2×10⁻⁶ Å.

### 4. `spectrum1d_io.py` -- WCS espectral real, nunca una mentira lineal (§16/§38)

Punto central del encargo, verbatim: *"No escribir una relación lineal
falsa si la calibración obtenida es polinómica."* Dos caminos según el
grado real de la solución:

- **Grado ≤ 1**: WCS lineal estándar (`CTYPE1='WAVE'`, `CRVAL1`/`CDELT1`) --
  exacto, porque la solución SÍ es una recta.
- **Grado ≥ 2**: convención `-TAB` (Greisen, Calabretta, Valdes & Allen
  2006, A&A 446, 747, sección 4) -- una tabla de búsqueda EXACTA en una
  extensión `BinTableHDU` llamada `WCS-TAB`, no una aproximación. Es un
  estándar FITS publicado, no una convención propia de este proyecto.

Ambos casos llevan además `CALTYPE` (`REAL`/`SYNTHETIC`), los
coeficientes exactos en `APSWAVE*`, y la procedencia completa en
`HISTORY`. Round-trip verificado exacto (error `0.0`) para grado 1 y
grado 3 sobre 1000 píxeles.

**Hallazgo real, validando contra el propio Vega del usuario**: el
header crudo de un FITS 2D trae `NAXIS2` (y `NAXIS=2`); copiarlo al
escribir un producto 1D hacía que `astropy` rechazara el archivo
entero (`VerifyError: NAXISj keyword out of range`) porque el filtro
de claves estructurales solo excluía `NAXIS`/`NAXIS1`, no `NAXIS2`.
Corregido (se descarta cualquier `NAXIS*`), con test de regresión.

### 5. `synthetic_lamp.py` -- generadores para pruebas, nunca para producción (§33)

`generate_synthetic_lamp_spectrum`/`generate_synthetic_lamp_frame2d`:
imagen 2D o espectro 1D con líneas REALES del catálogo en su posición
de píxel exacta, más curvatura de traza, ruido Poisson+lectura,
rayos cósmicos y píxeles muertos en posiciones conocidas (para poder
comprobar que se detectan donde de verdad están, no en otro sitio) --
usa el mismo catálogo público que consume el resto del motor, nunca
una lista duplicada que pudiera divergir en silencio.

### 6. GUI -- sugerencia con confirmación + guardado real

`WavelengthFitDialog` gana un selector de lámpara (Ne/Ar/He/HeNeAr) y
un botón "Sugerir automáticamente" que rellena la columna de longitud
de onda con la coincidencia de catálogo más cercana + su confianza --
**sugiere, nunca aplica**: sigue haciendo falta revisar cada celda y
pulsar "Ajustar solución". El diálogo construye ahora un
`WavelengthCalibrationRecord` real (`LAMP_REAL`, con la lámpara
declarada) en vez de solo la solución matemática.

Nueva acción "Guardar espectro calibrado (FITS)..." en el menú
Espectroscopía: escribe el espectro extraído con su WCS real y
`CALTYPE` verdadero -- antes, una calibración ajustada en el taller
vivía solo en memoria y se perdía al cerrar el programa (mismo hueco ya
cerrado para WCS espacial en el informe 53).

## Validación

**Cadena completa, de punta a punta** (§43, verbatim: *"comprobar que el
RMS recuperado es correcto"*): lámpara sintética Ne/Ar/HeNeAr (con
curvatura de traza, rayos cósmicos y píxeles muertos inyectados) →
`trace_spectrum` → `extract_sum` → `find_arc_lines` →
`match_lines_to_catalog` → `fit_wavelength_solution` → comparación
contra la verdad conocida del generador. Las tres lámparas recuperan la
solución real dentro de 1.0 Å en todo el rango, con RMS declarado del
orden correcto (no artificialmente bajo). 4 pruebas de integración,
todas verdes.

**Real, contra `veg_stacked.fits` del usuario**: extracción real (0
columnas inválidas de 1391, herencia directa de la slice 1) +
calibración de referencia etiquetada explícitamente `SYNTHETIC` (no hay
lámpara real entre los archivos adjuntados) + escritura FITS + relectura
-- `CALTYPE=SYNTHETIC` sobrevive, `OBJECT=Vega` se conserva, el WCS
releído reproduce exactamente la solución en memoria. Aquí es donde
apareció el hallazgo de `NAXIS2` de la sección 4.

Suite completa tras el cierre: **831 pasadas, 24 saltadas, 1 xfailed**
(`aps-test`, +45 sobre la slice 1) y **152 pasadas** de humo GUI
(`aps-gui`, +3). `ruff` limpio.

## Checklist de la slice

| Fase | Estado |
|---|---|
| IMPLEMENTACIÓN | `calibration_provenance.py`, `line_catalog.py`, `air_vacuum.py`, `spectrum1d_io.py`, `synthetic_lamp.py` |
| CONTRATO | `CalibrationSource`, `WavelengthCalibrationRecord`, `SpectralLine`, `LineMatch` |
| GUI | sugerencia con confirmación + "Guardar espectro calibrado..." |
| SALIDA | FITS 1D real, WCS lineal o `-TAB` exacta según el grado, `CALTYPE` |
| PROVENANCE | avisos reales (líneas insuficientes, simulación, estrella de referencia) |
| UNIT TEST | `test_calibration_provenance.py` (6), `test_line_catalog.py` (10), `test_air_vacuum.py` (6), `test_spectrum1d_io.py` (10), `test_synthetic_lamp.py` (9) |
| INTEGRATION TEST | `test_wavelength_calibration_pipeline.py` (4, RMS recuperado verificado) |
| GUI TEST | `test_qt_app_wavelength_smoke.py` (+3: sugerencia, guardado, guardado sin calibración) |
| FITS REAL | `veg_stacked.fits` -- extracción real + hallazgo de NAXIS2 |
| CERRADO (esta slice) | sí |

## Pendiente -- lo que sigue del encargo original

- **§12 predefinida/reutilización de solución instrumental** y
  **§14 calibración lateral/simultánea** (lámpara en región lateral de
  la misma imagen que el objeto): `CalibrationSource.REUSED_INSTRUMENTAL`
  ya existe como valor del enum, pero no hay todavía persistencia de
  perfiles de instrumento ni detección de región lateral.
- **§13 calibración por estrella de referencia**: `CalibrationSource.
  REFERENCE_STAR` existe y avisa correctamente, pero no hay todavía un
  motor que identifique líneas de Balmer en una estrella A/B real y
  derive una solución provisional de ahí.
- **§17-18 respuesta instrumental y calibración de flujo**: YA EXISTÍA
  con más sustancia de la que el informe 55 reportaba (`fluxcal.py`
  tiene Kasten-Young real, ajuste de función de sensibilidad real,
  corrección de extinción real) -- el hueco real es la falta de una
  biblioteca de estrellas estándar (CALSPEC, §49) para poder usarlo en
  la práctica.
- **§6 rayos cósmicos integrados**: `imtools/cosmic_rays.py` (L.A.Cosmic
  real) sigue sin cablearse explícitamente en el flujo de
  espectroscopía como paso de preprocesado.
- **§19 normalización de continuo dedicada**: `continuum.py` ya existe
  y funciona; falta integrarlo con el nuevo `WavelengthCalibrationRecord`
  para que un espectro normalizado declare de qué calibración viene.
- **§21-22 identificación automática de líneas del objeto tras
  calibrar** y **§62 ajuste Gaussiano/Voigt/multi-componente**:
  `lines.py::measure_line` ya mide una línea DADA su posición esperada;
  falta la etapa de detección+identificación automática después de
  calibrar, y los ajustes de perfil más allá del centroide/FWHM actual.
- **§23/§58-61 velocidad radial** (Doppler simple, cross-correlation,
  multi-línea, correcciones baricéntrica/heliocéntrica): no existe
  todavía.
- El resto de §27 (objetos extendidos), §44-45 (drift/calibración
  lateral), §46-47 (telúricas/extinción -- extinción atmosférica YA
  existe en `fluxcal.py`, telúricas no), §50-54 (magnitudes, échelle),
  §63-78 (diagnóstico de calidad extendido, informes, reproducibilidad
  vía configuración) -- enumerados en el informe 55, sin cambios.

Orden de continuación natural: rayos cósmicos integrados en el flujo →
calibración lateral/predefinida → biblioteca de estándares (CALSPEC) →
identificación automática de líneas de objeto → velocidad radial.
