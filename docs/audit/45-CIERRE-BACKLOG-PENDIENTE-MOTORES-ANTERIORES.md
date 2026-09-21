# 45 — Cierre de backlog: brechas reales dejadas pendientes por motores anteriores

El usuario pidió explícitamente "termina todo lo que quedaba pendiente
de los motores anteriores". Antes de tocar código se hizo un inventario
completo (lectura íntegra de los 44 informes de `docs/audit/`, grep de
TODO/PENDIENTE en el código, y el único informe INVESTIGACIÓN en vez de
CIERRE) para no depender de la memoria de la sesión. Este informe cierra
lo que resultó real y seguro de cerrar; documenta explícitamente lo que
NO se tocó y por qué.

## Cerrado en esta pasada (7 items reales)

1. **Incertidumbre del punto cero fotométrico nunca propagada**
   (`docs/audit/39-...`). `ZeropointFit.zeropoint_uncertainty_mag` se
   descartaba al construir `expected_band_flux` -- ahora se combina en
   cuadratura con la del flujo medido en `anomaly/vector.py::
   _photometric_anomaly`, evitando que un punto cero mal determinado
   infle la significancia fotométrica declarada.
2. **`fit_zeropoint` no exponía qué estrella rechazó su propio
   sigma-clip** (`docs/audit/19-...`). `ZeropointFit.used_mask` nuevo
   (misma longitud/orden que la entrada); la tabla exportable de
   `photometry.zeropoint` en la GUI gana una columna "usada" real.
3. **Procedencia astrométrica nunca escrita en el FITS guardado**
   (limitación implícita desde el cierre 37). "Guardar FITS con WCS..."
   ahora escribe `WCSRMS`/`WCSNSTR`/`HISTORY` reales en la cabecera.
4. **Autoría de revisión con un placeholder fijo** ("Revisor", Fase 8).
   Se pregunta el nombre real la primera vez y se persiste como
   preferencia (`services/app_preferences.py`), reutilizado como valor
   por defecto.
5. **`band_ratios` siempre vacío en producción** -- la brecha más
   profunda de esta pasada. Investigando el item "spectral anomaly /
   band_ratios" del backlog se encontró que NINGÚN mecanismo agrupaba
   nunca detecciones de bandas distintas de la misma fuente:
   `source_tracks.group_detections_into_tracks` agrupa
   deliberadamente solo DENTRO de cada banda (confirmado en el propio
   comentario del código -- fundir bandas confundiría "mismo objeto en
   dos filtros" con "mismo objeto en dos épocas"). Se construyó
   `_find_cross_band_reference_matches`, un emparejamiento SEPARADO
   solo por posición celeste de las referencias ya elegidas de cada
   traza, que nunca toca la agrupación temporal. Con esto,
   `Candidate.flux` refleja todas las bandas reales de una fuente
   multibanda registrada (antes solo la de su época de referencia), y
   `characterization.band_ratios` queda poblado con datos reales
   (incluido un alias `"OIII/HA"` en la orientación que ya espera
   `physics/observables.py`, aunque ese motor sigue sin conectarse al
   pipeline genérico -- ver "no tocado" más abajo).
6. **`WCSSolution`/`ZeropointFit` nunca sobrevivían más allá de la
   sesión de GUI activa** -- la limitación que el propio cierre 44
   dejó documentada explícitamente como bloqueante. `SessionState`
   gana `wcs_solutions`/`zeropoint_fits` (dict por ruta de imagen);
   "Generar informe científico..." los busca ahí y ahora sí puede
   mostrar residuales astrométricos/fotométricos reales desde la GUI,
   no solo cuando se llama a `build_candidate_report` a mano.
7. **Sin selector de sesiones recientes** (cierre 40, "trabajo de UX
   pendiente"). Archivo -> "Sesiones recientes" real, persistido vía
   preferencias, reabre con un clic.

## Verificado ya resuelto (sin cambios de código)

**"Auditoría de rutas de salida fijas nunca hecha"** (cierre 28,
Fase 10.2). Se auditaron todos los `writeto`/`save_fits_image`/`to_csv`
de `qt_app/`: los seis (guardar FITS con WCS, guardar sesión, exportar
tabla, generar informe de candidato/observación, reducir sesión de
LIGHTS) ya pasan por `QFileDialog`/`getExistingDirectory` real -- no
quedaba ningún flujo con ruta fija. La preocupación del cierre 28 ya
está cubierta por trabajo posterior sin que ningún informe lo marcara
explícitamente como cerrado.

## Deliberadamente NO tocado, con motivo

- **PSF Photometry** (`docs/audit/41-INVESTIGACION-...`, único informe
  INVESTIGACIÓN, no CIERRE). La investigación encontró flujo PSF
  sistemáticamente 2-12x menor que el de apertura sobre estrellas
  reales de M 31, sin resolver si es física esperada (apertura
  integrando nebulosidad difusa real que una PSF compacta excluye
  correctamente) o un sesgo real sin corregir. Reabrir esto exige
  validación sobre estrellas de campo aisladas y una decisión de
  política científica sobre qué flujo es "correcto" en campos
  extendidos -- no es una tarea de "conectar código que falta", es una
  pregunta científica abierta que el propio informe dejó
  explícitamente sin resolver por rigor, no por falta de tiempo.
  Repetir ese juicio sin datos nuevos habría sido descuidado.
- **Unificación de tipos `Measurement`/`SourceCatalog`**
  (`docs/audit/13-IRAF-CAPABILITY-MAP.md` §6). Marcado ahí mismo como
  "brecha de arquitectura real, deliberadamente NO resuelta" por tocar
  4 motores ya cerrados y probados. Sigue sin resolverse aquí por el
  mismo motivo: es una refactorización de arquitectura, no un gap
  funcional, y el riesgo de tocar motores estables por una limpieza sin
  capacidad nueva no se justifica dentro de este cierre.
- **Refactorizar los 5 motores con sigma-clip duplicado** hacia
  `diagnostics/outliers.py` (construido en el cierre 44 precisamente
  para diagnóstico, no para sustituir el rechazo real de cada motor).
  Limpieza real pero separada y de mayor riesgo (`fit_zeropoint`,
  `photometry.aperture`, `spectroscopy.continuum`/`trace`,
  `astrometry.plate_solve._robust_fit_wcs`) -- sin capacidad nueva que
  la justifique dentro de este cierre.
- **Expansión completa de espectroscopía** (extracción multi-apertura,
  medición de líneas/EW, combinación de espectros, tipo `Spectrum`
  unificado -- `docs/audit/13-...` §7). Son varios motores nuevos, no
  una conexión; permanecen como PENDIENTE documentado igual que antes.
- **Catálogo multi-proveedor** (`docs/audit/13-...` §6). Sigue siendo
  YAGNI real: solo Gaia tiene un consumidor de producción hoy.
- **Exportación a PDF**. Necesitaría una dependencia nueva no evaluada;
  CSV por tabla ya es trivial hoy vía `Table.to_csv` sin código nuevo.

## Ambientalmente inalcanzable desde este entorno (no un motor pendiente)

- **Backends reales de PyRAF/IRAF sin validar contra IRAF real**
  (`docs/audit/33-...`). El canal de red que distribuye los binarios de
  IRAF (`ssb.stsci.edu/astroconda`) está fuera de la lista blanca de
  este entorno -- ~19 pruebas marcadas `@requires_real_pyraf` no pueden
  ejecutarse aquí bajo ninguna circunstancia real.
- **Paquete Windows sin compilar en Windows real**
  (`docs/audit/24-...`). PyInstaller no hace compilación cruzada; Inno
  Setup es una herramienta solo de Windows. Ninguno de los dos puede
  ejecutarse en este sandbox Linux.

## Tests

21 tests nuevos/actualizados en esta pasada, todos contra datos reales
o motores reales (nunca solo "no lanza excepción"):
`tests/unit/anomaly/test_vector.py` (+1), `tests/unit/evidence/
test_chain_builder.py` (actualizado), `tests/unit/photometry/
test_photometric_calibration.py` (+2), `tests/unit/qt_app/
test_registry.py` (actualizado), `tests/integration/
test_generic_discovery_pipeline.py` (+2), `tests/gui_smoke/
test_qt_app_plate_solve_smoke.py` (actualizado), `tests/gui_smoke/
test_qt_app_candidates_smoke.py` (+2), `tests/gui_smoke/
test_qt_app_report_smoke.py` (+1).

## Validación

| conjunto | comando | resultado |
|---|---|---|
| Unit + integración + regresión | `pytest tests/ --ignore=tests/gui_smoke` (venv `aps-test`) | **663 passed, 21 skipped, 1 xfailed** (antes: 659) |
| GUI smoke completa | `xvfb-run pytest tests/gui_smoke/` (venv `aps-gui`) | **117 passed** (antes: 114) |

Validado además con las 3 épocas reales de M 31 usadas en toda la
sesión: mismo resultado y tiempo (7.6s vs 8.0s, dentro del ruido) antes
y después de la fusión multibanda -- confirma cero cambio de
comportamiento para el caso dominante real (una sola banda), y que el
nuevo barrido cruzado de bandas se salta por completo cuando no hace
falta.

## Cambio de motor

Backlog auditado de extremo a extremo. Siete brechas reales cerradas,
una verificada ya resuelta, el resto documentado explícitamente como
fuera de alcance (por riesgo/tamaño desproporcionado) o inalcanzable
(bloqueo de entorno) -- ninguna descartada en silencio. Disponible para
el siguiente motor, o para cualquiera de los items explícitamente
listados arriba si el usuario decide priorizarlos.
