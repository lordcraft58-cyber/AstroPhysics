"""Perfiles de instrumento persistentes -- ganancia, ruido de lectura y
geometría de overscan/recorte guardados por cámara, para que el usuario
no tenga que reintroducirlos a mano en cada sesión de reducción (hueco
señalado en `docs/audit/13-IRAF-CAPABILITY-MAP.md`, bloque `ccdred`).

Persistidos en un único archivo JSON bajo el directorio de configuración
del usuario -- no en `astrophysics_suite/`, porque tocar disco para leer
preferencias del usuario es responsabilidad de la capa de servicios, no
del motor científico.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

DEFAULT_PROFILE_STORE_PATH = Path.home() / ".astrophysics_suite" / "instrument_profiles.json"


@dataclass(frozen=True)
class InstrumentProfile:
    name: str
    gain_e_per_adu: float
    read_noise_e: float
    overscan_row_start: int | None = None
    overscan_row_end: int | None = None
    overscan_col_start: int | None = None
    overscan_col_end: int | None = None


class InstrumentProfileStore:
    def __init__(self, path: Path | None = None):
        self._path = path or DEFAULT_PROFILE_STORE_PATH

    def load_all(self) -> dict[str, InstrumentProfile]:
        if not self._path.exists():
            return {}
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        known_fields = {f.name for f in fields(InstrumentProfile)} - {"name"}
        return {
            name: InstrumentProfile(name=name, **{k: v for k, v in entry.items() if k in known_fields})
            for name, entry in raw.items()
        }

    def save(self, profile: InstrumentProfile) -> None:
        profiles = self.load_all()
        profiles[profile.name] = profile
        self._write(profiles)

    def delete(self, name: str) -> None:
        profiles = self.load_all()
        if name in profiles:
            del profiles[name]
            self._write(profiles)

    def _write(self, profiles: dict[str, InstrumentProfile]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {name: {k: v for k, v in asdict(profile).items() if k != "name"} for name, profile in profiles.items()}
        self._path.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8")
