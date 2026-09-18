"""Lector XISF (Extensible Image Serialization Format, el formato nativo
de PixInsight) -- implementación propia desde cero, NUNCA envuelve la
librería `xisf` de PyPI: esa librería es GPLv3, incompatible con la
licencia comercial cerrada de este producto (ver decisión del usuario y
docs/audit/34-PRUEBAS-CON-FITS-REALES.md). El formato XISF en sí es una
especificación pública de PixInsight/Pleiades Astrophoto -- no está bajo
GPL, solo esa implementación concreta lo está.

## Cobertura real (verificada, no solo escrita a partir de la especificación)

Se generaron archivos XISF reales con una herramienta de desarrollo
independiente (la librería GPLv3 mencionada arriba, usada solo como
herramienta de verificación en un entorno de desarrollo desechable --
NUNCA como dependencia del producto, ni importada desde ningún módulo de
`astrophysics_suite`/`qt_app`) y se decodificaron con este lector,
comparando los píxeles resultantes byte a byte contra los originales
(`tests/unit/io/test_xisf_reader.py`). Cubre:

- Bloques de imagen monolíticos `location="attachment:offset:size"` (el
  caso real al exportar/guardar desde PixInsight) -- sin compresión, y
  con compresión `zlib`, `lz4`/`lz4hc` (con y sin byte-shuffling) y
  `zstd` (con y sin byte-shuffling).
- `sampleFormat`: `UInt8/16/32/64`, `Float32/64` (verificados contra
  datos reales); `Complex32/64` está implementado siguiendo la
  especificación pero SIN verificar contra un archivo real (la
  astrofotografía normal nunca produce datos complejos).
- `colorSpace` Gray y RGB, almacenamiento planar (un plano contiguo por
  canal -- el que produce todo escritor XISF real).
- `FITSKeyword` -> dict de cabecera, mismo vocabulario que un header
  FITS real, para que el resto del pipeline (que ya sabe leer
  OBJECT/EXPTIME/RA/DEC/etc. de un dict) funcione sin cambios.

## Lo que NO cubre (explícito, no silencioso)

Bloques `inline`/`embedded` (datos en base64 dentro del propio XML) o
`path:` (referencia a un archivo externo); múltiples imágenes por
archivo (solo se lee la primera salvo que se pida otro índice);
verificación de `checksum` (se ignora si está presente). Cualquiera de
estos casos lanza `XISFError` con un mensaje explícito -- nunca decodifica
en silencio con un resultado incorrecto."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np

XISF_SIGNATURE = b"XISF0100"
_XISF_NS = "{http://www.pixinsight.com/xisf}"

_SAMPLE_FORMAT_DTYPES: dict[str, np.dtype] = {
    "UInt8": np.dtype("uint8"),
    "UInt16": np.dtype("uint16"),
    "UInt32": np.dtype("uint32"),
    "UInt64": np.dtype("uint64"),
    "Float32": np.dtype("float32"),
    "Float64": np.dtype("float64"),
    "Complex32": np.dtype("complex64"),
    "Complex64": np.dtype("complex128"),
}


class XISFError(ValueError):
    """El archivo no es un XISF válido, o usa una característica que este
    lector propio no cubre todavía (ver el docstring del módulo) --
    nunca se decodifica un resultado parcial o adivinado."""


def probe_xisf_signature(path: str) -> bool:
    """Comprobación barata (lee 8 bytes) de si `path` es un XISF real --
    para que el diálogo "Abrir" pueda decidir qué lector usar sin
    depender solo de la extensión del archivo."""
    try:
        with open(path, "rb") as f:
            return f.read(8) == XISF_SIGNATURE
    except OSError:
        return False


def is_xisf_path(path: str) -> bool:
    """`True` si `path` es (por extensión o por firma real) un XISF --
    único punto de esta decisión, usado por `fits_loader.py` y
    `fits_header_reader.py` para no duplicar el criterio."""
    return str(path).lower().endswith(".xisf") or probe_xisf_signature(str(path))


def _read_xisf_header_xml(path: str) -> bytes:
    """Bytes crudos de la cabecera XML -- solo lee los 16 bytes de
    preámbulo más la cabecera declarada, sin tocar el bloque de datos
    (barato incluso para archivos grandes comprimidos)."""
    p = Path(path)
    with open(p, "rb") as f:
        prefix = f.read(16)
        if prefix[:8] != XISF_SIGNATURE:
            raise XISFError(f"{path}: no es un archivo XISF válido (firma esperada {XISF_SIGNATURE!r}, encontrada {prefix[:8]!r})")
        header_len = struct.unpack("<I", prefix[8:12])[0]
        xml_bytes = f.read(header_len)
        if len(xml_bytes) != header_len:
            raise XISFError(f"{path}: la cabecera XML declara {header_len} bytes pero el archivo está truncado")
    return xml_bytes


def _find_xisf_image_element(path: str, xml_bytes: bytes, *, index: int = 0) -> ET.Element:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise XISFError(f"{path}: la cabecera XML del XISF no es válida: {exc}") from exc
    images = root.findall(f"{_XISF_NS}Image")
    if not images:
        raise XISFError(f"{path}: el archivo XISF no contiene ninguna imagen")
    if index >= len(images):
        raise XISFError(f"{path}: se pidió la imagen {index}, el archivo solo tiene {len(images)}")
    return images[index]


def _parse_geometry(path: str, image_elem: ET.Element) -> tuple[int, int, int]:
    geometry = image_elem.get("geometry", "")
    dims = geometry.split(":")
    if len(dims) != 3 or not all(d.isdigit() for d in dims):
        raise XISFError(f"{path}: geometry {geometry!r} no reconocida (se esperaba ancho:alto:canales)")
    width, height, channels = (int(d) for d in dims)
    return width, height, channels


def probe_xisf_shape(path: str, *, index: int = 0) -> tuple[int, ...]:
    """Forma real de la imagen sin descomprimir los píxeles -- solo lee y
    parsea la cabecera XML (barato incluso para bloques grandes
    comprimidos). Mismo convenio que `fits_loader.probe_fits_shape`:
    `(alto, ancho)` para una imagen normal, o `(canales, alto, ancho)`
    cuando hay más de un canal (tratado igual que un cubo FITS -- el
    llamador decide qué plano/canal usar, nunca se elige el primero en
    silencio)."""
    image_elem = _find_xisf_image_element(path, _read_xisf_header_xml(path), index=index)
    width, height, channels = _parse_geometry(path, image_elem)
    return (height, width) if channels == 1 else (channels, height, width)


def read_xisf_header(path: str, *, index: int = 0) -> dict[str, str | bool | int | float]:
    """Cabecera real de un XISF como dict `{nombre: valor}` -- sin tocar
    el bloque de píxeles en absoluto (ni siquiera comprobar su tamaño),
    para clasificar sesiones enteras de archivos por cabecera sin pagar
    el coste de descomprimir cada imagen (mismo propósito que
    `fits_header_reader.read_fits_header` para FITS)."""
    image_elem = _find_xisf_image_element(path, _read_xisf_header_xml(path), index=index)
    return _parse_fits_keywords(image_elem)


def _unshuffle(data: bytes, item_size: int) -> bytes:
    """Deshace el byte-shuffling (todos los bytes N de cada elemento
    consecutivos, luego todos los N+1, ...) antes de reinterpretar los
    bytes descomprimidos como el dtype real -- necesario porque XISF
    aplica el shuffle ANTES de comprimir para mejorar la compresión de
    datos numéricos tipados."""
    if item_size <= 1:
        return data
    n_items, remainder = divmod(len(data), item_size)
    if remainder != 0:
        raise XISFError(f"tamaño de datos ({len(data)}) no es múltiplo del tamaño de elemento ({item_size}) al deshacer el shuffle")
    shuffled = np.frombuffer(data, dtype=np.uint8).reshape(item_size, n_items)
    return shuffled.T.tobytes()


def _decompress_block(raw: bytes, compression: str | None) -> bytes:
    if not compression:
        return raw
    parts = compression.split(":")
    codec = parts[0]
    if len(parts) < 2:
        raise XISFError(f"atributo compression {compression!r} no reconocido (falta el tamaño sin comprimir)")
    uncompressed_size = int(parts[1])
    shuffled = codec.endswith("+sh")
    codec_name = codec[:-3] if shuffled else codec
    item_size = int(parts[2]) if shuffled and len(parts) > 2 else 1

    if codec_name == "zlib":
        decompressed = zlib.decompress(raw)
    elif codec_name in ("lz4", "lz4hc"):
        try:
            import lz4.block
        except ImportError as exc:
            raise XISFError("este XISF usa compresión LZ4 -- instala el paquete 'lz4' (pip install lz4) para poder leerlo") from exc
        decompressed = lz4.block.decompress(raw, uncompressed_size=uncompressed_size)
    elif codec_name == "zstd":
        try:
            import zstandard
        except ImportError as exc:
            raise XISFError("este XISF usa compresión zstd -- instala el paquete 'zstandard' (pip install zstandard) para poder leerlo") from exc
        decompressed = zstandard.ZstdDecompressor().decompress(raw, max_output_size=uncompressed_size)
    else:
        raise XISFError(f"códec de compresión XISF no soportado por este lector: {codec_name!r}")

    if len(decompressed) != uncompressed_size:
        raise XISFError(f"tamaño descomprimido inesperado: la cabecera declara {uncompressed_size} bytes, se obtuvieron {len(decompressed)}")
    return _unshuffle(decompressed, item_size) if shuffled else decompressed


def _parse_fits_keyword_value(raw: str) -> str | bool | int | float:
    """Convierte el valor literal de un `FITSKeyword` al tipo real que
    representa -- igual que la propia sintaxis de una tarjeta FITS:
    entrecomillado -> texto; `T`/`F` -> lógico; si no, numérico
    (entero si no lleva punto/exponente, si no coma flotante).

    Bug real encontrado probando con un XISF real de M31 (con WCS en los
    FITSKeyword): sin esta conversión, CRVAL1/CRPIX1/CD1_1/etc. llegaban
    como texto Python (`"10.9131301993"`) a `astropy.io.fits.Header`, que
    los escribía como tarjetas de TEXTO en vez de numéricas -- astropy.wcs
    los aceptaba con un aviso ("a floating-point value was expected") pero
    calculaba un WCS completamente incorrecto (RA/Dec desviadas decenas
    de grados), peor que no tener WCS -- nunca detectado hasta ejecutar
    la carga real de extremo a extremo, exactamente el motivo de probar
    siempre con datos reales antes de dar algo por terminado."""
    if len(raw) >= 2 and raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1].strip()
    if raw == "T":
        return True
    if raw == "F":
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw  # no numérico ni entrecomillado -- se conserva tal cual, nunca se descarta


def _parse_fits_keywords(image_elem: ET.Element) -> dict[str, str | bool | int | float]:
    header: dict[str, str | bool | int | float] = {}
    for kw in image_elem.findall(f"{_XISF_NS}FITSKeyword"):
        name = kw.get("name", "")
        if name:
            header[name] = _parse_fits_keyword_value(kw.get("value", ""))
    return header


def read_xisf_image(path: str, *, index: int = 0) -> tuple[np.ndarray, dict[str, str | bool | int | float]]:
    """Lee una imagen real de un archivo XISF. Devuelve `(datos, header)`:
    `datos` es un array numpy real (nunca una vista sobre un buffer
    comprimido), forma `(alto, ancho)` para imágenes monocromas o
    `(alto, ancho, canales)` para RGB -- mismo convenio channels-last que
    usa el resto del pipeline; `header` es un dict `{nombre: valor}`
    extraído de los `FITSKeyword` reales del archivo, mismo vocabulario
    que un header FITS."""
    data = Path(path).read_bytes()
    header_len = len(_read_xisf_header_xml(path))  # valida firma/truncado con el mismo mensaje que el resto de funciones
    image_elem = _find_xisf_image_element(path, data[16:16 + header_len], index=index)
    width, height, channels = _parse_geometry(path, image_elem)

    sample_format = image_elem.get("sampleFormat", "")
    dtype = _SAMPLE_FORMAT_DTYPES.get(sample_format)
    if dtype is None:
        raise XISFError(f"{path}: sampleFormat {sample_format!r} no soportado por este lector (soportados: {sorted(_SAMPLE_FORMAT_DTYPES)})")
    if image_elem.get("byteOrder") == "big":
        dtype = dtype.newbyteorder(">")

    location = image_elem.get("location", "")
    loc_parts = location.split(":")
    if len(loc_parts) != 3 or loc_parts[0] != "attachment":
        raise XISFError(f"{path}: location {location!r} no soportada -- este lector solo cubre bloques 'attachment' (el caso normal al exportar/guardar desde PixInsight)")
    offset, size = int(loc_parts[1]), int(loc_parts[2])
    raw_block = data[offset:offset + size]
    if len(raw_block) != size:
        raise XISFError(f"{path}: el bloque de datos declarado ({size} bytes en el offset {offset}) no cabe en el archivo real ({len(data)} bytes)")

    pixel_bytes = _decompress_block(raw_block, image_elem.get("compression"))

    expected_bytes = width * height * channels * dtype.itemsize
    if len(pixel_bytes) != expected_bytes:
        raise XISFError(f"{path}: tamaño de datos ({len(pixel_bytes)} bytes) no coincide con lo esperado por geometry/sampleFormat ({expected_bytes} bytes)")

    array = np.frombuffer(pixel_bytes, dtype=dtype)
    if channels == 1:
        array = array.reshape(height, width)
    else:
        # Almacenamiento planar (un plano contiguo por canal) -> (alto, ancho, canales)
        array = array.reshape(channels, height, width).transpose(1, 2, 0)

    return np.array(array), _parse_fits_keywords(image_elem)
