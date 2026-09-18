"""Debayering (demosaico) real de sensores CFA / cámaras OSC.

Laguna funcional encontrada probando con lights reales del usuario (ZWO
ASI533MC Pro, `BAYERPAT=RGGB`): ni el motor heredado ni el nuevo tenían
NINGUNA etapa de demosaico, así que la detección y la fotometría corrían
directamente sobre el mosaico de Bayer crudo. Eso sesga los resultados de
forma real y no obvia: bajo una apertura, solo 1 de cada 4 píxeles mide
rojo, 1 de cada 4 azul y 2 de cada 4 verde, con sensibilidades muy
distintas -- tanto el fondo estimado como el flujo integrado salen
sesgados, y la PSF aparente queda modulada por el propio patrón de
mosaico (ver docs/audit/35-DEBAYERING-OSC.md).

## Los dos métodos, y por qué importan cuál se usa

- **SuperPixel** (`debayer_superpixel`): cada bloque 2x2 del mosaico se
  convierte en UN píxel RGB (R del rojo real, B del azul real, G la
  media de los dos verdes reales). La imagen sale a media resolución,
  pero **ningún valor es interpolado**: todos los números son medidas
  reales del sensor. Es el método correcto para fotometría y detección
  científica -- no inventa señal donde no la había.
- **Bilineal** (`debayer_bilinear`): mantiene la resolución completa
  interpolando los canales que faltan en cada píxel. Se ve mejor y es lo
  normal para una imagen "bonita", pero **la mayoría de los valores son
  interpolados, no medidos** -- usarlo como entrada de fotometría
  introduce correlación entre píxeles vecinos y falsea las
  incertidumbres. Disponible aquí, pero nunca como método por defecto
  del camino científico.

Para el camino de detección/fotometría, `debayer_to_luminance` combina
SuperPixel + suma ponderada a un solo plano monocromo: sin interpolar,
sin el tablero de ajedrez del mosaico, y con el ruido de Poisson
correctamente propagado (es una suma de medidas reales).

## Orientación del patrón (nunca se adivina en silencio)

`BAYERPAT` describe el bloque 2x2 empezando en el primer píxel del array
tal y como está almacenado -- `data[0, 0]`. Algunos programas de captura
escriben el patrón pensando en la orientación de pantalla (arriba-abajo)
aunque FITS almacene las filas al revés, así que el patrón declarado
puede no coincidir con los datos reales. Por eso
`infer_bayer_pattern_from_data` comprueba el patrón CONTRA los propios
píxeles (los dos planos verdes de un CFA real son estadísticamente casi
idénticos entre sí, y distintos del rojo y del azul) y
`describe_bayer_agreement` informa explícitamente si la cabecera y los
datos no concuerdan -- nunca se corrige en silencio ni se asume que la
cabecera tiene razón.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

BAYER_PATTERNS = ("RGGB", "BGGR", "GRBG", "GBRG")


class BayerError(ValueError):
    """Patrón de Bayer no reconocido, o imagen que no se puede
    demosaicar (no 2D, lados impares) -- nunca se demosaica "a medias"
    ni se recorta en silencio."""


def bayer_pattern_from_header(header: dict | None) -> str | None:
    """Patrón declarado en la cabecera (`BAYERPAT`, o `COLORTYP` que
    escriben algunos programas), ya normalizado y con los desplazamientos
    `XBAYROFF`/`YBAYROFF` aplicados si los trae -- `None` si la cabecera
    no declara ninguno (una imagen monocroma normal, o un OSC ya
    demosaicado).

    Nunca inventa un patrón por defecto: sin `BAYERPAT` no se puede saber
    si la imagen es un mosaico ni con qué orientación, y asumir "RGGB
    porque es lo más común" produciría colores y fotometría
    silenciosamente incorrectos en cualquier cámara que no lo sea."""
    if not header:
        return None
    raw = header.get("BAYERPAT", header.get("COLORTYP", header.get("BAYERPATT")))
    if raw is None:
        return None
    pattern = str(raw).strip().strip("'\"").upper()
    if pattern not in BAYER_PATTERNS:
        return None
    x_offset = int(header.get("XBAYROFF", 0) or 0)
    y_offset = int(header.get("YBAYROFF", 0) or 0)
    return shift_bayer_pattern(pattern, x_offset=x_offset, y_offset=y_offset)


def shift_bayer_pattern(pattern: str, *, x_offset: int = 0, y_offset: int = 0) -> str:
    """Patrón equivalente cuando el origen del mosaico está desplazado
    (`XBAYROFF`/`YBAYROFF`, típico si la imagen viene recortada): el
    bloque 2x2 que le toca a `data[0, 0]` no es el mismo."""
    if pattern not in BAYER_PATTERNS:
        raise BayerError(f"patrón de Bayer no reconocido: {pattern!r} (esperado uno de {BAYER_PATTERNS})")
    block = np.array([[pattern[0], pattern[1]], [pattern[2], pattern[3]]])
    block = np.roll(block, shift=(-(y_offset % 2), -(x_offset % 2)), axis=(0, 1))
    return "".join(block.flatten())


def _channel_positions(pattern: str) -> dict[str, list[tuple[int, int]]]:
    """`{canal: [(fila%2, columna%2), ...]}` -- el verde aparece dos
    veces en todo patrón CFA de Bayer real."""
    if pattern not in BAYER_PATTERNS:
        raise BayerError(f"patrón de Bayer no reconocido: {pattern!r} (esperado uno de {BAYER_PATTERNS})")
    positions: dict[str, list[tuple[int, int]]] = {"R": [], "G": [], "B": []}
    for index, channel in enumerate(pattern):
        positions[channel].append((index // 2, index % 2))
    return positions


def _validate_mosaic(data: np.ndarray) -> np.ndarray:
    array = np.asarray(data)
    if array.ndim != 2:
        raise BayerError(f"el demosaico necesita una imagen 2D (mosaico CFA); recibida forma {array.shape}")
    if array.shape[0] < 2 or array.shape[1] < 2:
        raise BayerError(f"imagen demasiado pequeña para un mosaico 2x2: {array.shape}")
    return array.astype(np.float64, copy=False)


def debayer_superpixel(data: np.ndarray, pattern: str) -> np.ndarray:
    """Cada bloque 2x2 -> un píxel RGB, **sin interpolar nada**: R y B son
    la medida real de ese fotosito, G la media de los dos verdes reales
    del bloque. Devuelve `(alto//2, ancho//2, 3)` -- media resolución,
    pero todos los valores son medidas reales del sensor.

    Si el alto o el ancho es impar, se descarta la última fila/columna
    (un bloque 2x2 incompleto no tiene los cuatro colores) -- se
    documenta aquí porque cambia la forma de salida, nunca es silencioso
    para quien lee el código."""
    array = _validate_mosaic(data)
    height, width = array.shape[0] // 2 * 2, array.shape[1] // 2 * 2
    array = array[:height, :width]
    positions = _channel_positions(pattern)

    def plane(row: int, col: int) -> np.ndarray:
        return array[row::2, col::2]

    red_row, red_col = positions["R"][0]
    blue_row, blue_col = positions["B"][0]
    (g1_row, g1_col), (g2_row, g2_col) = positions["G"]

    rgb = np.empty((height // 2, width // 2, 3), dtype=np.float64)
    rgb[:, :, 0] = plane(red_row, red_col)
    rgb[:, :, 1] = 0.5 * (plane(g1_row, g1_col) + plane(g2_row, g2_col))
    rgb[:, :, 2] = plane(blue_row, blue_col)
    return rgb


def debayer_bilinear(data: np.ndarray, pattern: str) -> np.ndarray:
    """Resolución completa interpolando bilinealmente los canales que
    faltan en cada píxel. Devuelve `(alto, ancho, 3)`.

    **La mayoría de los valores de salida son interpolados, no medidos**
    -- para verlo está bien; para fotometría no (ver el docstring del
    módulo). El proceso de la GUI lo advierte explícitamente."""
    array = _validate_mosaic(data)
    height, width = array.shape
    positions = _channel_positions(pattern)

    rgb = np.zeros((height, width, 3), dtype=np.float64)
    for channel_index, channel in enumerate("RGB"):
        mask = np.zeros((height, width), dtype=bool)
        for row_offset, col_offset in positions[channel]:
            mask[row_offset::2, col_offset::2] = True
        measured = np.where(mask, array, 0.0)
        # Interpolación bilineal real = media de los vecinos medidos, con el
        # mismo núcleo aplicado a la máscara para dividir por cuántos vecinos
        # reales había (nunca se divide por un número fijo asumido).
        kernel = np.array([[0.25, 0.5, 0.25], [0.5, 1.0, 0.5], [0.25, 0.5, 0.25]], dtype=np.float64)
        weighted = _convolve_same(measured, kernel)
        weights = _convolve_same(mask.astype(np.float64), kernel)
        with np.errstate(invalid="ignore", divide="ignore"):
            interpolated = np.where(weights > 0, weighted / weights, 0.0)
        rgb[:, :, channel_index] = np.where(mask, array, interpolated)
    return rgb


def _convolve_same(image: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """Convolución 2D con borde replicado -- `scipy.signal.convolve2d`
    equivalente, escrito con numpy para no añadir una dependencia nueva
    a un módulo tan central."""
    pad_y, pad_x = kernel.shape[0] // 2, kernel.shape[1] // 2
    padded = np.pad(image, ((pad_y, pad_y), (pad_x, pad_x)), mode="edge")
    out = np.zeros_like(image, dtype=np.float64)
    for ky in range(kernel.shape[0]):
        for kx in range(kernel.shape[1]):
            weight = kernel[ky, kx]
            if weight != 0.0:
                out += weight * padded[ky : ky + image.shape[0], kx : kx + image.shape[1]]
    return out


def debayer_to_luminance(
    data: np.ndarray, pattern: str, *, weights: tuple[float, float, float] = (0.25, 0.5, 0.25),
) -> np.ndarray:
    """SuperPixel + suma ponderada -> un solo plano monocromo
    `(alto//2, ancho//2)`, pensado para detección y fotometría sobre
    datos OSC: sin el tablero del mosaico y sin ningún valor interpolado.

    Los pesos por defecto (1/4, 1/2, 1/4) son la proporción real de
    fotositos de cada color en un CFA de Bayer, es decir, la suma
    equivale a "todos los fotositos del bloque contados una vez" -- la
    combinación que conserva la estadística de Poisson del sensor. Se
    pueden cambiar (p. ej. pesos fotópicos para una luminancia visual),
    pero entonces la señal ya no es una simple suma de cuentas."""
    rgb = debayer_superpixel(data, pattern)
    w_r, w_g, w_b = weights
    return rgb[:, :, 0] * w_r + rgb[:, :, 1] * w_g + rgb[:, :, 2] * w_b


@dataclass(frozen=True)
class BayerAgreement:
    """Comparación real entre el patrón declarado en la cabecera y el que
    los propios píxeles respaldan -- para poder avisar al usuario en vez
    de demosaicar con un patrón equivocado sin decir nada."""

    header_pattern: str | None
    candidate_patterns: tuple[str, ...]
    """Los patrones compatibles con lo que dicen los datos -- vacío si no
    se pudo determinar."""
    agree: bool
    detail: str


def _plane_signature(plane: np.ndarray) -> tuple[float, float, float]:
    """Firma estadística robusta de un plano del mosaico: mediana (nivel),
    MAD (dispersión real, resistente a estrellas saturadas) y percentil
    99 (cuánta señal alta hay). Dos planos del MISMO filtro comparten las
    tres; dos filtros distintos casi nunca."""
    median = float(np.median(plane))
    mad = float(np.median(np.abs(plane - median)))
    p99 = float(np.percentile(plane, 99.0))
    return median, mad, p99


def _signature_distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """Distancia relativa (invariante de escala) entre dos firmas."""
    return sum(abs(x - y) / max(abs(x), abs(y), 1e-9) for x, y in zip(a, b))


def infer_bayer_pattern_from_data(data: np.ndarray) -> tuple[tuple[str, ...], str]:
    """Deduce a partir de los propios píxeles qué patrones son compatibles
    y devuelve `(patrones_candidatos, detalle)`.

    Se apoya en un hecho real de todo CFA de Bayer: los DOS fotositos
    verdes del bloque 2x2 llevan el mismo filtro, así que sus planos
    comparten nivel, dispersión y cola alta, mientras que el rojo y el
    azul difieren. Se comparan las dos diagonales posibles y se elige la
    pareja más parecida como "los dos verdes".

    La comparación usa una firma de TRES estadísticos robustos, no solo
    la mediana: con datos reales de 16 bits las medianas del plano rojo y
    del azul coinciden exactamente muy a menudo (el nivel de bias domina
    y los valores están cuantizados a enteros), y una heurística basada
    solo en la mediana declara empate y no decide nada -- encontrado de
    verdad con los lights reales de M 31 del usuario, donde los cuatro
    planos tenían medianas 2992/3168/3168/2992 (dos empates exactos) pero
    MADs claramente distintas.

    Solo distingue la ORIENTACIÓN de la diagonal verde (RGGB/BGGR frente
    a GRBG/GBRG); cuál de los dos restantes es el rojo y cuál el azul no
    se puede deducir de forma fiable de un campo cualquiera (en una
    nebulosa Hα domina el rojo, en una galaxia azul puede ser al revés),
    así que se devuelven los DOS candidatos, nunca uno inventado."""
    array = _validate_mosaic(data)
    planes = {
        (0, 0): array[0::2, 0::2], (0, 1): array[0::2, 1::2],
        (1, 0): array[1::2, 0::2], (1, 1): array[1::2, 1::2],
    }
    rows = min(p.shape[0] for p in planes.values())
    cols = min(p.shape[1] for p in planes.values())
    signatures = {k: _plane_signature(v[:rows, :cols]) for k, v in planes.items()}

    diagonal = _signature_distance(signatures[(0, 0)], signatures[(1, 1)])      # verdes en (0,0)+(1,1) -> GRBG/GBRG
    antidiagonal = _signature_distance(signatures[(0, 1)], signatures[(1, 0)])  # verdes en (0,1)+(1,0) -> RGGB/BGGR

    closer, farther = min(diagonal, antidiagonal), max(diagonal, antidiagonal)
    # Sin un margen claro entre las dos hipótesis no se decide nada: puede
    # ser una imagen monocroma, ya demosaicada, o un campo sin señal.
    if farther <= closer * 2.0:
        return (), (
            f"los cuatro planos del mosaico son demasiado parecidos entre sí para distinguir la pareja verde "
            f"(distancias {diagonal:.4f} y {antidiagonal:.4f}) -- la imagen no parece un CFA de Bayer sin demosaicar"
        )

    if antidiagonal < diagonal:
        return ("RGGB", "BGGR"), (
            f"los dos planos verdes están en la antidiagonal (distancia entre sus firmas {antidiagonal:.4f}, frente a "
            f"{diagonal:.4f} en la otra diagonal) -- compatible con RGGB o BGGR; cuál de los dos no se puede deducir "
            f"solo de los datos"
        )
    return ("GRBG", "GBRG"), (
        f"los dos planos verdes están en la diagonal principal (distancia entre sus firmas {diagonal:.4f}, frente a "
        f"{antidiagonal:.4f} en la otra) -- compatible con GRBG o GBRG; cuál de los dos no se puede deducir solo de "
        f"los datos"
    )


def describe_bayer_agreement(data: np.ndarray, header: dict | None) -> BayerAgreement:
    """Compara lo que declara la cabecera con lo que respaldan los
    píxeles -- pensado para que el proceso de la GUI pueda avisar
    ("la cabecera dice RGGB pero los datos parecen GRBG/GBRG") en vez de
    demosaicar mal en silencio."""
    header_pattern = bayer_pattern_from_header(header)
    candidates, detail = infer_bayer_pattern_from_data(data)
    if header_pattern is None:
        return BayerAgreement(None, candidates, False, f"La cabecera no declara BAYERPAT. Según los datos: {detail}.")
    if not candidates:
        return BayerAgreement(header_pattern, (), False, f"La cabecera declara {header_pattern}, pero {detail}.")
    if header_pattern in candidates:
        return BayerAgreement(header_pattern, candidates, True, f"La cabecera declara {header_pattern} y los datos lo respaldan: {detail}.")
    return BayerAgreement(
        header_pattern, candidates, False,
        f"AVISO: la cabecera declara {header_pattern}, pero {detail}. Es el caso típico de un FITS guardado con las "
        f"filas invertidas respecto a la orientación en que se escribió BAYERPAT -- comprueba el resultado antes de "
        f"usarlo para fotometría.",
    )
