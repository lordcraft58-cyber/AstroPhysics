"""`Project`: contenedor persistente de un proyecto científico -- qué
observaciones y candidatos pertenecen a él. El almacenamiento real
(equivalente a `DiscoveryStore` en el código heredado, ver
docs/audit/01-AUDITORIA-TECNICA-FASE1.md, seccion 2.2) es trabajo de la
Fase 6/7; este modelo es el índice serializable que ese almacenamiento
persiste.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Project:
    schema_version: int
    project_id: str
    name: str
    created_at: datetime
    observation_ids: tuple[str, ...] = ()
    candidate_ids: tuple[str, ...] = ()
    notes: str = ""

    @classmethod
    def create(cls, *, project_id: str, name: str, created_at: datetime, notes: str = "") -> "Project":
        return cls(schema_version=SCHEMA_VERSION, project_id=project_id, name=name, created_at=created_at, notes=notes)

    def with_observation(self, observation_id: str) -> "Project":
        if observation_id in self.observation_ids:
            return self
        return replace(self, observation_ids=self.observation_ids + (observation_id,))

    def with_candidate(self, candidate_id: str) -> "Project":
        if candidate_id in self.candidate_ids:
            return self
        return replace(self, candidate_ids=self.candidate_ids + (candidate_id,))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "name": self.name,
            "created_at": self.created_at.isoformat(),
            "observation_ids": list(self.observation_ids),
            "candidate_ids": list(self.candidate_ids),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Project":
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            project_id=data["project_id"],
            name=data["name"],
            created_at=datetime.fromisoformat(data["created_at"]),
            observation_ids=tuple(data.get("observation_ids", ())),
            candidate_ids=tuple(data.get("candidate_ids", ())),
            notes=data.get("notes", ""),
        )
