# AstroPhysics Suite — Fase 11.1: cierre del bloque "análisis de imagen"

Segundo bloque del orden de prioridad acordado (`CCDRED → análisis de imagen →
fotometría → astrometría → tablas/catálogos → espectroscopía`), abierto justo
después de cerrar `ccdred` (Fases 10.1-10.2). Cierra las cuatro capacidades que
`13-IRAF-CAPABILITY-MAP.md` §2 dejaba en `PENDIENTE`: aritmética entre imágenes
(el motor ya existía, sin camino de uso), estadística/histograma genérico,
máscaras/regiones/recortes independientes de cualquier proceso concreto, y
normalización de imagen genérica.

## 1. Estadísticas e histograma (`astrophysics_suite/imtools/statistics.py`)

Equivalente propio de la parte de estadística de imagen completa de
`imstatistics`/`astutil`: `compute_image_statistics()` (media, mediana,
desviación estándar clásica y robusta -- MAD × 1.4826, menos sensible a un rayo
cósmico o una fuente saturada --, mínimo/máximo, percentiles 1/5/95/99) y
`compute_histogram()`. Los píxeles no finitos (NaN/inf) se excluyen del cálculo,
nunca se cuentan como cero. 9 tests unitarios, incluida una comparación directa
que demuestra la robustez de la desviación MAD frente a un solo outlier extremo
donde la desviación estándar clásica queda completamente dominada por él.

## 2. Recorte y máscaras de región (`astrophysics_suite/imtools/regions.py`)

`crop()` (recorte genérico, equivalente a `imcopy` con una sección), y dos
máscaras de propósito general (`rectangular_mask`, `circular_mask`) -- distintas,
a propósito, de la máscara de apertura subpíxel de `photometry.aperture` (que
existe para medir flujo con precisión) y del recorte de overscan de
`reduction.overscan` (que es específico de esa corrección). 6 tests unitarios.

## 3. Normalización genérica (`astrophysics_suite/imtools/normalize.py`)

Tres funciones, independientes de la normalización a mediana 1.0 que ya hace
`reduction.master_frames.build_master_flat` para un fotograma de calibración
concreto (esa tiene un significado físico fijo; estas son de propósito general):
`normalize_minmax` (a [0, 1], sensible a un solo extremo), `normalize_percentile`
(a un rango análogo usando percentiles como extremos -- mucho más robusta) y
`normalize_sigma_clip` (z-score por MAD, opcionalmente recortado a ±n sigmas). 8
tests unitarios, incluida una comparación directa que demuestra cuánto más
robusta es la normalización por percentiles que la min/máx clásica ante un
outlier extremo (dos órdenes de magnitud menos aplastamiento del grueso de los
datos).

## 4. Cableado en la GUI

- **`imtools.crop`** (proceso cableado, `requires_picking=2`): dos clics marcan
  las esquinas opuestas del rectángulo -- reutiliza el mismo mecanismo genérico
  de selección de posiciones que ya construyó la Fase 9.6 §8 para fotometría de
  PSF y trazado espectral, sin ningún código de interacción nuevo. El orden de
  los clics no importa (las esquinas se ordenan antes de recortar).
- **`imtools.normalize`** (proceso cableado, imagen única): expone
  `normalize_percentile` con los percentiles como parámetros configurables --
  la variante más generalmente útil de las tres; `normalize_minmax`/
  `normalize_sigma_clip` quedan disponibles como motor pero no como procesos
  independientes en esta primera versión de la GUI (documentado así en el mapa
  de capacidades, no simulado como si tuvieran su propio control).
- **`imtools.statistics`** (proceso cableado, imagen única): informa las
  estadísticas por texto en la consola (`summary`/`log_lines`) y, como el taller
  todavía no tiene un widget de gráfico dedicado, dibuja el histograma como una
  imagen de barras en una ventana MDI nueva -- misma disciplina honesta que ya
  usa `spectroscopy.trace` para su tira 1D repetida: un compromiso explícito y
  documentado, no un widget real fingido.
- **Aritmética entre imágenes** (`qt_app/imtools/arithmetic_dialog.py`,
  `ArithmeticDialog`): a diferencia de los tres anteriores, necesita elegir una
  **segunda** ventana MDI -- no encaja en "un proceso transforma la imagen
  activa" (`ProcessDefinition.run`), así que se resuelve con un diálogo
  dedicado en el menú Herramientas ("Aritmética entre imágenes..."), mismo
  patrón que "Aplicar calibración..." en el menú Reducción. Selector de las dos
  ventanas abiertas + operación (+, −, ×, ÷), valida que tengan la misma forma
  antes de operar, corre en un hilo de fondo real (`CallableWorker`). La
  incertidumbre de cada operando se trata como no estimada (cero explícito, no
  un modelo de ruido inventado) -- es una utilidad genérica entre dos imágenes
  cualesquiera, no una calibración con ganancia/ruido de lectura conocidos como
  sí tiene `reduction.calibration`. La entrada `imtools.arithmetic` del árbol de
  procesos (antes listada sin `run=`) se retiró del explorador, igual que se
  retiraron `reduction.master_bias/dark/flat` en la Fase 9.6 -- habría sido
  información obsoleta y engañosa una vez que la capacidad existe, solo que
  accesible desde otro sitio.

## 5. Verificación

17 tests nuevos de lógica pura en `tests/unit/qt_app/test_registry.py`
(traducción de parámetros/resultado para los tres procesos nuevos, incluidos
los casos de error: número de puntos incorrecto en el recorte, orden de clics
invertido). 6 tests de humo GUI nuevos en
`tests/gui_smoke/test_qt_app_imtools_smoke.py`: recorte real por clics con la
forma resultante verificada contra el recorte esperado, normalización de
extremo a extremo, histograma con la forma de imagen de barras correcta,
aritmética real entre dos ventanas MDI con el resultado numérico verificado
(`100 - 30 = 70` exacto), rechazo de formas distintas sin lanzar el hilo de
fondo, y el aviso en la barra de estado cuando hay menos de dos imágenes
abiertas.

Suite completa verde en ambos entornos tras esta fase: 370 tests en el entorno
con PySide6 (`aps-gui`), 318 en el entorno sin GUI (`aps-test`), más `ruff`
limpio en los 11 archivos nuevos/tocados.

## 6. Estado del bloque tras esta fase

Las 6 capacidades de `13-IRAF-CAPABILITY-MAP.md` §2 quedan en `DISPONIBLE`,
ninguna `PENDIENTE`. Según el orden de prioridad acordado, el siguiente bloque a
abrir es `apphot`: hoy la fotometría de apertura de la GUI sigue fija al centro
de la imagen (ni clic ni detección automática de fuente) y no existe una
calibración fotométrica (punto cero) resuelta contra un catálogo real, solo una
constante que introduce el usuario.
