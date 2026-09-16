"""`Provenance`: de dónde sale un resultado -- versión de pipeline, modelo,
grid y datos de entrada, con sus hashes.

Generaliza la idea de `RunManifest` ya presente en el código heredado
(docs/audit/01-AUDITORIA-TECNICA-FASE1.md, seccion 13.10: "manifiesto de
ejecución reproducible... base correcta para la procedencia que pide el
Candidate Engine") para que cualquier motor -- no solo el pipeline
OIII/Hα -- pueda adjuntar procedencia a sus resultados.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Provenance:
    pipeline_version: str
    engine: str
    engine_version: str
    produced_at: datetime
    input_hashes: tuple[tuple[str, str], ...] = ()
    """Pares (nombre_del_input, sha256) -- p. ej. (("oiii_image", "<sha256>"), ...)."""
    model_id: str = ""
    grid_sha256: str = ""
    parameters_sha256: str = ""
    warnings: tuple[str, ...] = ()

    @classmethod
    def now(
        cls,
        *,
        pipeline_version: str,
        engine: str,
        engine_version: str,
        input_hashes: tuple[tuple[str, str], ...] = (),
        model_id: str = "",
        grid_sha256: str = "",
        parameters_sha256: str = "",
        warnings: tuple[str, ...] = (),
    ) -> "Provenance":
        return cls(
            pipeline_version=pipeline_version,
            engine=engine,
            engine_version=engine_version,
            produced_at=datetime.now(timezone.utc),
            input_hashes=input_hashes,
            model_id=model_id,
            grid_sha256=grid_sha256,
            parameters_sha256=parameters_sha256,
            warnings=warnings,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline_version": self.pipeline_version,
            "engine": self.engine,
            "engine_version": self.engine_version,
            "produced_at": self.produced_at.isoformat(),
            "input_hashes": [list(pair) for pair in self.input_hashes],
            "model_id": self.model_id,
            "grid_sha256": self.grid_sha256,
            "parameters_sha256": self.parameters_sha256,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Provenance":
        return cls(
            pipeline_version=data["pipeline_version"],
            engine=data["engine"],
            engine_version=data["engine_version"],
            produced_at=datetime.fromisoformat(data["produced_at"]),
            input_hashes=tuple(tuple(pair) for pair in data.get("input_hashes", ())),
            model_id=data.get("model_id", ""),
            grid_sha256=data.get("grid_sha256", ""),
            parameters_sha256=data.get("parameters_sha256", ""),
            warnings=tuple(data.get("warnings", ()) or ()),
        )
