"""Calibraciones espectrales de instrumento persistentes (§12): una
solución longitud de onda ya validada para una configuración concreta
(cámara + red de difracción/prisma + orden), reutilizable en sesiones
futuras sin repetir la identificación de líneas -- con la opción
explícita de recalcular SOLO el desplazamiento global (A0) por
correlación cruzada contra el espectro de lámpara guardado, en vez de
un reajuste completo sin nueva evidencia real.

Mismo patrón que `instrument_profiles.py` (Fase 10.2): JSON bajo el
directorio de configuración del usuario, en la capa de servicios porque
tocar disco es responsabilidad suya, no del motor científico.

AVISO explícito del propio encargo (§12, verbatim): *"indicar
claramente que un cambio temporal/mecánico del instrumento puede
desplazar el espectro"* -- por eso toda solución reutilizada de aquí
sale marcada `CalibrationSource.REUSED_INSTRUMENTAL`, nunca como si
fuera una calibración recién medida sobre esta observación.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from astrophysics_suite.spectroscopy.calibration_provenance import CalibrationSource, WavelengthCalibrationRecord
from astrophysics_suite.spectroscopy.wavelength import WavelengthSolution, reidentify_wavelength_solution

DEFAULT_SPECTRAL_PROFILE_STORE_PATH = Path.home() / ".astrophysics_suite" / "spectral_calibration_profiles.json"


@dataclass(frozen=True)
class SpectralCalibrationProfile:
    """Una solución de calibración guardada bajo un nombre de
    configuración de instrumento (p. ej. `"LHIRES III -- red 2400 l/mm"`)."""

    name: str
    coefficients: tuple[float, ...]
    degree: int
    rms_residual: float
    reference_pixel_shift: float
    n_lines_used: int
    n_lines_rejected: int = 0
    lamp_name: str | None = None
    reference_spectrum: tuple[float, ...] | None = None
    """Espectro 1D de la lámpara usado para el ajuste original -- se
    conserva para poder recalcular SOLO el desplazamiento global (§12)
    por correlación cruzada contra una nueva exposición de la misma
    lámpara, sin volver a identificar cada línea a mano. `None` si el
    perfil se guardó sin ese espectro: en ese caso `reidentify_profile_
    offset` no está disponible para este perfil, hace falta una
    calibración completa nueva."""
    saved_at_utc: str = ""

    def to_solution(self) -> WavelengthSolution:
        return WavelengthSolution(
            coefficients=np.array(self.coefficients, dtype=np.float64),
            degree=self.degree,
            rms_residual=self.rms_residual,
            residuals=np.zeros(0),
            reference_pixel_shift=self.reference_pixel_shift,
        )

    def to_record(self) -> WavelengthCalibrationRecord:
        """La solución guardada, lista para usar -- SIN recalcular nada,
        tal cual se validó la última vez. Marcada `REUSED_INSTRUMENTAL`:
        nunca se presenta como si acabara de medirse en esta sesión."""
        return WavelengthCalibrationRecord(
            solution=self.to_solution(),
            source=CalibrationSource.REUSED_INSTRUMENTAL,
            n_lines_used=self.n_lines_used,
            n_lines_rejected=self.n_lines_rejected,
            lamp_name=self.lamp_name,
        )


def profile_from_record(
    name: str, record: WavelengthCalibrationRecord, *, reference_spectrum: np.ndarray | None = None
) -> SpectralCalibrationProfile:
    """Empaqueta una calibración ya validada para guardarla como perfil
    reutilizable. Rechaza guardar una calibración `SYNTHETIC` como
    perfil instrumental: presentar una calibración de prueba como si
    fuera una solución instrumental validada sería exactamente el tipo
    de afirmación falsa que prohíbe el encargo -- para perfiles de
    prueba, construir `SpectralCalibrationProfile` directamente."""
    if record.is_synthetic:
        raise ValueError(
            "no se puede guardar una calibración SYNTHETIC como perfil de instrumento reutilizable "
            "-- un perfil implica una solución validada sobre una lámpara real"
        )
    solution = record.solution
    return SpectralCalibrationProfile(
        name=name,
        coefficients=tuple(float(c) for c in solution.coefficients),
        degree=solution.degree,
        rms_residual=solution.rms_residual,
        reference_pixel_shift=solution.reference_pixel_shift,
        n_lines_used=record.n_lines_used,
        n_lines_rejected=record.n_lines_rejected,
        lamp_name=record.lamp_name,
        reference_spectrum=tuple(float(v) for v in np.asarray(reference_spectrum))
        if reference_spectrum is not None
        else None,
        saved_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def reidentify_profile_offset(
    profile: SpectralCalibrationProfile, new_lamp_spectrum: np.ndarray, *, max_shift_px: int = 50
) -> WavelengthCalibrationRecord:
    """Recalcula ÚNICAMENTE el desplazamiento global A0 (§12) por
    correlación cruzada contra el espectro de lámpara guardado en el
    perfil -- nunca un reajuste completo de la forma del polinomio sin
    nueva evidencia de líneas. Requiere que el perfil se guardara con su
    `reference_spectrum`; si no, hace falta una calibración completa
    nueva (no hay con qué correlacionar)."""
    if profile.reference_spectrum is None:
        raise ValueError(
            f"el perfil {profile.name!r} no guardó su espectro de lámpara de referencia -- "
            "no se puede recalcular el desplazamiento por correlación cruzada; hace falta "
            "una calibración completa nueva con líneas identificadas"
        )
    reference_spectrum = np.array(profile.reference_spectrum, dtype=np.float64)
    new_spectrum = np.asarray(new_lamp_spectrum, dtype=np.float64)
    if reference_spectrum.shape != new_spectrum.shape:
        raise ValueError(
            f"el espectro de lámpara nuevo tiene {new_spectrum.shape[0]} píxeles, pero el perfil "
            f"{profile.name!r} se guardó con {reference_spectrum.shape[0]} -- no son la misma "
            "configuración de instrumento (o el recorte/binning cambió)"
        )
    shifted_solution = reidentify_wavelength_solution(
        profile.to_solution(), reference_spectrum, new_spectrum, max_shift_px=max_shift_px
    )
    return WavelengthCalibrationRecord(
        solution=shifted_solution,
        source=CalibrationSource.REUSED_INSTRUMENTAL,
        n_lines_used=profile.n_lines_used,
        n_lines_rejected=profile.n_lines_rejected,
        lamp_name=profile.lamp_name,
        offset_only_reidentified=True,
    )


class SpectralCalibrationProfileStore:
    def __init__(self, path: Path | None = None):
        self._path = path or DEFAULT_SPECTRAL_PROFILE_STORE_PATH

    def load_all(self) -> dict[str, SpectralCalibrationProfile]:
        if not self._path.exists():
            return {}
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        profiles: dict[str, SpectralCalibrationProfile] = {}
        for name, entry in raw.items():
            reference_spectrum = entry.get("reference_spectrum")
            profiles[name] = SpectralCalibrationProfile(
                name=name,
                coefficients=tuple(entry["coefficients"]),
                degree=int(entry["degree"]),
                rms_residual=float(entry["rms_residual"]),
                reference_pixel_shift=float(entry.get("reference_pixel_shift", 0.0)),
                n_lines_used=int(entry["n_lines_used"]),
                n_lines_rejected=int(entry.get("n_lines_rejected", 0)),
                lamp_name=entry.get("lamp_name"),
                reference_spectrum=tuple(reference_spectrum) if reference_spectrum is not None else None,
                saved_at_utc=entry.get("saved_at_utc", ""),
            )
        return profiles

    def save(self, profile: SpectralCalibrationProfile) -> None:
        profiles = self.load_all()
        profiles[profile.name] = profile
        self._write(profiles)

    def delete(self, name: str) -> None:
        profiles = self.load_all()
        if name in profiles:
            del profiles[name]
            self._write(profiles)

    def _write(self, profiles: dict[str, SpectralCalibrationProfile]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {
            name: {
                "coefficients": list(p.coefficients),
                "degree": p.degree,
                "rms_residual": p.rms_residual,
                "reference_pixel_shift": p.reference_pixel_shift,
                "n_lines_used": p.n_lines_used,
                "n_lines_rejected": p.n_lines_rejected,
                "lamp_name": p.lamp_name,
                "reference_spectrum": list(p.reference_spectrum) if p.reference_spectrum is not None else None,
                "saved_at_utc": p.saved_at_utc,
            }
            for name, p in profiles.items()
        }
        self._path.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8")
