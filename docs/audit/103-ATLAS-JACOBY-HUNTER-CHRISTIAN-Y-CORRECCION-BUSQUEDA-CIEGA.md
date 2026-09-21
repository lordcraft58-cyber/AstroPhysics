# 103 — CONSTRUIR: Atlas Jacoby-Hunter-Christian (1984) + corrección real en la búsqueda ciega

Dos entregas en un mismo ciclo de validación con datos reales de T-CrB
(espectrógrafo Alpy 600 de Shelyak, fotograma individual sin apilar) y
la biblioteca completa de Vireo que aportó el usuario.

## 1. Corrección real: la búsqueda ciega (informe 101) podía anclar mal

Validando `blind_calibrate_from_reference_star` contra un fotograma
individual REAL de T-CrB (no el stack normalizado de Siril del informe
101 -- este SÍ tiene cuentas ADU reales y S/N mediana real de 89.4, no
el ruido degenerado de antes), aparecieron dos problemas reales,
encontrados y corregidos en este orden:

1. **Maximizar solo el número de coincidencias podía ignorar la línea
   dominante real.** Sobre el espectro real, Hα era, con mucha
   diferencia, la desviación más fuerte detectada -- pero la búsqueda
   podía preferir una combinación que la dejaba fuera a cambio de
   encajar más detecciones débiles. Corregido: el criterio principal
   pasa a ser la amplitud real total de las detecciones usadas (más
   significativas, menos probable que sean ruido); el número de
   coincidencias y el residuo numérico ahora solo desempatan después.

2. **Hallazgo más profundo, tras aplicar la corrección anterior:** con
   exactamente `degree + 1` puntos (dos, para un ajuste de grado 1),
   SIEMPRE existe una transformación (dispersión, origen) que los hace
   encajar exactamente -- para CUALQUIER asignación a CUALQUIER par de
   líneas del catálogo. Residuo cero por construcción, no por evidencia
   real. Esto significa que ni siquiera el criterio de amplitud
   distingue una asignación correcta de una incorrecta que reutilice
   las dos mismas detecciones fuertes bajo otra transformación: ambas
   tienen la misma amplitud total y el mismo residuo (cero). Corregido
   exigiendo `degree + 2` coincidencias reales como mínimo (tres para
   grado 1, no dos) -- un tercer punto real e independiente es lo que
   de verdad corrobora la transformación. Test de regresión nuevo que
   construye exactamente esta colisión (una pareja fuerte desplazada
   0.4 px de la predicción exacta frente a una pareja débil pero exacta)
   y confirma que ninguna de las dos se acepta sola.

Con la corrección aplicada, sobre el fotograma real de T-CrB con el
catálogo de Balmer: **3 líneas reales simultáneas (Hγ, Hβ, Hα) bajo una
única dispersión lineal, RMS=1.90 Å** -- dispersión real encontrada
≈5.19 Å/px, consistente con el Alpy 600 del usuario (confirmado
directamente desde sus propios datos, no supuesto de una ficha técnica
incierta). El catálogo "Todas" (con líneas nebulares/Na D que no
aplican a este objeto) sigue encontrando una combinación peor -- se
recomienda al usuario restringir el catálogo de calibración a Balmer
para T-CrB.

## 2. Atlas Jacoby-Hunter-Christian (1984) incluido

El usuario aportó su copia completa de la biblioteca del programa Vireo
(`Spectra.zip`), que incluye el atlas real y publicado **Jacoby, G. H.,
Hunter, D. A., & Christian, C. A. (1984), ApJS, 56, 257, "A library of
stellar spectra"**: 161 espectros reales de estrellas concretas
(HD/BD/SAO/Feige), secuencia MK completa O5 a M7, clases de luminosidad
I a V. Datos reales, ya publicados, aportados por el propio usuario --
ni fabricados aquí ni descargados de la red (este entorno no tiene
acceso -- ver informe 101).

**`spectroscopy/jacoby_atlas.py`** (nuevo): `load_jacoby_atlas_index`
parsea el `.INX` real (formato de columnas FIJAS heredado del propio
atlas -- un nombre con espacio interno como `"HD 227018"` y un campo
combinado sin separador como `"O6.5III"` rompen un `split()` ingenuo;
verificado contra los 161 registros reales, cero descartes).
`load_jacoby_atlas_spectrum` reutiliza `import_ascii_spectrum` (informe
102) -- mismo formato de dos columnas, sin duplicar el parseo.
`bundled_atlas_paths` resuelve la copia ya incluida en el proyecto.

**Datos incluidos tal cual** en `spectroscopy/data/jacoby_atlas/`
(`JACOBY2.INX` + un `.SP` real por estrella, ~8.9 MB) -- los 161
archivos reales, verificados 1:1 contra el índice (cero huecos).

**GUI**: "Comparación con plantilla de referencia..." tiene ahora un
desplegable con las 161 estrellas reales del atlas (p. ej. "G6 V -- HD
22193") + "Usar este estándar del atlas", junto a los otros dos caminos
ya existentes (FITS 1D, texto). Sigue sin clasificar nada
automáticamente -- el usuario elige el estándar, ve el residuo real, y
decide, exactamente como ya hace en Vireo comparando contra varios
estándares a la vez.

**Fuera de alcance de esta entrega, mencionado pero no construido**: la
biblioteca de Vireo también incluye colecciones reales de estrellas de
carbono y de galaxias (`Carbon Stars/`, `Galaxies/`) -- no se integraron
todavía, ningún encargo explícito sobre ellas.

## Tests

- `tests/unit/spectroscopy/test_reference_star_calibration.py`: +1
  (colisión de dos puntos nunca se acepta sobre una de tres puntos
  real), 1 modificado (mensaje "al menos 3").
- `tests/unit/spectroscopy/test_jacoby_atlas.py` (nuevo): 11 tests --
  parseo de columnas fijas (simple, fusionado, nombre con "+"),
  cabecera DOS/EOF, rechazo honesto sin entradas reales, carga de
  espectro real, rechazo honesto de archivo faltante, y 3 tests contra
  el atlas real incluido (161 entradas completas, secuencia O-M real,
  entrada G6 V real con rango de longitud de onda esperado).
- `tests/gui_smoke/test_qt_app_template_comparison_smoke.py`: +1 (carga
  un estándar real del atlas incluido end-to-end y compara).

`pytest tests/unit tests/integration tests/regression -q`: **1790
passed, 25 skipped** (12 nuevos sobre la base de 1778 del informe 102).
`pytest tests/gui_smoke -q` bajo Xvfb: **223 passed** (1 nuevo sobre
222).
