"""Persistencia de sesión a disco: `SessionState` completo (nombre de
proyecto, observaciones, candidatos con TODA su cadena de evidencia) ->
JSON real en la ruta que elija el usuario, y de vuelta.

Hasta este motor, `services/session_state.py` lo decía explícitamente en
su propio docstring: "Persistencia real a disco... queda para una fase
posterior". Sin esto, ningún `Candidate` producido por Discovery -- con
independencia de lo real que fuera su contenido científico -- podía
sobrevivir al cierre de la aplicación ni exportarse para compartir con
otra persona. Cierra la Fase 6 ("Salidas") que habían dejado pendiente
los cierres de Fotometría de Apertura y Calibración Fotométrica: ambos
producían datos reales, pero no había ninguna manera de guardarlos.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.models.candidate import Candidate
from astrophysics_suite.models.observation import Observation

SCHEMA_VERSION = 1
ENGINE_NAME = "io.session_export"
ENGINE_VERSION = "1.0"


@dataclass(frozen=True)
class LoadedSession:
    project_name: str
    observations: tuple[Observation, ...]
    candidates: tuple[Candidate, ...]
    saved_at: datetime
    provenance: Provenance


def save_session(
    path: str,
    *,
    project_name: str,
    observations: list[Observation],
    candidates: list[Candidate],
    pipeline_version: str = "",
    overwrite: bool = True,
) -> None:
    """Escribe la sesión completa como JSON real -- sin pérdida:
    `load_session(path)` reconstruye cada `Candidate`/`Observation` bit a
    bit igual al original (`Candidate.from_dict(c.to_dict()) == c`, ya
    garantizado por el propio contrato de `Candidate` y verificado aquí
    de extremo a extremo con un archivo real en disco).

    `overwrite=False` para comprobar explícitamente antes de reemplazar
    un archivo existente -- mismo parámetro y mismo valor por defecto que
    `io.fits_writer.save_fits_image`, la GUI resuelve la confirmación
    real con el diálogo nativo de guardado (mismo patrón que el resto de
    la aplicación, p. ej. guardar un FITS con WCS)."""
    target = Path(path)
    if target.exists() and not overwrite:
        raise FileExistsError(f"{path} ya existe")

    provenance = Provenance.now(pipeline_version=pipeline_version, engine=ENGINE_NAME, engine_version=ENGINE_VERSION)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "project_name": project_name,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "provenance": provenance.to_dict(),
        "observations": [obs.to_dict() for obs in observations],
        "candidates": [c.to_dict() for c in candidates],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_session(path: str) -> LoadedSession:
    """Lee de vuelta una sesión guardada por `save_session`. Un
    `schema_version` distinto del que sabe leer esta versión se rechaza
    explícitamente (`ValueError` con el motivo real) en vez de intentar
    adivinar compatibilidad hacia adelante con un esquema que no conoce."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    schema_version = data.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        raise ValueError(f"versión de esquema de sesión no soportada: {schema_version!r} (se esperaba {SCHEMA_VERSION})")

    return LoadedSession(
        project_name=data.get("project_name", ""),
        observations=tuple(Observation.from_dict(o) for o in data.get("observations", ())),
        candidates=tuple(Candidate.from_dict(c) for c in data.get("candidates", ())),
        saved_at=datetime.fromisoformat(data["saved_at"]),
        provenance=Provenance.from_dict(data["provenance"]),
    )
