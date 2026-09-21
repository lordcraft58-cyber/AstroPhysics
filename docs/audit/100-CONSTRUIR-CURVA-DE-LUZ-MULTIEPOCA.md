# 100 — CONSTRUIR: Curva de luz multiépoca (Estrellas Variables)

Encargo directo del usuario (Nova Vul 2024, 103 LIGHTS reales de
`Observatorio Astronomico de Guirguillano`), fuera del ciclo de cierre
sistemático de 16 motores: una herramienta de GUI para fotometría
diferencial de una estrella variable con hasta 5 estrellas de
comparación, sobre N fotogramas del usuario, con gráfico real
exportable. Sección propia ("Estrellas Variables"), deliberadamente
separada de "Descubrimiento" (que busca fuentes nuevas/anómalas
comparando contra un catálogo, un problema distinto).

## Qué es y qué no es

No es un motor científico nuevo: reutiliza tres motores ya cerrados y
probados en el ciclo de auditoría --

- `photometry/aperture.py::aperture_photometry` (fotometría de apertura
  real, cerrado en el informe 95).
- `temporal/variability.py::analyze_variability` (ajuste lineal
  ponderado + chi² constante, migrado a nativo en el informe 97).
- `visualization/charts.py::render_series` (el mismo motor de gráficos
  ya usado en los informes científicos HTML -- "línea" es literalmente
  el tipo ya documentado para curvas de luz).

Lo nuevo es la orquestación: registrar N fotogramas entre sí sin
necesitar WCS ni red (los datos reales de Nova Vul no traían un WCS de
verdad, solo un apuntado aproximado de montura), y la interfaz para
elegir la variable + comparación a clic y calcular en lote.

## Hallazgo real durante la validación con datos reales

Con los 5 fotogramas de prueba de Nova Vul, un primer intento usando el
WCS "declarado" de la cabecera (`CRVAL`/`PIXSCALE`/ángulo asumido 0,
construido con `astrometry.optical_wcs.build_wcs_from_optics`, ya
cerrado) para predecir la posición de la variable en cada fotograma
posterior FALLÓ para los fotogramas 30/60/80 (ninguna fuente real cerca
de la posición prevista) -- el apuntado de montura registrado en la
cabecera no era lo bastante preciso para localizar la misma estrella dos
fotogramas después. Se sustituyó por un registro real basado en el
patrón de estrellas del propio campo (`astrometry/frame_registration.py`,
nuevo), que sí funcionó con 56-60 de 60 estrellas coincidentes en los 5
fotogramas -- mucho más fiable que fiarse de la cabecera cuando no hay
plate solving real detrás.

## Motor nuevo: `astrometry/frame_registration.py`

`estimate_frame_translation(reference_xy, target_xy)`: traslación
`(dx, dy)` real entre dos fotogramas por coincidencia de patrones (sin
WCS ni catálogo) -- prueba la traslación implicada por cada par de
estrellas candidatas y se queda con la que alinea más estrellas del
resto del campo. `refine_position(...)`: reajusta una posición prevista
a la fuente real más cercana, sin inventar una posición si no hay
ninguna cerca. 8 tests unitarios con datos sintéticos (traslación
conocida, solapamiento parcial de campo, campos sin relación real).

## Motor nuevo: `photometry/multi_frame.py`

`build_multi_frame_light_curve(frames, target_xy, comparison_xy, ...)`:
orquesta registro + fotometría de apertura + magnitud diferencial
(variable frente a la suma de 1 a 5 comparaciones, con propagación de
error real por cuadratura a partir de `net_flux_uncertainty`) +
`analyze_variability`. Ruido real por fotograma vía `GAIN`/`RDNOISE` de
cabecera cuando existen (`imtools.ccd_noise.ccd_noise_adu`, mismo motor
ya usado en reducción/espectroscopía), con la aproximación `sqrt(ADU)`
como respaldo declarado. Un fotograma sin traslación fiable, sin fuente
real cerca de la posición prevista, con flujo neto <= 0, o sin
`DATE-OBS` real, se registra con su `skip_reason` explícito y no entra
en el ajuste -- nunca un valor inventado. 9 tests unitarios con datos
sintéticos (tendencia real recuperada, fuente constante no marcada
variable, traslación inyectada recuperada, límites de 1-5 comparaciones,
GAIN/RDNOISE reales).

## Consolidación de código compartido

`io.fits_header_reader.parse_date_obs` (nuevo): única implementación
real del parseo de `DATE-OBS`, antes duplicada de forma privada en
`discovery/pipeline.py::_parse_epoch_time` (ahora delega en ella) --
mismo criterio de "una sola implementación real" ya aplicado varias
veces en el ciclo de cierre sistemático (informes 96-99).

## GUI: `qt_app/variable_stars/light_curve_dialog.py`

Menú nuevo **Estrellas Variables -> Curva de luz multiépoca...**: clic
en la imagen ya abierta para marcar la variable (primer clic) y hasta 5
comparaciones (siguientes clics, clic derecho para terminar) --
reutiliza el mecanismo de selección ya existente
(`ImageView.start_picking`). El diálogo permite añadir el resto de
LIGHTS desde disco, calcula en un hilo de fondo real
(`CallableWorker`), y muestra el gráfico real (PNG embebido) con
"Guardar gráfico como imagen..." y "Exportar tabla a CSV..." -- la
tabla también queda disponible en "Herramientas -> Exportar última
tabla a CSV..." como el resto de la suite. 3 tests de humo GUI end-to-end
bajo Xvfb (curva real con tendencia declinante detectada, sin imagen
activa, un solo clic sin comparación).

## Validación con datos reales

Los 5 fotogramas reales de Nova Vul 2024 (frames 1/30/60/80/103 de 103)
con las posiciones REALES de NOVA-VUL y CAL-1..4 que aportó el usuario
(coincidencia <1.3 px con las fuentes reales detectadas, confirmando
además la convención de eje Y de su archivo -- origen abajo, frente al
origen arriba del detector): **5/5 épocas válidas**, `variable_candidate
= True`, caída de brillo de **+0.01656 ± 0.00061 mag/hora** -- magnitud
y sentido consistentes con la propia reducción del usuario en FotoDif
para la misma noche.

## Fuera de alcance, dejado explícito (no silenciado)

1. **Conexión con el clasificador visual/IA de Discovery**
   (`anomaly/physical_tension.py`/`DiscoveryEvidenceEngine`): el
   `TemporalEvidence` que produce esta herramienta es el MISMO tipo real
   que ya consume la fusión de evidencia automática dentro de
   Discovery -- pero conectarlo de verdad requeriría construir un
   `Candidate` completo (Detección + Caracterización + Identificación)
   a partir de la estrella elegida a mano, no solo temporal. Es una
   ampliación real y más grande, no una casilla que faltara marcar aquí;
   queda pendiente de un encargo explícito.
2. **Tránsitos de exoplanetas**: descartado explícitamente por el
   usuario en esta conversación -- necesitaría un motor físico nuevo
   (modelo de tránsito con oscurecimiento de limbo), no orquestación
   sobre motores existentes.

## Validación de la suite completa

`pytest tests/unit tests/integration tests/regression -q`: **1757
passed, 24 skipped** (17 tests nuevos sobre la base de 1740 tras el
informe 99). `pytest tests/gui_smoke -q` bajo Xvfb: **217 passed** (3
nuevos sobre 214).
