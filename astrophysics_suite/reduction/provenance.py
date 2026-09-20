"""Procedencia real de la reducción: qué se le hizo exactamente a cada
LIGHT, en forma de `Provenance` (Fase 4) y de tarjetas FITS escribibles
en el archivo calibrado.

`CalibrationSteps` (en `calibration.py`) dice desde su primera versión
que existe *"para que la procedencia pueda declarar exactamente qué
calibración recibió cada imagen, nunca de forma implícita"* -- pero esa
procedencia nunca llegó a construirse, y el FITS calibrado se escribía
con la cabecera CRUDA tal cual. Un archivo reducido era
indistinguible de uno sin reducir salvo por los valores de los píxeles.
Este módulo cierra ese hueco.

Nada se declara de oídas: cada tarjeta sale de lo que el pipeline
registró de verdad (`LightFrameReduction`), y un paso que no se aplicó
no aparece como aplicado ni como no aplicado inventado -- simplemente
se escribe su `False` real.
"""
from __future__ import annotations

from dataclasses import dataclass

from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.reduction.calibration import CalibrationSteps

ENGINE_NAME = "reduction.session_pipeline"
ENGINE_VERSION = "1.0"

_HISTORY_PREFIX = "AstroPhysics Suite:"


@dataclass(frozen=True)
class ReductionRecord:
    """Lo que de verdad se le hizo a un LIGHT concreto -- reúne en un
    solo sitio lo que hasta ahora estaba repartido entre
    `CalibrationSteps` y campos sueltos de `LightFrameReduction`."""

    steps: CalibrationSteps
    overscan_corrected: bool = False
    trimmed: bool = False
    illumination_corrected: bool = False
    fringe_removed: bool = False
    fringe_scale_factor: float | None = None
    sky_subtracted: bool = False
    sky_degree: int | None = None
    gain_e_per_adu: float | None = None
    read_noise_e: float | None = None

    def describe(self) -> tuple[str, ...]:
        """Lista legible de los pasos REALMENTE aplicados, en el orden
        físico en que se aplicaron. Vacía si no se aplicó ninguno (lo
        que también es una respuesta honesta)."""
        applied: list[str] = []
        if self.overscan_corrected:
            applied.append("overscan restado")
        if self.trimmed:
            applied.append("recorte aplicado")
        if self.steps.bias_subtracted:
            applied.append("bias maestro restado")
        if self.steps.dark_subtracted:
            factor = self.steps.dark_scale_factor
            applied.append(f"dark maestro restado (escala {factor:.4f})" if factor is not None else "dark maestro restado")
        if self.steps.flat_divided:
            applied.append("dividido por flat maestro")
        if self.steps.bad_pixels_interpolated:
            applied.append("píxeles defectuosos interpolados")
        if self.illumination_corrected:
            applied.append("corrección de iluminación aplicada")
        if self.fringe_removed:
            factor = self.fringe_scale_factor
            applied.append(f"franjas eliminadas (escala {factor:.4f})" if factor is not None else "franjas eliminadas")
        if self.sky_subtracted:
            degree = self.sky_degree
            applied.append(f"fondo de cielo restado (superficie de grado {degree})" if degree is not None else "fondo de cielo restado")
        return tuple(applied)


def build_reduction_provenance(
    record: ReductionRecord,
    *,
    pipeline_version: str = "",
    input_hashes: tuple[tuple[str, str], ...] = (),
) -> Provenance:
    """`Provenance` real de un LIGHT reducido. `input_hashes` debe traer
    los sha256 reales de las entradas que intervinieron (el propio LIGHT
    y los fotogramas maestros usados) -- el llamador los tiene, este
    módulo no los inventa."""
    warnings: list[str] = []
    if not record.steps.bias_subtracted and not record.steps.dark_subtracted:
        warnings.append("sin bias ni dark: el nivel de offset del sensor no se ha eliminado")
    if not record.steps.flat_divided:
        warnings.append("sin flat: la respuesta no uniforme del sensor no se ha corregido")

    return Provenance.now(
        pipeline_version=pipeline_version,
        engine=ENGINE_NAME,
        engine_version=ENGINE_VERSION,
        input_hashes=input_hashes,
        warnings=tuple(warnings),
    )


def reduction_header_cards(record: ReductionRecord, *, provenance: Provenance | None = None) -> dict:
    """Tarjetas FITS reales que declaran la reducción aplicada, para
    escribirlas en el archivo calibrado.

    Se usan claves propias con prefijo `APS` (AstroPhysics Suite) para no
    pisar ninguna palabra clave estándar, más líneas `HISTORY` legibles
    por cualquier visor FITS -- el mismo criterio que ya se siguió al
    escribir la procedencia astrométrica (`WCSRMS`/`WCSNSTR`/`HISTORY`).
    """
    cards: dict = {
        "APSRED": True,
        "APSBIAS": bool(record.steps.bias_subtracted),
        "APSDARK": bool(record.steps.dark_subtracted),
        "APSFLAT": bool(record.steps.flat_divided),
        "APSBPM": bool(record.steps.bad_pixels_interpolated),
        "APSOSCAN": bool(record.overscan_corrected),
        "APSILLUM": bool(record.illumination_corrected),
        "APSFRING": bool(record.fringe_removed),
        "APSSKY": bool(record.sky_subtracted),
    }
    if record.steps.dark_scale_factor is not None:
        cards["APSDKSCL"] = float(record.steps.dark_scale_factor)
    if record.fringe_scale_factor is not None:
        cards["APSFRSCL"] = float(record.fringe_scale_factor)
    if record.sky_degree is not None:
        cards["APSSKYDG"] = int(record.sky_degree)
    if record.gain_e_per_adu is not None:
        cards["APSGAIN"] = float(record.gain_e_per_adu)
    if record.read_noise_e is not None:
        cards["APSRDNS"] = float(record.read_noise_e)

    if provenance is not None:
        cards["APSENG"] = f"{provenance.engine} {provenance.engine_version}"
        cards["APSDATE"] = provenance.produced_at.isoformat()

    applied = record.describe()
    history = [f"{_HISTORY_PREFIX} reducción aplicada"]
    if applied:
        history.extend(f"  - {step}" for step in applied)
    else:
        history.append("  - ningún paso de calibración aplicado")
    if provenance is not None:
        history.extend(f"  ! {w}" for w in provenance.warnings)
    cards["HISTORY"] = history
    return cards
