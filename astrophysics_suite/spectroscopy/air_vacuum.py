"""Conversión aire <-> vacío (§24) -- fórmulas estándar publicadas
(Morton 2000, ApJS 130, 403, ecuación 3; la misma convención que usa el
NIST Atomic Spectra Database para reportar longitudes de onda en aire
por encima de 2000 Å y en vacío por debajo). Nunca se mezclan
longitudes de onda de aire y vacío sin marcar la convención -- todas
las funciones de este módulo dejan explícito en su nombre y su
documentación cuál usan.

Válidas para el rango óptico estándar (aprox. 2000-30000 Å); fuera de
ahí, el propio índice de refracción del aire usado aquí deja de ser una
buena aproximación y no se debería confiar en el resultado sin
verificarlo contra una fuente específica para esa región.
"""
from __future__ import annotations

import numpy as np


def vacuum_to_air(wavelength_vacuum_angstrom: np.ndarray | float) -> np.ndarray | float:
    """Longitud de onda en vacío -> aire (Morton 2000, ec. 3):
    `n = 1 + 0.0000834254 + 0.02406147/(130 - s^2) + 0.00015998/(38.9 - s^2)`,
    con `s = 10^4 / lambda_vacuum[A]`; `lambda_air = lambda_vacuum / n`."""
    wave = np.asarray(wavelength_vacuum_angstrom, dtype=np.float64)
    s2 = (1.0e4 / wave) ** 2
    n = 1.0 + 0.0000834254 + 0.02406147 / (130.0 - s2) + 0.00015998 / (38.9 - s2)
    result = wave / n
    return float(result) if np.isscalar(wavelength_vacuum_angstrom) else result


def air_to_vacuum(wavelength_air_angstrom: np.ndarray | float) -> np.ndarray | float:
    """Inversa de `vacuum_to_air` (Morton 2000, ec. 1, la forma
    publicada directamente en función de la longitud de onda en aire --
    no una inversión numérica iterativa de la ecuación 3):
    `n = 1 + 0.00008336624212083 + 0.02408926869968/(130.1065924522 - s^2)
    + 0.0001599740894897/(38.92568793293 - s^2)`, con
    `s = 10^4 / lambda_air[A]`; `lambda_vacuum = lambda_air * n`."""
    wave = np.asarray(wavelength_air_angstrom, dtype=np.float64)
    s2 = (1.0e4 / wave) ** 2
    n = 1.0 + 0.00008336624212083 + 0.02408926869968 / (130.1065924522 - s2) + 0.0001599740894897 / (38.92568793293 - s2)
    result = wave * n
    return float(result) if np.isscalar(wavelength_air_angstrom) else result
