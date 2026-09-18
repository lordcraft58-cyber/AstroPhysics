from __future__ import annotations

from astrophysics_suite.diagnostics.outliers import flag_outliers


def test_flag_outliers_returns_nothing_with_fewer_than_two_points():
    assert flag_outliers(()) == ()
    assert flag_outliers((1.0,)) == ()


def test_flag_outliers_returns_nothing_for_tightly_clustered_values():
    values = (1.0, 1.01, 0.99, 1.02, 0.98, 1.0)
    assert flag_outliers(values) == ()


def test_flag_outliers_flags_a_real_deviant_point():
    values = (1.0, 1.01, 0.99, 1.02, 0.98, 50.0)
    assert flag_outliers(values) == (5,)


def test_flag_outliers_flags_multiple_deviant_points():
    values = (1.0, 1.0, 1.0, 1.0, -30.0, 1.0, 40.0)
    assert set(flag_outliers(values)) == {4, 6}


def test_flag_outliers_never_flags_identical_values():
    values = (5.0, 5.0, 5.0, 5.0, 5.0)
    assert flag_outliers(values) == ()


def test_flag_outliers_respects_looser_sigma_threshold():
    values = (0.0, 1.0, -1.0, 2.0, -2.0, 10.0)
    assert flag_outliers(values, sigma=3.0) != ()
    assert flag_outliers(values, sigma=100.0) == ()
