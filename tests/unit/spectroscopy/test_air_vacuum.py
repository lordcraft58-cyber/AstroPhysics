"""`air_vacuum.py`: conversión estándar publicada (Morton 2000),
verificada contra valores de referencia ampliamente citados (§24)."""
from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.air_vacuum import air_to_vacuum, vacuum_to_air


def test_h_alpha_air_to_vacuum_matches_the_well_known_reference_value():
    # H-alpha: 6562.8 A aire -> ~6564.6 A vacio, valor ampliamente citado
    # en la literatura (p. ej. NIST ASD, SDSS line lists).
    assert air_to_vacuum(6562.8) == pytest.approx(6564.6, abs=0.05)


def test_na_d2_air_to_vacuum_matches_the_well_known_reference_value():
    assert air_to_vacuum(5889.95) == pytest.approx(5891.58, abs=0.05)


def test_round_trip_air_vacuum_air_is_the_identity():
    for wavelength_air in (3968.5, 4861.3, 5889.95, 6562.8, 8600.0):
        vacuum = air_to_vacuum(wavelength_air)
        back_to_air = vacuum_to_air(vacuum)
        assert back_to_air == pytest.approx(wavelength_air, abs=1e-4)


def test_round_trip_vacuum_air_vacuum_is_the_identity():
    for wavelength_vacuum in (4000.0, 5000.0, 6564.6, 9000.0):
        air = vacuum_to_air(wavelength_vacuum)
        back_to_vacuum = air_to_vacuum(air)
        assert back_to_vacuum == pytest.approx(wavelength_vacuum, abs=1e-4)


def test_vacuum_wavelength_is_always_longer_than_air():
    # n_aire > 1 siempre en el rango optico: lambda_vacio = lambda_aire * n > lambda_aire
    for wavelength_air in (3968.5, 6562.8, 9000.0):
        assert air_to_vacuum(wavelength_air) > wavelength_air


def test_functions_accept_arrays_not_just_scalars():
    wavelengths = np.array([4861.3, 6562.8, 8600.0])
    vacuum = air_to_vacuum(wavelengths)
    assert isinstance(vacuum, np.ndarray)
    assert vacuum.shape == wavelengths.shape
    np.testing.assert_array_less(wavelengths, vacuum)
