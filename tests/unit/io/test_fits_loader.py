"""Prueba end-to-end (no simulada) de io/fits_loader.py: escribe un FITS
real y lo carga a través del wrapper nuevo, apoyado en `load_fits`/
`sha256_file` heredados."""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from astrophysics_suite.io.fits_loader import AmbiguousCubeError, build_observation, load_fits, load_image, probe_fits_shape
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d


def test_load_image_builds_real_image_ref(tmp_path):
    data = np.full((32, 32), 100.0, dtype=np.float32)
    path = tmp_path / "target_OIII.fits"
    _write_minimal_fits_2d(path, data, pixel_scale_arcsec=1.2)

    loaded = load_image(str(path), band="OIII")

    assert loaded.image_ref.band == "OIII"
    assert loaded.image_ref.role == "science"
    assert loaded.image_ref.pixel_scale_arcsec == pytest.approx(1.2, rel=1e-3)
    assert loaded.image_ref.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert loaded.legacy_image.data.shape == (32, 32)


def test_build_observation_from_real_files(tmp_path):
    oiii = np.full((16, 16), 50.0, dtype=np.float32)
    ha = np.full((16, 16), 60.0, dtype=np.float32)
    oiii_path = tmp_path / "target_OIII.fits"
    ha_path = tmp_path / "target_HALPHA.fits"
    _write_minimal_fits_2d(oiii_path, oiii, pixel_scale_arcsec=0.9)
    _write_minimal_fits_2d(ha_path, ha, pixel_scale_arcsec=0.9)

    observation, loaded = build_observation(
        [(str(oiii_path), "OIII"), (str(ha_path), "HA")],
        observation_id="OBS-TEST-0001",
        target_name="NGC 6960",
    )

    assert observation.observation_id == "OBS-TEST-0001"
    assert {im.band for im in observation.images} == {"OIII", "HA"}
    assert len(loaded) == 2
    # `loaded` se indexa por `ImageRef.path` (la ruta ya resuelta), que es
    # exactamente como la busca `run_generic_discovery` -- nunca por la
    # ruta cruda que recibió esta función, que puede ser un texto distinto
    # aunque señale al mismo archivo (ver test de la ruta relativa abajo).
    for image_ref in observation.images:
        assert loaded[image_ref.path].image_ref == image_ref
    oiii_loaded = next(li for li in loaded.values() if li.image_ref.band == "OIII")
    assert oiii_loaded.legacy_image.data.shape == (16, 16)

    # Roundtrip real: lo que se serializa se puede reconstruir idéntico.
    from astrophysics_suite.models.observation import Observation

    restored = Observation.from_dict(observation.to_dict())
    assert restored == observation


def test_build_observation_indexes_loaded_images_by_resolved_path_not_raw_input(tmp_path, monkeypatch):
    """Regresión de un bug real reportado en uso: si el llamador pasa una
    ruta cuyo texto difiere de `Path(ruta).resolve()` (una ruta relativa,
    o en Windows una ruta con '/' devuelta por `QFileDialog` mientras
    `Path.resolve()` normaliza a '\\'), `loaded_images[image_ref.path]`
    (la búsqueda real que hace `run_generic_discovery`) debía funcionar
    siempre -- antes del fix lanzaba `KeyError` porque el diccionario se
    indexaba por la ruta cruda, no por la resuelta."""
    data = np.full((16, 16), 50.0, dtype=np.float32)
    path = tmp_path / "target_OIII.fits"
    _write_minimal_fits_2d(path, data, pixel_scale_arcsec=0.9)

    monkeypatch.chdir(tmp_path)
    relative_path = path.name
    assert relative_path != str(Path(relative_path).resolve()), "la ruta relativa debe diferir de su forma resuelta para que el test reproduzca el bug real"

    observation, loaded = build_observation(
        [(relative_path, "OIII")],
        observation_id="OBS-TEST-0002",
        target_name="Campo con ruta relativa",
    )

    assert len(observation.images) == 1
    image_ref = observation.images[0]
    assert image_ref.path in loaded  # la búsqueda que hace run_generic_discovery
    assert loaded[image_ref.path].legacy_image.data.shape == (16, 16)


def test_load_image_handles_bzero_bscale_fits_without_memmap_error(tmp_path):
    """Bug real reportado en uso: astropy no puede memory-mapear un HDU cuyo
    header declara BZERO/BSCALE/BLANK -- la convención estándar con la que
    casi cualquier cámara CCD/CMOS de 16 bits guarda datos sin signo -- y solo
    lo descubre al acceder a `.data`, no al abrir el archivo
    ("Cannot load a memory-mapped image: BZERO/BSCALE/BLANK header keywords
    present. Set memmap=False."). `load_fits` debe manejarlo de forma
    transparente en vez de propagar el ValueError."""
    from astropy.io import fits

    raw_values = (np.arange(400, dtype=np.uint16).reshape(20, 20) + 1000)
    path = tmp_path / "camera_16bit_OIII.fits"
    fits.PrimaryHDU(raw_values).writeto(path)

    loaded = load_image(str(path), band="OIII")  # no debe lanzar ValueError de memmap

    np.testing.assert_array_equal(loaded.legacy_image.data.astype(np.uint16), raw_values)


def _write_cube_fits(path, shape):
    """FITS real con más de 2 ejes -- `_write_minimal_fits_2d` solo
    escribe 2D, así que estas pruebas necesitan astropy directamente."""
    from astropy.io import fits

    data = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    fits.PrimaryHDU(data).writeto(path)
    return data


def test_open_3d_fits_without_plane_raises_ambiguous_cube_error(tmp_path):
    """Bug real reportado en uso: "no me deja abrir imágenes de 3
    dimensiones". Antes del selector de plano de la GUI, esto era todo lo
    que un FITS 3D/4D podía hacer -- lanzar, sin ningún camino de vuelta.
    Verificado que sigue lanzando `AmbiguousCubeError` (comportamiento
    correcto y deliberado: nunca elegir un plano en silencio) para poder
    probar por separado que ahora SÍ hay una forma real de continuar
    (`plane=` explícito, ver el test siguiente)."""
    path = tmp_path / "cube_HA.fits"
    _write_cube_fits(path, (5, 24, 24))

    with pytest.raises(AmbiguousCubeError):
        load_image(str(path), band="HA")


def test_load_image_with_explicit_plane_selects_correct_2d_slice(tmp_path):
    path = tmp_path / "cube_HA.fits"
    data = _write_cube_fits(path, (5, 24, 24))

    loaded = load_image(str(path), band="HA", plane=2)

    assert loaded.legacy_image.data.shape == (24, 24)
    np.testing.assert_array_equal(loaded.legacy_image.data, data[2])
    assert loaded.legacy_image.original_shape == (5, 24, 24)
    assert loaded.legacy_image.selected_plane == (2,)
    assert loaded.legacy_image.cube_plane_is_explicit is True


def test_load_image_with_explicit_plane_tuple_selects_correct_slice_for_4d_cube(tmp_path):
    path = tmp_path / "cube4d.fits"
    data = _write_cube_fits(path, (3, 4, 16, 16))

    loaded = load_image(str(path), band="", plane=(1, 2))

    assert loaded.legacy_image.data.shape == (16, 16)
    np.testing.assert_array_equal(loaded.legacy_image.data, data[1, 2])


def test_load_fits_skips_a_non_image_extension_to_find_the_real_2d_frame(tmp_path):
    """§1: un fotograma 2D real (de espectroscopía o de cualquier otro
    origen) puede llegar con una HDU primaria vacía y/o una extensión de
    tabla real por delante (p. ej. un registro de órdenes de un echelle,
    o un log de adquisición) -- `_first_image_hdu_index` debe saltarlas y
    encontrar la imagen real, nunca fallar ni coger la tabla por error."""
    from astropy.io import fits

    data = np.full((41, 300), 1234.5, dtype=np.float32)
    path = tmp_path / "frame_with_table_extension.fits"
    primary = fits.PrimaryHDU()  # HDU primaria vacía, real en muchos productos de espectrógrafo
    table = fits.BinTableHDU.from_columns([fits.Column(name="ORDER", format="J", array=np.arange(5))])
    image = fits.ImageHDU(data=data, name="SCI")
    fits.HDUList([primary, table, image]).writeto(path)

    loaded = load_fits(str(path))

    assert loaded.hdu_index == 2  # la imagen real, no la HDU primaria vacía ni la extensión de tabla
    assert loaded.data.shape == (41, 300)
    np.testing.assert_allclose(loaded.data, data)


def test_probe_fits_shape_reads_shape_without_loading_pixels(tmp_path):
    path = tmp_path / "cube_OIII.fits"
    _write_cube_fits(path, (7, 30, 20))

    shape = probe_fits_shape(str(path))

    assert shape == (7, 30, 20)


def test_probe_fits_shape_matches_2d_fits(tmp_path):
    data = np.full((16, 16), 50.0, dtype=np.float32)
    path = tmp_path / "flat_OIII.fits"
    _write_minimal_fits_2d(path, data)

    assert probe_fits_shape(str(path)) == (16, 16)


def test_load_image_raises_a_real_clear_error_for_a_corrupt_file(tmp_path):
    """Nunca debe devolver una imagen inventada ni fallar en silencio --
    la GUI (`open_fits`) depende de que esto lance de verdad para poder
    mostrar el error real al usuario, no de que ella misma lo invente."""
    path = tmp_path / "not_really_a_fits.fits"
    path.write_bytes(b"esto no es un FITS real, solo texto")

    with pytest.raises(OSError, match="FITS"):
        load_image(str(path), band="OIII")


def test_load_image_raises_a_real_clear_error_for_a_missing_file():
    with pytest.raises(FileNotFoundError):
        load_image("/tmp/este_archivo_no_existe_nunca.fits", band="OIII")
