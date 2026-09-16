"""Preferencias de aplicación de bajo riesgo (p. ej. la última carpeta
usada para guardar un producto) -- mismo patrón de persistencia que
`instrument_profiles.py` (un único JSON bajo el directorio de
configuración del usuario, sin base de datos): son datos de conveniencia
de la GUI, no resultado científico, así que viven en la capa de
servicios, no en `astrophysics_suite/`.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_PREFERENCES_STORE_PATH = Path.home() / ".astrophysics_suite" / "app_preferences.json"


class AppPreferencesStore:
    def __init__(self, path: Path | None = None):
        self._path = path or DEFAULT_PREFERENCES_STORE_PATH

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._load().get(key, default)

    def set(self, key: str, value: str) -> None:
        preferences = self._load()
        preferences[key] = value
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(preferences, indent=2, ensure_ascii=False), encoding="utf-8")
