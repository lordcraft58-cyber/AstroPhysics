# 53 — Cierre de Astrometría / WCS

Tercer motor de la lista del usuario. El núcleo científico ya estaba
bien: cuatro motores que producen un WCS (`plate_solve`, `blind_solve`,
`wcs_fit` y `optical_wcs`), con sus tests. Los huecos estaban todos en
**lo que salía del programa**, y dos de ellos solo se ven con los FITS
reales del usuario.

## 1. El archivo mentía sobre quién lo había resuelto

**El hueco**: la copia FITS con WCS se escribía desde la ventana Qt, con
las tarjetas construidas a mano ahí mismo, y esta línea fija:

```python
header["HISTORY"] = f"WCS ajustado por AstroPhysics Suite (astrometry.wcs_fit): ..."
```

Una placa resuelta **en ciego** salía del programa declarando en su
cabecera un motor que no la había resuelto. `PlateSolveResult` ya traía
`provider` y `provenance` reales; la ventana los tiraba y se quedaba solo
con `.solution`.

**Lo hecho**: `astrophysics_suite/astrometry/provenance.py`, en la capa de
ciencia (probable sin Qt):

- `WCSRecord` — la solución **más** el motor que la produjo, el catálogo
  usado, cuántas estrellas se detectaron y cuántas se emparejaron.
- `build_wcs_provenance()` — `Provenance` real con avisos.
- `wcs_header_cards()` — el WCS estándar completo (CRVAL/CRPIX/CD/CTYPE,
  vía astropy) más `APSWCS`, `APSWCSRC`, `APSWCSVR`, `APSWCSMD`,
  `APSWCSSC`, `APSWCSCT`, `APSWCSNM`, `APSWCSDT` y `HISTORY`.

Los diálogos de resolución conservan ahora el `WCSRecord` real
(`result_record()`) en vez de dejar que la ventana vuelva a suponerlo.

**La prueba de humo afirmaba el error.**
`test_saving_wcs_fits_copy_writes_a_real_solvable_header` — que recorre
el camino de la resolución **automática** — comprobaba
`assert "wcs_fit" in str(header["HISTORY"])`. Es decir: verificaba que el
archivo declarase el motor equivocado, porque eso era lo que el código
escribía siempre. Ahora comprueba `astrometry.plate_solve`, y además que
`astrometry.wcs_fit` **no** aparezca.

## 2. Un WCS declarado desde la óptica no puede declarar calidad

`build_wcs_from_optics` deja `rms_residual_arcsec = 0.0` y `n_stars = 0`
**a propósito**, para no fingir un ajuste. Volcar esos campos a la
cabecera habría escrito `WCSRMS = 0.0`, que cualquier lector interpreta
como un ajuste perfecto — justo lo contrario de lo que significan.

`wcs_header_cards` escribe `WCSRMS`/`WCSNSTR` **solo si hay ajuste real
detrás**. Si no, escribe `APSWCSMD = F` y lo dice en el `HISTORY`.

## 3. El RMS de un ajuste con 3 estrellas es 230 veces menor que el error real

No es una regla de tradición: se midió. Con el WCS real del usuario
(ASI533MC Pro a 749 mm, 1.0355 "/px) y un error de centroide de 0.5 px,
400 ajustes por tamaño de muestra:

| n estrellas | RMS declarado | Error real en el centro | Ratio |
|---|---|---|---|
| 3 | 0.0032" | 0.7369" | **230×** |
| 4 | 0.3233" | 0.4545" | 1.4× |
| 6 | 0.4894" | 0.3299" | 0.7× |
| 12 | 0.6301" | 0.1879" | 0.3× |
| 30 | 0.6923" | 0.1150" | 0.2× |

Con 3 estrellas, `fit_wcs` resuelve CRVAL con tantas ecuaciones como
incógnitas: los residuales salen casi nulos **por construcción**. Un
usuario que lea `WCSRMS = 0.003` creerá tener astrometría de
milisegundos de arco teniendo 0.74". De 4 en adelante el RMS ya es del
orden correcto; de 6 en adelante es conservador.

De ahí `MIN_STARS_FOR_MEANINGFUL_RMS = 4`: por debajo, la procedencia
avisa, el diálogo lo enseña **antes** de guardar, y el aviso se escribe
dentro del archivo. El test
`test_the_three_star_rms_really_does_understate_the_error` vuelve a
medirlo en cada ejecución: un aviso solo vale si el hecho que denuncia
sigue siendo cierto.

## 4. El SIP del ASIAIR sobrevivía y torcía la solución nueva

Encontrado ejecutando la validación sobre un LIGHT real de M 31.

**El hueco**: el ASIAIR Mini del usuario ya había resuelto la placa y
dejó en la cabecera una solución TAN-SIP completa —
`CTYPE1 = 'RA---TAN-SIP'`, `CRPIX` en (2742, 1803), y 24 coeficientes
`A_*`/`B_*`/`AP_*`/`BP_*`. Al escribir el WCS nuevo se hacía:

```python
header = dict(view.header)            # trae todo lo anterior
header.update(...)                    # sobrescribe CRVAL/CRPIX/CD/CTYPE
```

`CTYPE` pasaba a `RA---TAN` (sin `-SIP`)... y **los coeficientes SIP se
quedaban dentro**. `astropy` los aplica igualmente, y lo dice:

> *SIP coefficients were detected, but CTYPE is missing a "-SIP" suffix.
> astropy.wcs is using the SIP distortion coefficients, therefore the
> coordinates calculated here might be incorrect.*

Error medido sobre el archivo real:

| píxel | discrepancia |
|---|---|
| (1504, 1504) — centro | **0.0000"** |
| (750, 2250) | 0.1402" |
| (0, 0) | 0.2420" |
| (3007, 0) | 0.5572" |
| (0, 3007) | **0.5579"** = 0.54 px |

Cero en el centro: ninguna comprobación centrada lo habría visto. Y como
cada programa decide por su cuenta si aplicar un SIP con `CTYPE`
incoherente, el mismo archivo significaba cosas distintas en programas
distintos.

**Lo hecho**: `strip_wcs_keywords()` borra la solución anterior **entera**
(WCS lineal, SIP, TPV, y la procedencia `APSWCS*`/`WCSRMS`/`WCSNSTR` de
un solve previo nuestro) antes de escribir la nueva, conservando los
metadatos reales de la observación. Tras el arreglo, el peor error sobre
el mismo archivo real es **3.4 × 10⁻¹¹ arcsec**.

El mismo arreglo se aplica en la reducción: **un LIGHT recortado
(`trim_region`) pierde el WCS de su cabecera cruda**, porque el recorte
mueve el origen y esas coordenadas dejan de describir estos píxeles.
Arrastrarlo es peor que no tener ninguno, porque parece válido.

## 5. Dos de los cuatro motores no ofrecían guardar nada

`_offer_to_save_wcs_fits_copy` solo se llamaba desde las dos
resoluciones automáticas. Un WCS **ajustado a mano** o **construido
desde la óptica** vivía solo en memoria y moría al cerrar el programa.
Ahora los cuatro ofrecen la copia, y la pregunta enseña de antemano qué
calidad tiene la solución y qué avisos lleva.

## Validación con datos reales

LIGHT real de M 31 (300 s, ASI533MC Pro, 3008×3008), dos caminos:

| Comprobación | Resultado |
|---|---|
| Óptica leída de la cabecera | ZWO ASI533MC Pro, 3.76 µm, 749 mm → 1.0355 "/px, campo 51.9'×51.9' |
| WCS declarado: `APSWCSMD` | `False`, sin `WCSRMS` ni `WCSNSTR` |
| Escala que mide astropy en el archivo | 1.0355 "/px |
| Centro releído | error 0.000000" |
| Fuentes detectadas por el detector real | 114 |
| Ajuste sobre 40 estrellas reales | RMS = 0.002816", sin avisos |
| `APSWCSRC` / `WCSNSTR` releídos | `astrometry.wcs_fit` / 40 |
| Solución ↔ archivo, 4 esquinas + centro | peor discrepancia 1.3 × 10⁻⁹ " |
| Restos del solve del ASIAIR | ninguno; sin aviso de SIP de astropy |

## Checklist del motor

| Fase | Estado |
|---|---|
| IMPLEMENTACIÓN | `astrometry/provenance.py` (record, procedencia, tarjetas, limpieza) |
| CONTRATO | `WCSRecord`, `is_measured`, `MIN_STARS_FOR_MEANINGFUL_RMS` |
| GUI | los 4 motores ofrecen la copia; la pregunta enseña calidad y avisos |
| SALIDA | FITS con WCS estándar + procedencia, sin restos del solve anterior |
| PROVENANCE | motor real por solución, con avisos escritos en el archivo |
| UNIT TEST | `tests/unit/astrometry/test_astrometry_provenance.py` (11) |
| INTEGRATION TEST | `tests/gui_smoke/test_qt_app_wcs_fits_copy_smoke.py` (6), más los 4 de humo ya existentes actualizados |
| FITS REAL | LIGHT de M 31 — ver tabla arriba |
| CERRADO | sí |

## Lo que sigue abierto en este motor

- **Sin distorsión de orden superior.** `wcs_fit` ajusta TAN lineal, el
  alcance declarado desde su primera versión (el modo por defecto de
  `ccmap`). Con un campo de 51.9' el término SIP del ASIAIR llega a
  medio píxel en las esquinas, así que **no es despreciable para este
  usuario**: ajustar SIP propio es un motor aparte, no un retoque.
- **`input_hashes` sigue sin rellenarse**, igual que en la reducción
  (informe 52): el parámetro existe y el llamador todavía no pasa los
  sha256 reales.
- **La copia con WCS no guarda incertidumbre** — no la hay: no se toca
  un solo píxel, solo la cabecera.

Suite completa tras el cierre: **757 pasadas, 24 saltadas, 1 xfailed**
(`aps-test`) y **149 pasadas** de humo GUI (`aps-gui`). `ruff` limpio.
