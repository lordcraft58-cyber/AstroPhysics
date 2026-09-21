"""Escritura y lectura de un espectro 1D calibrado como FITS real (§16,
§38) -- abrible en cualquier otro programa astronómico.

Dos convenciones WCS según la solución realmente ajustada, nunca una
mentira lineal sobre una solución que no lo es (§16, verbatim del
encargo: *"No escribir una relación lineal falsa si la calibración
obtenida es polinómica"*):

- **Grado <= 1** (constante o lineal): WCS lineal estándar,
  `CTYPE1='WAVE'`, `CRPIX1`/`CRVAL1`/`CDELT1` -- el caso simple, exacto,
  que cualquier programa FITS lee sin necesitar saber nada especial.
- **Grado >= 2** (polinómica): convención `-TAB` de "Representations of
  spectral coordinates in FITS" (Greisen, Calabretta, Valdes & Allen
  2006, A&A 446, 747, sección 4) -- una tabla de búsqueda EXACTA
  (`WCS-TAB`, extensión `BinTableHDU`) con la longitud de onda real de
  cada píxel, no una aproximación lineal. Es un estándar FITS publicado,
  no una convención propia de este proyecto.

Ambos casos, además, llevan las tarjetas propias `APSWAVE*` con los
coeficientes exactos del polinomio (round-trip exacto sin pasar por la
tabla, útil para cualquier consumidor de este mismo proyecto) y la
procedencia completa (`CALTYPE`, motor, avisos) de
`calibration_provenance.py`.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
from astropy.io import fits

from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.io.fits_writer import ascii_safe, wrap_history_lines
from astrophysics_suite.spectroscopy.calibration_provenance import (
    WavelengthCalibrationRecord,
    build_wavelength_provenance,
)

_HISTORY_PREFIX = "AstroPhysics Suite:"
_LINEAR_DEGREE_MAX = 1
"""Grado <= este valor se escribe como WCS lineal real; por encima, se
usa la tabla `-TAB` exacta -- nunca una aproximación lineal de un
polinomio de verdad."""

_UNSAFE_FILENAME_CHARS = re.compile(r"[^\w.-]+", re.UNICODE)
_REPEATED_UNDERSCORES = re.compile(r"_+")
_FALLBACK_PRODUCT_BASE = "espectro"
"""Marcador honesto cuando no hay ni `OBJECT` real ni ruta de origen de
la que derivar un nombre -- nunca se inventa un nombre de objeto."""


def standard_product_name(object_name: str | None, source_path: str | Path | None = None, *, kind: str = "1D") -> str:
    """Nombre de producto estándar (§37, p. ej. `Vega_1D.fits`): el
    `OBJECT` real de la cabecera FITS de origen, saneado a caracteres
    seguros de nombre de archivo, o -- si no hay `OBJECT` real -- el
    nombre base de `source_path`; sin ninguno de los dos, el marcador
    honesto `espectro` (nunca un nombre de objeto inventado)."""
    candidate = (object_name or "").strip()
    if not candidate and source_path:
        candidate = Path(source_path).stem
    safe = _UNSAFE_FILENAME_CHARS.sub("_", candidate)
    safe = _REPEATED_UNDERSCORES.sub("_", safe).strip("_")
    if not safe:
        safe = _FALLBACK_PRODUCT_BASE
    return f"{safe}_{kind}.fits"


def processing_history_path_for_product(product_path: str | Path) -> Path:
    """Ruta del historial de procesamiento (§36) que acompaña a un
    producto guardado -- un `.history.json` junto al FITS, nunca
    mezclado con sus datos científicos."""
    return Path(f"{product_path}.history.json")


def wavelength_header_cards(
    record: WavelengthCalibrationRecord, n_pixels: int, *, provenance: Provenance | None = None, bunit: str = "ADU"
) -> tuple[dict[str, Any], np.ndarray | None]:
    """Tarjetas FITS de la calibración -- WCS real más procedencia
    (`CALTYPE`/`APSWAVE*`/`HISTORY`).

    `bunit` describe el propio array de flujo que se está guardando --
    `"ADU"` por defecto (cuentas crudas, el caso de un espectro recién
    calibrado en longitud de onda), pero el llamador debe darlo real
    cuando el flujo ya pasó por una calibración física de verdad
    (p. ej. `"erg/s/cm2/Angstrom"` tras `fluxcal.calibrate_flux`) --
    nunca se asume aquí, y nunca se deja como `"ADU"` cuando no lo es.

    Devuelve `(cards, wave_table)`: `wave_table` es `None` cuando el
    grado permite un WCS lineal exacto (ya está todo en `cards`), o el
    array de longitud de onda por píxel cuando hace falta la tabla
    `-TAB` -- el llamador la escribe como extensión `WCS-TAB`.
    """
    solution = record.solution
    pixels = np.arange(n_pixels, dtype=np.float64)
    wavelengths = np.asarray(solution.pixel_to_wavelength(pixels), dtype=np.float64)

    cards: dict[str, Any] = {
        "CALTYPE": "SYNTHETIC" if record.is_synthetic else "REAL",
        "APSWAVSR": record.source.value,
        "APSWAVDG": int(solution.degree),
        "APSWAVRM": float(solution.rms_residual),
        "APSWAVNL": int(record.n_lines_used),
        "APSWAVNR": int(record.n_lines_rejected),
        "BUNIT": bunit,
    }
    if record.lamp_name:
        cards["APSWAVLM"] = record.lamp_name
    if record.reference_object:
        cards["APSWAVRO"] = record.reference_object

    wave_table: np.ndarray | None = None
    if solution.degree <= _LINEAR_DEGREE_MAX and n_pixels >= 2:
        # Ajuste lineal real (o constante): CRVAL1/CDELT1 describen la
        # solución EXACTAMENTE, no una aproximación -- np.polyval con un
        # polinomio de grado <=1 ES una recta.
        crval = float(solution.pixel_to_wavelength(0.0))
        cdelt = float(solution.coefficients[0]) if solution.degree == 1 else 0.0
        cards.update({"CTYPE1": "WAVE", "CUNIT1": "Angstrom", "CRPIX1": 1.0, "CRVAL1": crval, "CDELT1": cdelt})
    else:
        # Polinómica de verdad: tabla de búsqueda EXACTA (FITS -TAB,
        # Greisen et al. 2006) en vez de mentir con una recta.
        cards.update({
            "CTYPE1": "WAVE-TAB", "CUNIT1": "Angstrom",
            "PS1_0": "WCS-TAB", "PS1_1": "WAVELENGTH", "PV1_1": 1,
        })
        wave_table = wavelengths

    coeff_desc = ", ".join(f"a{i}={c:.6g}" for i, c in enumerate(solution.coefficients[::-1]))
    lines = [f"calibracion en longitud de onda ({record.source.value})"]
    lines.extend(record.describe())
    lines.append(f"coeficientes (grado ascendente): {coeff_desc}")
    if provenance is not None:
        lines.extend(f"! {w}" for w in provenance.warnings)
    cards["HISTORY"] = wrap_history_lines(lines, prefix=_HISTORY_PREFIX)
    return cards, wave_table


def save_spectrum1d_fits(
    path: str,
    flux: np.ndarray,
    record: WavelengthCalibrationRecord,
    *,
    flux_uncertainty: np.ndarray | None = None,
    header: dict[str, Any] | None = None,
    pipeline_version: str = "",
    overwrite: bool = True,
    flux_bunit: str = "ADU",
) -> None:
    """Escribe un espectro 1D calibrado como FITS real (§38): `OBJECT`,
    `DATE-OBS`, `EXPTIME`, `BUNIT`, WCS espectral real (lineal o `-TAB`
    exacta según el grado, ver docstring del módulo), y la procedencia
    completa (`CALTYPE`/avisos) de `calibration_provenance.py`.

    `header`, si se da, aporta metadatos reales de la observación
    (`OBJECT`, `DATE-OBS`, `EXPTIME`...) -- nunca se inventan aquí.
    Las claves de WCS/escalado del header de origen se descartan (igual
    que `astrometry.provenance.strip_wcs_keywords`): un header de un
    FITS 2D crudo no tiene ninguna relación con el eje de longitud de
    onda del espectro 1D extraído.

    `flux_bunit` describe las unidades reales de `flux` -- `"ADU"` por
    defecto. Hallazgo real: antes de este parámetro, `BUNIT` en el
    header de salida SIEMPRE era `"ADU"` pase lo que pase en `header`
    (`wavelength_header_cards` se aplica DESPUÉS y lo pisaba en
    silencio) -- así que un `flux` ya calibrado físicamente (p. ej. por
    `fluxcal.calibrate_flux`, en erg/s/cm2/Å) se guardaba etiquetado
    como si fueran cuentas crudas. Ahora el llamador debe dar las
    unidades reales explícitamente cuando no son ADU.
    """
    flux = np.asarray(flux, dtype=np.float64)
    if flux.ndim != 1:
        raise ValueError("save_spectrum1d_fits requiere un espectro 1D")
    if flux_uncertainty is not None and flux_uncertainty.shape != flux.shape:
        raise ValueError("flux_uncertainty debe tener la misma forma que flux")

    provenance = build_wavelength_provenance(record, pipeline_version=pipeline_version)
    wave_cards, wave_table = wavelength_header_cards(record, flux.size, provenance=provenance, bunit=flux_bunit)

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    hdu = fits.PrimaryHDU(data=flux.astype(np.float32))
    if header:
        for key, value in header.items():
            key_upper = key.upper()
            if key_upper in ("SIMPLE", "BITPIX", "EXTEND", "BZERO", "BSCALE", "BLANK") or key_upper.startswith(
                ("NAXIS", "CTYPE", "CRVAL", "CRPIX", "CDELT", "CUNIT", "PS1_", "PV1_", "WCSAXES")
            ):
                # `NAXIS*` del header de origen describe la imagen 2D
                # cruda -- este producto es 1D, con su propia forma; un
                # `NAXIS2` heredado hace que astropy rechace el archivo
                # entero al escribir (encontrado con el Vega real del
                # usuario: un FITS 2D crudo trae NAXIS2, y este código
                # solo filtraba NAXIS/NAXIS1, dejando pasar NAXIS2).
                continue
            if not isinstance(value, (int, float, bool, str)):
                continue
            try:
                hdu.header[key] = ascii_safe(value) if isinstance(value, str) else value
            except (ValueError, KeyError):
                continue
    for key, value in wave_cards.items():
        if key == "HISTORY":
            for line in value:
                hdu.header.add_history(ascii_safe(str(line)))
        else:
            hdu.header[key] = ascii_safe(value) if isinstance(value, str) else value

    hdus: list[fits.hdu.base._BaseHDU] = [hdu]
    if flux_uncertainty is not None:
        hdus.append(fits.ImageHDU(data=flux_uncertainty.astype(np.float32), name="UNCERT"))
    if wave_table is not None:
        # Convención -TAB: la columna vive en una BinTableHDU con el
        # mismo EXTNAME que declara PS1_0 ("WCS-TAB"), forma (N, 1).
        column = fits.Column(name="WAVELENGTH", format="1D", unit="Angstrom", array=wave_table.reshape(-1, 1))
        table_hdu = fits.BinTableHDU.from_columns([column], name="WCS-TAB")
        hdus.append(table_hdu)

    fits.HDUList(hdus).writeto(path, overwrite=overwrite)


def load_spectrum1d_fits(path: str) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Relee un espectro 1D guardado por `save_spectrum1d_fits` (o
    cualquier FITS 1D con WCS `WAVE`/`WAVE-TAB` estándar): devuelve
    `(wavelength, flux, header)`.

    Reconstruye `wavelength` a partir del WCS real del archivo -- lineal
    (`CRVAL1`/`CDELT1`) o tabla `-TAB` -- nunca supone `lambda = pixel`.
    """
    with fits.open(path) as hdul:
        flux = np.asarray(hdul[0].data, dtype=np.float64)
        header = dict(hdul[0].header)
        n_pixels = flux.size

        ctype = str(header.get("CTYPE1", "")).strip()
        if ctype == "WAVE-TAB":
            extname = str(header.get("PS1_0", "WCS-TAB"))
            if extname not in hdul:
                raise ValueError(f"CTYPE1=WAVE-TAB pero falta la extensión {extname!r} con la tabla de longitud de onda")
            column_name = str(header.get("PS1_1", "WAVELENGTH"))
            wavelength = np.asarray(hdul[extname].data[column_name], dtype=np.float64).reshape(-1)
        elif ctype == "WAVE":
            crpix = float(header.get("CRPIX1", 1.0))
            crval = float(header.get("CRVAL1", 0.0))
            cdelt = float(header.get("CDELT1", 1.0))
            pixel = np.arange(n_pixels, dtype=np.float64)
            wavelength = crval + (pixel + 1.0 - crpix) * cdelt
        else:
            raise ValueError(f"sin WCS de longitud de onda reconocible (CTYPE1={ctype!r}) -- pixel != longitud de onda")

    return wavelength, flux, header


def import_ascii_spectrum(path: str) -> tuple[np.ndarray, np.ndarray, str | None]:
    """Lee un espectro 1D real de un archivo de texto de dos columnas
    (longitud de onda en Å, flujo) -- formato genérico de bibliotecas
    espectrales externas (p. ej. MILES, INDO-US) o de cualquier otro
    programa, NO un formato propio de este proyecto -- para poder usarlo
    como plantilla en "Comparación con plantilla de referencia" sin
    tener que convertirlo a mano.

    Cualquier línea que no empiece por dos números reales se trata como
    cabecera/comentario y se descarta del array de datos -- pero la
    PRIMERA de esas líneas (si la hay) se devuelve tal cual, sin tocar,
    para no perder en silencio el metadato real de origen que traiga
    (p. ej. el identificador y las coordenadas del objeto en la propia
    cabecera del archivo). Exige longitud de onda estrictamente
    creciente -- un archivo desordenado o corrupto debe fallar de forma
    honesta, nunca reordenarse en silencio."""
    wavelengths: list[float] = []
    fluxes: list[float] = []
    header_line: str | None = None
    with open(path, encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split()
            parsed: tuple[float, float] | None = None
            if len(parts) >= 2:
                try:
                    parsed = (float(parts[0]), float(parts[1]))
                except ValueError:
                    parsed = None
            if parsed is not None:
                wavelengths.append(parsed[0])
                fluxes.append(parsed[1])
            elif header_line is None:
                header_line = line

    if len(wavelengths) < 2:
        raise ValueError(f"«{path}» no trae al menos dos filas reales de (longitud de onda, flujo)")
    wavelength = np.asarray(wavelengths, dtype=np.float64)
    flux = np.asarray(fluxes, dtype=np.float64)
    if not np.all(np.diff(wavelength) > 0):
        raise ValueError(
            f"«{path}» no tiene la longitud de onda estrictamente creciente de principio a fin -- "
            "revisa el archivo de origen, no se reordena en silencio"
        )
    return wavelength, flux, header_line


def save_reference_template_fits(
    path: str, wavelength: np.ndarray, flux: np.ndarray, *, object_name: str | None = None,
    source_note: str | None = None, overwrite: bool = True,
) -> None:
    """Escribe `wavelength`/`flux` REALES (p. ej. de `import_ascii_
    spectrum`) como FITS 1D con WCS `WAVE-TAB` EXACTO (§16, misma
    convención -TAB que ya usa `wavelength_header_cards` para una
    calibración polinómica -- tabla de búsqueda real, nunca una recta
    aproximada que introduciría un error que el archivo de origen no
    tenía) -- releíble después por `load_spectrum1d_fits` como plantilla
    en "Comparación con plantilla de referencia".

    Deliberadamente SIN ningún `CALTYPE`/`APSWAVSR` (esas tarjetas
    describen la procedencia de una calibración hecha por ESTE taller,
    `calibration_provenance.py`): un espectro de referencia importado de
    fuera no pasó por ninguna de ellas, y etiquetarlo con esas tarjetas
    sería una procedencia falsa."""
    wavelength = np.asarray(wavelength, dtype=np.float64)
    flux = np.asarray(flux, dtype=np.float64)
    if wavelength.ndim != 1 or wavelength.shape != flux.shape:
        raise ValueError("wavelength y flux deben ser arrays 1D reales de la misma forma")

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    hdu = fits.PrimaryHDU(data=flux.astype(np.float32))
    hdu.header["CTYPE1"] = "WAVE-TAB"
    hdu.header["CUNIT1"] = "Angstrom"
    hdu.header["PS1_0"] = "WCS-TAB"
    hdu.header["PS1_1"] = "WAVELENGTH"
    hdu.header["PV1_1"] = 1
    if object_name:
        hdu.header["OBJECT"] = ascii_safe(object_name)

    lines = ["plantilla de referencia importada de un archivo de texto externo (longitud de onda, flujo)"]
    if source_note:
        lines.append(f"cabecera de origen: {source_note}")
    lines.append("SIN calibracion propia de este taller -- datos tal cual venian en el archivo de origen")
    for line in wrap_history_lines(lines, prefix=_HISTORY_PREFIX):
        hdu.header.add_history(ascii_safe(line))

    column = fits.Column(name="WAVELENGTH", format="1D", unit="Angstrom", array=wavelength.reshape(-1, 1))
    table_hdu = fits.BinTableHDU.from_columns([column], name="WCS-TAB")
    fits.HDUList([hdu, table_hdu]).writeto(path, overwrite=overwrite)
