# AstroPhysics Suite — Fase 9: Suite de reducción y análisis estilo IRAF + taller PixInsight/Qt

## 1. Encargo

Auditar, refactorizar y expandir el programa para integrar las capacidades clásicas
de IRAF -- reducción de CCD (`imred.ccdred`), fotometría de apertura y PSF
(`noao.digiphot.apphot`/`daophot`), espectroscopía 1D/2D (`noao.onedspec`/
`twodspec`), astrometría/WCS (`images.coords`) y utilidades de imagen (`imtools`) --
bajo una GUI moderna inspirada en la arquitectura y estética de PixInsight (MDI,
iconos de proceso, STF, consola integrada), reemplazando la GUI en Tkinter de la
Fase 8. Instrucción explícita del propietario: "no te ciñas solo a lo que se expone
en el prompt... añade todas las funciones de IRAF actualizadas y que sean
interesantes... implementarlo entero en la suite pero hecho por nosotros" -- los
algoritmos se reimplementan con numpy/scipy/astropy, no se envuelven binarios de
IRAF ni pipelines de alto nivel de terceros (`ccdproc`, `photutils.psf`,
`specreduce`); esas bibliotecas existen y son excelentes, pero el encargo pide
explícitamente la reimplementación propia de la matemática.

## 2. Principio heredado que se mantiene intacto

Todo lo construido en Fases 1-7 sigue vigente y no se toca: el vocabulario de
`IdentificationState`/`ValueKind`, el `Candidate` inmutable con historial de
revisión, la cadena de evidencia, y la filosofía IMÁGENES -> DETECCIÓN ->
IDENTIFICACIÓN -> CARACTERIZACIÓN -> COMPARACIÓN -> ANOMALÍAS -> EVIDENCIAS ->
CANDIDATO CIENTÍFICO -> REVISIÓN HUMANA. Esta fase añade una etapa **anterior** a
todo ese pipeline -- IMÁGENES CRUDAS -> REDUCCIÓN -> IMÁGENES CALIBRADAS -- y dos
familias de análisis paralelas (fotometría de precisión, espectroscopía) que hoy no
existían como motores propios. Nada de la Fase 6/7 se reescribe; se le da una
entrada mejor (imágenes calibradas en vez de crudas) y se le añaden vecinos.

## 3. Estructura de paquetes nueva

```
astrophysics_suite/
  reduction/          # imred.ccdred
    frames.py           # CalibrationFrame, MasterFrame: contratos tipados
    overscan.py          # corrección de overscan + recorte (trim)
    combine.py           # combinación de N imágenes: media/mediana + sigma-clipping
    master_frames.py     # construir bias/dark/flat maestros a partir de combine.py
    calibration.py        # aplicar bias/dark(escalado por tiempo de exposición)/flat
    bad_pixel_mask.py     # máscara de píxeles defectuosos + interpolación
    fringe.py             # patrón de franjas: escalado óptimo + sustracción
  imtools/
    arithmetic.py          # ImageWithUncertainty + operaciones con propagación de error
    cosmic_rays.py         # L.A.Cosmic (van Dokkum 2001) reimplementado
    combine.py             # (reexporta reduction.combine -- utilidad genérica de pila)
  photometry/
    quality.py              # (Fase 6, sin cambios)
    aperture.py              # noao.digiphot.apphot: apertura múltiple + anillo de cielo
    psf.py                    # noao.digiphot.daophot: PSF analítica/empírica + ajuste simultáneo
  spectroscopy/                # noao.onedspec / twodspec (paquete nuevo)
    trace.py                    # extracción de traza: suma simple + óptima (Horne 1986)
    wavelength.py                # identify/reidentify: picos de líneas + ajuste polinómico
    fluxcal.py                    # sensfunc/calibrate: estrella estándar + masa de aire/extinción
    continuum.py                   # continuum: ajuste spline/polinómico iterativo con sigma-clip
  astrometry/                      # images.coords (paquete nuevo)
    wcs_fit.py                      # ccmap/ccsetwcs: ajuste de solución WCS desde pares pixel<->cielo
    registration.py                  # registro/reproyección entre imágenes
```

Cada módulo sigue la disciplina ya establecida: dataclasses `frozen=True`,
`Quantity`/`ValueKind` para cualquier valor derivado que lo amerite, `Provenance`
en las salidas que alimentan al Discovery Engine, cero dependencia de GUI, y tests
con datos sintéticos deterministas (no solo "no lanza excepción").

## 4. GUI nueva: `qt_app/` (PySide6)

Reemplaza `gui/` (Tkinter, Fase 8, conservada como referencia -- ver
`docs/audit/10-FASE8-GUI.md`) como interfaz final del producto.

```
qt_app/
  __main__.py            # punto de entrada: python -m qt_app
  theme.py                 # paleta oscura de baja saturación + hoja de estilos Qt (QSS)
  main_window.py             # QMainWindow: MDI + docks + menús + barra de herramientas
  mdi/
    image_window.py           # QMdiSubWindow con vista de imagen (zoom, pan)
    stf_view.py                 # Screen Transfer Function: autoestiramiento no destructivo
  docks/
    process_explorer.py         # árbol categorizado de procesos disponibles
    process_icons.py             # iconos de proceso arrastrables + instancias guardadas
    console_dock.py               # consola de registro/comandos en la parte inferior
    properties_dock.py             # parámetros del proceso seleccionado
  processes/
    base.py                        # ProcessDefinition: contrato uniforme proceso<->GUI
    registry.py                      # registro de todos los procesos disponibles
    <adaptadores finos hacia astrophysics_suite/*>  # la GUI nunca reimplementa ciencia
  workers.py                          # QThread + señales -- ningún proceso pesado en el hilo de GUI
```

La GUI **no** reimplementa ningún algoritmo: cada "proceso" es un adaptador fino
(`processes/*.py`) que construye parámetros desde la interfaz, llama a la función
real de `astrophysics_suite.reduction`/`imtools`/`photometry`/`spectroscopy`/
`astrometry`, y traduce el resultado a lo que la vista necesita mostrar -- misma
disciplina de "GUI nunca contiene lógica científica" que ya regía en `gui/app.py`
(Fase 8).

## 5. Orden de implementación (esta fase, en oleadas)

1. **`imtools`** (aritmética con incertidumbre + L.A.Cosmic): es la base que todo lo
   demás necesita (reducción combina imágenes con la misma aritmética; fotometría y
   espectroscopía necesitan rechazo de rayos cósmicos).
2. **`reduction` (ccdred)**: overscan, combinación con sigma-clipping, bias/dark/flat
   maestros, aplicación de calibración, máscara de píxeles defectuosos, franjas.
3. **`photometry.aperture` (apphot)** y **`photometry.psf` (daophot)**: reutilizan
   `detection.point_sources` para localizar fuentes; añaden fotometría de precisión.
4. **`astrometry`**: ajuste de WCS (`wcs_fit`) y registro/reproyección
   (`registration`) -- fotometría/espectroscopía multi-imagen los necesitan.
5. **`spectroscopy`**: traza, calibración en longitud de onda, calibración en flujo,
   continuo -- el más grande y el que más depende de lo anterior (astrometría para
   masa de aire vía coordenadas, aritmética para combinar exposiciones).
6. **`qt_app`**: taller PixInsight/Qt completo, incluyendo la migración del flujo de
   candidatos (Fase 8) como un proceso más del mismo shell.

Cada oleada se implementa con tests reales (FITS/espectros sintéticos con verdad
conocida, no solo "no lanza excepción") y se commitea por separado, igual que las
fases anteriores -- nunca "big bang".

## 6. Qué NO hace esta fase (alcance explícito)

- No reescribe `detection/point_sources.py` ni ningún motor de la Fase 6: los
  reutiliza.
- No integra automáticamente calibración/fotometría/espectroscopía en
  `discovery/pipeline.py::run_generic_discovery` -- esa integración (imagen
  calibrada -> Discovery Engine) es un paso deliberado y explícito de una fase
  posterior, para no mezclar "aquí se construye el motor" con "aquí se cablea al
  pipeline de descubrimiento" en el mismo cambio.
- No implementa el ajuste de líneas MAPPINGS/3MdB del modo especializado de choque
  (eso sigue documentado como pendiente en `docs/audit/09-FASE7-DISCOVERY-ENGINE.md`
  seccion 4) -- es un cuerpo de trabajo propio, no parte de IRAF.
