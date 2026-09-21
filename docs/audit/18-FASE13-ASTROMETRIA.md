# AstroPhysics Suite — Fase 13: cierre del núcleo de astrometría

Cuarto bloque del orden de prioridad acordado (`CCDRED → análisis de imagen →
fotometría → astrometría → tablas/catálogos → espectroscopía`). Hasta esta fase,
los cuatro motores de `astrophysics_suite/astrometry/` (`wcs_fit`, `registration`)
eran sólidos y estaban probados, pero **ninguno tenía un camino de uso desde la
GUI** -- exactamente el mismo patrón que ya se había cerrado para `ccdred` en las
Fases 10.1-10.2 (motor real, sin interacción construida).

## 1. Por qué no hay resolución automática de WCS ("blind solving")

Antes de describir lo que se cableó, conviene decir explícitamente lo que no: no
existe ninguna forma de que el taller adivine solo qué estrellas de una imagen
corresponden a qué estrellas de un catálogo sin ninguna pista previa (el problema
clásico de "blind plate solving", resuelto en herramientas como astrometry.net
mediante coincidencia de triángulos/geometría invariante -- un problema
algorítmicamente mucho más difícil que ajustar una WCS ya con las
correspondencias dadas). El propio `ccmap` de IRAF, en su modo interactivo
clásico, tampoco lo resolvía: el usuario aportaba los pares píxel↔cielo,
típicamente consultando un catálogo o una carta estelar por su cuenta. Esta fase
reproduce exactamente ese alcance -- ajuste real desde correspondencias dadas por
el usuario -- no una resolución automática, que queda documentada como pendiente
en `13-IRAF-CAPABILITY-MAP.md` §5.

## 2. `wcs_solution_from_astropy` -- puente entre el WCS del FITS y el motor propio

`astrophysics_suite/astrometry/wcs_fit.py` gana una función de conversión: un WCS
real ya cargado de un FITS (`astropy.wcs.WCS`, disponible en `ImageView.wcs` desde
la Fase 12) se convierte al `WCSSolution` propio del proyecto, para poder
reutilizarlo con `registration.reproject_to_reference` sin duplicar ninguna
álgebra. Es una lectura directa de la cabecera, no un ajuste -- los campos de
calidad de ajuste (`residuals_arcsec`, `rms_residual_arcsec`, `n_stars`) quedan
vacíos/cero a propósito, documentado así en el docstring para que nadie los lea
como si fueran la calidad de un ajuste real. Convierte también la convención de
píxel de referencia de FITS (1-indexada) a la 0-indexada que usa el resto del
proyecto (la misma que las posiciones marcadas a clic). 2 tests nuevos
(`tests/unit/astrometry/test_wcs_fit.py`) verifican que el resultado coincide con
`wcs.celestial.all_pix2world` directo en varios puntos, no solo en el de
referencia.

## 3. "Ajustar WCS..." (`qt_app/astrometry/wcs_fit_dialog.py`)

Nuevo menú de nivel superior "Astrometría". El flujo:

1. El usuario marca N >= 3 estrellas de referencia con clic sobre la imagen
   activa (reutiliza el mismo mecanismo genérico de selección de posiciones de la
   Fase 9.6 §8 -- picking no modal, ilimitado, clic derecho para terminar).
2. Al terminar, se abre `WCSFitDialog`: una tabla con una fila por estrella
   marcada (columnas x/y de solo lectura, RA/Dec editables) -- el usuario
   introduce la posición celeste de cada una.
3. "Ajustar WCS" llama a `fit_wcs` real (sin ningún cambio) y reporta el RMS del
   ajuste en segundos de arco y el número de estrellas usadas.
4. El `WCSSolution` resultante se guarda en `ImageView.fitted_wcs_solution` (un
   atributo nuevo, distinto de `ImageView.wcs` -- que es el WCS de la cabecera
   del FITS, si la tenía -- para no confundir "lo que traía el archivo" con "lo
   que el usuario acaba de ajustar a mano en esta sesión").

El ajuste en sí opera solo sobre las N posiciones marcadas (mínimos cuadrados de
unas pocas decenas de puntos como mucho, nunca sobre la imagen completa), así que
corre de forma síncrona -- no hace falta hilo de fondo para esto, a diferencia de
cualquier operación que toque el array de píxeles completo.

## 4. "Registrar por WCS compartido..." (`qt_app/astrometry/registration_dialog.py`)

Mismo patrón de diálogo dedicado que "Aritmética entre imágenes..." (Fase 11.1):
necesita elegir una **segunda** ventana MDI, así que no encaja en un
`ProcessDefinition` genérico. Selector de imagen de referencia + imagen a
reproyectar; cada una resuelve su WCS con la misma prioridad: un
`fitted_wcs_solution` recién ajustado a mano (si existe) antes que el `wcs`
cargado del FITS (si lo tenía) -- si ninguna de las dos ventanas elegidas tiene
WCS de ningún tipo, el diálogo lo dice explícitamente en vez de intentar
reproyectar con datos inventados. Corre en un hilo de fondo real
(`CallableWorker`, mismo mecanismo que el resto del taller) porque
`reproject_to_reference` sí recorre la imagen completa. El resultado se abre
como una nueva ventana MDI.

## 5. Corrección de un bug real encontrado al construir las pruebas: STF con campo casi vacío

Verificar el flujo de registro con datos sintéticos (una fuente puntual sobre un
fondo casi uniforme) hizo saltar un `ValueError: f(a) and f(b) must have
different signs` real en `qt_app/mdi/stf.py::_solve_midtones_balance`: cuando la
mediana robusta de la imagen (que domina la estadística en un campo con una única
fuente brillante sobre fondo plano) queda pegada casi exactamente al fondo, la
función de transferencia de tonos medios no puede alcanzar el nivel de fondo
objetivo con ningún balance -- no hay raíz que buscar, y `scipy.optimize.brentq`
lanzaba en vez de manejar el caso. No es un bug introducido por esta fase: es una
condición real de imagen (campo mayormente vacío con una fuente brillante,
perfectamente plausible en datos reales) que ya podía darse antes; esta fase lo
encontró al escribir un test de humo con exactamente esa estadística. Corregido
detectando el caso degenerado explícitamente (`objective()` sin cambio de signo en
el intervalo de búsqueda) y usando un balance de tonos medios neutro (0.5) en vez
de fallar -- el punto de corte de sombras/luces ya domina el estiramiento en ese
caso, así que el valor exacto de `m` deja de importar. Test de regresión en
`tests/unit/qt_app/test_stf.py`.

## 6. Verificación

2 tests unitarios nuevos para `wcs_solution_from_astropy` (comparación directa
contra `astropy.wcs.WCS.all_pix2world` real). 4 tests de humo GUI nuevos en
`tests/gui_smoke/test_qt_app_astrometry_smoke.py`:

- Ajuste de WCS de extremo a extremo: clic real en 4 estrellas sobre una imagen
  sintética, relleno de la tabla con las coordenadas exactas de un WCS conocido
  (`astropy.wcs.WCS` real, no simulado), y el `WCSSolution` resultante verificado
  con RMS < 0.001" (datos sin ruido, debe recuperar el WCS casi exactamente).
- Registro real entre dos ventanas: una imagen de referencia y la misma imagen
  desplazada 4 píxeles con su propio WCS consistente con ese desplazamiento;
  tras reproyectar, el pico de la fuente vuelve a estar en su posición original
  (no en la desplazada) -- confirma que la reproyección corrige el corrimiento de
  verdad, no que simplemente no falla.
- Caso sin WCS en ninguna ventana: mensaje de error claro, el hilo de fondo nunca
  se lanza.
- Avisos en la barra de estado cuando falta estado necesario (sin imagen activa,
  menos de dos imágenes abiertas).

Suite completa verde en ambos entornos tras esta fase: 391 tests en el entorno con
PySide6 (`aps-gui`), 333 en el entorno sin GUI (`aps-test`), más `ruff` limpio en
los 8 archivos nuevos/tocados.

## 7. Qué queda del bloque de astrometría (documentado, no oculto)

- **Registro por pares de estrellas emparejadas entre dos ventanas**
  (`fit_affine_transform`, motor real y probado): necesitaría una interacción de
  selección cruzada entre dos vistas MDI a la vez (marcar el mismo par de
  estrellas en ambas, en el mismo orden) que no se construyó en esta fase --
  "Registrar por WCS compartido..." cubre el caso donde ambas imágenes ya tienen
  WCS, que es el camino más común en la práctica (astrofotografía con
  *plate-solving* previo), pero no sustituye por completo a la alineación por
  estrellas cuando ninguna imagen tiene WCS todavía.
- **Resolución automática contra catálogo ("blind solving")**: fuera de alcance
  deliberado, ver §1.
- **Exportación de posiciones/residuos a archivo**: el RMS y los residuos del
  ajuste se reportan en la consola, pero no hay una exportación a CSV/tabla FITS
  -- ligado al vacío de arquitectura de "tablas" que señala
  `13-IRAF-CAPABILITY-MAP.md` §6, el siguiente bloque a abrir.
