"""Historial de procesamiento en JSON (§36) + trazabilidad de cadena
completa (§39): un registro real, con marca de tiempo, de CADA proceso
que se aplicó sobre una imagen/espectro concreto -- no solo el último
paso, sino la cadena entera (traza, extracción, calibración,
identificación...), tal como la fue ejecutando el usuario (a mano o vía
"Autoprocesar espectro", §34).

Guardado como un archivo `.history.json` junto al producto final
(`spectrum1d_io.processing_history_path_for_product`) -- APPEND, nunca
sobrescritura: `append_processing_history` lee lo que ya hubiera en ese
archivo y añade las entradas nuevas al final, así que guardar el mismo
producto varias veces (p. ej. tras corregir un parámetro y repetir un
paso) acumula la cadena real completa en vez de perder las entradas
anteriores -- exactamente lo que pide §39 ("nunca sobrescribir en
silencio")."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessingHistoryEntry:
    timestamp_utc: str
    """ISO 8601 real (`datetime.now(timezone.utc).isoformat()`) -- nunca
    un orden relativo ambiguo."""
    process_name: str
    """Nombre del proceso tal como aparece en el explorador (p. ej.
    'Extracción de traza' o 'Autoprocesar espectro (§34)')."""
    summary: str
    """El mismo `ProcessResult.summary` real que ya se mostró en el
    registro de operaciones al ejecutarlo -- nunca un texto distinto
    inventado para el historial."""


def load_processing_history(path: str | Path) -> tuple[ProcessingHistoryEntry, ...]:
    """Lee el historial real ya guardado en `path`, o una tupla vacía si
    el archivo todavía no existe -- nunca inventa entradas."""
    path = Path(path)
    if not path.exists():
        return ()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return tuple(ProcessingHistoryEntry(**item) for item in raw)


def append_processing_history(path: str | Path, entries: tuple[ProcessingHistoryEntry, ...]) -> None:
    """Añade `entries` al historial real ya guardado en `path` (si lo
    hay) y reescribe el archivo completo -- nunca descarta las entradas
    anteriores (§39: nunca sobrescribir en silencio la trazabilidad ya
    registrada).

    Idempotente frente a una entrada YA presente (misma marca de tiempo,
    proceso y resumen exactos): el llamador real de este módulo
    (`main_window`) guarda en cada vista el historial COMPLETO en
    memoria y lo vuelve a pasar entero en cada guardado -- sin
    deduplicar, cada nuevo guardado del mismo producto duplicaría todas
    las entradas ya escritas. El orden de aparición se conserva."""
    path = Path(path)
    combined = load_processing_history(path) + tuple(entries)
    deduped = tuple(dict.fromkeys(combined))
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(entry) for entry in deduped]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
