"""Caché local de catálogos en disco -- descarga una vez, consulta
siempre en local.

Motivación real (dos problemas distintos, el mismo remedio):

1. **Sin red no hay identificación.** Si Gaia no responde (sin internet,
   servicio caído, cortafuegos), Discovery no puede comprobar ninguna
   detección y todas quedan honestamente en `DISCOVERY_REVIEW` (ver
   `catalogs/gaia.py`). Con una descarga previa del campo, el análisis
   funciona igual sin red.
2. **Una consulta de red POR DETECCIÓN es insostenible.** El pipeline
   llama a `identify_detection` una vez por fuente: en los lights reales
   de M 31 del usuario, tras corregir el demosaico, eso son **1320
   consultas** a Gaia en un solo análisis. Aunque haya internet, es
   lentísimo y abusa del servicio público. Una descarga cónica del campo
   entero (una sola consulta) sirve las 1320 desde disco.

## Dónde vive (ruta conocida, no oculta)

`~/.astrophysics_suite/catalogs/<catálogo>.sqlite3` -- la misma carpeta
de configuración que ya usan `app_preferences.py` e
`instrument_profiles.py`. En Windows eso es
`C:\\Users\\<usuario>\\.astrophysics_suite\\catalogs\\`. Se puede pasar
otra ruta explícita al construir `CatalogCache`. SQLite es de la
biblioteca estándar: sin dependencias nuevas, con índice real y
resistente a un corte a mitad de escritura.

## La parte importante: "vacío" no significa lo mismo que "no descargado"

`query_cached_neighbors` devuelve `(filas, cobertura)`. `cobertura` dice
si esa posición cae DENTRO de alguna región ya descargada. Sin ese dato,
una lista vacía sería ambigua exactamente igual que el bug real que se
corrigió en `catalogs/gaia.py`: no es lo mismo "descargué este campo y
ahí no hay ninguna estrella catalogada" que "nunca descargué este
campo". El primero es un resultado científico; el segundo, una pregunta
sin responder.
"""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_CACHE_DIR = Path.home() / ".astrophysics_suite" / "catalogs"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS regions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    catalog TEXT NOT NULL,
    ra_deg REAL NOT NULL,
    dec_deg REAL NOT NULL,
    radius_arcsec REAL NOT NULL,
    mag_limit REAL NOT NULL,
    downloaded_at TEXT NOT NULL,
    n_sources INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    region_id INTEGER NOT NULL REFERENCES regions(id) ON DELETE CASCADE,
    source_id TEXT,
    ra_deg REAL NOT NULL,
    dec_deg REAL NOT NULL,
    mag_g REAL
);
CREATE INDEX IF NOT EXISTS idx_sources_dec ON sources (dec_deg);
CREATE INDEX IF NOT EXISTS idx_sources_ra ON sources (ra_deg);
"""


@dataclass(frozen=True)
class CachedRegion:
    """Una descarga real ya guardada en disco."""

    catalog: str
    ra_deg: float
    dec_deg: float
    radius_arcsec: float
    mag_limit: float
    downloaded_at: str
    n_sources: int


def _angular_separation_deg(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    delta_ra = r2 - r1
    numerator = math.hypot(
        math.cos(d2) * math.sin(delta_ra),
        math.cos(d1) * math.sin(d2) - math.sin(d1) * math.cos(d2) * math.cos(delta_ra),
    )
    denominator = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(delta_ra)
    return math.degrees(math.atan2(numerator, denominator))


class CatalogCache:
    """Catálogo descargado a disco, consultable sin red."""

    def __init__(self, catalog: str = "gaia", *, path: Path | None = None):
        self.catalog = catalog
        self.path = Path(path) if path is not None else DEFAULT_CACHE_DIR / f"{catalog}.sqlite3"

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.executescript(_SCHEMA)
        return connection

    def store_region(
        self, ra_deg: float, dec_deg: float, radius_arcsec: float, *, mag_limit: float, rows: list[dict],
    ) -> int:
        """Guarda una descarga real. Devuelve el número de fuentes
        guardadas. Una región vacía TAMBIÉN se guarda: "descargué este
        campo y no hay nada catalogado" es un resultado real que hay que
        poder distinguir de "nunca lo descargué"."""
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO regions (catalog, ra_deg, dec_deg, radius_arcsec, mag_limit, downloaded_at, n_sources) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (self.catalog, float(ra_deg), float(dec_deg), float(radius_arcsec), float(mag_limit), timestamp, len(rows)),
            )
            region_id = cursor.lastrowid
            connection.executemany(
                "INSERT INTO sources (region_id, source_id, ra_deg, dec_deg, mag_g) VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        region_id,
                        str(row.get("source_id", "")),
                        float(row["ra_deg"]),
                        float(row["dec_deg"]),
                        float(row["mag_g"]) if row.get("mag_g") is not None else None,
                    )
                    for row in rows
                ],
            )
        return len(rows)

    def regions(self) -> list[CachedRegion]:
        """Todo lo que ya está descargado -- para que la GUI pueda
        enseñarlo y el usuario sepa exactamente qué cubre su caché."""
        with self._connect() as connection:
            cursor = connection.execute(
                "SELECT catalog, ra_deg, dec_deg, radius_arcsec, mag_limit, downloaded_at, n_sources "
                "FROM regions WHERE catalog = ? ORDER BY downloaded_at DESC",
                (self.catalog,),
            )
            return [CachedRegion(*row) for row in cursor.fetchall()]

    def covers(self, ra_deg: float, dec_deg: float, *, margin_arcsec: float = 0.0) -> bool:
        """`True` si esa posición cae dentro de alguna región descargada
        (con `margin_arcsec` de holgura hacia adentro, para no servir
        resultados incompletos justo en el borde de lo descargado)."""
        for region in self.regions():
            separation_arcsec = _angular_separation_deg(ra_deg, dec_deg, region.ra_deg, region.dec_deg) * 3600.0
            if separation_arcsec <= max(0.0, region.radius_arcsec - margin_arcsec):
                return True
        return False

    def query_neighbors(
        self, ra_deg: float, dec_deg: float, *, radius_arcsec: float = 3.0, mag_limit: float = 99.0, max_rows: int = 25,
    ) -> tuple[list[dict], bool]:
        """`(filas, cubierto)` -- las fuentes locales dentro del radio, y
        si esa posición está realmente cubierta por una descarga previa.

        `cubierto=False` con lista vacía significa "no lo sé, nunca se
        descargó este campo", NUNCA "no hay nada ahí" -- quien llama debe
        tratarlo como una pregunta sin responder (ver el docstring del
        módulo)."""
        covered = self.covers(ra_deg, dec_deg, margin_arcsec=radius_arcsec)
        if not covered:
            return [], False

        radius_deg = radius_arcsec / 3600.0
        # Prefiltro rectangular por índice (barato), luego distancia angular real.
        dec_margin = radius_deg
        cos_dec = max(math.cos(math.radians(dec_deg)), 1e-6)
        ra_margin = radius_deg / cos_dec
        with self._connect() as connection:
            cursor = connection.execute(
                "SELECT s.source_id, s.ra_deg, s.dec_deg, s.mag_g FROM sources s "
                "JOIN regions r ON r.id = s.region_id "
                "WHERE r.catalog = ? AND s.dec_deg BETWEEN ? AND ? AND s.ra_deg BETWEEN ? AND ? "
                "AND (s.mag_g IS NULL OR s.mag_g <= ?)",
                (self.catalog, dec_deg - dec_margin, dec_deg + dec_margin, ra_deg - ra_margin, ra_deg + ra_margin, float(mag_limit)),
            )
            candidates = cursor.fetchall()

        rows: list[tuple[float, dict]] = []
        for source_id, row_ra, row_dec, mag_g in candidates:
            separation_arcsec = _angular_separation_deg(ra_deg, dec_deg, row_ra, row_dec) * 3600.0
            if separation_arcsec <= radius_arcsec:
                rows.append((separation_arcsec, {"source_id": source_id, "ra_deg": row_ra, "dec_deg": row_dec, "mag_g": mag_g}))
        rows.sort(key=lambda item: item[0])
        return [row for _, row in rows[:max_rows]], True

    def all_rows(self, *, mag_limit: float = 99.0, max_rows: int = 20_000) -> list[dict]:
        """TODAS las fuentes descargadas de este catálogo, sin importar
        la posición -- lo que necesita el resolutor CIEGO de placas
        (`astrometry/blind_solve.py`): sin un puntero aproximado no hay
        radio que buscar, así que en vez de una vecindad usa lo que ya
        haya en disco, de donde sea. Ordenadas de más a menos brillante
        (las estrellas sin magnitud, al final -- una magnitud desconocida
        no es "muy tenue") para que quien limite con `max_rows` se quede
        con las más útiles para formar asterismos reconocibles.

        Deduplicada por `source_id` cuando lo hay (dos regiones
        descargadas pueden solaparse y repetir la misma fuente real) --
        sin él, por posición redondeada a 4 decimales de grado (~0.4
        arcsec), suficiente para no contar dos veces la misma fila
        exacta sin fundir fuentes reales distintas y próximas."""
        with self._connect() as connection:
            cursor = connection.execute(
                "SELECT s.source_id, s.ra_deg, s.dec_deg, s.mag_g FROM sources s "
                "JOIN regions r ON r.id = s.region_id "
                "WHERE r.catalog = ? AND (s.mag_g IS NULL OR s.mag_g <= ?) "
                "ORDER BY (s.mag_g IS NULL), s.mag_g ASC",
                (self.catalog, float(mag_limit)),
            )
            rows = cursor.fetchall()

        seen: set[str] = set()
        result: list[dict] = []
        for source_id, ra_deg, dec_deg, mag_g in rows:
            key = str(source_id) if source_id else f"{ra_deg:.4f},{dec_deg:.4f}"
            if key in seen:
                continue
            seen.add(key)
            result.append({"source_id": source_id, "ra_deg": ra_deg, "dec_deg": dec_deg, "mag_g": mag_g})
            if len(result) >= max_rows:
                break
        return result

    def clear(self) -> None:
        """Borra todo lo descargado de ESTE catálogo -- la GUI lo ofrece
        explícitamente; nunca se limpia solo."""
        with self._connect() as connection:
            connection.execute("DELETE FROM sources WHERE region_id IN (SELECT id FROM regions WHERE catalog = ?)", (self.catalog,))
            connection.execute("DELETE FROM regions WHERE catalog = ?", (self.catalog,))

    def describe(self) -> str:
        """Resumen legible del estado real de la caché, para la GUI."""
        regions = self.regions()
        if not regions:
            return f"Sin datos descargados de {self.catalog} en {self.path}."
        total_sources = sum(region.n_sources for region in regions)
        return (
            f"{len(regions)} región(es) descargada(s) de {self.catalog}, {total_sources} fuentes en total, en "
            f"{self.path} (la más reciente: {regions[0].downloaded_at})."
        )


def download_field_to_cache(
    ra_deg: float, dec_deg: float, radius_arcsec: float, *,
    mag_limit: float = 20.0, max_rows: int = 50_000, cache: CatalogCache | None = None,
) -> tuple[bool, str]:
    """Descarga UNA vez el campo entero desde Gaia y lo guarda en disco.
    Devuelve `(ok, detalle)` -- nunca lanza ni deja la caché a medias:
    si la consulta real falla, no se guarda ninguna región (así
    `covers()` sigue diciendo honestamente que ese campo no está
    cubierto, en vez de fingir una descarga vacía)."""
    from astrophysics_suite.catalogs.gaia import last_gaia_availability, query_gaia_neighbors

    store = cache or CatalogCache("gaia")
    rows = query_gaia_neighbors(ra_deg, dec_deg, radius_arcsec=radius_arcsec, mag_limit=mag_limit, max_rows=max_rows)
    available, detail = last_gaia_availability()
    if not available:
        return False, (
            f"No se pudo descargar el campo: Gaia no respondió ({detail}). No se ha guardado nada -- la caché sigue "
            f"sin cubrir esta zona, que es la verdad."
        )
    n_stored = store.store_region(ra_deg, dec_deg, radius_arcsec, mag_limit=mag_limit, rows=rows)
    return True, (
        f"Descargadas y guardadas {n_stored} fuentes de Gaia en un radio de {radius_arcsec / 60.0:.1f}' alrededor de "
        f"RA={ra_deg:.5f} Dec={dec_deg:.5f} (hasta magnitud G {mag_limit}). Ruta: {store.path}"
    )
