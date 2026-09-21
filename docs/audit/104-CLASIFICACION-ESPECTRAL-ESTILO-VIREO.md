# 104 — CONSTRUIR: Clasificación espectral en vivo, estilo Vireo

Encargo directo del usuario tras usar "Comparación con plantilla de
referencia" (informe 103) y encontrarla limitada frente a su flujo real
en Vireo: *"que puedas ir pasando por todos los tipos de estrellas y se
vaya actualizando automático, mientras que puedas elegir el tipo de
operación entre espectros, como resta etc... y también con las líneas
de compuestos químicos. Tal cual Vireo."* Más una petición explícita de
poder elegir sobre qué ventana activa operar.

## Diagnóstico real antes de construir nada

La captura que mandó el usuario (comparando `frame10` con "M4 III --
HD 110964") mostraba el eje observado hasta ~20000 Å (imposible para un
Alpy 600, rango real ~3800-7500 Å) y solape real del 17% -- la
comparación salía casi vacía. Causa raíz verificada, NO una nueva
petición del usuario: en su captura anterior de "Autoprocesar espectro
(§34)" la casilla **"Búsqueda ciega de dispersión" estaba SIN marcar**,
así que la calibración partió de los valores genéricos por defecto
(1.4 Å/px, 3800 Å) en vez de buscarla -- exactamente el fallo ya
documentado en el informe 101/103. Con la casilla marcada (confirmado
en el mensaje siguiente del usuario) `frame10` calibra igual de bien que
`frame3`. Esto NO es un fallo de código: es una casilla fácil de pasar
por alto en un diálogo con muchos parámetros -- ver "Fuera de alcance"
más abajo.

## Qué se construyó

**`spectroscopy/template_comparison.py`**: nuevo parámetro `operation`
(`"subtract"` por defecto, o `"divide"`) en `compare_to_template` --
cociente real `observado / plantilla` (NaN honesto donde la plantilla
vale cero, nunca infinito silencioso). Mismo contrato que ya tenía la
resta, sin romper ningún uso existente (todos los tests previos siguen
pasando con el valor por defecto).

**`qt_app/spectroscopy/spectral_classification_dialog.py`** (nuevo):
`SpectralClassificationDialog` -- misma disposición que Vireo (lista de
estándares a la izquierda, tres paneles apilados: Estándar / Observado
/ Resultado). Cada clic en la lista, cada cambio de operación, de
normalización o de ventana observada **recalcula y redibuja al
momento** -- sin ningún botón "Comparar" que pulsar. Marca las líneas
químicas conocidas (Balmer/Ca II/Na D/nebulares, los mismos 5 catálogos
reales de `line_catalog.py`) sobre los tres paneles cuando la casilla
está activa (por defecto sí), filtrando solo las que caen dentro del
rango real mostrado -- nunca inventa una línea fuera de catálogo.

**Selector explícito de ventana**: el desplegable "Ventana observada
(ya calibrada)" lista todas las ventanas de imagen abiertas -- responde
directamente a la petición del usuario de poder elegir sobre qué
ventana activa operar, para este diálogo. Mismo patrón que ya usaba
"Comparación con plantilla de referencia".

Menú nuevo: **Espectroscopía -> Clasificación espectral (atlas, estilo
Vireo)...**. El diálogo anterior ("Comparación con plantilla de
referencia...") se conserva tal cual -- sigue siendo el camino directo
para una comparación puntual contra un FITS/texto propio, sin navegar
el atlas.

## Qué sigue igual (§25/§26, sin cambios)

Nunca clasifica ni sugiere un tipo espectral por sí solo: el usuario
navega, ve observado/estándar/resultado real bajo cada estrella, y
decide -- exactamente como en Vireo, la decisión de "a qué se parece"
la toma la persona, no el programa.

## Fuera de alcance de esta entrega

No se tocó el diálogo de "Autoprocesar espectro (§34)" para hacer la
casilla de búsqueda ciega más visible/difícil de olvidar (p. ej.
resaltarla, o avisar si la calibración usó valores por defecto sin
verificar) -- el problema real de esta entrega era la falta de una
vista de clasificación en vivo, no ese diálogo; si se repite la
confusión, es una mejora real a considerar aparte.

## Tests

- `tests/unit/spectroscopy/test_template_comparison.py`: +6 (cociente
  recupera un factor real conocido, cociente=1 para el mismo espectro,
  NaN real donde la plantilla es cero, operación por defecto, rechazo
  de operación desconocida).
- `tests/gui_smoke/test_qt_app_spectral_classification_smoke.py`
  (nuevo): 4 tests -- navegación en vivo por el atlas real recalcula
  sin botón adicional, cociente produce una razón real, líneas químicas
  se marcan/desmarcan según la casilla, exige una ventana ya calibrada.

`pytest tests/unit tests/integration tests/regression -q`: **1795
passed, 25 skipped** (5 nuevos sobre la base de 1790 del informe 103).
`pytest tests/gui_smoke -q` bajo Xvfb: **227 passed** (4 nuevos sobre
223).
