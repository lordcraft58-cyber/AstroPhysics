# 106 — CORREGIR: la búsqueda ciega podía devolver una calibración con
# longitud de onda negativa

Segunda vuelta sobre la misma queja del usuario ("pero compara el
continuo no el espectro"), esta vez con capturas reales de la
"Clasificación espectral" mostrando el eje observado arrancando en
~717-737 Å y llegando más allá de 5250-6755 Å -- un rango físicamente
imposible para un Alpy 600 (~3800-7500 Å reales, ~3700 Å de ancho, nunca
6000+). El usuario confirmó que ocurría igual con dos observaciones
DISTINTAS (T-CrB `frame4` y Vega), descartando que fuera un archivo
concreto en mal estado (el informe 101 ya había señalado un stack de
Siril normalizado como sospechoso -- esta vez no es eso).

## Diagnóstico con datos reales

Con los fotogramas sueltos reales que el usuario ya había compartido
(`T-CrB_900sec_1x1__frame3.fit`, `frame6.fit`, `Vega_1sec_1x1__frame6.fit`),
se reprodujo el mismo flujo real que usa "Autoprocesar espectro (§34)"
con "Búsqueda ciega de dispersión" activada (catálogo Balmer, igual que
el usuario). Resultado real, ANTES de esta corrección:

| Fotograma | Rango devuelto | Dispersión |
|---|---|---|
| T-CrB `frame3` | **-610 a 6610 Å** (negativo) | 5.19 Å/px |
| T-CrB `frame6` | **-11958 a 12476 Å** (negativo, absurdo) | 17.6 Å/px |
| Vega `frame6` | 2953 a 7714 Å (positivo, plausible) | 5.32 Å/px |

Los dos fotogramas de la MISMA estrella (T-CrB) daban soluciones
completamente inconsistentes entre sí -- la prueba de que al menos una
(o las dos) es física imposible: **luz real nunca tiene longitud de
onda negativa**.

## Causa raíz

`blind_calibrate_from_reference_star` (informe 101, ya corregido una vez
en el informe 103 para exigir `degree + 2` puntos en vez de `degree + 1`)
sigue sin verificar la PLAUSIBILIDAD física del resultado: solo exige
que la dispersión esté en un rango razonable (`[0.1, 20]` Å/px) y que al
menos `degree + 2` detecciones reales encajen dentro de tolerancia. Con
solo 4 líneas de Balmer en el catálogo y pocas detecciones reales, una
combinación puede seguir casando 3+ detecciones reales dentro de
tolerancia (residuo bajo) y aun así extrapolar, desde esos puntos hasta
el borde del sensor, a una longitud de onda negativa -- evidencia de que
esa combinación concreta no es la asignación correcta, sin importar cuán
bajo sea su residuo.

## Corrección

Se descarta cualquier combinación candidata cuya solución implique una
longitud de onda negativa en **cualquier punto real del sensor** (entre
`pixel.min()` y `pixel.max()` del espectro extraído, no solo en las
detecciones usadas) -- restricción física dura, no un umbral arbitrario:

```python
if min(origin + dispersion * pixel_min, origin + dispersion * pixel_max) < 0.0:
    continue  # luz real nunca tiene longitud de onda negativa
```

**Resultado sobre los mismos fotogramas reales, con la corrección:**

| Fotograma | Rango devuelto | Dispersión |
|---|---|---|
| T-CrB `frame3` | 2620.0 - 4878.6 Å | 1.6249 Å/px |
| T-CrB `frame6` | 2624.7 - 4878.5 Å | 1.6214 Å/px |
| Vega `frame6` | 2952.9 - 7713.8 Å (sin cambios) | 3.4251 Å/px |

Los dos fotogramas INDEPENDIENTES de T-CrB ahora convergen, cada uno por
su cuenta, a la práctica misma solución (diferencia <5 Å en origen,
<0.01 Å/px en dispersión) -- consistencia real entre dos observaciones
independientes del mismo objeto, la mejor evidencia disponible en este
entorno (sin lámpara de arco ni acceso de red) de que el filtro
selecciona una asignación más fiable. Vega, que ya daba un resultado
plausible antes, no cambia.

**Honestidad sobre el límite de esta corrección**: esto NO es una prueba
de que 1.62 Å/px sea la dispersión real de tu Alpy 600 -- no hay forma
de verificarlo en este entorno (sin acceso a la documentación real del
instrumento ni a una lámpara de calibración). Solo descarta soluciones
que son IMPOSIBLES; con un catálogo de solo 4 líneas, más de una
asignación puede seguir siendo posible. La calibración sigue marcada
como PROVISIONAL (mismo aviso de siempre). Si conoces la dispersión
aproximada real de tu Alpy 600 (de la documentación de Shelyak), usar
"Calibrar por estrella de referencia..." dándola tú mismo (en vez de la
búsqueda ciega) elimina esta ambigüedad de raíz.

## Tests

- `tests/unit/spectroscopy/test_reference_star_calibration.py`: +1
  (`test_blind_calibrate_from_reference_star_rejects_a_combination_that_implies_negative_wavelength`,
  reconstruye exactamente la combinación real e imposible encontrada en
  T-CrB `frame3` -- antes se devolvía tal cual, ahora falla
  honestamente con `ValueError`). 13 tests en el archivo, todos pasan.

`pytest tests/unit tests/integration tests/regression -q`: **1796
passed, 24 skipped** (+1 sobre los 1795 del informe 105).
`pytest tests/gui_smoke -q` bajo Xvfb: **218 passed, 1 skipped** (sin
cambios -- esta corrección no toca ningún diálogo Qt).
