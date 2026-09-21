"""Registro de fotogramas por coincidencia real de patrones de estrellas
-- sin WCS ni catálogo, solo geometría entre dos listas de fuentes ya
detectadas.

## Por qué existe, además de `registration.py`/`plate_solve.py`

`registration.py` alinea contra una imagen de referencia YA registrada
(mismo campo, mismo WCS). `plate_solve.py`/`blind_solve.py` resuelven
contra Gaia real (necesitan red). Este módulo cubre el caso intermedio,
real y frecuente en monturas de aficionado sin plate solving automático:
la cabecera trae un RA/Dec de apuntado aproximado (a veces con un ángulo
de cámara declarado, no medido), que puede tener un error de decenas de
píxeles -- demasiado para localizar la MISMA estrella entre fotogramas
con seguridad, pero el patrón de estrellas real del campo sigue siendo
idéntico salvo una traslación pequeña (deriva de seguimiento). Se
aprovecha eso: sin necesitar ninguna coordenada celeste, solo dos listas
de posiciones de píxel ya detectadas.
"""
from __future__ import annotations

import numpy as np


def estimate_frame_translation(
    reference_xy: np.ndarray,
    target_xy: np.ndarray,
    *,
    tolerance_px: float = 3.0,
    top_k: int = 15,
) -> tuple[float, float, int]:
    """Desplazamiento `(dx, dy)` real entre dos fotogramas del mismo
    campo, estimado por coincidencia de patrones.

    `reference_xy`/`target_xy`: posiciones `(x, y)` de fuentes ya
    detectadas en cada fotograma (ver `detection.point_sources.
    detect_point_sources_in_array`), ordenadas de más a menos brillante
    -- el orden importa: solo se prueban las `top_k` primeras de cada
    lista como candidatas a corresponderse, por coste computacional
    (probar todos los pares de un campo con miles de fuentes sería
    O(n²) sin necesidad, cuando el campo casi siempre tiene una decena de
    estrellas brillantes e inconfundibles).

    Prueba la traslación implicada por cada par (candidata de
    referencia, candidata de destino), y se queda con la que hace
    coincidir más estrellas del resto del campo (dentro de
    `tolerance_px`) -- un campo estelar real tiene un patrón único, así
    que la traslación correcta es la única que alinea casi todo el campo
    a la vez; una traslación al azar solo alinea, por casualidad, muy
    pocas.

    Devuelve `(dx, dy, n_inliers)`. `n_inliers` es la métrica de
    confianza real del resultado -- compárese con `len(reference_xy)`:
    pocos inliers frente al total significa que el campo cambió
    demasiado (nubes, tracking perdido, fotograma distinto) para fiarse
    de la traslación encontrada. Con listas vacías devuelve `(0.0, 0.0,
    0)` -- nunca inventa un desplazamiento sin datos."""
    if len(reference_xy) == 0 or len(target_xy) == 0:
        return 0.0, 0.0, 0
    reference_xy = np.asarray(reference_xy, dtype=float)
    target_xy = np.asarray(target_xy, dtype=float)

    best_dx, best_dy, best_score = 0.0, 0.0, -1
    for i in range(min(top_k, len(reference_xy))):
        for j in range(min(top_k, len(target_xy))):
            dx, dy = target_xy[j] - reference_xy[i]
            shifted = reference_xy + np.array([dx, dy])
            score = 0
            for point in shifted:
                distance = float(np.min(np.sum((target_xy - point) ** 2, axis=1)) ** 0.5)
                if distance <= tolerance_px:
                    score += 1
            if score > best_score:
                best_score, best_dx, best_dy = score, float(dx), float(dy)
    return best_dx, best_dy, best_score


def refine_position(
    detected_xy: np.ndarray, x0: float, y0: float, *, search_radius_px: float = 4.0,
) -> tuple[float, float, bool]:
    """Reajusta `(x0, y0)` (predicha por `estimate_frame_translation`,
    una traslación global, no un ajuste estrella a estrella) a la fuente
    real detectada más cercana dentro de `search_radius_px`.

    Corrige el error residual de una traslación puramente global
    (rotación de campo pequeña, distorsión óptica, error de centroide de
    la estrella usada para la traslación) sin inventar una posición: si
    no hay ninguna fuente real lo bastante cerca, se devuelve la
    posición predicha tal cual, marcada explícitamente como NO
    reajustada -- para que quien mida fotometría ahí sepa que está
    midiendo en una posición estimada, no confirmada por una fuente
    real."""
    if len(detected_xy) == 0:
        return x0, y0, False
    detected_xy = np.asarray(detected_xy, dtype=float)
    distances = np.sum((detected_xy - np.array([x0, y0])) ** 2, axis=1) ** 0.5
    i = int(np.argmin(distances))
    if distances[i] <= search_radius_px:
        return float(detected_xy[i, 0]), float(detected_xy[i, 1]), True
    return x0, y0, False
