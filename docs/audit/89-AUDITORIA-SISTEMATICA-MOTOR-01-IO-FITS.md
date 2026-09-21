# 89 — Auditoría sistemática, motor 1/16: IO/FITS

Primer motor de la nueva fase pedida explícitamente por el usuario:
auditar/corregir/completar/conectar/testear/validar/documentar
motor por motor, en orden fijo, sin construir nada nuevo. IO/FITS ya
se había cerrado formalmente (informe 51), así que esta auditoría
re-verifica ese cierre contra un checklist de 20 puntos más estricto
en vez de darlo por bueno, y encontró tres huecos reales, menores pero
reales -- ninguno bloqueaba el motor, todos se cierran aquí.

## Mapa del motor (fase previa, sin tocar código)

**Archivos**: `astrophysics_suite/io/{__init__,fits_reader,fits_loader,
fits_writer,fits_header_reader,xisf_reader,session_export}.py`.
**Modelo**: `astrophysics_suite/models/observation.py` (`ImageRef`,
`Observation`). **GUI**: `qt_app/main_window.py::open_fits_dialog/
open_fits/add_image_window`, `qt_app/io/cube_plane_dialog.py`.
**Consumidores**: `detection/point_sources.py`, `discovery/pipeline.py`,
`photometry/quality.py`, `astrometry/provenance.py`,
`reduction/provenance.py`, `spectroscopy/spectrum1d_io.py`,
`qt_app/reduction/{reduce_session_dialog,build_master_frame_dialog}.py`.
**Tests**: `tests/unit/io/` (6 archivos, 39 tests antes de este informe),
`tests/regression/test_fits_reader_matches_legacy.py` (10, 3 solo con
`ASTROPHYSICS_REAL_FITS_DIR`), `tests/gui_smoke/test_qt_app_smoke.py`
(open_fits: BZERO/BSCALE, cubo 3D + cancelar, error de archivo corrupto).

## Hallazgos y cierre

### 1. `io/__init__.py` describía un estado que ya no existe

El docstring del paquete seguía diciendo *"delega la lectura real de
FITS en legacy...load_fits"* -- cierto en la Fase 6, slice 1, falso
desde el informe 51 (`fits_reader.py` es una reimplementación propia,
sin ninguna dependencia del monolito para leer un solo píxel). Quien
abriera este paquete primero se llevaba una idea equivocada de la
arquitectura real. Corregido para reflejar el estado actual y explicar
por qué el texto anterior estaba desactualizado, no solo borrarlo.

### 2. `resolve_path` existía, tenía cero consumidores

`fits_reader.py::resolve_path` (un envoltorio trivial de `Path(path).
resolve()`) no lo llamaba nadie -- ni código de producción ni tests.
Mientras tanto, `fits_loader.py::load_image` duplicaba la misma línea a
mano al construir `ImageRef.path`. Conectado: `load_image` ahora llama
a `resolve_path`, eliminando la duplicación en vez de dejar una función
huérfana o borrarla sin más.

### 3. El flujo GUI de abrir un XISF real nunca se había probado de extremo a extremo

`open_fits`/`open_fits_dialog` sí despachan un `.xisf` correctamente
(mismo camino que un FITS, vía `load_image`), y `io.fits_loader.
load_image` ya estaba probado con XISF a nivel de unidad
(`test_fits_loader_xisf.py`, 4 tests) -- pero ningún test de humo GUI
abría un `.xisf` real por el flujo real de la ventana principal. Cierra
el hueco de cobertura: nuevo test que construye un XISF real (mismo
formato byte a byte que el resto de la suite XISF) y lo abre vía
`main_window.open_fits`, confirmando datos y cabecera.

### 4. Manejo de errores del lector sin prueba directa a nivel de motor

`load_fits`/`load_image` ya lanzaban excepciones reales y claras para
un archivo corrupto (`OSError` de astropy: *"this file does not appear
to be a valid FITS file"*) o inexistente (`FileNotFoundError`) --
verificado manualmente antes de escribir el test. Pero solo había
prueba GUI de que ALGO se capturaba (`except Exception` genérico); no
había prueba a nivel de motor de que el error es real y específico, no
un `except` demasiado amplio escondiendo un fallo distinto. Dos tests
nuevos lo dejan explícito.

## Validación con datos reales

`tests/regression/test_fits_reader_matches_legacy.py` con
`ASTROPHYSICS_REAL_FITS_DIR` apuntando a una copia local de los tres
archivos reales del usuario (`Light_M31_300s_0001.fit`,
`dbxtract_HA_registered.fit`, `dbxtract_OIII.fit`, ~18-27 MB cada uno,
ASI533MC Pro real): **10/10 passed**, incluidos los 3 que solo corren
con archivos reales -- el lector nuevo coincide byte a byte con el
legacy sobre los datos reales del usuario, no solo sobre sintéticos.

## Qué queda fuera, documentado (no bloquea el cierre)

- **Sin escritor XISF** (ya documentado en el informe 51): el programa
  lee XISF nativo pero escribe siempre FITS. Motor nuevo, no un cable
  suelto -- fuera de alcance de esta fase (no se construye nada nuevo).
- **`load_fits(..., allow_first_plane=True)`** ("vista rápida": toma el
  primer plano de un cubo sin preguntar, marcando `cube_plane_is_
  explicit=False`) es una capacidad real, documentada, y verificada en
  la prueba de regresión contra legacy -- pero ningún camino de
  producción la usa hoy; la GUI siempre pide el plano explícito vía
  `CubePlaneDialog`. No es un backend roto ni a medias: es una opción
  del motor sin consumidor todavía. No se le construye un consumidor
  en esta fase (sería funcionalidad nueva); queda anotado por si algún
  motor futuro (p. ej. una miniatura rápida de un cubo) la necesita.

## Checklist de cierre (20 puntos)

| Punto | Estado |
|---|---|
| Implementación científica real | Sí -- lector/escritor FITS y XISF propios, sin legacy |
| Entrada definida | Sí -- ruta de archivo (FITS/XISF), plano opcional para cubos |
| Salida definida | Sí -- `LoadedImage`/`FitsImage`/`ImageRef`/`Observation` |
| Tipos coherentes | Sí -- dataclasses tipadas en todo el flujo |
| Unidades correctas | Sí -- `pixel_scale_arcsec`, sin conversión que aplique aquí |
| Incertidumbres cuando correspondan | N/A en carga (no mide); `save_fits_image` preserva la que le pasan |
| Manejo explícito de datos faltantes | Sí -- WCS/escala ausentes nunca inventados (`None`/`has_wcs=False`) |
| NOT_AVAILABLE cuando proceda | Sí -- mismo criterio que la fila anterior |
| Provenance | Sí -- `ImageRef.sha256`/`path` en cada imagen cargada |
| Errores correctamente gestionados | Sí -- excepciones reales y específicas, verificadas con test directo (hallazgo 4) |
| Funciona independientemente | Sí -- sin GUI, ver `tests/unit/io/` |
| Conectado al motor anterior | N/A (primer motor) |
| Conectado al siguiente | Sí -- `LoadedImage` alimenta Reduction/Astrometry/Detection directamente |
| GUI funcional | Sí -- abrir FITS/XISF, cubo 3D/4D con selector de plano, error visible |
| Guardado de resultados correcto | Sí -- `save_fits_image` (BZERO/BSCALE nunca arrastrados, incertidumbre real) |
| Rutas de salida controladas por el usuario | Sí -- `QFileDialog` nativo en cada guardado |
| Tests unitarios | Sí -- 41 (39 + 2 nuevos) en `tests/unit/io/` |
| Tests de integración | Sí -- consumido end-to-end por Discovery/Reducción/Astrometría (motores posteriores) |
| Test de regresión | Sí -- 10/10 contra legacy, byte a byte |
| Validación con datos reales/controlados | Sí -- 3 archivos reales del usuario, ver arriba |
| Documentación actualizada | Sí -- `__init__.py` corregido (hallazgo 1) |
| Ningún placeholder presentado como funcionalidad | Sí -- confirmado, sin excepciones |

## Validación de la suite completa

- `ruff check astrophysics_suite qt_app tests`: limpio.
- Unitaria + integración + regresión (con `ASTROPHYSICS_REAL_FITS_DIR`):
  **1695 passed** (antes: 1690), **21 skipped** (antes: 24 -- los 3 que
  ahora sí corrieron), 1 xfailed.
- Humo GUI completa: **209 passed** (antes: 208).

## CHECKPOINT

```
MOTOR: IO/FITS
ESTADO: CERRADO
IMPLEMENTACIÓN: astrophysics_suite/io/{fits_reader,fits_loader,fits_writer,fits_header_reader,xisf_reader,session_export}.py
ENTRADA: ruta de archivo (FITS/XISF real), plano opcional para cubos
SALIDA: LoadedImage / FitsImage / ImageRef / Observation
GUI: sí (qt_app/main_window.py::open_fits*, qt_app/io/cube_plane_dialog.py)
PROVENANCE: sí (ImageRef.sha256/path)
TESTS: 41 unitarios + 10 regresión + 4 humo GUI relevantes = 55
TESTS PASADOS: 55 (1695 unit/integración/regresión + 209 humo GUI en conjunto, sin fallos)
TESTS FALLIDOS: 0
VALIDACIÓN REAL: sí (3 archivos reales del usuario, byte a byte contra legacy)
PROBLEMAS RESTANTES: ninguno bloqueante. Documentados y fuera de alcance: sin escritor XISF; allow_first_plane sin consumidor de producción.
CONTRATO HACIA EL SIGUIENTE MOTOR (Reduction): LoadedImage.legacy_image (FitsImage: .data ndarray, .header dict, .wcs, .pixel_scale_arcsec) + ImageRef (.path, .sha256, .band, .role, .has_wcs) -- exactamente lo que reduction/session_pipeline.py ya consume hoy.
```

## Cambio de motor

IO/FITS re-auditado y cerrado bajo el checklist de 20 puntos. Siguiente
en el orden fijo del usuario: **Reduction**.
