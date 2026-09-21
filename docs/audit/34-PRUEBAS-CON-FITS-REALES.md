# 34 — Pruebas con FITS reales del usuario + soporte XISF

Pedido explícito: "quiero que hagas las pruebas con los fits reales que
te voy a subir... quiero que se puedan añadir .xisf también. Cuando
tengas las pruebas de estos fits, quiero que mejoremos todo."

El usuario subió 5 archivos reales:

- `Light_M_31_300.0s_Bin1_*_0001/0002/0003.fit` -- 3 lights reales de
  M 31, cámara OSC (ZWO ASI533MC Pro, `BAYERPAT=RGGB`), 3008×3008,
  uint16, **con WCS+SIP ya resuelto en la cabecera** (software de
  captura/plate-solve previo), `GAIN`/`OFFSET`/`CCD-TEMP` reales.
- `dbxtract_OIII.fit` / `dbxtract_HA_registered.fit` -- señales de Hα y
  OIII ya extraídas y registradas entre sí por PixInsight
  (`DynamicBackgroundExtraction`-style, según el nombre), float32,
  2560×2648, **3 HDU** (imagen real + `Thumbnail` + `ICCProfile`, ambas
  extensiones típicas de una exportación FITS real de PixInsight), **sin
  WCS, sin OBJECT, sin DATE-OBS, sin FILTER** -- solo historial real de
  `StarAlignment` (PixInsight) en el header.

## 1. Carga real -- sin bugs de carga

`load_image`/`probe_fits_shape`/`detect_point_sources` cargaron y
procesaron los 5 archivos reales sin fallos: multi-HDU (ignora
Thumbnail/ICCProfile correctamente, usa el HDU 0 real), `float32`
big-endian (`>f4`, como escribe FITS de verdad) sin problemas de
compatibilidad con photutils/scipy, uint16 OSC sin problemas. Detección
de fuentes puntuales real: 45/45/51 fuentes en los 3 lights, 77/104 en
OIII/Hα, todas en unos 3s por imagen (confirma que la corrección de
rendimiento de la ronda anterior sigue funcionando con datos reales).

`run_generic_discovery` sobre los 3 lights reales de M 31 completo en
**18.8s** (141 detecciones, 141 candidatos) -- reconoce correctamente
el WCS ya presente en la cabecera (`WCS_PRESENTE`, nunca intenta
resolver la placa de nuevo).

## 2. Bug real de honestidad epistémica en la identificación Gaia

Los 141 candidatos reales de M 31 salían **UNMATCHED** ("sin fuentes
Gaia en el radio de búsqueda") -- una afirmación falsa: este entorno de
desarrollo no tiene salida de red hacia `gea.esac.esa.int` (confirmado:
`Error 403: Host not in allowlist`), así que Gaia nunca llegó a
responder. `UNMATCHED` es un estado que declara "se consultó el
catálogo y no había nada cerca" -- muy distinto de "no se pudo
consultar". Para un campo tan poblado como M 31, decenas de esas 141
"no-coincidencias" son casi con toda seguridad estrellas de primer
plano de la Vía Láctea que SÍ están en Gaia -- declararlas UNMATCHED es
justo el tipo de afirmación no verificada que el encargo prohíbe
explícitamente.

**Corrección real** en `astrophysics_suite/catalogs/gaia.py`:
`query_gaia_neighbors` registra ahora si la consulta real pudo hablar
con Gaia (`last_gaia_availability()`, aislado por hilo vía
`threading.local` -- cada `DiscoveryJob` corre en su propio hilo de
fondo). `identify_detection` reinicia ese estado al valor por defecto
ANTES de cada consulta (evita que una llamada real anterior en el mismo
hilo contamine la siguiente) y lo pasa a `classify_against_gaia_neighbors`,
que ahora distingue: lista vacía + Gaia disponible -> `UNMATCHED` (como
antes, sin cambios); lista vacía + Gaia NO disponible -> `DISCOVERY_REVIEW`
con el motivo real ("Gaia no disponible: Error 403...") -- nunca una
afirmación de no-coincidencia sin haber podido comprobarlo.

Verificado contra los 3 lights reales tras la corrección:
`n_known=0, n_unmatched=0, n_discovery_review=141` -- honesto: ninguno
de los 141 se declara ni conocido ni "confirmado sin coincidencia",
todos quedan para revisión humana con el motivo real explícito.

Un segundo bug (de test, no de producto) encontrado durante la propia
verificación: el estado por hilo de `last_gaia_availability()` se
filtraba entre pruebas distintas ejecutadas en el mismo proceso de
pytest (mismo hilo principal) si una prueba anterior hacía una llamada
real que dejaba `available=False` puesto. Corregido reiniciando el
estado al principio de cada `identify_detection()`, con una prueba de
regresión dedicada
(`test_identify_detection_does_not_leak_unavailable_state_from_a_previous_real_call`).

Suite afectada: `tests/unit/catalogs/test_gaia.py` (+3 pruebas),
`tests/unit/catalogs/test_gaia_network.py` (+1, real contra la
condición de red real de este entorno), `tests/unit/services/
test_discovery_service.py` (1 prueba existente actualizada: el
resultado correcto ante un fallo real de Gaia es `DISCOVERY_REVIEW`,
no `UNMATCHED`), `tests/integration/test_generic_discovery_pipeline.py`
(sin cambios, sigue en verde).

## 3. Soporte de lectura XISF (formato nativo de PixInsight)

Pedido explícito del usuario. La única librería Python mantenida para
XISF (`xisf` en PyPI) es **GPLv3** -- incompatible con la licencia
comercial cerrada de este producto (distribuirla combinada obligaría a
liberar el código fuente completo bajo una licencia compatible).
Consultado con el usuario, que eligió una implementación propia.

**`astrophysics_suite/io/xisf_reader.py`** -- lector escrito desde cero
(el formato en sí es una especificación pública de PixInsight, no la
implementación GPLv3). Verificado de verdad, no solo escrito a partir
de la especificación: se generaron archivos XISF reales con esa
librería GPLv3 como **herramienta de desarrollo desechable** (nunca una
dependencia del proyecto, nunca importada desde `astrophysics_suite`/
`qt_app`, instalada en un venv temporal fuera del repositorio y borrada
al terminar) y se decodificaron con el lector propio, comparando los
píxeles resultantes byte a byte contra los originales -- incluyendo
**los lights y las señales OIII/Hα reales del usuario** convertidos a
XISF real (comprimido zstd+shuffle y lz4+shuffle) y recargados de
extremo a extremo a través de `fits_loader.load_image`.

Cobertura verificada: bloques `attachment` (el caso real al exportar
desde PixInsight) sin comprimir y con zlib/lz4/lz4hc/zstd (con y sin
byte-shuffling); `UInt8/16/32/64`, `Float32/64`; Gray y RGB
(almacenamiento planar); `FITSKeyword` -> header dict. `lz4` y
`zstandard` (las librerías reales de descompresión, BSD, no GPL) se
añaden como dependencias reales del producto
(`requirements-app.txt`/`requirements-test.txt`).

**Bug real encontrado en la propia verificación**: al convertir un
XISF real de un light de M 31 (con WCS+SIP completo en los
`FITSKeyword`) de vuelta a un FITS temporal para reutilizar el
`load_fits` heredado, los valores llegaban como texto Python en vez de
número -- `astropy.io.fits.Header` los escribía como tarjetas de TEXTO,
y `astropy.wcs.WCS` calculaba un WCS **numéricamente incorrecto** (RA/Dec
desviadas decenas de grados) en vez de simplemente no tener WCS -- peor
que la ausencia total. Corregido: `_parse_fits_keyword_value` ahora
distingue el tipo real de cada valor de `FITSKeyword` (entrecomillado ->
texto; `T`/`F` -> lógico; si no, entero o coma flotante), igual que la
sintaxis real de una tarjeta FITS. Verificado de nuevo tras la
corrección: WCS reconstruido con `pixel_scale_arcsec` exacto y
`pixel_to_world` correcto en el campo real de M 31.

**Integración**: `fits_loader.load_image`/`probe_fits_shape` reconocen
un `.xisf` (por extensión o por firma real, nunca solo por el nombre) y
lo decodifican transparentemente -- el resto del pipeline (WCS, cubos,
escala de píxel) no distingue el formato de origen. `fits_header_reader.
read_fits_header` también reconoce XISF (para la clasificación de
sesiones de calibración). Los diálogos de "Abrir FITS/XISF", "Nueva
observación", "Seleccionar LIGHTS"/"Seleccionar fotogramas" (construir
fotograma maestro) y el escaneo de carpeta de `ReduceSessionDialog`
ahora incluyen `*.xisf` en su filtro -- probado que `build_observation`
mezcla FITS y XISF en la misma observación sin problemas.

**Lo que NO cubre** (explícito, nunca silencioso): bloques
inline/embedded o referencias a archivo externo, múltiples imágenes por
archivo (solo la primera salvo índice explícito), verificación de
checksum. Cualquiera de estos casos lanza `XISFError` con el motivo
real. Tampoco hay escritura de XISF (solo lectura) -- el producto sigue
guardando en FITS, como siempre.

Tests: `tests/unit/io/test_xisf_reader.py` (16 pruebas, autocontenidas,
sin depender de ninguna librería XISF de terceros), `tests/unit/io/
test_fits_loader_xisf.py` (5 pruebas de integración, incluida la del
bug de WCS/SIP encontrado).

## 4. Hallazgo real pendiente: sin debayering para cámaras OSC

Los 3 lights reales son de una cámara OSC (ZWO ASI533MC Pro,
`BAYERPAT=RGGB`) -- ni el motor heredado ni el nuevo tienen ninguna
etapa de debayering/demosaico en ningún punto del pipeline (confirmado:
`grep` de "debayer"/"Bayer" en el código solo encuentra el *aviso* de
`legacy...select_science_row` de que el FITS "parece CFA/Bayer", nunca
un algoritmo real que lo corrija). Esto significa que la detección de
fuentes y la fotometría corren hoy directamente sobre el mosaico Bayer
crudo -- cada píxel muestrea un solo canal de color, lo que sesga tanto
el fondo estimado como el flujo medido de cada fuente. No es un bug de
esta ronda (es una laguna funcional preexistente, nunca cubierta), mencionado
aquí porque se hizo evidente probando con datos OSC reales por primera
vez. Pendiente de decidir alcance con el usuario antes de implementarlo
(qué modo de debayering usar de forma científica -- SuperPixel o
Bilinear -- y si debe ser un paso explícito como el resto de procesos
de `imtools`/`reduction`, nunca automático dentro de Discovery).

## 5. Verificación

Suite completa sin regresiones: `aps-test` 443 passed / 35 skipped / 1
xfailed; `aps-gui` 538 passed / 20 skipped / 1 xfailed.
