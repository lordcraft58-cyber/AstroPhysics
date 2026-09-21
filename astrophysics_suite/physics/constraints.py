"""Comprobación de consistencia física interna, con el contrato
explícito -- corrige de raíz una brecha real y documentada.

## La brecha (medida, no supuesta)

`PhysicalConstraintEngine.evaluate(row, estimates)` busca `radius_pc`,
`velocity_kms`, `age_yr` y `postshock_temperature_K` **todos dentro de
`estimates`**, el diccionario de magnitudes INFERIDAS que produce
`infer_physical_parameters`. Pero ese diccionario nunca contiene
`radius_pc` ni `velocity_kms`: esos dos son observables MEDIDOS, y viven
en `row`. Resultado comprobado ejecutándolo con una fila real de un
resto de supernova (radio 5 pc, velocidad 120 km/s):

    evaluate(row, estimates) -> 0 comprobaciones
    evaluate(row, estimates + observables medidos) -> 2 comprobaciones
        (Sedov edad-radio-velocidad, choque fuerte T-v)

Es decir: las dos consistencias físicas internas del motor eran
**inalcanzables en la ruta de producción**, no por un umbral, sino
porque los datos que necesitan nunca llegaban a donde las busca.

## La corrección

No se parchea con un `if faltan: return []`, ni se toca la física
heredada (que es correcta y está probada). Se hace explícito el contrato
que el motor necesitaba desde el principio:

    evaluate_consistency(observables_medidos, magnitudes_inferidas)

y este módulo promueve los observables medidos al espacio de parámetros
donde el motor los busca, marcándolos con su procedencia real
(OBSERVADO, frente a INFERIDO), de forma que una tensión siempre se
puede desmontar en "qué se midió" y "qué se dedujo".
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.models.physical import PhysicalInference
from astrophysics_suite.physics.inference import _get_float

ENGINE_NAME = "physics.constraints"
ENGINE_VERSION = "1.0"

#: Observables que el motor de consistencia busca en el espacio de
#: parámetros pero que son MEDIDOS, no inferidos -- el origen exacto de
#: la brecha que este módulo corrige.
#:
#: `age_yr` y `postshock_temperature_K` están aquí por una razón distinta
#: y más sutil, detectada al probar un caso deliberadamente inconsistente:
#: `infer_physical_parameters` DERIVA la edad con exactamente la misma
#: fórmula de Sedov (`0.4·R/v`) que el motor de consistencia usa como
#: predicción, y la temperatura con la misma relación de choque fuerte
#: que la otra comprobación. Comparar una inferencia contra la fórmula
#: que la produjo es una tautología: z sale 0 SIEMPRE y la comprobación
#: no puede detectar ninguna tensión, aunque sea alcanzable.
#:
#: Por eso, cuando existe un valor MEDIDO de forma independiente (una
#: edad histórica del remanente, una temperatura de rayos X), ese valor
#: tiene prioridad sobre el inferido en el espacio de consistencia: solo
#: así la comprobación contrasta dos cosas realmente independientes.
MEASURED_PARAMETERS_NEEDED_BY_CONSTRAINTS = (
    ("radius_pc", "radius_err_pc", "pc", True),
    ("velocity_kms", "velocity_err_kms", "km/s", True),
    ("age_yr", "age_err_yr", "yr", False),
    ("postshock_temperature_K", "postshock_temperature_err_K", "K", False),
)


@dataclass(frozen=True)
class ConsistencyIssue:
    """Una comprobación de consistencia física realmente evaluada."""

    constraint: str
    z_score: float | None
    flagged: bool
    classification: str
    assumptions: tuple[str, ...]
    detail: dict

    @property
    def is_physical_tension(self) -> bool:
        return self.flagged and self.classification != "measurement_issue"


@dataclass(frozen=True)
class ConsistencyResult:
    """Resultado completo, siempre desmontable: qué se evaluó, qué no se
    pudo evaluar y por qué."""

    issues: tuple[ConsistencyIssue, ...]
    not_evaluated: dict[str, str]
    threshold_sigma: float

    @property
    def physical_tensions(self) -> tuple[ConsistencyIssue, ...]:
        return tuple(issue for issue in self.issues if issue.is_physical_tension)

    @property
    def max_tension_sigma(self) -> float | None:
        values = [abs(i.z_score) for i in self.physical_tensions if i.z_score is not None]
        return max(values) if values else None


def _parameter_space_from(
    measured: dict[str, float], inferred: PhysicalInference | None,
) -> tuple[dict[str, dict], dict[str, str]]:
    """Espacio de parámetros unificado que el motor de consistencia
    necesita: magnitudes inferidas MÁS observables medidos, cada uno con
    su estado real. Devuelve también qué faltó y por qué."""
    space: dict[str, dict] = {}
    missing: dict[str, str] = {}

    if inferred is not None:
        for name, quantity in inferred.parameters.items():
            if quantity.is_available and quantity.value is not None:
                space[name] = {
                    "value": float(quantity.value),
                    "error": float(quantity.error) if quantity.error is not None else float("nan"),
                    "unit": quantity.unit,
                    "status": "INFERIDO",
                }

    for name, error_name, unit, required in MEASURED_PARAMETERS_NEEDED_BY_CONSTRAINTS:
        value = measured.get(name)
        if value is None or not math.isfinite(float(value)):
            if required:
                missing[name] = (
                    "observable medido ausente -- sin él, las consistencias que lo usan no se pueden evaluar "
                    "(no se sustituye por ningún valor supuesto)"
                )
            elif name in space:
                # Existe el valor INFERIDO pero no uno medido independiente:
                # la comprobación que lo use será tautológica (compara la
                # inferencia contra la fórmula que la generó). Se deja, pero
                # se registra para que no se lea como una validación real.
                missing[name] = (
                    "solo hay valor inferido, no una medida independiente -- la comprobación que lo use compara la "
                    "inferencia contra la fórmula que la produjo y no puede detectar tensión (z=0 por construcción)"
                )
            continue
        error = measured.get(error_name)
        # El valor MEDIDO tiene prioridad sobre el inferido: es lo único que
        # convierte la comprobación en un contraste real entre dos fuentes
        # independientes.
        space[name] = {
            "value": float(value),
            "error": float(error) if error is not None and math.isfinite(float(error)) else float("nan"),
            "unit": unit,
            "status": "OBSERVADO",
        }

    return space, missing


def _evaluate_physical_constraints(row: dict, estimates: dict, *, min_sigma: float) -> dict:
    """Busca incompatibilidades entre parámetros relacionados por física
    básica -- migrado 1:1 del `PhysicalConstraintEngine.evaluate`
    heredado (cierre sistemático del motor 11/16, informe 99). Nunca
    convierte una incompatibilidad en descubrimiento: devuelve
    restricciones, z/tensión y los supuestos que permiten interpretar el
    resultado, mismas fórmulas y criterios que la versión heredada."""
    r = dict(row or {})
    p = dict(estimates or {})
    issues: list[dict] = []

    def par(name: str) -> tuple[float, float]:
        d = p.get(name, {})
        try:
            v = float(d.get("value"))
        except (TypeError, ValueError):
            v = float("nan")
        if not math.isfinite(v):
            v = float("nan")
        try:
            e = abs(float(d.get("error")))
        except (TypeError, ValueError):
            e = float("nan")
        if not math.isfinite(e):
            e = float("nan")
        return v, e

    # Kinematic age consistency: age = 0.4 R/v in the uniform Sedov self-similar case.
    R, Re = par("radius_pc")
    v, ve = par("velocity_kms")
    age, agee = par("age_yr")
    if all(math.isfinite(q) for q in (R, v, age)) and R > 0 and v > 0:
        pred = 0.4 * R * 3.0856775814913673e13 / (v * 1e3) / (365.25 * 86400.0)
        pred_err = abs(pred) * math.sqrt((Re / R) ** 2 + (ve / v) ** 2) if math.isfinite(Re) and Re > 0 and math.isfinite(ve) and ve > 0 else float("nan")
        den = math.sqrt(max(0.0, pred_err**2) + (agee**2 if math.isfinite(agee) and agee > 0 else 0.0))
        z = (age - pred) / den if den > 0 else float("nan")
        issues.append({
            "constraint": "Sedov age-radius-velocity", "observed_age_yr": age, "predicted_age_yr": pred,
            "z_score": float(z) if math.isfinite(z) else None,
            "flag": bool(math.isfinite(z) and abs(z) >= min_sigma),
            "assumptions": ["spherical", "adiabatic", "uniform_medium", "self_similar_eta=0.4"],
        })

    # Strong shock consistency: T ~= (3/16) mu mp v^2 / kB for gamma=5/3.
    T, Te = par("postshock_temperature_K")
    if math.isfinite(v) and math.isfinite(T) and v > 0 and T > 0:
        kB = 1.380649e-23
        mp = 1.67262192369e-27
        mu = 0.61
        pred = (3.0 / 16.0) * mu * mp * (v * 1e3) ** 2 / kB
        pe = abs(pred * 2 * ve / v) if math.isfinite(ve) and ve > 0 else float("nan")
        den = math.sqrt(max(0.0, pe**2) + (Te**2 if math.isfinite(Te) and Te > 0 else 0.0))
        z = (T - pred) / den if den > 0 else float("nan")
        issues.append({
            "constraint": "Strong-shock T-v", "observed_temperature_K": T, "predicted_temperature_K": pred,
            "z_score": float(z) if math.isfinite(z) else None,
            "flag": bool(math.isfinite(z) and abs(z) >= min_sigma),
            "assumptions": ["gamma=5/3", "mu=0.61", "fully_ionized", "strong_shock"],
        })

    # Ratio sanity; negative or non-finite flux-derived ratios are measurement issues.
    ratio = _get_float(r, "ratio", "oiii_ha_ratio")
    if math.isfinite(ratio) and ratio <= 0:
        issues.append({"constraint": "positive emission-line ratio", "flag": True, "classification": "measurement_issue"})

    return {
        "engine_version": "1.0",
        "issues": issues,
        "n_physical_tensions": sum(bool(i.get("flag")) and i.get("classification") != "measurement_issue" for i in issues),
        "n_measurement_issues": sum(i.get("classification") == "measurement_issue" for i in issues),
        "threshold_sigma": min_sigma,
    }


def evaluate_consistency(
    measured_observables: dict[str, float],
    inferred: PhysicalInference | None,
    *,
    sigma_threshold: float = 4.0,
) -> ConsistencyResult:
    """Evalúa las consistencias físicas internas con el contrato
    explícito: observables MEDIDOS + magnitudes INFERIDAS.

    A diferencia de la llamada heredada directa, aquí los observables
    medidos llegan de verdad a donde el motor los busca, así que las
    comprobaciones dejan de ser inalcanzables."""
    parameter_space, missing = _parameter_space_from(measured_observables, inferred)
    raw = _evaluate_physical_constraints(measured_observables, parameter_space, min_sigma=sigma_threshold)

    issues = tuple(
        ConsistencyIssue(
            constraint=str(item.get("constraint", "desconocida")),
            z_score=float(item["z_score"]) if item.get("z_score") is not None else None,
            flagged=bool(item.get("flag")),
            classification=str(item.get("classification", "physical")),
            assumptions=tuple(item.get("assumptions") or ()),
            detail={k: v for k, v in item.items() if k not in ("constraint", "z_score", "flag", "classification", "assumptions")},
        )
        for item in raw.get("issues", [])
    )

    not_evaluated = dict(missing)
    evaluated_names = {issue.constraint for issue in issues}
    if "Sedov age-radius-velocity" not in evaluated_names:
        not_evaluated.setdefault(
            "Sedov age-radius-velocity",
            "necesita radio (pc), velocidad (km/s) y edad inferida simultáneamente",
        )
    if "Strong-shock T-v" not in evaluated_names:
        not_evaluated.setdefault(
            "Strong-shock T-v",
            "necesita velocidad (km/s) y temperatura post-choque inferida simultáneamente",
        )

    return ConsistencyResult(issues=issues, not_evaluated=not_evaluated, threshold_sigma=float(sigma_threshold))


def physical_tension_quantity(result: ConsistencyResult) -> Quantity:
    """La tensión física como `Quantity` lista para la dimensión
    `physical` del `AnomalyVector` -- con su valor en sigmas cuando se
    pudo evaluar, y NO DISPONIBLE (con motivo) cuando no."""
    if not result.issues:
        reason = "; ".join(f"{k}: {v}" for k, v in sorted(result.not_evaluated.items())) or "sin observables físicos suficientes"
        return Quantity.not_available(unit="sigma", method=ENGINE_NAME, reference=reason)
    max_sigma = result.max_tension_sigma
    if max_sigma is None:
        return Quantity(
            value=0.0, error=None, unit="sigma", kind=ValueKind.OBSERVED, method=ENGINE_NAME,
            notes=tuple(f"{issue.constraint}: consistente" for issue in result.issues),
        )
    return Quantity(
        value=float(max_sigma), error=None, unit="sigma", kind=ValueKind.OBSERVED, method=ENGINE_NAME,
        notes=tuple(f"{issue.constraint}: z={issue.z_score:.2f}" for issue in result.physical_tensions if issue.z_score is not None),
    )
