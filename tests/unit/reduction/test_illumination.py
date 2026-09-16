from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.reduction.illumination import apply_illumination_correction, build_illumination_map


def test_build_illumination_map_isolates_large_scale_gradient_from_pixel_noise():
    # lienzo grande frente al kernel de suavizado -- el sesgo de borde del
    # filtrado gaussiano (relleno por reflexión) se extiende ~3-4 sigmas
    # hacia dentro; con sigma=10 hace falta margen de sobra para comparar
    # solo la región donde ese sesgo ya es despreciable.
    height, width = 160, 160
    sigma = 10.0
    margin = 45
    yy, xx = np.mgrid[0:height, 0:width]
    true_illumination = 1.0 + 0.4 * (xx / (width - 1))  # gradiente suave conocido

    rng = np.random.default_rng(0)
    pixel_noise = rng.normal(0, 0.02, (height, width))  # ruido píxel a píxel, alta frecuencia
    flat_data = true_illumination * (1.0 + pixel_noise)

    illumination = build_illumination_map(flat_data, smoothing_sigma_px=sigma)

    assert illumination.data.shape == (height, width)
    np.testing.assert_allclose(np.median(illumination.data), 1.0, atol=1e-6)
    # el suavizado debe recuperar el gradiente de verdad (ya normalizada a
    # mediana 1.0 igual que `illumination.data`), no el ruido de alta frecuencia
    expected_normalized = true_illumination / float(np.median(true_illumination))
    interior = slice(margin, -margin)
    np.testing.assert_allclose(illumination.data[interior, interior], expected_normalized[interior, interior], atol=0.02)


def test_build_illumination_map_rejects_non_positive_sigma():
    with pytest.raises(ValueError):
        build_illumination_map(np.ones((10, 10)), smoothing_sigma_px=0.0)


def test_apply_illumination_correction_flattens_science_image_with_matching_pattern():
    height, width = 160, 160
    sigma = 5.0
    margin = 25
    yy, xx = np.mgrid[0:height, 0:width]
    true_illumination = 1.0 + 0.3 * (xx / (width - 1))
    flat_data = true_illumination.copy()
    illumination = build_illumination_map(flat_data, smoothing_sigma_px=sigma)

    uniform_sky = 1000.0
    science = uniform_sky * true_illumination

    corrected = apply_illumination_correction(science, illumination)

    # la corrección aplana la imagen a un nivel constante -- no
    # necesariamente `uniform_sky` exacto, porque el mapa de iluminación
    # está normalizado a SU PROPIA mediana, no anclado al valor absoluto
    # de `true_illumination`; lo que importa es que el resultado sea
    # plano, no el valor absoluto que alcanza.
    interior = slice(margin, -margin)
    corrected_interior = corrected[interior, interior]
    np.testing.assert_allclose(corrected_interior, float(np.mean(corrected_interior)), rtol=5e-3)


def test_apply_illumination_correction_rejects_shape_mismatch():
    illumination = build_illumination_map(np.ones((10, 10)))
    with pytest.raises(ValueError):
        apply_illumination_correction(np.ones((5, 5)), illumination)
