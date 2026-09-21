"""Lectura/escritura de imágenes (FITS y XISF nativo) y construcción de
`Observation`/`ImageRef` (Fase 4).

La lectura de FITS vive en `fits_reader.py` -- reimplementación propia,
sin ninguna dependencia del monolito legacy, verificada campo a campo y
píxel a píxel contra él (`tests/regression/test_fits_reader_matches_
legacy.py`, ver docs/audit/51-CIERRE-IO-FITS-AL-100.md). Este docstring
describía un estado anterior (Fase 6, slice 1) en el que `fits_loader.py`
sí delegaba en `legacy...load_fits` -- ya no es cierto, corregido para
no confundir a quien lea este paquete primero.
"""
