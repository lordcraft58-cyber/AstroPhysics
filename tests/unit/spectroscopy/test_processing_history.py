"""`processing_history.py` (§36/§39): historial de procesamiento real en
JSON, siempre por APPEND -- nunca pierde entradas anteriores al guardar
de nuevo."""
from __future__ import annotations

from astrophysics_suite.spectroscopy.processing_history import (
    ProcessingHistoryEntry,
    append_processing_history,
    load_processing_history,
)


def test_load_processing_history_is_empty_without_a_real_file(tmp_path):
    assert load_processing_history(tmp_path / "nothing.history.json") == ()


def test_append_processing_history_writes_and_reads_back_real_entries(tmp_path):
    path = tmp_path / "spectrum.fits.history.json"
    entry = ProcessingHistoryEntry(timestamp_utc="2026-01-01T00:00:00+00:00", process_name="Extracción de traza", summary="Traza extraída (óptima)")
    append_processing_history(path, (entry,))
    loaded = load_processing_history(path)
    assert loaded == (entry,)


def test_append_processing_history_accumulates_across_calls(tmp_path):
    path = tmp_path / "spectrum.fits.history.json"
    first = ProcessingHistoryEntry(timestamp_utc="2026-01-01T00:00:00+00:00", process_name="Extracción de traza", summary="primera pasada")
    append_processing_history(path, (first,))

    second = ProcessingHistoryEntry(timestamp_utc="2026-01-01T00:05:00+00:00", process_name="Calibrar por estrella de referencia", summary="segunda pasada")
    append_processing_history(path, (second,))

    assert load_processing_history(path) == (first, second)


def test_append_processing_history_is_idempotent_when_passed_the_full_growing_list_again(tmp_path):
    # `main_window` guarda en la vista el historial COMPLETO en memoria y
    # lo vuelve a pasar entero en cada guardado del mismo producto -- sin
    # deduplicar, la segunda llamada duplicaría las entradas ya escritas.
    path = tmp_path / "spectrum.fits.history.json"
    first = ProcessingHistoryEntry(timestamp_utc="2026-01-01T00:00:00+00:00", process_name="Extracción de traza", summary="primera pasada")
    append_processing_history(path, (first,))

    second = ProcessingHistoryEntry(timestamp_utc="2026-01-01T00:05:00+00:00", process_name="Guardar espectro calibrado (FITS)", summary="guardado")
    append_processing_history(path, (first, second))  # la lista completa en memoria, incluida `first` otra vez

    assert load_processing_history(path) == (first, second)


def test_append_processing_history_creates_missing_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "spectrum.fits.history.json"
    entry = ProcessingHistoryEntry(timestamp_utc="2026-01-01T00:00:00+00:00", process_name="Informe de calidad", summary="OK")
    append_processing_history(path, (entry,))
    assert path.exists()
    assert load_processing_history(path) == (entry,)
