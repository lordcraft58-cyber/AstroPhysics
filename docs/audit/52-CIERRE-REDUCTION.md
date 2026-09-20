# 52 — Cierre de Reduction

Segundo motor de la lista del usuario, tras IO/FITS (informe 51). La
auditoría encontró **tres huecos reales**, y la validación con FITS
reales destapó un **cuarto** que ninguna prueba sintética podía ver.

## 1. La reducción no declaraba nada — pero decía que sí

**El hueco**: `CalibrationSteps` (en `reduction/calibration.py`) llevaba
desde su primera versión una promesa explícita en el docstring:

> *"para que la procedencia … pueda declarar exactamente qué calibración
> recibió cada imagen, nunca de forma implícita"*

Esa procedencia **nunca se construía**. `LightFrameReduction` llevaba los
`CalibrationSteps` en memoria, pero nadie los convertía en `Provenance`
ni en nada persistente. El contrato existía escrito; no existía en
código.

**Lo hecho**: `astrophysics_suite/reduction/provenance.py`, con tres
piezas:

- `ReductionRecord` — reúne en un solo sitio lo que estaba repartido
  entre `CalibrationSteps` y campos sueltos de `LightFrameReduction`
  (overscan, recorte, iluminación, franjas, cielo, ganancia, ruido de
  lectura). Su `.describe()` lista **solo los pasos realmente
  aplicados**, en el orden físico en que se aplicaron; si no se aplicó
  ninguno devuelve una tupla vacía, que también es una respuesta.
- `build_reduction_provenance()` — `Provenance` real (Fase 4) con dos
  avisos honestos: sin bias ni dark, el offset del sensor sigue ahí; sin
  flat, la respuesta no uniforme sigue ahí. No son adornos: viajan con el
  archivo.
- `reduction_header_cards()` — tarjetas FITS `APS*` más líneas `HISTORY`
  legibles por cualquier visor.

`reduce_light_frames` ahora rellena `record` y `provenance` en cada
`LightFrameReduction`.

## 2. El archivo calibrado era indistinguible de un crudo

**El hueco**: `reduce_session_dialog.py` escribía el producto con
`header=headers[index]` — **la cabecera cruda literal**. Un FITS
reducido salía del programa sin una sola marca de que hubiera pasado por
él. Reabierto una semana después, o abierto por otra persona, no había
forma de saber si estaba calibrado, ni con qué.

**Lo hecho**: la cabecera de salida es ahora la original **más** el
registro real:

```
APSRED  = T                        / pasó por el pipeline
APSBIAS = T / APSDARK = F / APSFLAT = F
APSSKY  = T / APSSKYDG = 2
APSGAIN, APSRDNS, APSDKSCL, APSFRSCL, APSOSCAN, APSILLUM, APSFRING, APSBPM
APSENG  = 'reduction.session_pipeline 1.0'
APSDATE = '2026-09-20T00:45:34.873259+00:00'
HISTORY AstroPhysics Suite: reduccion aplicada
HISTORY   - fondo de cielo restado (superficie de grado 2)
HISTORY   ! sin bias ni dark: el nivel de offset del sensor no se ha eliminado
HISTORY   ! sin flat: la respuesta no uniforme del sensor no se ha corregido
```

Un paso que no se aplicó aparece con su `False` real, no ausente. Los
avisos de la procedencia se escriben en el propio archivo: el producto
lleva encima lo que le falta.

**Detalle ASCII**: el estándar FITS solo admite ASCII imprimible en las
tarjetas, y todo este producto escribe en castellano. Había un
`except ValueError: continue` que descartaba **en silencio** cualquier
valor con tilde. Ahora `_ascii_safe()` translitera (ó→o, ñ→n): en
memoria se conserva el castellano real, en el archivo se escribe
`reduccion aplicada`. Se translitera, no se pierde.

## 3. La incertidumbre propagada se tiraba al guardar

**El hueco**: el motor propaga incertidumbre por píxel con cuidado a
través de toda la cadena (`UncertainImage`), y el diálogo guardaba solo
`frame.calibrated.data`. La única medida honesta del error de cada píxel
moría en memoria.

**Lo hecho**: `save_fits_image(..., uncertainty=...)` escribe una
extensión `UNCERT` real, con el mismo nombre de extensión que ya usaban
los fotogramas maestros (`reduction/master_frames.py`) — una convención
en todo el producto, no una por motor. Se valida la forma; una imagen
guardada sin incertidumbre **no** genera una extensión vacía fingiendo
que hay error medido. El apilado combinado también guarda la suya.

## 4. `BZERO`/`BSCALE` heredados corrompían todos los píxeles

Este no salió de la auditoría: salió de ejecutar la reducción sobre los
**tres LIGHTS reales de M 31** del usuario.

**El hueco**: copiar la cabecera cruda arrastraba también `BZERO=32768` y
`BSCALE=1`. Esas palabras clave no describen la imagen — describen cómo
estaban representados los **enteros del archivo de origen**. La cámara
real del usuario (ZWO ASI533MC Pro) escribe `BITPIX=16` con
`BZERO=32768`. Al releer el archivo calibrado, astropy aplicaba
`dato * BSCALE + BZERO` sobre datos que ya eran `float32`, y **cada píxel
aparecía desplazado +32768 ADU**.

Se detectó porque la mediana tras restar el cielo salió `32768.77` en vez
de `~0`. Nada fallaba: el archivo se abría bien, se veía bien, y estaba
mal. Ninguna prueba sintética lo habría visto, porque todas escribían
LIGHTS en `float32`, que no llevan `BZERO`.

**Lo hecho**: `_SCALING_KEYS = ("BZERO", "BSCALE", "BLANK")` se descartan
siempre al escribir. Tras el arreglo la mediana real es `0.77`.

## Validación con datos reales

Tres LIGHTS de M 31, 300 s, Bin1, ZWO ASI533MC Pro, 3008×3008:

| Comprobación | Resultado |
|---|---|
| Pasos declarados | `fondo de cielo restado (superficie de grado 2)` |
| Avisos de procedencia | falta bias/dark **y** falta flat — correcto, no hay calibración en este conjunto |
| Tarjetas `APS*` releídas del disco | todas presentes y con el valor real |
| Metadatos originales conservados | `OBJECT='M 31'`, `INSTRUME='ZWO ASI533MC Pro'`, `FOCALLEN=749`, `XPIXSZ=3.76` |
| Extensión `UNCERT` | 3008×3008, mediana 55.5 ADU, todo finito |
| Mediana de los datos tras restar cielo | `0.77` (era `32768.77` antes del punto 4) |
| Apilado de los 3 | mediana, 6 056 461 píxeles con los 3 LIGHTS, 2 991 603 con rechazo de outliers |

No hay bias/dark/flat reales en este conjunto, así que la validación
ejecuta los pasos que **sí** se pueden aplicar a crudos reales (resta de
fondo de cielo) y comprueba que la procedencia dice la verdad incómoda:
que faltaron los tres maestros.

## Checklist del motor

| Fase | Estado |
|---|---|
| IMPLEMENTACIÓN | `reduction/provenance.py` + `fits_writer` extendido |
| CONTRATO | `ReductionRecord`, `Provenance` real, tarjetas `APS*` |
| GUI | `ReduceSessionDialog` escribe cabecera + `UNCERT` en cada producto y en el combinado |
| SALIDA | FITS con procedencia legible por cualquier visor |
| PROVENANCE | `reduction.session_pipeline 1.0`, con avisos |
| UNIT TEST | `tests/unit/reduction/test_reduction_provenance.py` (10) |
| INTEGRATION TEST | `tests/gui_smoke/test_qt_app_reduce_session_smoke.py` (+1, extremo a extremo por el diálogo con LIGHTS uint16) |
| FITS REAL | 3 LIGHTS de M 31 — ver tabla arriba |
| CERRADO | sí |

Suite completa tras el cierre: **746 pasadas, 24 saltadas, 1 xfailed**
(`aps-test`) y **143 pasadas** de humo GUI (`aps-gui`). `ruff` limpio.

## Lo que sigue abierto en este motor

- **No existe escritor XISF.** Se lee XISF en todo el programa (informe
  51), pero los productos calibrados salen siempre en FITS. Es un motor
  aparte, no un cable suelto.
- **El hash de las entradas no se rellena.**
  `build_reduction_provenance(input_hashes=...)` acepta los sha256
  reales del LIGHT y de los maestros usados, y el llamador todavía no se
  los pasa. Se deja el parámetro porque el dato existe
  (`io.fits_reader.sha256_file`) y el contrato lo pide; rellenarlo exige
  que la biblioteca de maestros guarde el hash de sus entradas, que hoy
  no hace.
