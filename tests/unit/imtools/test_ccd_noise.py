"""`ccd_noise.py`: ruido de disparo real (Poisson en electrones, no en
ADU crudo) más ruido de lectura, extraído de `imtools.cosmic_rays` para
que cualquier consumidor lo reutilice en vez de aproximar con
`sqrt(ADU)`."""
from __future__ import annotations

import math

import numpy as np
import pytest

from astrophysics_suite.imtools.ccd_noise import ccd_noise_adu


def test_matches_manual_poisson_plus_read_noise_computation():
    data = np.array([100.0, 400.0, 900.0])
    gain = 2.0
    read_noise = 5.0

    result = ccd_noise_adu(data, gain_e_per_adu=gain, read_noise_e=read_noise)

    expected = np.array([math.sqrt(d * gain + read_noise**2) / gain for d in data])
    np.testing.assert_allclose(result, expected)


def test_gain_one_and_zero_read_noise_reduces_to_sqrt_adu():
    """El caso límite (gain=1, ruido de lectura=0) debe coincidir
    exactamente con la aproximación sqrt(ADU) que este motor reemplaza."""
    data = np.array([25.0, 100.0, 2500.0])

    result = ccd_noise_adu(data, gain_e_per_adu=1.0, read_noise_e=0.0)

    np.testing.assert_allclose(result, np.sqrt(data))


def test_higher_gain_reduces_the_noise_in_adu_for_the_same_signal():
    data = np.array([1000.0])
    low_gain = ccd_noise_adu(data, gain_e_per_adu=1.0, read_noise_e=0.0)
    high_gain = ccd_noise_adu(data, gain_e_per_adu=4.0, read_noise_e=0.0)
    assert high_gain[0] < low_gain[0]


def test_negative_signal_is_clipped_to_zero_before_the_poisson_term():
    result = ccd_noise_adu(np.array([-50.0]), gain_e_per_adu=1.0, read_noise_e=3.0)
    assert result[0] == pytest.approx(3.0)


def test_rejects_non_positive_gain():
    with pytest.raises(ValueError):
        ccd_noise_adu(np.array([100.0]), gain_e_per_adu=0.0, read_noise_e=0.0)
    with pytest.raises(ValueError):
        ccd_noise_adu(np.array([100.0]), gain_e_per_adu=-1.0, read_noise_e=0.0)


def test_rejects_negative_read_noise():
    with pytest.raises(ValueError):
        ccd_noise_adu(np.array([100.0]), gain_e_per_adu=1.0, read_noise_e=-1.0)
