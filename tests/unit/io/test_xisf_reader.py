"""Pruebas del lector XISF propio (`io.xisf_reader`).

Los archivos de prueba se construyen aquí mismo, byte a byte, siguiendo
el formato real (firma + longitud de cabecera + XML + bloque de datos)
-- nunca dependen de la librería `xisf` de PyPI (GPLv3, deliberadamente
nunca una dependencia de este proyecto, ver el docstring de
`xisf_reader.py`). El formato en sí SÍ se verificó de verdad contra esa
librería como herramienta de desarrollo desechable (nunca en el
producto ni en la suite de tests) -- ver
docs/audit/34-PRUEBAS-CON-FITS-REALES.md."""
from __future__ import annotations

import struct
import zlib

import numpy as np
import pytest

from astrophysics_suite.io.xisf_reader import XISFError, probe_xisf_shape, probe_xisf_signature, read_xisf_image

XISF_SIGNATURE = b"XISF0100"
_BLOCK_ALIGN = 16


def _write_minimal_xisf(
    path, data: np.ndarray, *, color_space: str = "Gray", fits_keywords: dict[str, str] | None = None,
    compression: str | None = None,
) -> None:
    """`data` en forma (alto, ancho) o (alto, ancho, canales). `compression`
    es uno de `None`, `"zlib"`, `"lz4"`, `"lz4+sh"`, `"zstd"`, `"zstd+sh"`
    -- construye el atributo `compression` real y comprime el bloque con
    la misma librería real que usará el lector."""
    if data.ndim == 2:
        height, width = data.shape
        channels = 1
        planar = data
    else:
        height, width, channels = data.shape
        planar = np.transpose(data, (2, 0, 1))  # channels-first, como todo escritor XISF real

    raw = planar.tobytes()
    sample_format = {
        np.dtype("uint8"): "UInt8", np.dtype("uint16"): "UInt16", np.dtype("uint32"): "UInt32",
        np.dtype("float32"): "Float32", np.dtype("float64"): "Float64",
    }[data.dtype]

    compression_attr = ""
    if compression is None:
        block = raw
    else:
        shuffled = compression.endswith("+sh")
        codec = compression[:-3] if shuffled else compression
        item_size = data.dtype.itemsize
        to_compress = raw
        if shuffled:
            arr = np.frombuffer(raw, dtype=np.uint8).reshape(-1, item_size)
            to_compress = arr.T.tobytes()  # shuffle: todos los bytes 0, luego todos los 1, ...
        if codec == "zlib":
            block = zlib.compress(to_compress)
        elif codec in ("lz4", "lz4hc"):
            import lz4.block
            block = lz4.block.compress(to_compress, store_size=False)
        elif codec == "zstd":
            import zstandard
            block = zstandard.ZstdCompressor().compress(to_compress)
        else:
            raise ValueError(codec)
        suffix = f":{item_size}" if shuffled else ""
        compression_attr = f' compression="{compression}:{len(raw)}{suffix}"'

    kw_xml = "".join(
        f'<FITSKeyword name="{k}" value="{v!r}" comment="" />' if isinstance(v, str) else ""
        for k, v in (fits_keywords or {}).items()
    )
    # Offset del bloque de datos: se alinea a un múltiplo de _BLOCK_ALIGN tras
    # la cabecera. Marcador de ancho FIJO (12 dígitos): si se sustituyera por
    # un texto de longitud distinta, cambiaría el tamaño de la propia
    # cabecera XML, y con ello el offset real -- un problema autorreferente
    # que un solo reemplazo no resuelve en general. Con ancho fijo, la
    # sustitución nunca cambia la longitud, así que es exacta de una vez.
    placeholder = "0" * 12
    xml = (
        f'<?xml version="1.0" encoding="utf8"?>'
        f'<xisf xmlns="http://www.pixinsight.com/xisf" version="1.0">'
        f'<Image id="image" geometry="{width}:{height}:{channels}" colorSpace="{color_space}" '
        f'sampleFormat="{sample_format}"{compression_attr} location="attachment:{placeholder}:{len(block)}">{kw_xml}</Image>'
        f'</xisf>'
    )
    xml_bytes = xml.encode("utf-8")
    header_len = len(xml_bytes)
    data_offset = 16 + header_len
    padding = (-data_offset) % _BLOCK_ALIGN
    data_offset += padding
    real_offset_str = str(data_offset).zfill(len(placeholder))
    assert len(real_offset_str) == len(placeholder), "el offset real necesita más dígitos que el ancho fijo reservado -- amplía el marcador"
    xml_bytes = xml_bytes.replace(placeholder.encode("ascii"), real_offset_str.encode("ascii"), 1)

    with open(path, "wb") as f:
        f.write(XISF_SIGNATURE)
        f.write(struct.pack("<I", header_len))
        f.write(b"\x00\x00\x00\x00")
        f.write(xml_bytes)
        f.write(b"\x00" * padding)
        f.write(block)


def test_probe_xisf_signature(tmp_path):
    path = tmp_path / "real.xisf"
    _write_minimal_xisf(path, np.zeros((4, 4), dtype=np.uint16))
    assert probe_xisf_signature(str(path)) is True
    other = tmp_path / "not_xisf.fits"
    other.write_bytes(b"SIMPLE  =                    T\n" + b" " * 100)
    assert probe_xisf_signature(str(other)) is False
    assert probe_xisf_signature(str(tmp_path / "does_not_exist.xisf")) is False


def test_reads_uncompressed_uint16_mono(tmp_path):
    rng = np.random.default_rng(0)
    data = rng.integers(0, 65535, size=(30, 40), dtype=np.uint16)
    path = tmp_path / "mono_u16.xisf"
    _write_minimal_xisf(path, data, fits_keywords={"OBJECT": "M 31", "EXPTIME": "300.0"})

    array, header = read_xisf_image(str(path))
    assert array.shape == (30, 40)
    assert array.dtype == np.uint16
    assert np.array_equal(array, data)
    assert header["OBJECT"] == "M 31"
    assert header["EXPTIME"] == "300.0"


def test_reads_uncompressed_float32_mono(tmp_path):
    rng = np.random.default_rng(1)
    data = rng.random((25, 35), dtype=np.float32).astype(np.float32) * 0.5
    path = tmp_path / "mono_f32.xisf"
    _write_minimal_xisf(path, data)

    array, _ = read_xisf_image(str(path))
    assert array.dtype == np.float32
    assert np.array_equal(array, data)


def test_reads_planar_rgb(tmp_path):
    rng = np.random.default_rng(2)
    data = rng.integers(0, 4095, size=(20, 24, 3), dtype=np.uint16)
    path = tmp_path / "rgb.xisf"
    _write_minimal_xisf(path, data, color_space="RGB")

    array, _ = read_xisf_image(str(path))
    assert array.shape == (20, 24, 3)
    assert np.array_equal(array, data)


@pytest.mark.parametrize("compression", ["zlib", "lz4", "lz4+sh", "zstd", "zstd+sh"])
def test_reads_each_supported_compression_codec(tmp_path, compression):
    rng = np.random.default_rng(3)
    data = rng.integers(2500, 5000, size=(50, 60), dtype=np.uint16)  # rango realista de ADU, como los lights reales
    path = tmp_path / f"compressed_{compression.replace('+', '_')}.xisf"
    _write_minimal_xisf(path, data, compression=compression)

    array, _ = read_xisf_image(str(path))
    assert np.array_equal(array, data)


def test_rejects_file_without_real_xisf_signature(tmp_path):
    path = tmp_path / "fake.xisf"
    path.write_bytes(b"NOT-XISF" + b"\x00" * 100)
    with pytest.raises(XISFError, match="no es un archivo XISF"):
        read_xisf_image(str(path))


def test_rejects_unsupported_location_kind(tmp_path):
    xml = (
        b'<?xml version="1.0" encoding="utf8"?>'
        b'<xisf xmlns="http://www.pixinsight.com/xisf" version="1.0">'
        b'<Image id="image" geometry="4:4:1" colorSpace="Gray" sampleFormat="UInt16" location="inline:base64" />'
        b'</xisf>'
    )
    path = tmp_path / "inline.xisf"
    with open(path, "wb") as f:
        f.write(XISF_SIGNATURE)
        f.write(struct.pack("<I", len(xml)))
        f.write(b"\x00\x00\x00\x00")
        f.write(xml)
    with pytest.raises(XISFError, match="location"):
        read_xisf_image(str(path))


def test_probe_xisf_shape_mono_matches_real_shape_without_decompressing(tmp_path):
    data = np.zeros((30, 40), dtype=np.uint16)
    path = tmp_path / "mono.xisf"
    _write_minimal_xisf(path, data, compression="zlib")  # comprimido -- probe no debe necesitar descomprimir
    assert probe_xisf_shape(str(path)) == (30, 40)


def test_probe_xisf_shape_rgb_reports_channels_first_like_a_cube(tmp_path):
    data = np.zeros((30, 40, 3), dtype=np.uint16)
    path = tmp_path / "rgb.xisf"
    _write_minimal_xisf(path, data, color_space="RGB")
    assert probe_xisf_shape(str(path)) == (3, 30, 40)


def test_rejects_truncated_data_block(tmp_path):
    data = np.zeros((10, 10), dtype=np.uint16)
    path = tmp_path / "truncated.xisf"
    _write_minimal_xisf(path, data)
    # Trunca el archivo a la mitad del bloque de datos declarado.
    raw = path.read_bytes()
    path.write_bytes(raw[: len(raw) - 50])
    with pytest.raises(XISFError, match="no cabe en el archivo real"):
        read_xisf_image(str(path))
