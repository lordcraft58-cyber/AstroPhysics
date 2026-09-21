# 35 — Demosaico de cámaras OSC + caché local de catálogos

Pedido explícito: "corrige la debayerizacion y dime porque no se puede
usar gaia o simbad, y sino que se descarge en el propio ordenador en una
ruta conocida y coja los datos de ahi".

## 0. Por qué "no se puede usar Gaia/SIMBAD" (respuesta corta: sí se puede)

No es una limitación del programa. El entorno de desarrollo donde se
ejecuta este trabajo es un contenedor en la nube con una lista blanca de
red muy restringida: `gea.esac.esa.int` (Gaia) y el host de SIMBAD no
están en ella, y cualquier consulta devuelve `Error 403: Host not in
allowlist`. En un Windows normal con internet, ambos funcionan. Lo que
sí era un problema real del programa -- y ya está corregido, ver
docs/audit/34 -- es que una consulta fallida se declaraba como
"comprobado, sin coincidencia" en vez de "no se pudo comprobar".

Dicho eso, la caché local que pidió el usuario resuelve un problema real
INDEPENDIENTE de la red, ver sección 2.

## 1. Demosaico (debayering) de cámaras OSC

### El problema real, medido

Los lights del usuario son de una ZWO ASI533MC Pro: un sensor de color
(OSC) que entrega un **mosaico de Bayer** (`BAYERPAT=RGGB`), donde cada
píxel mide UN solo color. El pipeline no tenía ninguna etapa de
demosaico, así que detección y fotometría corrían directamente sobre ese
mosaico. Medido sobre un light real de M 31:

| | Detección sobre el mosaico crudo | Tras demosaicar (SuperPixel) |
|---|---|---|
| Fuentes detectadas | **45** | **416** |
| Tiempo | 3,92 s | 1,40 s |

Es decir, el mosaico estaba ocultando en torno al **90% de las estrellas
reales del campo**. Se ve directamente en el perfil de una estrella
brillante: sobre el mosaico crudo la fila central alterna
`5544, 6068, 11324, 15632, 21652, 25760, 13904, ...` -- ese diente de
sierra par/impar es el propio patrón de Bayer, no la PSF; el detector
intenta ajustar una gaussiana a algo que no lo es. Tras demosaicar el
perfil es suave, como debe ser.

Sobre el Discovery completo de los 3 lights reales: **141 candidatos
antes, 1320 después**.

### Qué se implementó

`astrophysics_suite/imtools/debayer.py`, con tres métodos reales:

- **SuperPixel**: cada bloque 2x2 -> un píxel RGB (R y B del fotosito
  real, G la media de los dos verdes reales). Media resolución, pero
  **ningún valor interpolado**: todo son medidas del sensor.
- **Luminancia** (SuperPixel + suma ponderada 1/4·R + 1/2·G + 1/4·B): un
  plano monocromo sin el tablero del mosaico y sin interpolar. Los pesos
  son la proporción real de fotositos de cada color, así que la suma
  conserva la estadística de Poisson del sensor. **Es el camino que usa
  la detección/fotometría.**
- **Bilineal**: resolución completa interpolando los canales que faltan.
  Se ve mejor, pero la mayoría de sus valores son inventados por
  interpolación: vale para mirar, no para medir. El proceso de la GUI lo
  advierte explícitamente en su resumen.

### Nunca se adivina el patrón

Sin `BAYERPAT` en la cabecera no se demosaica nada: asumir "RGGB porque
es lo más común" produciría colores y fotometría incorrectos en
silencio con cualquier otra cámara. Además, `describe_bayer_agreement`
**comprueba el patrón declarado contra los propios píxeles**: los dos
fotositos verdes de un CFA real llevan el mismo filtro, así que sus
planos comparten nivel, dispersión y cola alta. Si cabecera y datos no
concuerdan (caso típico: un FITS guardado con las filas invertidas
respecto a la orientación en que se escribió `BAYERPAT`), se avisa en
vez de demosaicar mal sin decir nada.

**Bug real encontrado en esa heurística durante la propia verificación**:
la primera versión comparaba solo las MEDIANAS de los planos. Con los
lights reales (enteros de 16 bits, dominados por el nivel de bias) las
medianas eran 2992 / 3168 / 3168 / 2992 -- **dos empates exactos**, así
que declaraba "esto no parece un mosaico" para una imagen OSC
perfectamente normal. Los datos SÍ distinguían los planos, pero por
dispersión (MAD 122,69 ≈ 122,70 para los verdes, frente a 107,49 vs
79,30 para R/B). Corregido usando una firma de tres estadísticos
robustos (mediana + MAD + percentil 99). Con eso, el patrón real RGGB
del usuario se confirma con una distancia de 0,0000 frente a 0,0190.

### El WCS también se reescala (y astropy no sirve para esto)

El binificado 2x2 **dobla la escala de píxel**, así que el WCS hay que
adaptarlo o las coordenadas celestes salen mal. El camino obvio,
`wcs[::2, ::2]` de astropy, **no funciona** con matriz CD (lo normal en
un FITS ya resuelto por plate solving): avisa "cdelt will be ignored
since cd is present" y deja la escala SIN cambiar -- con el light real
de M 31 eso da un error de **857 segundos de arco** (14 minutos de
arco). Por eso `astrometry/wcs_fit.rescale_wcs_for_binning` hace la
transformación explícita (CD × factor, CRPIX recolocado, coeficientes
SIP escalados por `factor**(p+q-1)`). Verificado contra el WCS+SIP real
del light: **error máximo 0,00000 segundos de arco** en todo el campo.

### Integración

- Discovery demosaica automáticamente cualquier imagen con `BAYERPAT`
  ANTES de resolver la placa y de detectar (resolver la placa sobre la
  luminancia da muchas más estrellas para emparejar), ajusta la FWHM de
  detección a la mitad (el binificado la reduce) y reporta lo que hizo
  en `DiscoveryRunSummary.cfa_status`, con el mismo patrón que
  `wcs_status`: estado (`MOSAICO_DEMOSAICADO`, `SIN_MOSAICO_DECLARADO`,
  `DEMOSAICO_DESACTIVADO`, `DEMOSAICO_FALLIDO`) y motivo legible. Se
  puede desactivar con `auto_debayer=False`.
- Proceso explícito en el taller: "Demosaico de mosaico de color
  (OSC/Bayer)", con método y patrón elegibles. Para ello se añadió un
  tipo de parámetro `choice` (desplegable) a `ParameterSpec`.

## 2. Caché local de catálogos en disco

### El problema real, medido

Discovery consulta el catálogo **una vez por detección**. Tras corregir
el demosaico, los 3 lights reales de M 31 dan 1320 detecciones: eso son
**1320 consultas de red a Gaia en un solo análisis**. Aunque haya
internet, es lentísimo y abusa de un servicio público gratuito. Y sin
internet, ninguna detección se puede comprobar.

### Qué se implementó

`astrophysics_suite/catalogs/local_cache.py`: descarga cónica del campo
**una sola vez** y consulta local después.

- **Ruta conocida**: `~/.astrophysics_suite/catalogs/gaia.sqlite3` -- en
  Windows, `C:\Users\<usuario>\.astrophysics_suite\catalogs\`. Es la
  misma carpeta que ya usan las preferencias y los perfiles de
  instrumento. SQLite es de la biblioteca estándar: sin dependencias
  nuevas, con índice real.
- `query_gaia_neighbors` **consulta la caché primero**. Si el campo está
  descargado, sirve desde disco y no toca la red. Si no lo está, sigue
  por red como siempre.
- Diálogo en la GUI: Astrometría -> "Descargar catálogo del campo
  (trabajar sin red)...". Pre-rellena el centro y el radio desde el WCS
  real de la imagen activa (o desde el nombre del objeto vía SIMBAD),
  muestra el estado real de la caché y permite vaciarla.

### "Vacío" y "no descargado" no son lo mismo

`query_neighbors` devuelve `(filas, cubierto)`. Sin ese segundo dato, una
lista vacía sería exactamente igual de ambigua que el bug corregido en
docs/audit/34: no es lo mismo "descargué este campo y ahí no hay ninguna
estrella catalogada" (resultado científico) que "nunca descargué este
campo" (pregunta sin responder). Por el mismo motivo, una descarga que
falla **no guarda una región vacía** -- eso haría que la caché mintiera
diciendo que ya cubre esa zona. Y un archivo de caché corrupto degrada a
"no cubierto" y deja que el análisis siga por red, nunca lo rompe.

### Verificación real de extremo a extremo

Con el campo de M 31 en la caché y la red **bloqueada a propósito**:

```
detecciones: 416
KNOWN (identificadas contra el catálogo local): 40
UNMATCHED (consultado de verdad, sin coincidencia): 376
DISCOVERY_REVIEW (no se pudo comprobar): 0
consultas de RED realizadas: 0
tiempo: 2,7 s
```

Es decir: identificación completa, sin internet, sin ninguna consulta al
servicio, en menos de 3 segundos.

## 3. Tests

- `tests/unit/imtools/test_debayer.py` (19): los 4 patrones, recuperación
  exacta de cada canal, media real de los dos verdes, valores medidos
  intactos en bilineal, bloques 2x2 incompletos descartados (nunca
  rellenados), desplazamientos `XBAYROFF`/`YBAYROFF`, inferencia del
  patrón desde los datos (incluida la regresión del empate de medianas) y
  aviso cuando cabecera y datos no concuerdan.
- `tests/unit/astrometry/test_wcs_fit.py` (+2): el reescalado coincide
  exactamente con el centro real del superpíxel; no muta el WCS original.
- `tests/integration/test_generic_discovery_pipeline.py` (+3): Discovery
  demosaica un mosaico real y lo declara; detecta al menos tantas fuentes
  como sin demosaicar; una imagen monocroma no se toca.
- `tests/unit/catalogs/test_local_cache.py` (11): persistencia real en
  disco, cobertura frente a vacío, borde de región, radio y límite de
  magnitud, descarga fallida que no deja región fantasma, servicio desde
  caché sin tocar la red, vuelta a la red fuera del campo descargado, y
  caché corrupta que no rompe el análisis.
- `tests/gui_smoke/test_qt_app_debayer_and_cache_smoke.py` (9): el
  proceso de demosaico está cableado y corre sobre un mosaico real, se
  niega a adivinar el patrón sin cabecera, advierte de la interpolación
  en bilineal; el diálogo de caché pre-rellena el campo desde un WCS
  real, informa honestamente de un fallo de descarga y muestra el estado
  real de la caché.

Suite completa sin regresiones: `aps-test` 479 passed / 36 skipped / 1
xfailed; `aps-gui` 583 passed / 20 skipped / 1 xfailed.
