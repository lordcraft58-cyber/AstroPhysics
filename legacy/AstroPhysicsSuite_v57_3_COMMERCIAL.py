#!/usr/bin/env python3
"""
AstroPhysics Suite v57.0.0 — astrophysical discovery platform
"""
from __future__ import annotations

import os as _os_boot
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS", "BLIS_NUM_THREADS",
           "GOTO_NUM_THREADS", "OPENBLAS_MAIN_FREE"):
    _os_boot.environ[_k] = "1"
del _os_boot, _k

import argparse
import csv
import dataclasses
import gc
import hashlib
import io
import json
import logging
import math
import os
import platform
import re
import shutil
import sys
import textwrap
import statistics
import time
import threading
import urllib.parse
import urllib.request
import zipfile

# Windows/VS Code: fuerza UTF-8 para consola y depurador, evitando UnicodeEncodeError
# con caracteres científicos como Δ, α, β, μ y −. El manejo binario/FITS no se modifica.
if sys.platform == "win32":
    for _stream_name in ("stdout", "stderr"):
        try:
            _stream = getattr(sys, _stream_name)
            if hasattr(_stream, "reconfigure"):
                _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass
    del _stream_name
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Protocol

import numpy as np
import scipy.ndimage as ndi
from scipy import optimize
from scipy.interpolate import PchipInterpolator
from scipy.special import erf

# Compatibilidad NumPy 1.x/2.x para integración numérica.
trapezoid = getattr(np, "trapezoid", None)
if trapezoid is None:
    from scipy.integrate import trapezoid

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from torch.utils.data import TensorDataset, DataLoader
    HAS_TORCH = True
except Exception:
    torch = nn = F = TensorDataset = DataLoader = None
    HAS_TORCH = False

try:
    from scipy import sparse as _sparse
    HAS_SPARSE = True
except Exception:
    _sparse = None
    HAS_SPARSE = False

try:
    import photutils  # noqa: F401
    try:
        photutils.future_column_names = True
    except Exception:
        pass
except Exception:
    photutils = None

try:
    from photutils.background import Background2D, MedianBackground, SigmaClip
    HAS_PHOTUTILS_BACKGROUND = True
except Exception:
    Background2D = MedianBackground = SigmaClip = None
    HAS_PHOTUTILS_BACKGROUND = False

try:
    from photutils.detection import DAOStarFinder
    HAS_PHOTUTILS_DAO = True
except Exception:
    DAOStarFinder = None
    HAS_PHOTUTILS_DAO = False

HAS_PHOTUTILS = bool(HAS_PHOTUTILS_BACKGROUND or HAS_PHOTUTILS_DAO)

try:
    import openpyxl  # noqa: F401
    HAS_OPENPYXL = True
except Exception:
    openpyxl = None
    HAS_OPENPYXL = False

__version__ = "57.0.0"
SCHEMA_VERSION = 39
LOG = logging.getLogger("aps")
try:
    logging.getLogger("fontTools").setLevel(logging.WARNING)
except Exception:
    pass


# ====================================================================
# v30: FILTROS PERMITIDOS
# ====================================================================
# Solo se permiten dos familias de filtros. No se inventan curvas T(lambda);
# los datos nominales del fabricante se usan para identificación/QC, mientras
# que la calibración espectrofotométrica exige una respuesta espectral real.
FILTER_PRESETS = {
    "SVBONY SV220 Hα/OIII 7 nm": {
        "manufacturer": "SVBONY", "model": "SV220", "type": "dual-band",
        "fwhm_oiii_nm": 7.0, "fwhm_ha_nm": 7.0,
        "oiii_center_nm": 500.7, "ha_center_nm": 656.3,
        "oiii_peak_min": 0.90, "ha_peak_min": 0.94,
        "oiii_transmission": 0.90, "ha_transmission": 0.94, "blocking": ">OD5",
        "approximate": False, "calibration_ready": False,
        "source": "SVBONY official product specification",
        "warning": "Especificación nominal: para calibración espectrofotométrica trazable se requiere T(lambda) real."
    },
    "Optolong L-Quad Enhance": {
        "manufacturer": "Optolong", "model": "L-Quad Enhance", "type": "broadband-quad",
        "fwhm_oiii_nm": None, "fwhm_ha_nm": None,
        "oiii_center_nm": 500.7, "ha_center_nm": 656.3,
        "approximate": True, "calibration_ready": False,
        "source": "Optolong L-QEF official specification",
        "warning": "Filtro de banda ancha de cuatro bandas; no se usa una curva T(lambda) inventada. Para fotometría/espectrofotometría cuantitativa se requiere la respuesta medida del filtro y del sistema cámara+óptica."
    }
}
FILTER_VISIBLE = list(FILTER_PRESETS.keys())
FILTER_NARROWBAND_VISIBLE = ["SVBONY SV220 Hα/OIII 7 nm"]
FILTER_BROADBAND_CONTEXT_VISIBLE = ["Optolong L-Quad Enhance"]
FILTER_DEFAULT = FILTER_NARROWBAND_VISIBLE[0]

CAMERA_PROFILE_ASI533MC_PRO = {
    "name": "ZWO ASI533MC Pro",
    "sensor": "Sony IMX533",
    "format": "1 inch",
    "resolution": (3008, 3008),
    "pixel_size_um": 3.76,
    "adc_bits": 14,
    "full_well_e": 50000.0,
    "qe_peak": 0.80,
    "read_noise_e_range": (1.0, 3.8),
    "cooling_delta_t_max_c": 35.0,
    "response_status": "nominal_manufacturer",
    "warning": "QE real del conjunto cámara+óptica no sustituida por un único valor pico.",
}

@dataclass
class FilterTransmission:
    name: str
    wavelength_nm: np.ndarray
    transmission: np.ndarray
    source_type: str
    source_reference: Optional[str] = None
    source_url: Optional[str] = None
    source_file: Optional[str] = None
    sha256: Optional[str] = None
    version: str = "1.0"
    date_added_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    approximate: bool = False
    units: str = "nm"

@dataclass
class FilterResponse:
    name_filter: str
    transmission_oiii_4959: float
    transmission_oiii_5007: float
    transmission_ha_6563: float
    transmission_nii_6548: float
    transmission_nii_6584: float
    integration_method: str = "sample_at_line"
    warnings: list[str] = field(default_factory=list)

def _normalise_curve_columns(rows):
    if not rows:
        raise ValueError("Curva de filtro vacía")
    cols = {str(k).strip().lower(): k for k in rows[0].keys()}
    wk = next((cols[k] for k in ("wavelength_nm","wavelength_angstrom","wavelength","lambda_nm","lambda") if k in cols), None)
    tk = next((cols[k] for k in ("transmission","throughput","t","response") if k in cols), None)
    if wk is None or tk is None:
        raise ValueError(f"Curva requiere wavelength_nm/wavelength_angstrom + Transmission; columnas={list(rows[0].keys())}")
    wl=[]; tr=[]
    is_angstrom = "angstrom" in str(wk).lower()
    for r in rows:
        try:
            w=float(r[wk]); t=float(r[tk])
        except (TypeError,ValueError):
            continue
        if math.isfinite(w) and math.isfinite(t): wl.append(w * (0.1 if is_angstrom else 1.0)); tr.append(t)
    if len(wl)<2: raise ValueError("Curva con menos de 2 puntos válidos")
    wl=np.asarray(wl,float); tr=np.asarray(tr,float)
    order=np.argsort(wl); wl=wl[order]; tr=tr[order]
    keep=np.r_[True,np.diff(wl)>0]; wl=wl[keep]; tr=tr[keep]
    if tr.max()>1.0 and tr.max()<=100.0:
        tr=tr/100.0
    tr=np.clip(tr,0.0,1.0)
    if len(wl)<2 or np.any(~np.isfinite(tr)):
        raise ValueError("Curva de transmisión inválida")
    return wl,tr,"Å→nm" if is_angstrom else "nm"

def load_filter_curve(path, name=None):
    p=Path(path)
    if not p.is_file(): raise FileNotFoundError(str(p))
    suf=p.suffix.lower()
    if suf == ".json":
        with p.open(encoding="utf-8") as fh: data=json.load(fh)
        rows=data.get("curve",data) if isinstance(data,dict) else data
        if isinstance(rows,dict):
            wk="wavelength_angstrom" if "wavelength_angstrom" in rows else "wavelength_nm" if "wavelength_nm" in rows else "wavelength"
            tk="Transmission" if "Transmission" in rows else "transmission" if "transmission" in rows else "throughput"
            if wk in rows and tk in rows: rows=[{wk:w,tk:t} for w,t in zip(rows[wk],rows[tk])]
    else:
        text=p.read_text(encoding="utf-8-sig"); rows=[]
        try:
            dialect=csv.Sniffer().sniff(text[:8192],delimiters=",;\t")
            rows=list(csv.DictReader(io.StringIO(text),dialect=dialect))
        except csv.Error:
            pass
        if not rows:
            lines=[ln.strip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith(("#",";"))]
            if len(lines)>=2:
                header=re.split(r"[\s,;\t]+",lines[0])
                for ln in lines[1:]:
                    parts=re.split(r"[\s,;\t]+",ln)
                    if len(parts)>=len(header): rows.append(dict(zip(header,parts)))
    wl,tr,unit_note=_normalise_curve_columns(rows)
    return FilterTransmission(name=name or p.stem,wavelength_nm=wl,transmission=tr,
                              source_type="usuario_supplied",source_reference=str(p.resolve()),
                              source_file=str(p.resolve()),sha256=sha256_file(p),approximate=False,
                              units="nm",version="user-1.0"),unit_note


def _curve_eval(curve, wave_nm):
    return float(np.interp(float(wave_nm), curve.wavelength_nm, curve.transmission, left=0.0, right=0.0))

def build_filter_response(curve: FilterTransmission, name=None):
    source_note="Curva T(λ) medida/proporcionada" if (curve is not None and not bool(getattr(curve,"approximate",False))) else "Curva T(λ) nominal/aproximada"
    return FilterResponse(name_filter=name or curve.name,
                          transmission_oiii_4959=_curve_eval(curve,495.9),
                          transmission_oiii_5007=_curve_eval(curve,500.7),
                          transmission_ha_6563=_curve_eval(curve,656.3),
                          transmission_nii_6548=_curve_eval(curve,654.8),
                          transmission_nii_6584=_curve_eval(curve,658.4),
                          warnings=[f"{source_note}: integración simplificada en líneas; QE/atmósfera no incluidas salvo que se proporcionen."])

def demix_two_filters(o1,o2,t1_oiii,t1_ha,t2_oiii,t2_ha,sigma1=None,sigma2=None,mc=0,seed=0):
    A=np.array([[float(t1_oiii),float(t1_ha)],[float(t2_oiii),float(t2_ha)]],float)
    det=float(np.linalg.det(A))
    cond=float(np.linalg.cond(A)) if np.all(np.isfinite(A)) else float("inf")
    if not np.all(np.isfinite(A)): raise ValueError("Matriz de demezcla con valores no finitos")
    if abs(det)<1e-6 or not np.isfinite(cond) or cond>100:
        raise ValueError(f"Demezcla bloqueada: matriz singular/mal condicionada (det={det:.3g}, cond={cond:.3g})")
    if min(A.ravel())<0: raise ValueError("Demezcla bloqueada: transmisiones negativas")
    y=np.array([float(o1),float(o2)], dtype=float)
    if not np.all(np.isfinite(y)):
        raise ValueError("Demezcla bloqueada: observaciones no finitas")
    a,b,c,d = A[0,0], A[0,1], A[1,0], A[1,1]
    inv_det = 1.0 / det
    x0 = (d*y[0] - b*y[1]) * inv_det
    x1 = (-c*y[0] + a*y[1]) * inv_det
    result={"oiii":float(x0),"ha":float(x1),"determinant":det,"condition_number":cond,"method":"2x2-direct-determinant-inversion"}
    if mc and sigma1 is not None and sigma2 is not None:
        if not (math.isfinite(float(sigma1)) and math.isfinite(float(sigma2)) and float(sigma1) >= 0 and float(sigma2) >= 0):
            raise ValueError("Demezcla bloqueada: incertidumbre MC inválida")
        rng=np.random.default_rng(seed)
        ys=np.column_stack([rng.normal(o1,sigma1,mc),rng.normal(o2,sigma2,mc)])
        xs=np.empty_like(ys,dtype=float)
        xs[:,0]=(d*ys[:,0]-b*ys[:,1])*inv_det
        xs[:,1]=(-c*ys[:,0]+a*ys[:,1])*inv_det
        result["mc_percentiles"]={"oiii":[float(v) for v in np.percentile(xs[:,0],[16,50,84])],"ha":[float(v) for v in np.percentile(xs[:,1],[16,50,84])]}
    return result



def _photometric_validation_evidence(photometric_calibrated, zeropoint_source, zeropoint_error_mag, oiii_curve, ha_curve, calibration_id):
    """Valida la evidencia mínima para declarar calibración fotométrica.

    Un booleano del usuario nunca es suficiente. Requerimos origen del zeropoint,
    incertidumbre positiva, curvas con hash y, para la modalidad validada, un ID de
    calibración que permita rastrear la sesión/estándar utilizado.
    """
    source_ok=bool(str(zeropoint_source or '').strip())
    err_ok=math.isfinite(float(zeropoint_error_mag)) and float(zeropoint_error_mag)>0
    curve_hash_ok=all(bool(getattr(c,'sha256',None)) for c in (oiii_curve,ha_curve))
    curve_provenance_ok=all((not bool(getattr(c,'approximate',False))) and bool(getattr(c,'source_reference',None) or getattr(c,'source_file',None)) for c in (oiii_curve,ha_curve))
    cal_id_ok=bool(str(calibration_id or '').strip())
    return {"requested":bool(photometric_calibrated),"zeropoint_source":source_ok,
            "zeropoint_error":err_ok,"filter_curve_hashes":curve_hash_ok,"filter_curve_provenance":curve_provenance_ok,
            "calibration_id":cal_id_ok,
            "complete":bool(source_ok and err_ok and curve_hash_ok and curve_provenance_ok and cal_id_ok)}


def calibrate_from_filters(oiii_filter_name, ha_filter_name,
                           exptime_oiii=1.0, exptime_ha=1.0,
                           nii_over_ha=0.0, ebv=0.0, ebv_err=0.0,
                           oiii_curve: Optional[FilterTransmission]=None,
                           ha_curve: Optional[FilterTransmission]=None,
                           photometric_calibrated: bool = False,
                           oiii_zp_factor: float = 1.0,
                           ha_zp_factor: float = 1.0,
                           r_v: float = 3.1,
                           zeropoint_source: str = "",
                           zeropoint_error_mag: float = float("nan"),
                           calibration_id: str = ""):
    """Construye la corrección de líneas y determina si puede declararse validada.

    Los presets aproximados y las curvas de transmisión no equivalen por sí solos
    a una calibración fotométrica. La bandera explícita del usuario solo habilita
    productos dependientes de la grilla cuando las curvas y zeropoints proceden
    de una calibración instrumental documentada.
    """
    for label, value in (("EXPTIME OIII", exptime_oiii), ("EXPTIME Hα", exptime_ha),
                         ("NII/Hα", nii_over_ha), ("E(B−V)", ebv), ("σE(B−V)", ebv_err),
                         ("R_V", r_v), ("ZP OIII", oiii_zp_factor), ("ZP Hα", ha_zp_factor)):
        if not math.isfinite(float(value)):
            raise ValueError(f"{label} no finito")
    if float(exptime_oiii) <= 0 or float(exptime_ha) <= 0:
        raise ValueError("EXPTIME debe ser > 0")
    if float(ebv) < 0 or float(ebv_err) < 0:
        raise ValueError("E(B−V) y su incertidumbre deben ser >= 0")
    if not (2.0 <= float(r_v) <= 6.0):
        raise ValueError("R_V fuera del dominio CCM89 implementado (2.0–6.0)")
    if float(nii_over_ha) < -1.0:
        raise ValueError("NII/Hα no puede ser < -1")
    unknown = {"oiii_transmission":1.0, "ha_transmission":1.0}
    fo = FILTER_PRESETS.get(oiii_filter_name, unknown)
    fh = FILTER_PRESETS.get(ha_filter_name, unknown)
    o3_t = float(fo.get("oiii_transmission", 1.0))
    ha_t = float(fh.get("ha_transmission", 1.0))
    curve_ok = oiii_curve is not None and ha_curve is not None
    lqef_selected = (oiii_filter_name == "Optolong L-Quad Enhance" or ha_filter_name == "Optolong L-Quad Enhance")
    if lqef_selected and not curve_ok:
        raise ValueError("L-QEF es broadband: para convertirlo en respuesta espectral cuantitativa se requiere T(lambda) medida del filtro/sistema.")
    if curve_ok:
        required = ((oiii_curve, 495.9, "OIII 495.9"), (oiii_curve, 500.7, "OIII 500.7"),
                    (ha_curve, 656.3, "Hα 656.3"), (ha_curve, 654.8, "[N II] 654.8"),
                    (ha_curve, 658.4, "[N II] 658.4"))
        for curve, wave, label in required:
            lo, hi = float(np.min(curve.wavelength_nm)), float(np.max(curve.wavelength_nm))
            if not (lo <= wave <= hi):
                raise ValueError(f"Curva de usuario no cubre {label} Å ({wave/10:.1f} nm): rango {lo:.2f}–{hi:.2f} nm")
        o3_t = max((_curve_eval(oiii_curve, 495.9) + 3.0*_curve_eval(oiii_curve, 500.7))/4.0, 1e-6)
        ha_t = max(_curve_eval(ha_curve, 656.3), 1e-6)
        t6548 = max(_curve_eval(ha_curve, 654.8), 0.0)
        t6584 = max(_curve_eval(ha_curve, 658.4), 0.0)
        nii_rel = (0.25*t6548 + 0.75*t6584) / ha_t
        if o3_t <= 0 or ha_t <= 0:
            raise ValueError("Curvas de usuario con transmisión nula en líneas principales")
    ex_o3 = float(exptime_oiii) if exptime_oiii > 0 else 1.0
    ex_ha = float(exptime_ha) if exptime_ha > 0 else 1.0
    zp_o3 = float(oiii_zp_factor)
    zp_ha = float(ha_zp_factor)
    if not (math.isfinite(zp_o3) and zp_o3 > 0): zp_o3 = 1.0
    if not (math.isfinite(zp_ha) and zp_ha > 0): zp_ha = 1.0
    f = (ha_t / o3_t) * (ex_ha / ex_o3) * (zp_ha / zp_o3)
    nii_rel = locals().get("nii_rel", 1.0)
    # La contribución [N II] que entra en la banda Hα depende de la transmisión
    # relativa del filtro en 654.8/658.4 nm. No se aplica ya como factor plano.
    f *= max(0.0, 1.0 + float(nii_over_ha) * float(nii_rel))
    # CCM89: cualquier fallo de dominio o parámetro debe abortar la calibración;
    # nunca se permite devolver silenciosamente un factor sin extinción.
    dk = ccm89_alav(5007.0, float(r_v)) - ccm89_alav(6563.0, float(r_v))
    f *= 10 ** (0.4 * float(ebv) * float(r_v) * dk)
    validation_evidence=_photometric_validation_evidence(photometric_calibrated, zeropoint_source, zeropoint_error_mag, oiii_curve, ha_curve, calibration_id)
    zp_frac_err=(0.4*math.log(10)*float(zeropoint_error_mag)) if math.isfinite(float(zeropoint_error_mag)) and float(zeropoint_error_mag)>0 else 0.0
    validated=bool(validation_evidence["requested"] and curve_ok and validation_evidence["complete"])
    if photometric_calibrated and not validated:
        missing=[k for k,v in validation_evidence.items() if k not in {"requested","complete"} and not v]
        basis = "calibration_requested_but_unvalidated"
        warning=("Se solicitó calibración validada pero faltan evidencias: " + ", ".join(missing) + ". Resultado no validado.")
    elif validated:
        basis = "validated_photometric"
        warning = ("Calibración fotométrica marcada explícitamente por el usuario. "
                   "Las curvas y zeropoints deben proceder de una calibración instrumental "
                   "documentada; cualquier velocidad/temperatura/tiempo sigue condicionada "
                   "a la grilla y a sus hipótesis.")
    elif curve_ok:
        basis = "user_curve_relative"
        warning = ("Curvas de usuario aplicadas como corrección relativa de respuesta. "
                   "No es calibración fotométrica absoluta.")
    else:
        basis = "preset_approximate"
        warning = ("Preset de transmisión nominal: el cociente permanece instrumental/relativo. "
                   "No se permite tratar L-QEF como una respuesta estrecha Halpha/OIII.")
    return LineCalibration(
        oiii_transmission=o3_t, ha_transmission=ha_t,
        oiii_exptime_s=ex_o3, ha_exptime_s=ex_ha,
        oiii_zp_factor=zp_o3, ha_zp_factor=zp_ha,
        nii_over_ha=float(nii_over_ha), nii_transmission_rel=float(nii_rel), ebv=float(ebv), ebv_err=float(ebv_err), r_v=float(r_v),
        calib_frac_err=float(zp_frac_err), calibrated=validated, oiii_filter=oiii_filter_name, ha_filter=ha_filter_name,
        calibration_basis=basis, calibration_warning=warning,
        photometric_calibrated=validated,
        zeropoint_source=str(zeropoint_source),
        zeropoint_error_mag=float(zeropoint_error_mag) if math.isfinite(float(zeropoint_error_mag)) else float("nan"),
        calibration_id=str(calibration_id), validation_evidence=dict(validation_evidence)), f, validated


# ====================================================================
# GRILLA EMBEBIDA
# ====================================================================
DEFAULT_SHOCK_GRID_CSV = """v_kms,ratio,n0
80,0.05,1.0
100,0.10,1.0
120,0.20,1.0
150,0.40,1.0
180,0.80,1.0
200,1.20,1.0
250,2.50,1.0
300,5.00,1.0
350,7.00,1.0
400,8.50,1.0
450,9.50,1.0
500,10.0,1.0
80,0.02,10.0
100,0.05,10.0
150,0.20,10.0
200,0.60,10.0
250,1.30,10.0
300,2.50,10.0
350,3.80,10.0
400,5.00,10.0
450,5.80,10.0
500,6.50,10.0
100,0.01,100.0
150,0.05,100.0
200,0.20,100.0
250,0.50,100.0
300,1.00,100.0
350,1.50,100.0
400,2.00,100.0
450,2.40,100.0
500,2.80,100.0
"""


# ====================================================================
# RAM / WORKERS
# ====================================================================
def _available_ram_gb() -> float:
    try:
        import psutil
        return psutil.virtual_memory().available / 1024 ** 3
    except Exception:
        pass
    try:
        if sys.platform == "win32":
            import ctypes

            class _MSX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = _MSX(); m.dwLength = ctypes.sizeof(_MSX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return float(m.ullAvailPhys) / 1024 ** 3
        if hasattr(os, "sysconf"):
            return float(os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")) / 1024 ** 3
    except Exception:
        pass
    return 8.0


def _safe_worker_count(requested: int) -> int:
    ncpu = os.cpu_count() or 2
    ram = _available_ram_gb()
    ram_cap = max(1, int((ram - 2.0) / 0.5))
    hard_cap = 4 if sys.platform == "win32" else 6
    return max(1, min(int(requested), ncpu - 1, ram_cap, hard_cap))


# ====================================================================
# DEPENDENCIAS
# ====================================================================
try:
    from astropy.io import fits as _fits
    from astropy.wcs import WCS as _WCS
    from astropy.wcs.utils import proj_plane_pixel_scales as _pps
    try:
        from astropy.io import ascii as _ascii
    except Exception:
        _ascii = None
    HAS_ASTROPY = True
except Exception:
    _fits = _WCS = _pps = _ascii = None
    HAS_ASTROPY = False

try:
    from skimage.registration import phase_cross_correlation as _pcc
    HAS_SKIMAGE = True
except Exception:
    _pcc = None
    HAS_SKIMAGE = False

try:
    from skimage.feature import canny as _canny
    HAS_CANNY = True
except Exception:
    _canny = None
    HAS_CANNY = False

try:
    import importlib.util as _ilu
    import signal as _signal
    HAS_SKLEARN = _ilu.find_spec("sklearn") is not None
    del _ilu
except Exception:
    HAS_SKLEARN = False

try:
    import pandas as pd  # noqa: F401
    HAS_PANDAS = True
except Exception:
    pd = None
    HAS_PANDAS = False

try:
    import matplotlib
    matplotlib.use("Agg")
    # PDF con fuentes Unicode: evita errores de codificación de caracteres griegos en Windows.
    try:
        matplotlib.rcParams["pdf.fonttype"] = 42
        matplotlib.rcParams["ps.fonttype"] = 42
    except Exception:
        pass
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.patches import Rectangle
    import matplotlib.pyplot as plt
    HAS_MPL = True
except Exception:
    Figure = PdfPages = Rectangle = plt = None
    HAS_MPL = False

try:
    from astroquery.simbad import Simbad
    HAS_SIMBAD = True
except Exception:
    HAS_SIMBAD = False

try:
    from astroquery.gaia import Gaia
    HAS_GAIA = True
except Exception:
    Gaia = None
    HAS_GAIA = False


RESEARCH_SOURCES = {
    "Fesen+2021_725pc": "https://arxiv.org/abs/2109.05368",
    "Fesen+2018_735pc": "https://academic.oup.com/mnras/article/481/2/1786/5088377",
    "Raymond+2020_CygLoop": "https://iopscience.iop.org/article/10.3847/1538-4357/abb821",
    "Hester+1994_OIII": "https://ui.adsabs.harvard.edu/abs/1994ApJ...422..721H",
    "Alarie+2019_3MdB": "https://arxiv.org/abs/1908.08579",
    "Allen+2008_MAPPINGSIII": "https://arxiv.org/abs/0805.0204",
    "Sutherland+Dopita_1993": "https://ui.adsabs.harvard.edu/abs/1993ApJS...88..253S",
    "Cardelli+1989_CCM": "https://ui.adsabs.harvard.edu/abs/1989ApJ...345..245C",
}


# ====================================================================
# LITERATURA
# ====================================================================
LITERATURE_DB = {
    "veil": {
        "canonical": "Cygnus Loop / Veil Nebula",
        "aliases": ["ngc 6960", "ngc6960", "ngc 6992", "ngc6992", "ngc 6995", "ngc6995",
                    "ic 1340", "ic1340", "cygnus loop", "veil nebula", "veil", "sh2-103",
                    "witch's broom", "cirrus nebula"],
        "distance_pc": (735.0, 25.0, "Fesen et al. 2018"),
        "v_shock_kms": (70.0, 150.0, "Raymond et al. 2020 (NE)"),
        "age_yr": (10000.0, 20000.0, "Levenson et al. 1998"),
        "radius_pc": (18.0, 20.0, "Fesen et al. 2021 (radio)"),
        "n0_cm3": (0.1, 10.0, "Raymond et al. 2020"),
        "ratio_oiii_ha": (0.3, 2.5, "Hester et al. 1994"),
        "notes": "SNR tipo shell en Cygnus; distancia Gaia EDR3 ~725-735 pc.",
    },
    "cas_a": {
        "canonical": "Cassiopeia A",
        "aliases": ["cassiopeia a", "cas a", "casa", "3c 461", "3c461"],
        "distance_pc": (3400.0, 300.0, "Reed et al. 1995"),
        "v_shock_kms": (4000.0, 6000.0, "Vink et al. 2022"),
        "age_yr": (340.0, 20.0, "Fesen et al. 2006"),
        "radius_pc": (1.6, 0.1, "Gotthelf et al. 2001"),
    },
    "tycho": {
        "canonical": "SN 1572 (Tycho)",
        "aliases": ["sn 1572", "sn1572", "tycho", "tycho's supernova", "3c 10", "3c10"],
        "distance_pc": (3000.0, 500.0, "Ruiz-Lapuente 2004"),
        "v_shock_kms": (4000.0, 8000.0, "Raymond et al. 2021"),
        "age_yr": (453.0, 5.0, "Año 1572"),
        "radius_pc": (3.7, 0.3, "Warren et al. 2005"),
    },
    "kepler": {
        "canonical": "SN 1604 (Kepler)",
        "aliases": ["sn 1604", "sn1604", "kepler", "3c 358"],
        "distance_pc": (5900.0, 800.0, "Reynolds et al. 2007"),
        "v_shock_kms": (1500.0, 4000.0, "Vink 2008"),
        "age_yr": (415.0, 5.0, "Año 1604"),
    },
    "sn1006": {
        "canonical": "SN 1006",
        "aliases": ["sn 1006", "sn1006", "pks 1459-41"],
        "distance_pc": (2200.0, 200.0, "Winkler et al. 2003"),
        "v_shock_kms": (2800.0, 6000.0, "Winkler et al. 2014"),
        "age_yr": (1014.0, 5.0, "Año 1006"),
    },
    "vela": {
        "canonical": "Vela SNR",
        "aliases": ["vela", "vela snr", "msh 08-44"],
        "distance_pc": (287.0, 10.0, "Dodson et al. 2003"),
        "v_shock_kms": (300.0, 500.0, "Aschenbach et al. 1995"),
        "age_yr": (11000.0, 1000.0, "Reichley et al. 1970"),
    },
    "ic443": {
        "canonical": "IC 443 (Jellyfish)",
        "aliases": ["ic 443", "ic443", "jellyfish nebula", "sh2-248"],
        "distance_pc": (1500.0, 100.0, "Olbert et al. 2001"),
        "v_shock_kms": (30.0, 100.0, "Lee et al. 2012"),
        "age_yr": (20000.0, 5000.0, "Petre et al. 1988"),
    },
    "w44": {
        "canonical": "W44 (G34.7-0.4)",
        "aliases": ["w44", "g34.7-0.4", "3c 392"],
        "distance_pc": (3000.0, 200.0, "Cardillo et al. 2016"),
        "v_shock_kms": (100.0, 300.0, "Reach et al. 2019"),
    },
}


def find_literature(target_name: str) -> Optional[dict]:
    if not target_name:
        return None
    name = target_name.strip().lower().replace("-", " ").replace("_", " ")
    name_compact = name.replace(" ", "")
    best = None
    best_score = 0
    for key, entry in LITERATURE_DB.items():
        for alias in entry.get("aliases", []):
            a = alias.lower().replace("-", " ").replace("_", " ")
            a_compact = a.replace(" ", "")
            if name_compact == a_compact:
                score = 100
            elif a_compact in name_compact or name_compact in a_compact:
                score = len(a_compact)
            else:
                score = 0
            if score > best_score:
                best_score = score
                best = {"key": key, **entry, "matched_alias": alias}
    return best


# ====================================================================
# CLAVES DE PERFIL
# ====================================================================
def profile_key(row) -> Optional[str]:
    try:
        x = int(round(float(row["x"])))
        y = int(round(float(row["y"])))
        return f"{x:05d}_{y:05d}"
    except Exception:
        return None


def profile_key_of(x, y) -> str:
    return f"{int(round(float(x))):05d}_{int(round(float(y))):05d}"


def star_profile_key(det_id: int) -> str:
    return f"star_{int(det_id):04d}"


# ====================================================================
# GAIA
# ====================================================================
GAIA_MAX_RADIUS_DEG = 1.0
GAIA_DEFAULT_MAG_LIMIT = 18.0


def query_gaia_sources(ra_deg, dec_deg, radius_deg=0.5, mag_limit=GAIA_DEFAULT_MAG_LIMIT,
                       max_rows=2000):
    if not HAS_GAIA:
        return None
    radius_deg = min(float(radius_deg), GAIA_MAX_RADIUS_DEG)
    try:
        query = f"""
        SELECT TOP {int(max_rows)}
            source_id, ra, dec, pmra, pmdec, parallax, parallax_error,
            phot_g_mean_mag, phot_bp_mean_mag, phot_rp_mean_mag, bp_rp,
            radial_velocity, ruwe, astrometric_excess_noise,
            teff_gspphot, logg_gspphot, mh_gspphot, distance_gspphot,
            ag_gspphot, classprob_dsc_combmod_star
        FROM gaiadr3.gaia_source
        WHERE 1=CONTAINS(
            POINT('ICRS', ra, dec),
            CIRCLE('ICRS', {ra_deg:.6f}, {dec_deg:.6f}, {radius_deg:.6f})
        )
          AND phot_g_mean_mag < {mag_limit}
        ORDER BY phot_g_mean_mag ASC
        """
        LOG.info("Gaia cone search: RA=%.5f Dec=%.5f r=%.3f°", ra_deg, dec_deg, radius_deg)
        job = Gaia.launch_job_async(query=query)
        return job.get_results()
    except Exception as exc:
        LOG.warning("Gaia falló: %s", exc)
        return None


def estimate_field_center_from_gaia(ra_hint, dec_hint, radius_deg=0.5,
                                     mag_limit=17.0, max_rows=3000):
    if not HAS_GAIA:
        return None, None, 0, "Gaia no disponible"
    tbl = query_gaia_sources(ra_hint, dec_hint, radius_deg, mag_limit, max_rows)
    if tbl is None or len(tbl) < 5:
        n = 0 if tbl is None else len(tbl)
        return None, None, n, f"Gaia: solo {n} fuentes"
    ra = np.asarray(tbl["ra"], float)
    dec = np.asarray(tbl["dec"], float)
    ra_c = float(np.median(ra))
    dec_c = float(np.median(dec))
    return (ra_c, dec_c, len(tbl),
            f"Gaia DR3 centroide: {len(tbl)} fuentes → RA={ra_c:.5f}°, Dec={dec_c:.5f}°")


def gaia_distance_pc(ra_deg, dec_deg, radius_deg=0.3, max_rows=500):
    """Deprecated: no uses mediana de paralajes de estrellas de campo como distancia del remanente."""
    raise RuntimeError("No se permite derivar la distancia del remanente con la mediana de estrellas de campo; use una distancia justificada e independiente.")


def verify_wcs_with_gaia(im, detected_sources, max_match_arcsec=3.0):
    """Comprueba WCS mediante correspondencias estrictamente uno-a-uno."""
    if im.wcs is None or not HAS_GAIA or detected_sources is None or len(detected_sources) < 5:
        return None
    try:
        H,W=im.data.shape
        ra0,dec0=im.pixel_to_world(np.array([W/2]),np.array([H/2]))
        if not (math.isfinite(ra0[0]) and math.isfinite(dec0[0])): return None
        scale=im.pixel_scale_arcsec or 1.0
        radius_deg=math.hypot(H,W)*scale/3600.0/2.0
        tbl=query_gaia_sources(ra0[0],dec0[0],radius_deg,mag_limit=18.0,max_rows=3000)
        if tbl is None or len(tbl)<5: return None
        gra=np.asarray(tbl["ra"],float); gdec=np.asarray(tbl["dec"],float)
        gx,gy=im.wcs.celestial.all_world2pix(gra,gdec,0)
        det_xy=np.asarray(detected_sources[:,:2],float); gxy=np.column_stack([gx,gy])
        tol_px=max_match_arcsec/max(scale,1e-6)
        if det_xy.size==0 or gxy.size==0:
            return {"n_matched":0,"rms_arcsec":float("nan"),"offset_arcsec":float("nan"),"matching":"hungarian_1to1","initial_pairs":0,"inliers":0,"outliers":0}
        from scipy.optimize import linear_sum_assignment
        C=np.linalg.norm(det_xy[:,None,:]-gxy[None,:,:],axis=2)
        penalty=tol_px*10.0
        Cg=np.where(np.isfinite(C)&(C<tol_px),C,penalty)
        ri,ci=linear_sum_assignment(Cg)
        good=np.isfinite(C[ri,ci])&(C[ri,ci]<tol_px)
        ri,ci=ri[good],ci[good]
        n0=len(ri)
        if n0<3:
            return {"n_matched":n0,"rms_arcsec":float("nan"),"offset_arcsec":float("nan"),"matching":"hungarian_1to1","initial_pairs":n0,"inliers":n0,"outliers":0}
        dd=np.column_stack([det_xy[ri,0]-gxy[ci,0],det_xy[ri,1]-gxy[ci,1]])
        for _ in range(3):
            rr=np.hypot(dd[:,0],dd[:,1]); med=float(np.median(rr)); mad=float(1.4826*np.median(np.abs(rr-med)))
            thr=max(0.8*tol_px,med+3.0*max(mad,1e-6)); keep=rr<=thr
            if keep.sum()<3 or keep.sum()==len(dd): break
            dd=dd[keep]
        dx=dd[:,0]*scale; dy=dd[:,1]*scale
        return {"n_matched":int(len(dd)),"rms_arcsec":float(np.sqrt(np.mean(dx**2+dy**2))),"offset_arcsec":float(np.hypot(np.mean(dx),np.mean(dy))),"median_dx_arcsec":float(np.median(dx)),"median_dy_arcsec":float(np.median(dy)),"matching":"hungarian_1to1","initial_pairs":n0,"inliers":int(len(dd)),"outliers":int(n0-len(dd))}
    except Exception as exc:
        LOG.warning("verify_wcs_with_gaia falló: %s", exc); return None


# SIMBAD
# ====================================================================
_SIMBAD_TYPE_KEYWORDS = (
    "snr", "hii", "pn", "pne", "agn", "lin", "sbg", "bir", "rneb", "drkn", "ism",
    "mol", "cld", "cor", "com", "gal",
    "glc", "opc", "cl*", "asc", "moc", "grp",
    "eb*", "v*", "by*", "rs*", "lpv", "wvir", "c*", "cv*", "xb*", "lm*",
    "sb*", "**", "wr*", "be*", "em*", "tt*", "y*", "ae*", "fu*", "or*",
    "x", "gam", "lmc", "smc", "psr", "pulsar", "radio", "rfb", "bll", "qso",
    "asteroid", "planet", "satellite",
    "g", "gi", "ggg", "lea", "sb", "lin", "sed",
)


def pretty_simbad_type(otype):
    code = str(otype or "").strip()
    lo = code.lower()
    mapping = {
        "v*": "estrella variable", "eb*": "binaria eclipsante",
        "**": "sistema doble/múltiple", "em*": "estrella de emisión",
        "be*": "estrella Be", "snr": "remanente de supernova",
        "hii": "región H II", "pn": "nebulosa planetaria",
        "agn": "núcleo galáctico activo", "g": "galaxia",
        "glc": "cúmulo globular", "cl*": "cúmulo abierto",
        "x": "fuente de rayos X", "ism": "medio interestelar",
        "mol": "nube molecular", "cor": "núcleo denso",
        "rfb": "fuente de radio", "psr": "púlsar", "gam": "fuente de rayos γ",
        "wr*": "estrella Wolf-Rayet", "tt*": "estrella T Tauri",
    }
    for k, label in mapping.items():
        if lo == k or lo.startswith(k + "."):
            return label
    return code


def is_simbad_interesting(otype):
    lo = str(otype or "").lower()
    if not lo:
        return False
    for bad in ("*", "**", "ir", "nIR", "opt"):
        if lo == bad:
            return False
    if "x" == lo or lo.startswith("x") or lo in ("x", "xb*", "x.*"):
        return True
    return any(k in lo for k in _SIMBAD_TYPE_KEYWORDS)


def query_simbad_field(ra_deg, dec_deg, radius_deg=0.6, max_rows=500):
    if not HAS_SIMBAD or not HAS_ASTROPY:
        return []
    try:
        from astropy.coordinates import SkyCoord
        import astropy.units as u
        sb = Simbad()
        sb.ROW_LIMIT = int(max_rows)
        try:
            sb.add_votable_fields("otype", "sptype")
        except Exception:
            pass
        coord = SkyCoord(float(ra_deg), float(dec_deg), unit="deg", frame="icrs")
        tab = sb.query_region(coord, radius=float(radius_deg) * u.deg)
        if tab is None or len(tab) == 0:
            return []
        names = list(tab.colnames)
        otype_col = next((c for c in ("otype", "OTYPE", "otype_txt") if c in names), None)
        sptype_col = next((c for c in ("sp_type", "SP_TYPE", "sp_type_txt") if c in names), None)
        LOG.info("SIMBAD columnas: otype=%s sptype=%s (total=%d)", otype_col, sptype_col, len(names))
        out = []
        for rec in tab:
            def sval(col, *alts):
                for c in (col,) + alts:
                    if c in names:
                        try:
                            v = rec[c]
                            if v is None or (isinstance(v, str) and not v.strip()):
                                continue
                            return str(v)
                        except Exception:
                            continue
                return ""
            try:
                ra = float(rec["ra"])
            except Exception:
                ra = float("nan")
            try:
                dec = float(rec["dec"])
            except Exception:
                dec = float("nan")
            otype = sval(otype_col) if otype_col else ""
            out.append({
                "main_id": sval("main_id", "MAIN_ID"),
                "ra_deg": ra,
                "dec_deg": dec,
                "otype": otype,
                "sp_type": sval(sptype_col) if sptype_col else "",
            })
        LOG.info("SIMBAD: %d objetos en %.2f°", len(out), radius_deg)
        return out
    except Exception as exc:
        LOG.warning("SIMBAD campo fallo: %s", exc)
        return []


# ====================================================================
# CARACTERIZACIÓN ESTELAR
# ====================================================================
def stellar_spectral_class(teff, bp_rp=float("nan")):
    t = finite(teff, float("nan"))
    if not math.isfinite(t):
        c = finite(bp_rp, float("nan"))
        if math.isfinite(c):
            if c < -0.2: return "B/A"
            if c < 0.3: return "A/F"
            if c < 0.8: return "F/G"
            if c < 1.4: return "G/K"
            return "K/M"
        return "?"
    if t >= 30000: return "O"
    if t >= 10000: return "B"
    if t >= 7500: return "A"
    if t >= 6000: return "F"
    if t >= 5200: return "G"
    if t >= 3700: return "K"
    return "M"


def stellar_luminosity_class(logg):
    g = finite(logg, float("nan"))
    if not math.isfinite(g):
        return ""
    if g < 1.8: return "supergigante"
    if g < 3.2: return "gigante"
    if g < 4.0: return "subgigante"
    return "sec. principal"


def stellar_interest_note(row):
    notes = []
    simbad_type = str(row.get("simbad_otype") or "").lower()
    if str(row.get("simbad_main_id") or "").strip():
        notes.append("identificada en SIMBAD")
    if any(k in simbad_type for k in ("eb*", "by*", "rs*", "lpv", "v*", "rot*")):
        notes.append("actividad/variabilidad")
    if "**" in simbad_type or "**" in str(row.get("simbad_sptype") or "").lower():
        notes.append("sistema múltiple")
    if any(k in simbad_type for k in ("em*", "be*", "hae", "yb*")):
        notes.append("emisión")
    teff = finite(row.get("teff_k"), float("nan"))
    if math.isfinite(teff):
        if teff >= 15000: notes.append("caliente")
        elif teff <= 3800: notes.append("fría")
    pm = finite(row.get("pm_total_masyr"), float("nan"))
    if math.isfinite(pm) and pm >= 80:
        notes.append(f"μ alto ({pm:.0f} mas/a)")
    ag = finite(row.get("ag_mag"), float("nan"))
    if math.isfinite(ag) and ag >= 1.5:
        notes.append(f"extinción G={ag:.2f}")
    rv = finite(row.get("radial_velocity_kms"), float("nan"))
    if math.isfinite(rv) and abs(rv) >= 100:
        notes.append(f"RV={rv:+.0f} km/s")
    return "; ".join(dict.fromkeys(notes)) or "sin indicador destacado"


def _match_points_one_to_one(det_xy, target_xy, max_dist):
    """Asignación estrictamente uno-a-uno dentro de max_dist usando Hungarian."""
    det_xy=np.asarray(det_xy,float); target_xy=np.asarray(target_xy,float)
    if det_xy.size==0 or target_xy.size==0: return np.empty((0,2),int)
    if det_xy.ndim!=2 or target_xy.ndim!=2 or det_xy.shape[1]!=2 or target_xy.shape[1]!=2:
        raise ValueError("Coordenadas de matching deben ser Nx2")
    from scipy.optimize import linear_sum_assignment
    d=np.linalg.norm(det_xy[:,None,:]-target_xy[None,:,:],axis=2)
    penalty=float(max_dist)*10.0
    cost=np.where(np.isfinite(d)&(d<=max_dist),d,penalty)
    rr,cc=linear_sum_assignment(cost)
    keep=np.isfinite(d[rr,cc])&(d[rr,cc]<=max_dist)
    return np.column_stack([rr[keep],cc[keep]]).astype(int)


def _build_stellar_catalog(im, detected_sources, gaia_tab=None, simbad_objects=None,
                           match_arcsec=5.0):
    """Construye un catálogo estelar con asociaciones estrictamente uno-a-uno.

    La posición detectada es la referencia primaria. Gaia/SIMBAD aportan contexto;
    ninguna coincidencia de catálogo convierte una fuente en un descubrimiento nuevo.
    """
    det = np.asarray(detected_sources, float)
    if det.ndim != 2 or det.shape[1] < 2 or len(det) == 0:
        return [], []
    base_rows = [
        {"det_id": i + 1, "x_px": float(x), "y_px": float(y),
         "peak_adu": float(det[i, 2]) if det.shape[1] > 2 else float("nan")}
        for i, (x, y) in enumerate(det[:, :2])
    ]
    if im.wcs is None:
        for r in base_rows:
            r["source_id"] = None
            r["note"] = "sin WCS: no se pudo cruzar con Gaia"
            r["interest"] = "sin indicador destacado"
        return base_rows, []
    if gaia_tab is None or len(gaia_tab) == 0:
        for r in base_rows:
            r["note"] = "Gaia no devolvió fuentes para este campo"
            r["interest"] = "sin indicador destacado"
        return base_rows, []
    try:
        gra = np.asarray(gaia_tab["ra"], float)
        gdec = np.asarray(gaia_tab["dec"], float)
        valid_g = np.isfinite(gra) & np.isfinite(gdec)
        gx_all = np.full(len(gra), np.nan, float)
        gy_all = np.full(len(gdec), np.nan, float)
        if valid_g.any():
            gx, gy = im.wcs.celestial.all_world2pix(gra[valid_g], gdec[valid_g], 0)
            gx_all[valid_g] = np.asarray(gx, float)
            gy_all[valid_g] = np.asarray(gy, float)
        gvalid = np.isfinite(gx_all) & np.isfinite(gy_all)
        gxy = np.column_stack([gx_all[gvalid], gy_all[gvalid]])
        gindices = np.nonzero(gvalid)[0]
        detxy = det[:, :2]
        scale = max(float(im.pixel_scale_arcsec or 1.0), 1e-6)
        max_px = float(match_arcsec) / scale
        pairs = _match_points_one_to_one(detxy, gxy, max_px) if len(gxy) else np.empty((0, 2), int)
        match_by_det = {int(a): int(gindices[int(b)]) for a, b in pairs}

        simbad_objects = simbad_objects or []
        stree_xy = np.empty((0, 2), float)
        stree_indices = np.empty(0, int)
        if simbad_objects:
            sra = np.asarray([finite(o.get("ra_deg"), float("nan")) for o in simbad_objects], float)
            sdec = np.asarray([finite(o.get("dec_deg"), float("nan")) for o in simbad_objects], float)
            valid_s = np.isfinite(sra) & np.isfinite(sdec)
            if valid_s.any():
                sx, sy = im.wcs.celestial.all_world2pix(sra[valid_s], sdec[valid_s], 0)
                stree_xy = np.column_stack([np.asarray(sx, float), np.asarray(sy, float)])
                stree_indices = np.nonzero(valid_s)[0]

        s_pairs = (_match_points_one_to_one(detxy, stree_xy, max_px)
                   if len(stree_xy) else np.empty((0, 2), int))
        simbad_by_det = {int(a): int(stree_indices[int(b)]) for a, b in s_pairs}

        rows = []
        for i, r in enumerate(base_rows):
            gi = match_by_det.get(i)
            if gi is not None:
                dp = float(np.hypot(detxy[i, 0] - gx_all[gi], detxy[i, 1] - gy_all[gi]))
                r["match_arcsec"] = dp * scale
                for col, outname in (
                    ("source_id", "source_id"), ("ra", "ra_deg"), ("dec", "dec_deg"),
                    ("phot_g_mean_mag", "g_mag"), ("phot_bp_mean_mag", "bp_mag"),
                    ("phot_rp_mean_mag", "rp_mag"), ("bp_rp", "bp_rp"),
                    ("parallax", "parallax_mas"), ("parallax_error", "parallax_error_mas"),
                    ("pmra", "pmra_masyr"), ("pmdec", "pmdec_masyr"),
                    ("radial_velocity", "radial_velocity_kms"), ("ruwe", "ruwe"),
                    ("astrometric_excess_noise", "astrometric_excess_noise"),
                    ("teff_gspphot", "teff_k"), ("logg_gspphot", "logg"),
                    ("mh_gspphot", "mh_dex"), ("distance_gspphot", "distance_pc"),
                    ("ag_gspphot", "ag_mag"), ("classprob_dsc_combmod_star", "star_probability"),
                ):
                    if col in gaia_tab.colnames:
                        try:
                            r[outname] = json_sanitize(gaia_tab[col][gi])
                        except (TypeError, ValueError, IndexError):
                            r[outname] = None
                pmra = finite(r.get("pmra_masyr"), float("nan"))
                pmdec = finite(r.get("pmdec_masyr"), float("nan"))
                r["pm_total_masyr"] = float(math.hypot(pmra, pmdec)) if np.isfinite(pmra) and np.isfinite(pmdec) else float("nan")
                r["spectral_class_est"] = stellar_spectral_class(r.get("teff_k"), r.get("bp_rp"))
                r["luminosity_class_est"] = stellar_luminosity_class(r.get("logg"))
            else:
                r["match_arcsec"] = float("nan")
                r["note"] = "sin contrapartida Gaia"

            si = simbad_by_det.get(i)
            if si is not None:
                o = simbad_objects[si]
                r["simbad_main_id"] = str(o.get("main_id", ""))
                r["simbad_otype"] = str(o.get("otype", ""))
                r["simbad_type_pretty"] = pretty_simbad_type(o.get("otype", ""))
                r["simbad_sptype"] = str(o.get("sp_type", ""))
                loc = np.flatnonzero(stree_indices == si)
                if loc.size:
                    sx, sy = stree_xy[int(loc[0])]
                    r["simbad_match_arcsec"] = float(np.hypot(detxy[i, 0] - sx, detxy[i, 1] - sy) * scale)
                else:
                    # Integridad defensiva: una asociación SIMBAD nunca debe
                    # provocar IndexError por desalineación de índices auxiliares.
                    r["simbad_match_arcsec"] = float("nan")
                    r["note"] = "asociación SIMBAD inconsistente; descartada métricamente"
            r["interest"] = stellar_interest_note(r)
            rows.append(r)

        highlights = []
        for o in simbad_objects:
            oid = str(o.get("main_id") or "").strip()
            if not oid:
                continue
            ot = str(o.get("otype") or "").strip()
            if is_simbad_interesting(ot):
                oo = dict(o)
                oo["type_pretty"] = pretty_simbad_type(ot)
                highlights.append(oo)
        return rows, highlights[:50]
    except (ValueError, TypeError, IndexError, RuntimeError) as exc:
        LOG.warning("Cruce estelar Gaia/SIMBAD fallo: %s", exc)
        for r in base_rows:
            r["note"] = f"error cruzando Gaia: {exc}"
            r["interest"] = "sin indicador destacado"
        return base_rows, []

def stellar_summary(stars):
    stars = [s for s in (stars or []) if s.get("source_id") is not None]
    if not stars:
        return {"n_matched": 0, "types": {}, "n_interesting": 0, "brightest": None}
    types = {}
    for s in stars:
        t = str(s.get("spectral_class_est") or "?")
        types[t] = types.get(t, 0) + 1
    bright = min(stars, key=lambda r: finite(r.get("g_mag"), 99.0))
    return {"n_matched": len(stars), "types": types,
            "n_interesting": sum("sin indicador" not in str(s.get("interest")) for s in stars),
            "brightest": {k: bright.get(k) for k in
                          ("source_id","g_mag","bp_rp","teff_k",
                           "spectral_class_est","simbad_main_id","interest")}}


# ====================================================================
# RESOLUCIÓN DE CENTRO / RADIO
# ====================================================================
def resolve_object_center_legacy(target_name: str, ra_hint=None, dec_hint=None):
    if target_name and HAS_SIMBAD:
        try:
            s = Simbad()
            result = s.query_object(target_name)
            if result is not None and len(result) > 0:
                ra = float(result['ra'][0]); dec = float(result['dec'][0])
                return ra, dec, f"SIMBAD: {target_name} → RA={ra:.5f}°, Dec={dec:.5f}°"
        except Exception as exc:
            LOG.debug("SIMBAD falló: %s", exc)
    if ra_hint is not None and dec_hint is not None and \
       math.isfinite(ra_hint) and math.isfinite(dec_hint):
        return float(ra_hint), float(dec_hint), "RA/Dec manual"
    return None, None, "no resuelto"


def compute_remnant_radius_from_center(im_ha, rows, ra_c, dec_c, distance_pc):
    if im_ha.wcs is None or not math.isfinite(ra_c) or not math.isfinite(dec_c):
        return float("nan"), float("nan")
    scale = im_ha.pixel_scale_arcsec
    if scale is None:
        return float("nan"), float("nan")
    xs = [r["x"] for r in rows if math.isfinite(finite(r.get("x")))]
    ys = [r["y"] for r in rows if math.isfinite(finite(r.get("y")))]
    if len(xs) < 3:
        return float("nan"), float("nan")
    cx_px, cy_px = float(np.median(xs)), float(np.median(ys))
    try:
        ra_an, dec_an = im_ha.pixel_to_world(np.array([cx_px]), np.array([cy_px]))
        if not (math.isfinite(ra_an[0]) and math.isfinite(dec_an[0])):
            return float("nan"), float("nan")
        sep_arcsec = angular_separation_arcsec(ra_an[0], dec_an[0], ra_c, dec_c)
        r_cand_px = float(np.percentile(np.hypot(np.array(xs) - cx_px,
                                                 np.array(ys) - cy_px), 90))
        r_cand_arcsec = r_cand_px * scale
        r_total_arcsec = sep_arcsec + r_cand_arcsec
        r_total_pc = r_total_arcsec / C.arcsec_per_rad * distance_pc
        return float(r_total_pc), float(r_total_arcsec)
    except Exception as exc:
        LOG.warning("compute_remnant_radius: %s", exc)
        return float("nan"), float("nan")


def estimate_remnant_radius_uncertainty(im_ha, rows, ra_c, dec_c, distance_pc, n_boot=500, seed=20260915):
    """Estimación bootstrap reproducible de la incertidumbre geométrica del radio aproximado."""
    if im_ha.wcs is None or not math.isfinite(finite(ra_c,float("nan"))) or not math.isfinite(finite(dec_c,float("nan"))):
        return float("nan"), float("nan")
    scale=finite(im_ha.pixel_scale_arcsec,float("nan"))
    d=finite(distance_pc,float("nan"))
    pts=np.array([[finite(r.get("x"),np.nan),finite(r.get("y"),np.nan)] for r in (rows or [])],float)
    pts=pts[np.all(np.isfinite(pts),axis=1)]
    if len(pts)<3 or not np.isfinite(scale) or scale<=0 or not np.isfinite(d) or d<=0:
        return float("nan"), float("nan")
    rng=np.random.default_rng(seed); vals=[]
    for _ in range(int(max(100,n_boot))):
        q=pts[rng.integers(0,len(pts),len(pts))]
        cx,cy=np.median(q[:,0]),np.median(q[:,1])
        try:
            ra_an,dec_an=im_ha.pixel_to_world(np.array([cx]),np.array([cy]))
            sep=angular_separation_arcsec(ra_an[0],dec_an[0],ra_c,dec_c)
            rp=np.percentile(np.hypot(q[:,0]-cx,q[:,1]-cy),90)*scale
            vals.append(sep+rp)
        except Exception:
            continue
    if len(vals)<50: return float("nan"), float("nan")
    arr=np.asarray(vals,float); lo,hi=np.percentile(arr,[16,84])
    return float((hi-lo)/2), float(np.std(arr,ddof=1))


def build_literature_comparison(summary, target_name, user_distance_pc=None):
    """Compara usando incertidumbre combinada cuando existe y rangos cuando no.

    La entrada se normaliza con el contrato científico común para evitar divergencias
    entre los informes HTML/PDF y la capa de QC.
    """
    # summary puede ser el bloque real del pipeline; normalizamos sus aliases sin inventar datos.
    _np = normalize_scientific_payload({"summary": summary}).get("summary", {})
    summary = _np
    lit=find_literature(target_name) if target_name else None
    if lit is None:
        return {"found":False,"target":target_name or "(sin nombre)","note":"Objeto no en BD local."}
    rows=[]
    def scalar_row(quantity,obs,obs_err,ref,ref_err,unit,source):
        obs_ok=obs is not None and math.isfinite(finite(obs,float("nan")))
        ref_ok=ref is not None and math.isfinite(finite(ref,float("nan")))
        if not (obs_ok and ref_ok):
            return {"quantity":quantity,"observed":"—","literature":"—","delta":"sin datos","flag":"sin datos","source":source}
        err_ok=obs_err is not None and ref_err is not None and math.isfinite(finite(obs_err,float("nan"))) and math.isfinite(finite(ref_err,float("nan"))) and obs_err>0 and ref_err>0
        if err_ok:
            sigma=math.hypot(float(obs_err),float(ref_err)); z=(float(obs)-float(ref))/sigma
            flag="OK" if abs(z)<=2 else ("tensión" if abs(z)<=3 else "discrepancia")
            delta=f"z={z:+.2f} ({unit})"
        else:
            flag="sin incertidumbre"; delta="magnitudes comparadas sin σ combinada"
        return {"quantity":quantity,"observed":f"{float(obs):.3f} ± {float(obs_err):.3f} {unit}" if err_ok else f"{float(obs):.3f} {unit}",
                "literature":f"{float(ref):.3f} ± {float(ref_err):.3f} {unit}" if ref_err is not None and math.isfinite(finite(ref_err,float("nan"))) else f"{float(ref):.3f} {unit}",
                "delta":delta,"flag":flag,"z_score":(float(z) if err_ok else None),"source":source}

    d_lit,d_err,d_src=lit.get("distance_pc",(None,None,"—")); d_obs=user_distance_pc or summary.get("distance_pc")
    rows.append(scalar_row("Distancia",d_obs,summary.get("distance_err_pc"),d_lit,d_err,"pc",d_src))
    v_lit_lo,v_lit_hi,v_src=lit.get("v_shock_kms",(None,None,"—")); v_obs=summary.get("v_kms_median"); v_err=summary.get("v_kms_median_err")
    if v_obs is not None and math.isfinite(finite(v_obs,float("nan"))) and v_lit_lo is not None and v_lit_hi is not None:
        if v_err is not None and math.isfinite(finite(v_err,float("nan"))) and v_err>0:
            ref=(v_lit_lo+v_lit_hi)/2.0; ref_err=max((v_lit_hi-v_lit_lo)/2.0,1e-9)
            rr=scalar_row("V_shock mediana",v_obs,v_err,ref,ref_err,"km/s",v_src); rr["literature_interval"]=[v_lit_lo,v_lit_hi]; rows.append(rr)
        else:
            inside=v_lit_lo<=v_obs<=v_lit_hi; rows.append({"quantity":"V_shock mediana","observed":f"{v_obs:.1f} km/s","literature":f"{v_lit_lo:.0f}–{v_lit_hi:.0f} km/s","delta":"dentro de rango" if inside else "fuera de rango","flag":"OK" if inside else "tensión","source":v_src})
    else:
        rows.append({"quantity":"V_shock mediana","observed":"no medida","literature":f"{v_lit_lo:.0f}–{v_lit_hi:.0f} km/s" if v_lit_lo is not None else "—","delta":"no medida","flag":"sin datos","source":v_src})
    r_lo,r_hi,r_src=lit.get("ratio_oiii_ha",(None,None,"—")); r_obs=summary.get("ratio_median")
    if r_obs is not None and math.isfinite(finite(r_obs,float("nan"))) and r_lo is not None and r_hi is not None:
        inside=r_lo<=r_obs<=r_hi; rows.append({"quantity":"[O III]/Hα mediano","observed":f"{r_obs:.3f} ± {finite(summary.get('ratio_median_err_approx'),0):.3f}","literature":f"{r_lo:.2f}–{r_hi:.2f}","delta":"dentro de intervalo" if inside else "fuera de intervalo","flag":"OK" if inside else "tensión","source":r_src})
    else:
        rows.append({"quantity":"[O III]/Hα mediano","observed":"—","literature":f"{r_lo:.2f}–{r_hi:.2f}" if r_lo is not None else "—","delta":"sin datos","flag":"sin datos","source":r_src})
    age_lo,age_hi,age_src=lit.get("age_yr",(None,None,"—")); age_obs=(summary.get("ages_yr") or {}).get("sedov_taylor")
    if age_obs is not None and math.isfinite(finite(age_obs,float("nan"))) and age_lo is not None and age_hi is not None:
        inside=age_lo<=age_obs<=age_hi; rows.append({"quantity":"Edad dinámica (Sedov)","observed":f"{age_obs:.0f} yr","literature":f"{age_lo:.0f}–{age_hi:.0f} yr","delta":"dentro de intervalo" if inside else "fuera de intervalo","flag":"OK" if inside else "tensión","source":age_src})
    else:
        rows.append({"quantity":"Edad dinámica (Sedov)","observed":"no calculada","literature":f"{age_lo:.0f}–{age_hi:.0f} yr" if age_lo is not None else "—","delta":"no calculada","flag":"sin datos","source":age_src})
    tension=sum(r.get("flag") in ("tensión","discrepancia") for r in rows); ok=sum(r.get("flag")=="OK" for r in rows)
    verdict="Consistente dentro de incertidumbres/rangos" if tension==0 and ok>=2 else ("Hay tensiones: revisar calibración/modelo" if tension else "Comparación parcial o insuficiente")
    return {"found":True,"target":target_name,"matched_alias":lit.get("matched_alias",""),"canonical":lit.get("canonical",target_name),"rows":rows,"verdict":verdict,"notes":lit.get("notes",""),"references":dict(RESEARCH_SOURCES)}


# ====================================================================
# CONSTANTES
# ====================================================================
@dataclass(frozen=True)
class Const:
    m_H: float = 1.67353e-24
    m_p: float = 1.67262192369e-24
    k_B: float = 1.380649e-16
    pc: float = 3.0856775814913673e18
    yr: float = 365.25 * 86400.0
    arcsec_per_rad: float = 206264.80624709636
    gamma: float = 5.0 / 3.0
    km: float = 1e5
    au_per_yr_kms: float = 4.740470463533348


C = Const()


@dataclass(frozen=True)
class Composition:
    y_He: float = 0.10
    z_metals_mass_frac: float = 0.0134

    @property
    def mu_H(self) -> float:
        return 1.0 + 4.0 * self.y_He

    @property
    def mass_per_H(self) -> float:
        return self.mu_H * C.m_p

    def particles_per_H(self, ionization):
        return {"neutral": 1.0 + self.y_He, "H+He0": 2.0 + self.y_He,
                "H+He+": 2.0 + 2.0 * self.y_He, "H+He++": 2.0 + 3.0 * self.y_He}[ionization]

    def electrons_per_H(self, ionization):
        return {"neutral": 0.0, "H+He0": 1.0, "H+He+": 1.0 + self.y_He,
                "H+He++": 1.0 + 2.0 * self.y_He}[ionization]

    def chi_tot(self, ionization):
        return self.particles_per_H(ionization)

    def chi_e(self, ionization):
        return self.electrons_per_H(ionization)

    def mu(self, ionization):
        return self.mu_H / self.particles_per_H(ionization)


def finite(v, default=float("nan")):
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def robust_stats(x, clip_sigma=3.0, iters=5):
    a = np.asarray(x, dtype=np.float64).ravel()
    a = a[np.isfinite(a)]
    if a.size == 0:
        return 0.0, 1.0
    for _ in range(iters):
        med = np.median(a)
        mad = 1.4826 * np.median(np.abs(a - med))
        if mad <= 0:
            mad = np.std(a)
            break
        keep = np.abs(a - med) < clip_sigma * mad
        if keep.all():
            break
        a = a[keep]
    med = float(np.median(a))
    mad = float(1.4826 * np.median(np.abs(a - med)))
    return med, max(mad, 1e-12)


# ------------------------------------------------------------------------------------
# Mediana del resumen con corte de calidad por SNR (fix v25.10)
# ------------------------------------------------------------------------------------
# Motivo: `results` incluye TODOS los candidatos que superaron el snr_min de detección de
# la cresta, snr_min que es deliberadamente permisivo para no perder filamentos débiles
# reales. En un campo con ruido moderado eso implica que una fracción sustancial de los
# candidatos "ok" son detecciones marginales (snr_pix apenas por encima del umbral) cuyo
# ajuste de pico puede converger con un offset prácticamente arbitrario. Una mediana simple
# sobre TODOS los candidatos no es robusta cuando esa fracción marginal ronda el 50%: el
# sigma-clipping de `robust_stats` tampoco basta ahí (dos "nubes" de tamaño similar no son
# outliers en el sentido MAD). La solución correcta es excluir las detecciones marginales
# de la cifra TITULAR del resumen (quedan igualmente en el catálogo completo, sin perder
# información), y aplicar `robust_stats` solo como red de seguridad dentro del subconjunto
# ya filtrado. Verificado con un caso sintético reproducible (ver selftest: "resumen robusto
# ante contaminación"): sin este corte, snr_min=3 daba offset_px_median≈+0.04 px en un campo
# con una única cresta real desplazada -6 px; con el corte, da ≈-5.99 px.
SUMMARY_SNR_FACTOR = 1.5   # umbral titular = P.snr_min * SUMMARY_SNR_FACTOR (sobre snr_pix)
SUMMARY_MIN_N = 3          # por debajo de esto, se cae al conjunto completo (con aviso)


def quality_gated_median(rows: list, key: str, min_snr: float) -> dict:
    """Mediana robusta con trazabilidad del corte SNR y error robusto aproximado.

    El error se informa como SEM de la dispersión MAD, útil como indicador de la
    estabilidad del resumen y no como incertidumbre instrumental individual.
    """
    pares=[(finite(r.get(key)), finite(r.get("snr_pix"))) for r in rows]
    pares=[(v,sn) for v,sn in pares if math.isfinite(v)]
    n_total=len(pares); altos=[v for v,sn in pares if math.isfinite(sn) and sn>=min_snr]
    fallback=len(altos)<SUMMARY_MIN_N; usados=[v for v,_ in pares] if fallback else altos
    if not usados:
        return {"median":float("nan"),"robust_mad":float("nan"),"stderr_approx":float("nan"),
                "n_used":0,"n_total":n_total,"min_snr_applied":float(min_snr),"fallback_to_all":fallback,"sufficient_data":False}
    med,mad=robust_stats(np.asarray(usados,dtype=np.float64))
    return {"median":med,"robust_mad":float(mad),
            "stderr_approx":float(mad/max(math.sqrt(len(usados)),1.0)),
            "n_used":len(usados),"n_total":n_total,
            "min_snr_applied":float(min_snr),
            "fallback_to_all":fallback,
            "sufficient_data":bool(not fallback)}

def json_sanitize(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return v if math.isfinite(v) else None
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return [json_sanitize(x) for x in obj.tolist()]
    if isinstance(obj, (list, tuple)):
        return [json_sanitize(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): json_sanitize(v) for k, v in obj.items()}
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return json_sanitize(dataclasses.asdict(obj))
    if isinstance(obj, Path):
        return str(obj)
    return obj


def atomic_json_dump(payload, path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(json_sanitize(payload), fh, ensure_ascii=False, indent=2, allow_nan=False)
    for attempt in range(3):
        try: os.replace(tmp,target); break
        except PermissionError:
            if attempt==2: raise
            time.sleep(0.05*(attempt+1))


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


@dataclass
class RunManifest:
    software: str = f"AstroPhysics Suite {__version__}"
    schema_version: int = SCHEMA_VERSION
    created_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    python: str = field(default_factory=lambda: sys.version.split()[0])
    platform: str = field(default_factory=platform.platform)
    packages: dict = field(default_factory=dict)
    inputs: dict = field(default_factory=dict)
    parameters: dict = field(default_factory=dict)
    fits_metadata: dict = field(default_factory=dict)
    seed: int = 20260910
    warnings: list = field(default_factory=list)
    quality_flags: list = field(default_factory=list)
    registration: dict = field(default_factory=dict)
    calibration: dict = field(default_factory=dict)
    detection: dict = field(default_factory=dict)
    background: dict = field(default_factory=dict)
    profiles: dict = field(default_factory=dict)
    grid: dict = field(default_factory=dict)
    filters: dict = field(default_factory=dict)
    filter_curve_sha256: dict = field(default_factory=dict)
    configuration_sha256: Optional[str] = None
    parameters_sha256: Optional[str] = None
    inputs_sha256: Optional[str] = None

    def add_input(self, role, path):
        p = Path(path)
        if not p.is_file():
            return
        self.inputs[role] = {"path": str(p.resolve()), "sha256": sha256_file(p),
                             "bytes": p.stat().st_size}

    def collect_versions(self):
        for m in ("numpy", "scipy", "astropy", "skimage", "sklearn", "pandas", "matplotlib", "astroquery"):
            try:
                self.packages[m] = __import__(m).__version__
            except Exception:
                self.packages[m] = "absent"


# ====================================================================
# ACUMULACIÓN
# ====================================================================
# ====================================================================
# REPRODUCIBILIDAD / FIRMA DE ANÁLISIS
# ====================================================================
def analysis_signature(P, manifest):
    """Firma conjunta estable con hashes separados de parámetros e inputs."""
    inputs={k:v.get("sha256") for k,v in manifest.inputs.items() if isinstance(v,dict) and v.get("sha256")}
    params=json_sanitize(dataclasses.asdict(P))
    manifest.parameters_sha256=hashlib.sha256(json.dumps(params,sort_keys=True,ensure_ascii=False).encode("utf-8")).hexdigest()
    manifest.inputs_sha256=hashlib.sha256(json.dumps(inputs,sort_keys=True,ensure_ascii=False).encode("utf-8")).hexdigest()
    manifest.configuration_sha256=hashlib.sha256(json.dumps({"inputs":inputs,"parameters":params},sort_keys=True,ensure_ascii=False).encode("utf-8")).hexdigest()
    return manifest.configuration_sha256


def load_seen(seen_path, cell=8):
    p = Path(seen_path)
    if not p.is_file():
        return set()
    try:
        data = json.load(open(p, encoding="utf-8"))
    except Exception:
        return set()
    out = set()
    for c in data:
        try:
            out.add((int(c["i"]), int(c["j"])))
        except Exception:
            try:
                out.add((int(c["x"] // cell), int(c["y"] // cell)))
            except Exception:
                continue
    return out


def save_seen(seen_path, rows, cell=8):
    cells = set()
    for r in rows:
        try:
            cells.add((int(r["x"] // cell), int(r["y"] // cell)))
        except Exception:
            continue
    payload = [{"x": i * cell + cell / 2, "y": j * cell + cell / 2, "i": i, "j": j}
               for (i, j) in sorted(cells)]
    p = Path(seen_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def load_previous_profiles(prof_path):
    p = Path(prof_path)
    if not p.is_file():
        return {}
    try:
        data = json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}
    raw = data.get("profiles", {}) if isinstance(data, dict) else {}
    return {str(k): v for k, v in raw.items() if "_" in str(k)}


def merge_catalogs(old_path, new_payload):
    p = Path(old_path)
    new_rows = new_payload.get("candidates", [])
    if not p.is_file():
        for i, r in enumerate(new_rows):
            r["id"] = i
        new_payload.setdefault("summary", {})["n_accumulated"] = len(new_rows)
        new_payload["summary"]["n_new_this_run"] = len(new_rows)
        return new_payload
    try:
        old = json.load(open(p, encoding="utf-8"))
    except Exception:
        for i, r in enumerate(new_rows):
            r["id"] = i
        return new_payload
    old_rows = old.get("candidates") or []
    merged = {}
    for r in old_rows:
        k = profile_key(r)
        if k is not None:
            merged[k] = r
    added = 0
    for r in new_rows:
        k = profile_key(r)
        if k is None:
            continue
        if k not in merged:
            added += 1
        old_r = merged.get(k)
        if old_r and old_r.get("candidate_type") == "star" and \
           r.get("candidate_type") != "star":
            r["candidate_type"] = "star"
            r["status"] = "rejected_star"
            r["reason"] = "fuente puntual (marca heredada de corrida previa)"
        merged[k] = r
    out_rows = list(merged.values())
    for i, r in enumerate(out_rows):
        if r.get("candidate_type") == "star":
            r["id"] = -(i + 1)
        else:
            r["id"] = i
    new_payload["candidates"] = out_rows
    new_payload.setdefault("summary", {})["n_accumulated"] = len(out_rows)
    new_payload["summary"]["n_new_this_run"] = added
    return new_payload


# ====================================================================
# FITS I/O
# ====================================================================
@dataclass
class FitsImage:
    path: str
    data: np.ndarray
    header: dict
    pixel_scale_arcsec: Optional[float]
    wcs: Any = None
    bunit: str = ""
    exptime: Optional[float] = None
    filter_name: str = ""
    hdu_index: int = 0
    wcs_source: str = ""
    original_ndim: int = 2
    original_shape: tuple = ()
    selected_plane: Optional[tuple] = None   # None si el FITS ya era 2D; si no, índices usados
    cube_plane_is_explicit: bool = True      # False solo si se usó allow_first_plane (quicklook)

    @property
    def shape(self):
        return self.data.shape

    def pixel_to_world(self, x, y):
        if self.wcs is None:
            return (np.full_like(np.asarray(x, float), np.nan),
                    np.full_like(np.asarray(y, float), np.nan))
        try:
            ra, dec = self.wcs.celestial.all_pix2world(np.asarray(x, float),
                                                        np.asarray(y, float), 0)
            return np.asarray(ra, float), np.asarray(dec, float)
        except Exception:
            return (np.full_like(np.asarray(x, float), np.nan),
                    np.full_like(np.asarray(y, float), np.nan))


def angular_separation_arcsec(ra1, dec1, ra2, dec2):
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    dr = r2 - r1
    num = math.hypot(math.cos(d2) * math.sin(dr),
                     math.cos(d1) * math.sin(d2) - math.sin(d1) * math.cos(d2) * math.cos(dr))
    den = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(dr)
    return math.degrees(math.atan2(num, den)) * 3600.0


def _pixel_scale_from_header(h):
    for key in ("CDELT2", "CDELT1"):
        v = finite(h.get(key))
        if math.isfinite(v) and v != 0:
            return abs(v) * 3600.0
    cd = [finite(h.get(k)) for k in ("CD1_1", "CD1_2", "CD2_1", "CD2_2")]
    if all(math.isfinite(v) for v in cd):
        det = abs(cd[0] * cd[3] - cd[1] * cd[2])
        if det > 0:
            return math.sqrt(det) * 3600.0
    v = finite(h.get("PIXSCALE", h.get("SECPIX", h.get("PLTSCALE"))))
    return v if math.isfinite(v) and v > 0 else None


def load_light_wcs(path, target_name=""):
    if not HAS_ASTROPY:
        return None, None, "astropy ausente"
    try:
        with _fits.open(str(path), memmap=True, lazy_load_hdus=True) as hdul:
            for i, h in enumerate(hdul):
                if not getattr(h, "is_image", False):
                    continue
                if h.header.get("NAXIS", 0) < 2:
                    continue
                try:
                    w = _WCS(h.header, naxis=2)
                    if w.has_celestial:
                        scale = float(np.mean(np.abs(_pps(w.celestial))) * 3600.0)
                        return w, scale, f"WCS light (HDU {i}): escala {scale:.4f}″/px"
                except Exception:
                    continue
            hdr = dict(hdul[0].header)
            scale = _pixel_scale_from_header(hdr)
            if scale:
                return None, scale, f"Escala del light (sin WCS): {scale:.4f}″/px"
            return None, None, "Light sin WCS ni CDELT"
    except Exception as exc:
        return None, None, f"Error: {exc}"


class AmbiguousCubeError(ValueError):
    """FITS con más de 2 ejes de datos (cubo 3D/4D) sin un plano/canal explícito.
    Ver requisito de la auditoría: 'no seleccionar automáticamente el primer plano
    de un FITS 3D/4D sin avisar'. Antes de esta versión, load_fits colapsaba con
    `while data.ndim > 2: data = data[0]` sin ningún aviso ni registro — un cubo
    mal indexado podía analizarse como si fuera la imagen 2D correcta sin que
    nada lo delatara. Ahora hay que decidir explícitamente."""
    pass


def _select_cube_plane(data: np.ndarray, plane):
    """Reduce un array de ndim>2 a 2D usando `plane` (índice entero para el eje
    sobrante más externo, o tupla de índices si hay varios ejes de sobra).
    Nunca decide por sí solo: si faltan índices, es un error de uso del llamador
    (ya se validó antes de llegar aquí)."""
    extra = data.ndim - 2
    if isinstance(plane, (int, np.integer)):
        if extra != 1:
            raise AmbiguousCubeError(f"El cubo {data.shape} requiere {extra} índices; proporcione una tupla explícita.")
        idx = (int(plane),)
    else:
        idx = tuple(int(p) for p in plane)
    if len(idx) != extra:
        raise AmbiguousCubeError(
            f"Se requieren {extra} índice(s) de plano para un cubo de forma {data.shape}; "
            f"se recibieron {len(idx)}.")
    out = data
    for axis, i in enumerate(idx):
        if i < 0 or i >= out.shape[0]:
            raise AmbiguousCubeError(f"Índice de plano {i} fuera de rango para el eje extra {axis} de forma {data.shape}")
        out = out[i]
    return out, idx


def _preserve_fits_array_view(data):
    """Preserva vistas/memmap; no hace conversiones globales de dtype."""
    arr = np.asanyarray(data)
    if not np.issubdtype(arr.dtype, np.number):
        raise TypeError(f"FITS: dtype no numérico: {arr.dtype}")
    return arr


def load_fits(path, hdu=None, memmap=True, plane=None, allow_first_plane=False):
    """Carga un FITS 2D. Si el HDU seleccionado tiene más de 2 ejes (cubo 3D/4D):
      - `plane` explícito (int o tupla)  -> se usa ese plano, se registra en el resultado.
      - `plane=None` y `allow_first_plane=True` -> se usa el plano 0 (SOLO pensado para
        vistas rápidas/miniaturas no científicas: se marca `cube_plane_is_explicit=False`
        para que nadie lo confunda con una selección deliberada).
      - `plane=None` y `allow_first_plane=False` (por defecto) -> AmbiguousCubeError,
        con la forma del cubo en el mensaje para que el usuario indique el plano correcto."""
    path = str(path)
    if HAS_ASTROPY:
        with _fits.open(path, memmap=memmap, lazy_load_hdus=True) as hdul:
            idx = hdu
            if idx is None:
                for i, h in enumerate(hdul):
                    if getattr(h, "is_image", False) and h.header.get("NAXIS", 0) >= 2:
                        idx = i
                        break
            if idx is None:
                raise ValueError(f"{path}: no hay HDU de imagen 2D")
            h = hdul[idx]
            raw = _preserve_fits_array_view(h.data)
            original_ndim, original_shape = raw.ndim, tuple(raw.shape)
            selected_plane, explicit = None, True
            if raw.ndim > 2:
                if plane is not None:
                    data, selected_plane = _select_cube_plane(raw, plane)
                elif allow_first_plane:
                    data, selected_plane = _select_cube_plane(raw, 0)
                    explicit = False
                    LOG.warning("%s: cubo %s sin plano explícito; usando plano 0 "
                                "(SOLO vista rápida, no válido para análisis científico)",
                                path, original_shape)
                else:
                    raise AmbiguousCubeError(
                        f"{path}: el HDU {idx} tiene forma {original_shape} (ndim={raw.ndim}), "
                        f"no es una imagen 2D. Indica explícitamente el plano/canal a usar "
                        f"(p.ej. --oiii-plane / --ha-plane en la CLI, o plane=... en la API) "
                        f"en vez de asumir el primero por defecto.")
            else:
                data = raw
            # Mantener memmap/vistas; el casteo a float32 se hace en las operaciones que lo necesitan.
            data = _preserve_fits_array_view(data)
            header = {k: h.header[k] for k in h.header.keys()
                      if k and k not in ("COMMENT", "HISTORY")}
            wcs, scale, src = None, None, ""
            try:
                w = _WCS(h.header, naxis=2)
                if w.has_celestial:
                    wcs = w
                    scale = float(np.mean(np.abs(_pps(w.celestial))) * 3600.0)
                    src = "WCS del propio FITS"
            except (ValueError, TypeError, AttributeError) as exc:
                LOG.debug("WCS no disponible en %s: %s", path, exc)
            if scale is None:
                scale = _pixel_scale_from_header(header)
                if scale:
                    src = "CDELT/PIXSCALE del propio FITS"
    else:
        data, header = _read_primary_fits_minimal(path)
        original_ndim, original_shape = data.ndim, tuple(data.shape)
        selected_plane, explicit = None, True
        if data.ndim > 2:
            if plane is not None:
                data, selected_plane = _select_cube_plane(data, plane)
            elif allow_first_plane:
                data, selected_plane = _select_cube_plane(data, 0)
                explicit = False
            else:
                raise AmbiguousCubeError(
                    f"{path}: forma {original_shape} (ndim={data.ndim}), no es 2D. "
                    f"Indica explícitamente el plano/canal a usar.")
        wcs, scale, src = None, _pixel_scale_from_header(header), ""
        idx = 0
    if data.ndim != 2:
        raise AmbiguousCubeError(f"{path}: tras seleccionar plano, la forma sigue siendo "
                                 f"{data.shape} (se requiere estrictamente 2D).")
    return FitsImage(path=path, data=data, header=header, pixel_scale_arcsec=scale,
                     wcs=wcs, bunit=str(header.get("BUNIT", "")),
                     exptime=(finite(header.get("EXPTIME")) if "EXPTIME" in header else None),
                     filter_name=str(header.get("FILTER", header.get("FILTER1", ""))),
                     hdu_index=int(idx), wcs_source=src,
                     original_ndim=original_ndim, original_shape=original_shape,
                     selected_plane=selected_plane, cube_plane_is_explicit=explicit)


def _read_primary_fits_minimal(path):
    header={}
    with open(path,"rb") as fh:
        while True:
            block=fh.read(2880)
            if len(block)<2880: raise ValueError("FITS truncado")
            end=False
            for i in range(0,2880,80):
                card=block[i:i+80].decode("ascii","replace"); key=card[:8].strip()
                if key=="END": end=True; break
                if "=" in card[8:10]:
                    val=card[10:].split("/")[0].strip()
                    if val.startswith("'"): header[key]=val.strip("'").strip()
                    else:
                        try: header[key]=int(val) if val.lstrip("+-").isdigit() else float(val)
                        except ValueError: header[key]=val
            if end: break
        bitpix=int(header["BITPIX"]); nax=int(header["NAXIS"])
        shape=tuple(int(header[f"NAXIS{i}"]) for i in range(nax,0,-1))
        if nax!=2:
            # Minimal reader cannot make an informed cube-plane selection without Astropy.
            raise AmbiguousCubeError(f"{path}: lector FITS mínimo no admite NAXIS={nax}; instale astropy o use una imagen 2D.")
        dtype={8:">u1",16:">i2",32:">i4",64:">i8",-32:">f4",-64:">f8"}[bitpix]
        count=int(np.prod(shape)); raw=np.frombuffer(fh.read(count*np.dtype(dtype).itemsize),dtype=dtype).reshape(shape)
        data=raw.astype(np.float64)*float(header.get("BSCALE",1.0))+float(header.get("BZERO",0.0))
    return data.astype(np.float32),header


# ====================================================================
# FONDO
# ====================================================================
@dataclass
class Background:
    bkg: np.ndarray
    rms: np.ndarray
    box: int

    def subtract(self, data):
        return data - self.bkg


def estimate_background(data, box=64, filter_size=3, clip_sigma=3.0, mask=None, use_photutils=True):
    a=np.asarray(data,np.float32)
    if a.ndim!=2: raise ValueError(f"estimate_background requiere 2D, recibido {a.shape}")
    ext_mask=~np.isfinite(a)
    if mask is not None:
        ext_mask |= np.asarray(mask,bool)
    if use_photutils and HAS_PHOTUTILS_BACKGROUND and Background2D is not None:
        try:
            box_size=(max(8,int(box)),max(8,int(box)))
            sigclip=SigmaClip(sigma=float(clip_sigma),maxiters=5) if SigmaClip else None
            b=Background2D(a,box_size=box_size,filter_size=(3,3),sigma_clip=sigclip,
                           bkg_estimator=MedianBackground(),mask=ext_mask)
            return Background(np.asarray(b.background,np.float32),np.maximum(np.asarray(b.background_rms,np.float32),1e-12),int(box))
        except Exception as exc:
            LOG.warning("Background2D falló (%s); fallback interno",exc)
    H,W=a.shape; ny,nx=max(1,math.ceil(H/box)),max(1,math.ceil(W/box)); bk=np.zeros((ny,nx),float); rm=np.zeros((ny,nx),float)
    for j in range(ny):
        for i in range(nx):
            tile=a[j*box:(j+1)*box,i*box:(i+1)*box]
            if ext_mask is not None: tile=np.where(ext_mask[j*box:(j+1)*box,i*box:(i+1)*box],np.nan,tile)
            med,sig=robust_stats(tile,clip_sigma); bk[j,i],rm[j,i]=med,sig
    if filter_size>1 and min(ny,nx)>=filter_size:
        bk=ndi.median_filter(bk,size=filter_size,mode="nearest"); rm=ndi.median_filter(rm,size=filter_size,mode="nearest")
    yy=(np.arange(H)+0.5)/box-0.5; xx=(np.arange(W)+0.5)/box-0.5
    gy,gx=np.meshgrid(np.clip(yy,0,ny-1),np.clip(xx,0,nx-1),indexing="ij")
    order_bk=3 if min(ny,nx)>=4 else 1
    bkg=ndi.map_coordinates(bk,[gy,gx],order=order_bk,mode="nearest").astype(np.float32)
    rms=ndi.map_coordinates(rm,[gy,gx],order=1,mode="nearest").astype(np.float32)
    return Background(bkg=bkg,rms=np.maximum(rms,1e-12),box=box)

@dataclass
class FITSQuality:
    metadata: dict
    mask: np.ndarray
    variance: np.ndarray

def wcs_quality_report(im: FitsImage) -> dict:
    """Diagnóstico WCS trazable: presencia, escala, orientación y huella."""
    out={"present":bool(im.wcs is not None),"celestial":False,
         "pixel_scale_arcsec":im.pixel_scale_arcsec,"orientation_deg":None,
         "footprint_ra_dec_deg":None,"warnings":[]}
    if im.wcs is None:
        out["warnings"].append("No hay WCS celeste válido.")
        return json_sanitize(out)
    try: out["celestial"]=bool(im.wcs.has_celestial)
    except Exception: out["celestial"]=False
    try:
        m=np.asarray(im.wcs.pixel_scale_matrix,float)
        if m.shape==(2,2) and np.all(np.isfinite(m)):
            out["orientation_deg"]=float(np.degrees(np.arctan2(m[1,0],m[0,0])))
    except Exception as exc:
        out["warnings"].append(f"No se pudo determinar orientación WCS: {type(exc).__name__}: {exc}")
    try:
        fp=np.asarray(im.wcs.calc_footprint(),float)
        if fp.ndim==2 and fp.shape[1]>=2 and np.all(np.isfinite(fp[:,:2])):
            out["footprint_ra_dec_deg"]=fp[:,:2].tolist()
    except Exception as exc:
        out["warnings"].append(f"No se pudo calcular huella WCS: {type(exc).__name__}: {exc}")
    if out["pixel_scale_arcsec"] is None:
        out["warnings"].append("WCS presente pero escala de píxel no determinada.")
    return json_sanitize(out)


def fits_metadata_summary(im: FitsImage):
    h=im.header or {}
    wanted=("BUNIT","EXPTIME","FILTER","GAIN","RDNOISE","AIRMASS","SATURATE","DATE-OBS","MJD-OBS","INSTRUME","TELESCOP","OBJECT")
    md={k:h.get(k,None) for k in wanted}
    md.update({"shape":list(im.shape),"dtype":str(im.data.dtype),"hdu":im.hdu_index,"pixel_scale_arcsec":im.pixel_scale_arcsec,
               "wcs_source":im.wcs_source,"original_ndim":im.original_ndim,"original_shape":list(im.original_shape),
               "selected_plane":list(im.selected_plane) if im.selected_plane is not None else None,
               "cube_plane_is_explicit": bool(im.cube_plane_is_explicit),
               "wcs_quality": wcs_quality_report(im)})
    return json_sanitize(md)

def build_quality_mask(im: FitsImage, saturation_margin=0.999):
    a=np.asarray(im.data,np.float32); mask=~np.isfinite(a)
    sat=finite(im.header.get("SATURATE"),float("nan"))
    if math.isfinite(sat) and sat>0: mask |= a >= saturation_margin*sat
    return mask

def build_variance_map(im: FitsImage, background: Background):
    a=np.asarray(im.data,np.float32); b=np.asarray(background.bkg,np.float32)
    gain=finite(im.header.get("GAIN"),float("nan")); rn=finite(im.header.get("RDNOISE"),float("nan"))
    sky=np.asarray(background.rms,np.float32)**2
    if math.isfinite(gain) and gain>0 and math.isfinite(rn) and rn>=0:
        sig=np.maximum(a-b,0)/gain+(rn/gain)**2+sky
        return np.maximum(sig,1e-12).astype(np.float32),"physical_poisson_readnoise_plus_sky"
    return np.maximum(np.asarray(background.rms,np.float32)**2,1e-12).astype(np.float32),"local_rms_fallback"


# ====================================================================
# REGISTRO
# ====================================================================
@dataclass
class Registration:
    """Resultado del registro. CONVENCIÓN DE SIGNO (inequívoca, no cambiar sin
    actualizar apply_shift y todos los llamadores): dx, dy es el desplazamiento
    que hay que APLICAR A LA IMAGEN [O III] (vía apply_shift(oiii_data, dx, dy))
    para alinearla con Hα. Verificado con test sintético de shift subpíxel
    conocido en selftest ("registro: signo verificado con shift subpíxel...")."""
    dx: float
    dy: float
    dx_err: float
    dy_err: float
    n_stars: int
    method: str
    residual_rms_px: float
    notes: str = ""
    n_sources_oiii: int = 0
    n_sources_ha: int = 0
    n_matches_initial: int = 0
    n_inliers: int = 0
    n_outliers: int = 0


RESAMPLING_WARNING = ("Remuestreo con spline cúbico: la interpolación de brillo "
                      "superficial NO conserva el flujo exactamente y puede introducir ringing.")


def apply_shift(data, dx, dy, order=3):
    """Aplica el desplazamiento (dx, dy) a `data` (convención: mover el contenido
    de la imagen +dx en X y +dy en Y; ver docstring de Registration). Con
    dx=Registration.dx, dy=Registration.dy calculados por register_on_stars,
    esto es exactamente 'desplazar [O III] para alinearla con Hα'."""
    a = np.asarray(data, np.float32)
    mask = np.isfinite(a)
    filled = np.where(mask, a, 0.0)
    out = ndi.shift(filled, shift=(dy, dx), order=order,
                    mode="constant", cval=0.0, prefilter=order > 1)
    m = ndi.shift(mask.astype(np.float32), shift=(dy, dx), order=1,
                  mode="constant", cval=0.0)
    out = np.where(m > 0.99, out / np.maximum(m, 1e-6), np.nan)
    return out.astype(np.float32)


def mask_point_sources(data, sources, radius_px=4.0):
    a = np.array(data, np.float32, copy=True)
    if sources is None or len(sources) == 0:
        return a
    H, W = a.shape
    r = int(math.ceil(radius_px))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    disk = (xx * xx + yy * yy) <= radius_px * radius_px
    for x, y, _ in sources:
        xi, yi = int(round(x)), int(round(y))
        y0, y1 = max(yi - r, 0), min(yi + r + 1, H)
        x0, x1 = max(xi - r, 0), min(xi + r + 1, W)
        if y1 <= y0 or x1 <= x0:
            continue
        sub = disk[(y0 - (yi - r)):(y1 - (yi - r)),
                   (x0 - (xi - r)):(x1 - (xi - r))]
        region = a[y0:y1, x0:x1]
        region[sub] = np.nan
        a[y0:y1, x0:x1] = region
    return a


# ====================================================================
# DETECCIÓN DE FUENTES PUNTUALES — DAOStarFinder (photutils)
# ====================================================================


DAO_SHARPLO = 0.30
DAO_SHARPHI = 0.90
DAO_ROUNDLO = -0.50
DAO_ROUNDHI = 0.50


def _detect_point_sources_legacy(data, bkg, fwhm_px=3.0, threshold_sigma=6.0,
                                 max_sources=2000, roundness_max=0.55,
                                 min_fwhm_factor=0.55, max_fwhm_factor=2.0,
                                 edge_margin=None, psf_score_min=0.45):
    sig = max(float(fwhm_px) / 2.354820045, 0.4)
    img = np.asarray(data, np.float32) - np.asarray(bkg.bkg, np.float32)
    img = np.where(np.isfinite(img), img, 0.0)
    noise = np.maximum(np.asarray(bkg.rms, np.float32), 1e-6)
    sm = ndi.gaussian_filter(img, sig)
    size = max(3, int(2 * math.ceil(fwhm_px) + 1))
    peaks = ((sm == ndi.maximum_filter(sm, size=size, mode="nearest")) &
             (sm > float(threshold_sigma) * noise))
    ys, xs = np.nonzero(peaks)
    if xs.size == 0:
        return np.zeros((0, 3), dtype=np.float64)
    order = np.argsort(sm[ys, xs])[::-1][:max_sources * 6]
    radius = max(2, int(math.ceil(2.2 * fwhm_px)))
    H, W = img.shape
    edge_margin = radius + 1 if edge_margin is None else int(edge_margin)
    out = []
    min_sep = max(1.0, 0.55 * fwhm_px)
    for k in order:
        x0, y0 = int(xs[k]), int(ys[k])
        if (x0 < edge_margin or y0 < edge_margin or
                x0 >= W - edge_margin or y0 >= H - edge_margin):
            continue
        cut = img[y0-radius:y0+radius+1, x0-radius:x0+radius+1]
        if cut.size == 0:
            continue
        finite_cut = np.isfinite(cut)
        if finite_cut.sum() < 0.6 * cut.size:
            continue
        peak = float(img[y0, x0])
        if not math.isfinite(peak) or peak <= 0:
            continue
        w = np.clip(np.where(finite_cut, cut, 0.0), 0.0, None)
        total = float(w.sum())
        if total <= 0:
            continue
        local_noise = float(np.median(noise[y0-radius:y0+radius+1,
                                             x0-radius:x0+radius+1]))
        local_noise = max(local_noise, 1e-6)
        if peak / local_noise < threshold_sigma:
            continue
        gy, gx = np.mgrid[-radius:radius+1, -radius:radius+1]
        cx = float((w * gx).sum() / total); cy = float((w * gy).sum() / total)
        mxx = float((w * (gx-cx)**2).sum() / total)
        myy = float((w * (gy-cy)**2).sum() / total)
        mxy = float((w * (gx-cx)*(gy-cy)).sum() / total)
        tr = mxx + myy
        det = max(mxx * myy - mxy * mxy, 0.0)
        if tr <= 0:
            continue
        disc = math.sqrt(max(0.25 * tr * tr - det, 0.0))
        l1 = tr / 2 + disc; l2 = max(tr / 2 - disc, 1e-9)
        ellipticity = 1.0 - math.sqrt(l2 / l1)
        if ellipticity > roundness_max:
            continue
        fwhm_major = 2.354820045 * math.sqrt(l1)
        fwhm_minor = 2.354820045 * math.sqrt(l2)
        if not (min_fwhm_factor * fwhm_px <= fwhm_minor <= max_fwhm_factor * fwhm_px):
            continue
        if not (min_fwhm_factor * fwhm_px <= fwhm_major <= max_fwhm_factor * fwhm_px):
            continue
        x = x0 + cx; y = y0 + cy
        if any(math.hypot(x-px, y-py) < min_sep for px, py, _ in out):
            continue
        out.append((x, y, total))
        if len(out) >= max_sources:
            break
    return np.asarray(out, dtype=np.float64).reshape(-1, 3)


def detect_point_sources_legacy(data, bkg, fwhm_px=3.0, threshold_sigma=5.0,
                         max_sources=3000, **_ignored_kwargs):
    if HAS_PHOTUTILS:
        try:
            img = (np.asarray(data, np.float32) - np.asarray(bkg.bkg, np.float32))
            img = np.where(np.isfinite(img), img, 0.0)
            rms_med = float(np.median(np.asarray(bkg.rms, np.float32)))
            threshold = float(threshold_sigma) * max(rms_med, 1e-9)
            daofind = DAOStarFinder(
                fwhm=float(fwhm_px),
                threshold=threshold,
                sharplo=DAO_SHARPLO, sharphi=DAO_SHARPHI,
                roundlo=DAO_ROUNDLO, roundhi=DAO_ROUNDHI,
                exclude_border=True,
            )
            sources = daofind(img)
            if sources is None or len(sources) == 0:
                LOG.info("DAOStarFinder: 0 fuentes (¿umbral alto?)")
                return np.zeros((0, 3), dtype=np.float64)
            xs = np.asarray(sources["xcentroid"], float)
            ys = np.asarray(sources["ycentroid"], float)
            flux = (np.asarray(sources["flux"], float)
                    if "flux" in sources.colnames
                    else np.ones_like(xs))
            order = np.argsort(flux)[::-1][:int(max_sources)]
            xs, ys, flux = xs[order], ys[order], flux[order]
            LOG.info("DAOStarFinder: %d fuentes (σ=%.1f, fwhm=%.1f px)",
                     len(xs), threshold_sigma, fwhm_px)
            return np.column_stack([xs, ys, flux]).astype(np.float64)
        except Exception as exc:
            LOG.warning("DAOStarFinder falló (%s); usando detector legacy", exc)
    return _detect_point_sources_legacy(
        data, bkg, fwhm_px=fwhm_px, threshold_sigma=threshold_sigma,
        max_sources=max_sources, **_ignored_kwargs)


def enrich_star_rows(im: FitsImage, sources, bkg: Background):
    """Métricas locales auditables de fuente puntual, independientes de Gaia/SIMBAD."""
    rows = []
    if sources is None:
        return rows
    a = np.asarray(im.data, np.float32) - np.asarray(bkg.bkg, np.float32)
    rms = np.maximum(np.asarray(bkg.rms, np.float32), 1e-12)
    if a.ndim != 2 or rms.shape != a.shape:
        raise ValueError("enrich_star_rows: imagen y mapa RMS deben ser 2D y de igual forma")
    H, W = a.shape
    sat = finite(im.header.get("SATURATE"), float("nan"))
    src_arr = np.asarray(sources, float)
    if src_arr.size == 0:
        return rows
    src_arr = np.atleast_2d(src_arr)
    if src_arr.shape[1] < 2:
        raise ValueError("enrich_star_rows: sources debe contener x,y[,flux]")
    for det_id, row in enumerate(src_arr, 1):
        x, y = float(row[0]), float(row[1])
        flux = float(row[2]) if row.size >= 3 and math.isfinite(row[2]) else float("nan")
        xi, yi = int(round(x)), int(round(y)); r = 11
        y0, y1 = max(0, yi-r), min(H, yi+r+1); x0, x1 = max(0, xi-r), min(W, xi+r+1)
        cut = a[y0:y1, x0:x1]; local_rms = rms[y0:y1, x0:x1]
        good = np.isfinite(cut) & np.isfinite(local_rms) & (local_rms > 0)
        peak = float(np.nanmax(cut)) if np.isfinite(cut).any() else float("nan")
        noise = float(np.nanmedian(local_rms[good])) if np.any(good) else float("nan")
        local_snr_median = float(np.nanmedian(cut[good] / local_rms[good])) if np.any(good) else float("nan")
        roi_mean = float(np.nanmean(cut)) if np.isfinite(cut).any() else float("nan")
        roi_median = float(np.nanmedian(cut)) if np.isfinite(cut).any() else float("nan")
        snr_peak = peak/max(noise,1e-12) if math.isfinite(peak) and math.isfinite(noise) else float("nan")
        border = float(min(x, W-1-x, y, H-1-y))
        w = np.clip(np.nan_to_num(cut, nan=0.0), 0, None)
        gy, gx = np.mgrid[y0:y1, x0:x1]; total = float(w.sum())
        fwhm = ellipticity = sharp = float("nan")
        if total > 0:
            cx = float((w*gx).sum()/total); cy = float((w*gy).sum()/total)
            mxx = float((w*(gx-cx)**2).sum()/total); myy = float((w*(gy-cy)**2).sum()/total); mxy = float((w*(gx-cx)*(gy-cy)).sum()/total)
            tr = mxx+myy; disc = math.sqrt(max(0.25*(mxx-myy)**2+mxy*mxy,0.0)); l1=max(tr/2+disc,1e-9); l2=max(tr/2-disc,1e-9)
            fwhm = 2.354820045*math.sqrt(l1*l2); ellipticity = 1.0-math.sqrt(l2/l1)
            rr2=(gx-cx)**2+(gy-cy)**2; rcore=max(1.5,fwhm/2); rann=max(2.5,fwhm)
            core=float(w[rr2<=rcore**2].sum()); ann=float(w[(rr2>rcore**2)&(rr2<=rann**2)].sum()); sharp=core/max(ann,1e-12)
        saturated = bool(math.isfinite(sat) and math.isfinite(peak) and peak >= 0.999*sat)
        quality = "saturated" if saturated else ("edge" if border < max(5.0, fwhm if math.isfinite(fwhm) else 5.0) else ("ok" if math.isfinite(snr_peak) and snr_peak >= 5 else "low_snr"))
        rows.append({"det_id":det_id,"x_px":x,"y_px":y,"flux_adu":flux,"peak_adu":peak,"snr":snr_peak,"snr_peak":snr_peak,
                     "local_rms_adu":noise,"local_snr_median":local_snr_median,"roi_mean_adu":roi_mean,"roi_median_adu":roi_median,
                     "roi":{"x0":x0,"x1":x1,"y0":y0,"y1":y1,"width_px":x1-x0,"height_px":y1-y0},
                     "fwhm_px":float(fwhm),"ellipticity":float(ellipticity),"sharpness_index":float(sharp),"border_distance_px":border,
                     "saturated":saturated,"quality":quality})
    return rows

def register_on_stars(oiii, ha, bkg_oiii, bkg_ha, fwhm_px=3.0, search_radius_px=12.0):
    """Registra [O III] sobre Hα por traslación usando fuentes puntuales comunes.
    CONVENCIÓN DE SIGNO: el (dx, dy) devuelto es el desplazamiento a aplicar a
    LA IMAGEN [O III] (con apply_shift) para alinearla con Hα; ver Registration.
    El emparejamiento final es estrictamente uno-a-uno (asignación húngara,
    scipy.optimize.linear_sum_assignment) sobre los candidatos hallados por una
    búsqueda inicial por vecino más cercano (KD-tree) iterada hasta converger en
    un desplazamiento aproximado; esa búsqueda inicial SÍ puede emparejar varias
    fuentes de un lado con una misma fuente del otro (no es el resultado final,
    solo bootstrap del desplazamiento aproximado), pero el ajuste final que se
    reporta (dx, dy, RMS, n_stars) usa exclusivamente parejas uno-a-uno."""
    s1 = detect_point_sources(oiii, bkg_oiii, fwhm_px, threshold_sigma=5.0, max_sources=3000)
    s2 = detect_point_sources(ha, bkg_ha, fwhm_px, threshold_sigma=5.0, max_sources=3000)
    if len(s1) < 5 or len(s2) < 5:
        return _register_phase_fallback(oiii, ha, bkg_oiii, bkg_ha,
                                        note=f"pocas estrellas ({len(s1)},{len(s2)})")
    from scipy.spatial import cKDTree
    from scipy.optimize import linear_sum_assignment
    s1 = s1[np.argsort(s1[:,2])[::-1]]
    s2 = s2[np.argsort(s2[:,2])[::-1]]
    tree = cKDTree(s2[:, :2])
    shift = np.zeros(2, dtype=float)
    for _ in range(5):
        q = s1[:, :2] + shift
        dist, idx = tree.query(q, k=1, distance_upper_bound=search_radius_px)
        valid = np.isfinite(dist) & (dist < search_radius_px) & (idx < len(s2))
        if int(valid.sum()) < 5:
            return _register_phase_fallback(oiii, ha, bkg_oiii, bkg_ha,
                                            note="sin emparejamientos estelares robustos")
        vec = s2[idx[valid], :2] - s1[valid, :2]
        dx0, sx = robust_stats(vec[:, 0]); dy0, sy = robust_stats(vec[:, 1])
        new_shift = np.array([dx0, dy0], dtype=float)
        residual = np.hypot(vec[:, 0] - dx0, vec[:, 1] - dy0)
        keep = residual < max(0.8, 3.0 * math.hypot(sx, sy))
        if int(keep.sum()) >= 5:
            vec2 = vec[keep]
            dx0, sx = robust_stats(vec2[:, 0]); dy0, sy = robust_stats(vec2[:, 1])
            new_shift[:] = (dx0, dy0)
        shift = 0.5 * shift + 0.5 * new_shift

    # --- Refinamiento final: emparejamiento ESTRICTAMENTE uno-a-uno (húngaro) ---
    # El bucle anterior (vecino más cercano) puede asignar la misma estrella de
    # Hα a más de una estrella de [O III] si hay pares cercanos; eso sesgaría
    # ligeramente las estadísticas finales. Se restringe la asignación húngara al
    # universo pequeño de candidatos ya localizados (no a las hasta 3000 fuentes
    # totales), así el coste computacional es trivial.
    q = s1[:, :2] + shift
    dist_all, idx_all = tree.query(q, k=1, distance_upper_bound=search_radius_px)
    cand1 = np.where(np.isfinite(dist_all) & (dist_all < search_radius_px) & (idx_all < len(s2)))[0]
    n_matches_initial = int(len(cand1))
    if n_matches_initial < 5:
        return _register_phase_fallback(oiii, ha, bkg_oiii, bkg_ha,
                                        note="sin candidatos para asignación húngara")
    cand2 = np.unique(idx_all[cand1])
    C = np.linalg.norm(q[cand1][:, None, :] - s2[cand2][None, :, :2], axis=2)
    C_bloqueada = np.where(C < search_radius_px, C, 1e6)
    row_ind, col_ind = linear_sum_assignment(C_bloqueada)
    ok = C_bloqueada[row_ind, col_ind] < search_radius_px
    i1, i2 = cand1[row_ind[ok]], cand2[col_ind[ok]]
    if len(i1) < 5:
        return _register_phase_fallback(oiii, ha, bkg_oiii, bkg_ha,
                                        note="asignación húngara sin suficientes inliers")

    vec = s2[i2, :2] - s1[i1, :2]
    dx, sx = robust_stats(vec[:, 0]); dy, sy = robust_stats(vec[:, 1])
    residual = np.hypot(vec[:, 0] - dx, vec[:, 1] - dy)
    inlier_mask = residual < max(0.8, 3.0 * math.hypot(sx, sy))
    n_inliers = int(inlier_mask.sum())
    if n_inliers >= 5:
        vec = vec[inlier_mask]
        dx, sx = robust_stats(vec[:, 0]); dy, sy = robust_stats(vec[:, 1])
        residual = np.hypot(vec[:, 0] - dx, vec[:, 1] - dy)
    else:
        n_inliers = len(vec)

    return Registration(dx=dx, dy=dy,
                        dx_err=sx / math.sqrt(max(len(vec), 1)),
                        dy_err=sy / math.sqrt(max(len(vec), 1)),
                        n_stars=len(vec), method="stars-hungarian-1to1",
                        residual_rms_px=float(np.sqrt(np.mean(residual ** 2))),
                        notes=f"Traslación robusta usando {len(vec)} estrellas (emparejamiento uno-a-uno)",
                        n_sources_oiii=len(s1), n_sources_ha=len(s2),
                        n_matches_initial=n_matches_initial, n_inliers=n_inliers,
                        n_outliers=n_matches_initial - n_inliers)


def _register_phase_fallback(oiii, ha, bkg_oiii, bkg_ha, note):
    a = np.nan_to_num(oiii - bkg_oiii.bkg)
    b = np.nan_to_num(ha - bkg_ha.bkg)
    a = a - ndi.gaussian_filter(a, 8.0)
    b = b - ndi.gaussian_filter(b, 8.0)
    if HAS_SKIMAGE:
        try:
            shift, err, _ = _pcc(b, a, upsample_factor=20, normalization=None)
            dy, dx = float(shift[0]), float(shift[1])
            method, e = "phase-correlation", float(err)
        except Exception as exc:
            LOG.warning("phase_cross_correlation falló: %s", exc)
            dy = dx = 0.0
            method, e = "none-failed", float("nan")
    else:
        F = np.fft.fft2(a) * np.conj(np.fft.fft2(b))
        cc = np.abs(np.fft.ifft2(F))
        iy, ix = np.unravel_index(int(np.argmax(cc)), cc.shape)
        dy = -float(iy if iy <= a.shape[0] // 2 else iy - a.shape[0])
        dx = -float(ix if ix <= a.shape[1] // 2 else ix - a.shape[1])
        method, e = "fft-xcorr", float("nan")
    return Registration(dx=dx, dy=dy, dx_err=float("nan"), dy_err=float("nan"),
                        n_stars=0, method=method, residual_rms_px=e,
                        notes=f"Fallback por fase ({note})")


# ====================================================================
# CRESTAS
# ====================================================================
@dataclass
class RidgeMap:
    response: np.ndarray
    nx: np.ndarray
    ny: np.ndarray
    scale: np.ndarray
    anisotropy: np.ndarray


def hessian_ridge_response(image, sigmas=(1.0, 1.5, 2.2, 3.2, 4.6), beta=0.5):
    img = np.nan_to_num(np.asarray(image, np.float64), nan=0.0)
    best = np.full(img.shape, -np.inf)
    out_nx = np.zeros(img.shape)
    out_ny = np.zeros(img.shape)
    out_sc = np.zeros(img.shape)
    out_an = np.ones(img.shape)
    for s in sigmas:
        hxx = ndi.gaussian_filter(img, s, order=(0, 2)) * s * s
        hyy = ndi.gaussian_filter(img, s, order=(2, 0)) * s * s
        hxy = ndi.gaussian_filter(img, s, order=(1, 1)) * s * s
        tr = 0.5 * (hxx + hyy)
        disc = np.sqrt(np.maximum(0.25 * (hxx - hyy) ** 2 + hxy ** 2, 0.0))
        lmin = tr - disc
        lmax = tr + disc
        ratio = np.abs(lmax) / np.maximum(np.abs(lmin), 1e-12)
        resp = np.where(lmin < 0, -lmin * np.exp(-(ratio ** 2) / (2 * beta * beta)), 0.0)
        vx = np.where(np.abs(hxy) > 1e-12, hxy, np.where(hxx <= hyy, 1.0, 0.0))
        vy = np.where(np.abs(hxy) > 1e-12, lmin - hxx, np.where(hxx <= hyy, 0.0, 1.0))
        nrm = np.hypot(vx, vy) + 1e-30
        upd = resp > best
        best = np.where(upd, resp, best)
        out_nx = np.where(upd, vx / nrm, out_nx)
        out_ny = np.where(upd, vy / nrm, out_ny)
        out_sc = np.where(upd, s, out_sc)
        out_an = np.where(upd, ratio, out_an)
        del hxx, hyy, hxy, tr, disc, lmin, lmax, ratio, resp, vx, vy, nrm, upd
    best[~np.isfinite(best)] = 0.0
    return RidgeMap(best, out_nx, out_ny, out_sc, out_an)


def ridge_candidates(image, bkg, rm, snr_min=4.0, min_separation_px=8.0,
                     max_candidates=2000, border=16, max_anisotropy=0.5):
    H, W = image.shape
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    r_plus = ndi.map_coordinates(rm.response, [yy + rm.ny, xx + rm.nx], order=1, mode="nearest")
    r_minus = ndi.map_coordinates(rm.response, [yy - rm.ny, xx - rm.nx], order=1, mode="nearest")
    nms = (rm.response >= r_plus) & (rm.response >= r_minus) & (rm.response > 0)
    sig = np.nan_to_num(image - bkg.bkg) / bkg.rms
    ok = nms & (sig >= snr_min) & np.isfinite(image) & (rm.anisotropy <= max_anisotropy)
    ok[:border, :] = ok[-border:, :] = False
    ok[:, :border] = ok[:, -border:] = False
    ys, xs = np.nonzero(ok)
    if xs.size == 0:
        return []
    order = np.argsort(rm.response[ys, xs])[::-1]
    cell = max(1.0, min_separation_px)
    taken = set()
    cands = []
    for k in order:
        x, y = int(xs[k]), int(ys[k])
        key = (int(x // cell), int(y // cell))
        if any((key[0] + i, key[1] + j) in taken for i in (-1, 0, 1) for j in (-1, 0, 1)):
            continue
        taken.add(key)
        cands.append({"x": x, "y": y, "nx": float(rm.nx[y, x]), "ny": float(rm.ny[y, x]),
                      "scale_px": float(rm.scale[y, x]), "ridge_response": float(rm.response[y, x]),
                      "anisotropy": float(rm.anisotropy[y, x]), "snr_pix": float(sig[y, x])})
        if len(cands) >= max_candidates:
            break
    return cands


class FilamentDetectionStrategy(Protocol):
    """Contrato para estrategias de detección reproducibles de filamentos."""
    def detect(self, image, variance, masks, config): ...


@dataclass
class FilamentDetectionResult:
    strategy: str
    ridge_map: RidgeMap
    candidates: list
    binary_mask: np.ndarray
    metrics: dict = field(default_factory=dict)


class HessianFilamentStrategy:
    def detect(self, image, variance, masks, config):
        raw=np.asarray(image,np.float32); bkg=masks.get("background")
        if bkg is None: raise ValueError("HessianFilamentStrategy requiere background")
        work=raw-np.asarray(bkg.bkg,np.float32)
        if masks.get("star_mask") is not None:
            work=np.array(work,copy=True); work[np.asarray(masks["star_mask"],bool)]=np.nan
        rm=hessian_ridge_response(work,config.sigmas)
        cands=ridge_candidates(raw,bkg,rm,config.snr_min,config.min_separation_px,config.max_candidates)
        if masks.get("star_mask") is not None:
            sm=np.asarray(masks["star_mask"],bool)
            cands=[c for c in cands if not sm[min(max(int(round(c["y"])),0),sm.shape[0]-1),min(max(int(round(c["x"])),0),sm.shape[1]-1)]]
        binary=np.zeros(raw.shape,bool)
        for c in cands: binary[int(round(c["y"])),int(round(c["x"]))]=True
        return FilamentDetectionResult("hessian",rm,cands,binary,{"n_candidates":len(cands)})


class CannyFilamentStrategy:
    def detect(self, image, variance, masks, config):
        a=np.asarray(image,np.float32); bkg=masks.get("background")
        if bkg is None: raise ValueError("CannyFilamentStrategy requiere background")
        rms=np.sqrt(np.maximum(np.asarray(variance,np.float32),1e-12)) if variance is not None else np.asarray(bkg.rms,np.float32)
        sn=(a-np.asarray(bkg.bkg,np.float32))/np.maximum(rms,1e-12)
        # Adaptive thresholds in SNR space; Canny if available, gradient fallback otherwise.
        if HAS_CANNY:
            lo=float(max(0.5,np.percentile(sn[np.isfinite(sn)],[50])[0]/2.0))
            hi=float(max(lo+0.5,config.snr_min))
            edges=_canny(np.nan_to_num(sn,nan=0.0),sigma=1.2,low_threshold=lo,high_threshold=hi)
        else:
            gx,gy=np.gradient(ndi.gaussian_filter(np.nan_to_num(sn),1.0)); g=np.hypot(gx,gy)
            thr=float(np.percentile(g[np.isfinite(g)],95)) if np.isfinite(g).any() else np.inf
            edges=g>=thr
        if masks.get("star_mask") is not None: edges=np.asarray(edges,bool)&~np.asarray(masks["star_mask"],bool)
        lab,n=ndi.label(edges); sizes=np.bincount(lab.ravel()) if n else np.array([0])
        min_size=max(8,int(getattr(config,"filament_min_component",24)))
        if n: edges=np.isin(lab,np.flatnonzero(sizes>=min_size))
        gy,gx=np.gradient(ndi.gaussian_filter(np.nan_to_num(a-np.asarray(bkg.bkg)),1.0))
        mag=np.hypot(gx,gy)+1e-12; nx=gx/mag; ny=gy/mag
        resp=np.where(edges,np.minimum(np.maximum(sn,0),50),0.0)
        rm=RidgeMap(resp,nx,ny,np.ones_like(resp),np.ones_like(resp))
        cands=ridge_candidates(a,bkg,rm,config.snr_min,config.min_separation_px,config.max_candidates,max_anisotropy=1.5)
        return FilamentDetectionResult("canny_snr",rm,cands,edges,{"n_edges":int(edges.sum()),"n_candidates":len(cands),"canny_available":HAS_CANNY})


def outward_normal(grad, x, y, nx, ny):
    gy, gx = grad
    g = gx[y, x] * nx + gy[y, x] * ny
    return (nx, ny) if g <= 0 else (-nx, -ny)


# ====================================================================
# CLASIFICACIÓN DE CANDIDATOS vs ESTRELLAS
# ====================================================================
def annotate_point_source_proximity(cands, sources, exclusion_radius_px):
    if not cands:
        return cands
    if sources is None or len(sources) == 0:
        for c in cands:
            c["candidate_type"] = "shock"
            c["source_distance_px"] = float("nan")
        return cands
    try:
        from scipy.spatial import cKDTree
        xy = np.asarray(sources[:, :2], dtype=float)
        tree = cKDTree(xy)
        q = np.asarray([[float(c["x"]), float(c["y"])] for c in cands], dtype=float)
        dist, _ = tree.query(q, k=1)
        for c, d in zip(cands, np.asarray(dist, dtype=float)):
            c["source_distance_px"] = float(d)
            aniso = finite(c.get("anisotropy"), 1.0)
            is_ridge = aniso > 1.8
            if d <= exclusion_radius_px and not is_ridge:
                c["candidate_type"] = "star"
            elif d <= exclusion_radius_px * 0.6:
                c["candidate_type"] = "star"
            else:
                c["candidate_type"] = "shock"
    except Exception as exc:
        LOG.warning("No se pudo calcular proximidad a estrellas: %s", exc)
        for c in cands:
            c["candidate_type"] = "shock"
            c["source_distance_px"] = float("nan")
    return cands


def annotate_existing_catalog_stars(rows, sources, exclusion_radius_px):
    if not rows or sources is None or len(sources) == 0:
        return rows
    tmp = [r for r in rows if math.isfinite(finite(r.get("x"))) and math.isfinite(finite(r.get("y")))]
    if not tmp:
        return rows
    try:
        from scipy.spatial import cKDTree
        tree = cKDTree(np.asarray(sources[:, :2], float))
        q = np.asarray([[float(r["x"]), float(r["y"])] for r in tmp], dtype=float)
        dist, _ = tree.query(q, k=1)
        for r, d in zip(tmp, np.asarray(dist, dtype=float)):
            r["source_distance_px"] = float(d)
            if d <= exclusion_radius_px:
                r["candidate_type"] = "star"
                r["status"] = "rejected_star"
                r["reason"] = "fuente puntual: excluida del análisis de frentes"
            else:
                r.setdefault("candidate_type", "shock")
    except Exception as exc:
        LOG.warning("No se pudo actualizar el catálogo acumulado: %s", exc)
    return rows


# ====================================================================
# PERFILES ESTELARES
# ====================================================================
def extract_stellar_profile(image, bkg, x, y, rmax=18, dr=0.5):
    arr = np.asarray(image, np.float32); H, W = arr.shape
    rmax = float(min(rmax, max(2.0, min(H, W) / 4.0)))
    x0 = float(x); y0 = float(y)
    yy, xx = np.mgrid[max(0,int(y0-rmax-1)):min(H,int(y0+rmax+2)),
                       max(0,int(x0-rmax-1)):min(W,int(x0+rmax+2))]
    cut = arr[yy,xx] - bkg.bkg[yy,xx]
    rr = np.hypot(xx-x0, yy-y0)
    edges = np.arange(0.0, rmax+dr, dr)
    t=[]; prof=[]; err=[]
    for a,b in zip(edges[:-1],edges[1:]):
        m=(rr>=a)&(rr<b)&np.isfinite(cut)
        vals=cut[m]
        if vals.size<3: continue
        t.append(0.5*(a+b))
        prof.append(float(np.nanmedian(vals)))
        err.append(float(1.4826*np.nanmedian(np.abs(vals-np.nanmedian(vals)))/math.sqrt(vals.size)))
    return {"r_px": t, "ha": prof, "err": err}


def build_stellar_profiles(im_ha, im_o3, bkg_ha, bkg_o3, stars, max_profiles=300):
    out = {}
    rows = sorted(stars or [], key=lambda r: finite(r.get("g_mag"), 99.0))[:max_profiles]
    for r in rows:
        x_px = finite(r.get("x_px"), float("nan"))
        y_px = finite(r.get("y_px"), float("nan"))
        if not (math.isfinite(x_px) and math.isfinite(y_px)):
            continue
        key = star_profile_key(int(r.get("det_id", 0)))
        try:
            ha = extract_stellar_profile(im_ha.data, bkg_ha, x_px, y_px)
            o3 = extract_stellar_profile(im_o3.data, bkg_o3, x_px, y_px)
            n = min(len(ha["r_px"]), len(o3["r_px"]))
            if n < 5:
                continue
            out[key] = {
                "r_px": ha["r_px"][:n], "ha": ha["ha"][:n], "ha_err": ha["err"][:n],
                "oiii": o3["ha"][:n], "oiii_err": o3["err"][:n],
                "x_px": float(x_px), "y_px": float(y_px),
                "det_id": r.get("det_id"), "source_id": r.get("source_id"),
                "g_mag": r.get("g_mag"), "bp_rp": r.get("bp_rp"),
                "spectral_class_est": r.get("spectral_class_est"),
                "luminosity_class_est": r.get("luminosity_class_est"),
                "simbad_main_id": r.get("simbad_main_id"),
                "simbad_otype": r.get("simbad_otype"),
                "simbad_type_pretty": r.get("simbad_type_pretty"),
                "interest": r.get("interest", ""),
            }
        except Exception:
            continue
    return out


# ====================================================================
# OPERADOR DE MEDIDA
# ====================================================================
@dataclass
class Profile:
    t: np.ndarray
    y: np.ndarray
    yerr: np.ndarray
    n_valid: np.ndarray
    cov: Optional[np.ndarray] = None
    method: str = "operator-sparse"
    valid_frac: Optional[np.ndarray] = None


def gaussian_kernel(sigma_px, truncate=3.0):
    if sigma_px <= 0:
        return np.ones((1, 1))
    r = int(math.ceil(truncate * sigma_px))
    g = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma_px) ** 2)
    k = np.outer(g, g)
    return k / k.sum()


class SamplingOperator:
    def __init__(self, mat, shape, valid_frac, sparse_backend, min_valid_frac=0.5):
        self.mat, self.shape, self.valid_frac = mat, shape, valid_frac
        self.sparse, self.min_valid_frac = sparse_backend, min_valid_frac

    @property
    def empty_rows(self):
        return self.valid_frac < self.min_valid_frac

    @property
    def n_bins(self):
        return self.mat.shape[0]

    def matvec(self, img):
        return np.asarray(self.mat @ np.nan_to_num(np.asarray(img, np.float64)).ravel()).ravel()

    def cov(self, var):
        v = np.nan_to_num(np.asarray(var, np.float64)).ravel()
        if self.sparse:
            return np.asarray((self.mat.multiply(v[None, :]) @ self.mat.T).todense())
        return (self.mat * v[None, :]) @ self.mat.T


def sampling_operator(x, y, shape, kernel=None, bad=None, min_valid_frac=0.5):
    x = np.asarray(x, np.float64); y = np.asarray(y, np.float64)
    if x.ndim == 1:
        x, y = x[:, None], y[:, None]
    n_bins, width = x.shape
    ny_, nx_ = shape
    kernel = np.ones((1, 1)) if kernel is None else np.asarray(kernel, np.float64)
    kh, kw = kernel.shape
    ky, kx = np.indices(kernel.shape)
    ky, kx, kv = (ky - kh // 2).ravel(), (kx - kw // 2).ravel(), kernel.ravel()
    x0, y0 = np.floor(x), np.floor(y)
    fx, fy = x - x0, y - y0
    corners = [(0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)),
               (0, 1, (1 - fx) * fy), (1, 1, fx * fy)]
    rows, cols, vals = [], [], []
    rid = np.broadcast_to(np.arange(n_bins)[:, None], (n_bins, width))
    for dx, dy, wgt in corners:
        for oy, ox, kval in zip(ky, kx, kv):
            ix = (x0 + dx + ox).astype(int)
            iy = (y0 + dy + oy).astype(int)
            w = wgt * kval / width
            inside = (ix >= 0) & (ix < nx_) & (iy >= 0) & (iy < ny_)
            rows.append(rid[inside])
            cols.append((iy[inside] * nx_ + ix[inside]))
            vals.append(w[inside])
    rows = np.concatenate(rows); cols = np.concatenate(cols); vals = np.concatenate(vals)
    total_w = np.bincount(rows, weights=vals, minlength=n_bins)
    if bad is not None:
        badv = np.asarray(bad, bool).ravel()
        good = ~badv[cols]
        rows, cols, vals = rows[good], cols[good], vals[good]
    valid_w = np.bincount(rows, weights=vals, minlength=n_bins)
    valid_frac = np.where(total_w > 0, valid_w / np.maximum(total_w, 1e-300), 0.0)
    scale = np.where(valid_w > 0, 1.0 / np.maximum(valid_w, 1e-300), 0.0)
    scale[valid_frac < min_valid_frac] = 0.0
    vals = vals * scale[rows]
    keep = vals != 0
    rows, cols, vals = rows[keep], cols[keep], vals[keep]
    if HAS_SPARSE:
        mat = _sparse.csr_matrix((vals, (rows, cols)), shape=(n_bins, ny_ * nx_))
        return SamplingOperator(mat, shape, valid_frac, True, min_valid_frac)
    mat = np.zeros((n_bins, ny_ * nx_))
    np.add.at(mat, (rows, cols), vals)
    return SamplingOperator(mat, shape, valid_frac, False, min_valid_frac)


def background_projector(t, cov, edge_mask, min_points=6):
    t = np.asarray(t, np.float64)
    e = np.asarray(edge_mask, bool) & np.isfinite(t)
    if e.sum() < min_points:
        raise ValueError(f"fondo GLS: solo {int(e.sum())} bins de borde")
    X = np.column_stack([np.ones_like(t), t / max(float(np.max(np.abs(t))), 1e-12)])
    Ce = np.asarray(cov, np.float64)[np.ix_(e, e)]
    Ce = Ce + np.eye(Ce.shape[0]) * (1e-10 * max(float(np.trace(Ce)) / Ce.shape[0], 1e-300))
    Wi = np.linalg.pinv(Ce)
    Xe = X[e]
    B = np.zeros((2, t.size))
    B[:, e] = np.linalg.solve(Xe.T @ Wi @ Xe, Xe.T @ Wi)
    return np.eye(t.size) - X @ B


def integration_weights(t, mask):
    w = np.zeros(t.size)
    idx = np.flatnonzero(mask)
    if idx.size < 2:
        return w
    dt = np.diff(t[idx])
    w[idx[:-1]] += 0.5 * dt
    w[idx[1:]] += 0.5 * dt
    return w


def extract_profile(data, bkg, x0, y0, nx, ny, half_length=20, width=7, step=0.5,
                    psf_sigma_px=0.0, with_cov=True):
    t = np.arange(-half_length, half_length + step / 2, step)
    w = np.arange(width) - (width - 1) / 2.0
    tx, ty = -ny, nx
    X = x0 + t[:, None] * nx + w[None, :] * tx
    Y = y0 + t[:, None] * ny + w[None, :] * ty
    kernel = gaussian_kernel(psf_sigma_px)
    pad = kernel.shape[0] // 2 + 2
    H, W = data.shape
    xa, xb = int(max(0, math.floor(X.min()) - pad)), int(min(W, math.ceil(X.max()) + pad + 1))
    ya, yb = int(max(0, math.floor(Y.min()) - pad)), int(min(H, math.ceil(Y.max()) + pad + 1))
    if xb <= xa or yb <= ya:
        nanv = np.full(t.size, np.nan)
        return Profile(t, nanv, nanv, np.zeros(t.size), None, "operator-empty", np.zeros(t.size))
    img = np.asarray(data[ya:yb, xa:xb], np.float64) - np.asarray(bkg.bkg[ya:yb, xa:xb], np.float64)
    var = np.asarray(bkg.rms[ya:yb, xa:xb], np.float64) ** 2
    bad = ~np.isfinite(img) | ~np.isfinite(var)
    op = sampling_operator(X - xa, Y - ya, img.shape, kernel, bad)
    y = op.matvec(np.where(bad, 0.0, img))
    cov = op.cov(np.where(bad, 0.0, var))
    empty = op.empty_rows
    y[empty] = np.nan
    yerr = np.sqrt(np.maximum(np.diag(cov), 0.0))
    yerr[empty] = np.nan
    return Profile(t=t, y=y, yerr=yerr, n_valid=op.valid_frac * width,
                   cov=cov if with_cov else None,
                   method="operator-sparse" if op.sparse else "operator-dense",
                   valid_frac=op.valid_frac)


# ====================================================================
# AJUSTE
# ====================================================================
@dataclass
class PeakFit:
    center: float
    center_err: float
    sigma: float
    amplitude: float
    baseline: float
    snr: float
    chi2_red: float
    method: str
    ok: bool


def _gauss_lin_step(p, t):
    A, t0, s, b0, b1, b2 = p
    z = (t - t0) / (math.sqrt(2.0) * s)
    return A * np.exp(-0.5 * ((t - t0) / s) ** 2) + b0 + b1 * t + b2 * 0.5 * (1.0 - erf(z))


GLS_EIG_RTOL = 1e-6


def _whitener(prof, m):
    if prof.cov is None:
        return None
    Cm = prof.cov[np.ix_(m, m)]
    if not np.all(np.isfinite(Cm)) or Cm.shape[0] == 0:
        return None
    lam, U = np.linalg.eigh(0.5 * (Cm + Cm.T))
    keep = lam > GLS_EIG_RTOL * max(float(lam.max()), 1e-300)
    if keep.sum() < 8:
        return None
    return (U[:, keep] / np.sqrt(lam[keep])[None, :]).T


def _parabola_peak(t, ys):
    k = int(np.argmax(ys))
    if 0 < k < t.size - 1:
        y1, y2, y3 = ys[k - 1], ys[k], ys[k + 1]
        den = (y1 - 2 * y2 + y3)
        dt = 0.5 * (y1 - y3) / den if den != 0 else 0.0
        return t[k] + dt * (t[1] - t[0])
    return t[k]


def fit_peak(prof, t_window=None, step=True):
    m = np.isfinite(prof.y) & np.isfinite(prof.yerr)
    if t_window is not None:
        m &= np.abs(prof.t) <= t_window
    if m.sum() < 5:
        return PeakFit(np.nan, np.nan, np.nan, np.nan, np.nan, 0.0, np.nan, "insufficient", False)
    t = prof.t[m]; y = prof.y[m]; e = np.maximum(prof.yerr[m], 1e-12)
    step_t = float(abs(prof.t[1] - prof.t[0])) if prof.t.size > 1 else 1.0
    ys = ndi.gaussian_filter1d(y, 1.0)
    k = int(np.argmax(ys))
    y_range = float(np.ptp(ys))
    if y_range <= 0:
        return PeakFit(float(t[k]), step_t, step_t, 0.0, float(np.median(y)), 0.0, np.nan, "flat", False)
    A0 = max(ys[k] - np.median(y), 1e-9)
    inner = float(np.median(y[: max(3, k // 2)])) if k > 2 else float(np.median(y))
    outer = float(np.median(y[min(len(y) - 3, (k + len(y)) // 2):])) if k < len(y) - 3 else inner
    p0 = [A0, float(t[k]), max(1.0, 0.1 * (t[-1] - t[0])), outer, 0.0, max(inner - outer, 0.0)]
    lo = [0.0, float(t[0]), 0.3, -np.inf, -np.inf, 0.0]
    hi = [np.inf, float(t[-1]), 0.9 * (t[-1] - t[0]), np.inf, np.inf, np.inf if step else 1e-9]
    if not step:
        p0[5] = 0.0
        hi[5] = 0.0
    best_ls = None
    try:
        L = _whitener(prof, m)
    except Exception:
        L = None
    def resid(p):
        r = _gauss_lin_step(p, t) - y
        return L @ r if L is not None else r / e
    try:
        res = optimize.least_squares(resid, p0, bounds=(lo, hi), x_scale="jac", max_nfev=800)
        dof = max((L.shape[0] if L is not None else t.size) - 6, 1)
        chi2r = float(np.sum(res.fun ** 2) / dof)
        J = res.jac
        try:
            cov = np.linalg.pinv(J.T @ J) * max(chi2r, 1.0)
            A, t0, s, b0, b1, _b2 = res.x
            t0_err = float(math.sqrt(max(cov[1, 1], 0.0)))
            snr = float(A / max(math.sqrt(max(cov[0, 0], 0.0)), 1e-12))
        except Exception:
            A, t0, s, b0, b1, _b2 = res.x
            t0_err = step_t
            snr = float(A / max(np.median(e), 1e-12))
        ok = bool(res.success and snr > 2.0 and float(t[0]) <= t0 <= float(t[-1]))
        meth = ("gauss+lin+step" if step else "gauss+lin") + ("+GLS" if L is not None else "+WLS")
        best_ls = PeakFit(float(t0), t0_err, float(s), float(A), float(b0), float(snr),
                          chi2r, meth, ok)
    except Exception as exc:
        LOG.debug("fit_peak LSQ fallback: %s", exc)
    t0_par = _parabola_peak(t, ys)
    noise = float(np.median(e))
    A_par = float(ys[k] - np.median(y))
    snr_par = A_par / max(noise, 1e-12)
    par = PeakFit(float(t0_par), step_t, step_t, A_par, float(np.median(y)),
                  float(snr_par), np.nan, "parabola", bool(snr_par > 2.0))
    if best_ls is not None and best_ls.ok:
        return best_ls
    if par.ok:
        return par
    return best_ls if best_ls is not None else par


# ====================================================================
# CALIBRACIÓN
# ====================================================================
def ccm89_alav(wave_angstrom, r_v=3.1):
    """A(lambda)/A(V) de Cardelli, Clayton & Mathis (1989).

    Dominio implementado: 0.3 <= x <= 10 micron^-1 y 2 <= R_V <= 6,
    consistente con la implementación pública de referencia dust_extinction.
    Para las líneas Hα/[O III] se usa la rama óptica 1.1 <= x <= 3.3.
    """
    wave_angstrom = float(wave_angstrom)
    r_v = float(r_v)
    if not math.isfinite(wave_angstrom) or wave_angstrom <= 0:
        raise ValueError("Longitud de onda inválida para CCM89")
    if not math.isfinite(r_v) or not (2.0 <= r_v <= 6.0):
        raise ValueError("CCM89 requiere 2.0 <= R_V <= 6.0")
    x = 1e4 / wave_angstrom
    if 0.3 <= x < 1.1:
        a, b = 0.574 * x ** 1.61, -0.527 * x ** 1.61
    elif 1.1 <= x <= 3.3:
        y = x - 1.82
        a = (1 + 0.17699 * y - 0.50447 * y ** 2 - 0.02427 * y ** 3 + 0.72085 * y ** 4
             + 0.01979 * y ** 5 - 0.77530 * y ** 6 + 0.32999 * y ** 7)
        b = (1.41338 * y + 2.28305 * y ** 2 + 1.07233 * y ** 3 - 5.38434 * y ** 4
             - 0.62251 * y ** 5 + 5.30260 * y ** 6 - 2.09002 * y ** 7)
    else:
        raise ValueError("CCM89 fuera de rango")
    return a + b / r_v


@dataclass
class LineCalibration:
    oiii_transmission: float = 1.0
    ha_transmission: float = 1.0
    oiii_exptime_s: float = 1.0
    ha_exptime_s: float = 1.0
    oiii_zp_factor: float = 1.0
    ha_zp_factor: float = 1.0
    nii_over_ha: float = 0.0
    nii_transmission_rel: float = 1.0
    ebv: float = 0.0
    ebv_err: float = 0.0
    r_v: float = 3.1
    calib_frac_err: float = 0.0
    calibrated: bool = False
    oiii_filter: str = ""
    ha_filter: str = ""
    calibration_basis: str = "instrumental"
    calibration_warning: str = ""
    photometric_calibrated: bool = False
    spcc_ratio_factor: float = 1.0
    # v38: curvas T(λ) asociadas a esta calibración, conservadas para provenance/UI.
    filter_curve_oiii: str = ""
    filter_curve_ha: str = ""
    zeropoint_source: str = ""
    zeropoint_error_mag: float = float("nan")
    calibration_id: str = ""
    validation_evidence: dict = field(default_factory=dict)

    def ratio_correction(self):
        vals=(self.ha_transmission,self.oiii_transmission,self.ha_exptime_s,self.oiii_exptime_s,
              self.ha_zp_factor,self.oiii_zp_factor,self.r_v,self.ebv,self.ebv_err,self.nii_over_ha)
        if not all(math.isfinite(float(v)) for v in vals):
            raise ValueError("Parámetros de calibración no finitos")
        if min(self.ha_transmission,self.oiii_transmission,self.ha_exptime_s,self.oiii_exptime_s,self.ha_zp_factor,self.oiii_zp_factor) <= 0:
            raise ValueError("Transmisiones, exposiciones y ZP deben ser > 0")
        if self.ebv < 0 or self.ebv_err < 0 or self.nii_over_ha < -1:
            raise ValueError("Parámetros de extinción/NII fuera de rango")
        f = (self.ha_transmission * self.ha_exptime_s * self.ha_zp_factor) / \
            (self.oiii_transmission * self.oiii_exptime_s * self.oiii_zp_factor)
        f *= (1.0 + self.nii_over_ha * self.nii_transmission_rel)
        dk = ccm89_alav(5007.0, self.r_v) - ccm89_alav(6563.0, self.r_v)
        f *= 10 ** (0.4 * self.ebv * self.r_v * dk)
        frac = math.sqrt(self.calib_frac_err ** 2 + (0.4 * math.log(10) * self.r_v * dk * self.ebv_err) ** 2)
        return f, frac


@dataclass
class LineRatio:
    value: float
    err: float
    log10: float
    log10_err: float
    calibrated: bool
    flux_oiii: float
    flux_ha: float
    log10_err_stat: float = float("nan")
    log10_err_sys: float = float("nan")
    method: str = "delta-method"


@dataclass
class FluxMeasurement:
    flux: float
    flux_err: float
    centroid: float
    centroid_err: float
    n_aperture: int
    n_edge: int
    chi2_red_bkg: float
    method: str
    ok: bool


def integrated_line_flux(prof, fit, n_sigma=2.5):
    if not fit.ok or not math.isfinite(fit.sigma):
        return float("nan"), float("nan")
    m = np.isfinite(prof.y) & (np.abs(prof.t - fit.center) <= n_sigma * fit.sigma)
    if m.sum() < 3:
        return float("nan"), float("nan")
    dt = float(abs(prof.t[1] - prof.t[0]))
    y = prof.y[m] - fit.baseline
    return float(np.sum(y) * dt), float(math.sqrt(np.sum(prof.yerr[m] ** 2)) * dt)


def measure_line_flux(prof, center, sigma, n_sigma=2.5, edge_gap_px=2.0):
    nan = float("nan")
    if not (math.isfinite(center) and math.isfinite(sigma) and sigma > 0):
        return FluxMeasurement(nan, nan, nan, nan, 0, 0, nan, "undefined", False)
    good = np.isfinite(prof.y) & np.isfinite(prof.yerr)
    t = prof.t
    cov = prof.cov if prof.cov is not None else np.diag(np.nan_to_num(prof.yerr, nan=0.0) ** 2)
    cov = np.where(np.isfinite(cov), cov, 0.0)
    ap = good & (np.abs(t - center) <= n_sigma * sigma)
    edge = good & (np.abs(t - center) >= n_sigma * sigma + edge_gap_px)
    if ap.sum() < 3:
        return FluxMeasurement(nan, nan, nan, nan, int(ap.sum()), int(edge.sum()), nan, "aperture-too-small", False)
    p = np.where(good, prof.y, 0.0)
    try:
        M = background_projector(t, cov, edge)
        q = M @ p
        Cq = M @ cov @ M.T
        Ce = Cq[np.ix_(edge, edge)]
        var_e = np.maximum(np.diag(Ce), 1e-300)
        chi2_bkg = float(np.sum(q[edge] ** 2 / var_e) / max(int(edge.sum()) - 2, 1))
    except Exception:
        return FluxMeasurement(nan, nan, nan, nan, int(ap.sum()), int(edge.sum()), nan, "no-edge-bands", False)
    w = integration_weights(t, ap)
    F = float(w @ q)
    vF = float(w @ Cq @ w)
    if F > 0 and vF > 0 and F / math.sqrt(vF) > 2.5:
        c = float((w * t) @ q / F)
        d = w * (t - c) / F
        vc = float(d @ Cq @ d)
        cen, cen_err = c, math.sqrt(max(vc, 0.0))
    else:
        cen, cen_err = nan, nan
    return FluxMeasurement(F, math.sqrt(max(vF, 0.0)), cen, cen_err,
                           int(ap.sum()), int(edge.sum()), chi2_bkg,
                           "operator+GLS-background", True)


def line_ratio(f_oiii, e_oiii, f_ha, e_ha, cal, cov_oiii_ha=0.0):
    corr, cfrac = cal.ratio_correction()
    if not (math.isfinite(f_oiii) and math.isfinite(f_ha)) or not math.isfinite(e_ha) or f_ha <= 3 * e_ha:
        return LineRatio(np.nan, np.nan, np.nan, np.nan, cal.calibrated, f_oiii, f_ha,
                         method="non-detection-ha")
    r = corr * f_oiii / f_ha
    if not (f_oiii > 0):
        return LineRatio(r, np.nan, np.nan, np.nan, cal.calibrated, f_oiii, f_ha,
                         method="non-detection-oiii")
    var_stat = (e_oiii / f_oiii) ** 2 + (e_ha / f_ha) ** 2 - 2.0 * cov_oiii_ha / (f_oiii * f_ha)
    frac_stat = math.sqrt(max(var_stat, 0.0))
    frac = math.sqrt(frac_stat ** 2 + cfrac ** 2)
    ln10 = math.log(10)
    return LineRatio(r, abs(r) * frac, math.log10(r) if r > 0 else float("nan"),
                     frac / ln10, cal.calibrated, f_oiii, f_ha,
                     log10_err_stat=frac_stat / ln10, log10_err_sys=cfrac / ln10)


def classify_front(offset_value, offset_err, ratio, units="arcsec"):
    if not math.isfinite(offset_value):
        return "indeterminado", "sin desfase medible"
    sig = abs(offset_value) / offset_err if (math.isfinite(offset_err) and offset_err > 0) else 0.0
    if sig < 2:
        base = "coincidente"
        just = f"|Δ|={offset_value:.2f} {units} < 2σ ({offset_err:.2f} {units})"
    elif offset_value > 0:
        base = "OIII_delante"
        just = f"[O III] {offset_value:.2f}±{offset_err:.2f} {units} hacia fuera"
    else:
        base = "OIII_detras"
        just = f"[O III] {abs(offset_value):.2f}±{offset_err:.2f} {units} hacia dentro"
    if not math.isfinite(ratio.value):
        return base, just + "; cociente no medible"
    if not ratio.calibrated:
        return base, just + f"; [O III]/Hα={ratio.value:.2f} INSTRUMENTAL"
    r = ratio.value
    if base == "OIII_detras" and r < 0.5:
        return "no_radiativo_incompleto", just + f"; [O III]/Hα={r:.2f}"
    if base == "OIII_delante" and r >= 0.5:
        return "radiativo_completo", just + f"; [O III]/Hα={r:.2f}"
    if r > 3.0:
        return "radiativo_incompleto_OIII_dominante", just + f"; [O III]/Hα={r:.2f}"
    return base, just + f"; [O III]/Hα={r:.2f}"


# ====================================================================
# FÍSICA
# ====================================================================
class CoolingCurve:
    DEFAULT = np.array([
        [4.00, -23.9], [4.10, -23.0], [4.20, -22.3], [4.30, -21.9], [4.40, -21.7], [4.50, -21.8],
        [4.60, -21.9], [4.70, -21.7], [4.80, -21.5], [4.90, -21.3], [5.00, -21.2], [5.10, -21.1],
        [5.20, -21.0], [5.30, -21.1], [5.40, -21.3], [5.50, -21.5], [5.60, -21.7], [5.70, -21.9],
        [5.80, -22.0], [5.90, -22.1], [6.00, -22.1], [6.20, -22.3], [6.40, -22.4], [6.60, -22.6],
        [6.80, -22.8], [7.00, -22.9], [7.50, -23.0], [8.00, -22.8], [8.50, -22.55],
    ])

    def __init__(self, table=None, efficiency=1.0, name="SD93-approx", allow_extrapolation=False):
        tab = np.asarray(self.DEFAULT if table is None else table, np.float64)
        tab = tab[np.argsort(tab[:, 0])]
        self.logT, self.logL = tab[:, 0], tab[:, 1]
        self._f = PchipInterpolator(self.logT, self.logL, extrapolate=False)
        self.efficiency = float(efficiency)
        self.name = name
        self.allow_extrapolation = bool(allow_extrapolation)

    @classmethod
    def from_csv(cls, path, **kw):
        rows = []
        with open(path, newline="") as fh:
            for r in csv.DictReader(fh):
                rows.append([float(r["logT"]), float(r["logLambda"])])
        return cls(np.asarray(rows), name=Path(path).name, **kw)

    def __call__(self, T):
        arr = np.asarray(T, np.float64)
        lt = np.log10(arr)
        if not self.allow_extrapolation:
            if np.any(~np.isfinite(lt)) or np.any(lt < self.logT[0]) or np.any(lt > self.logT[-1]):
                raise ValueError(f"CoolingCurve: T fuera del dominio [{10**self.logT[0]:.3g}, {10**self.logT[-1]:.3g}] K")
        else:
            lt = np.clip(lt, self.logT[0], self.logT[-1])
        return self.efficiency * 10.0 ** self._f(lt)


@dataclass
class ShockState:
    v_s_kms: float
    n0: float
    T0: float
    ionization: str
    mach: float
    compression: float
    n_H_post: float
    n_e_post: float
    n_t_post: float
    T_post: float
    T_e_post: float
    T_i_post: float
    beta_te_ti: float
    P_ram: float
    P_thermal_post: float
    t_cool_isobaric_integrated_yr: float
    L_cool_isobaric_integrated_pc: float
    t_cool_instantaneous_isochoric_yr: float
    L_cool_instantaneous_advective_pc: float
    regime: str


def rankine_hugoniot(v_s_kms, n0, T0=1e4, comp=None, ionization_pre="H+He+",
                     ionization_post="H+He++", beta_te_ti=1.0, cooling=None,
                     T_floor=1e4, gamma=C.gamma):
    comp = comp or Composition()
    if not (beta_te_ti > 0 and math.isfinite(beta_te_ti)):
        raise ValueError("beta_te_ti debe ser positivo")
    v = v_s_kms * C.km
    mu0 = comp.mu(ionization_pre); mu2 = comp.mu(ionization_post)
    rho0 = comp.mass_per_H * n0
    cs0 = math.sqrt(gamma * C.k_B * T0 / (mu0 * C.m_p))
    M = v / cs0
    if M <= 1.0:
        raise ValueError(f"v_s={v_s_kms} km/s subsónico (M={M:.2f})")
    r = (gamma + 1) * M * M / ((gamma - 1) * M * M + 2)
    T2_over_T1 = (2 * gamma * M * M - (gamma - 1)) * ((gamma - 1) * M * M + 2) / ((gamma + 1) ** 2 * M * M)
    T2 = T2_over_T1 * T0 * (mu2 / mu0)
    nH2 = n0 * r
    ne2 = nH2 * comp.chi_e(ionization_post)
    nt2 = nH2 * comp.chi_tot(ionization_post)
    n_ion = nt2 - ne2
    P_th = nt2 * C.k_B * T2
    Te = P_th / (C.k_B * (ne2 + n_ion / beta_te_ti))
    Ti = Te / beta_te_ti
    P_ram = rho0 * v * v
    cool = cooling or CoolingCurve()
    t_inst = 1.5 * nt2 * C.k_B * T2 / (ne2 * nH2 * float(cool(T2)))
    L_inst = (v / r) * t_inst
    if T2 > T_floor * 1.05:
        Tg = np.logspace(math.log10(T_floor), math.log10(T2), 400)
        fe, fH = ne2 / nt2, nH2 / nt2
        dtdT = 2.5 * C.k_B / (fe * fH * (nt2 * T2 / Tg) * cool(Tg))
        t_cool = float(trapezoid(dtdT, Tg))
        vT = (v / r) * (Tg / T2)
        L_cool = float(trapezoid(vT * dtdT, Tg))
    else:
        t_cool, L_cool = 0.0, 0.0
    return ShockState(v_s_kms=v_s_kms, n0=n0, T0=T0, ionization=ionization_post,
                      mach=M, compression=r, n_H_post=nH2, n_e_post=ne2, n_t_post=nt2,
                      T_post=T2, T_e_post=Te, T_i_post=Ti, beta_te_ti=beta_te_ti,
                      P_ram=P_ram, P_thermal_post=P_th,
                      t_cool_isobaric_integrated_yr=t_cool / C.yr,
                      L_cool_isobaric_integrated_pc=L_cool / C.pc,
                      t_cool_instantaneous_isochoric_yr=t_inst / C.yr,
                      L_cool_instantaneous_advective_pc=L_inst / C.pc,
                      regime=regime_from_physics(v_s_kms, t_cool / C.yr))


def regime_from_physics(v_s_kms, t_cool_yr, age_yr=None):
    """Clasificación basada en t_age/t_cool; no presupone umbrales universales de velocidad."""
    v=finite(v_s_kms,float("nan"))
    if not math.isfinite(v): return "indeterminado"
    age=finite(age_yr,float("nan")); tc=finite(t_cool_yr,float("nan"))
    if not (math.isfinite(age) and math.isfinite(tc) and age>0 and tc>0):
        return "cinemático_sin_clasificación_radiativa"
    ratio=age/tc
    state="pre-enfriamiento" if ratio<0.1 else ("enfriamiento_incompleto" if ratio<1.0 else "enfriamiento_desarrollado")
    return f"{state} (t_age/t_cool={ratio:.3g})"


def shock_monte_carlo(v_kms, v_err, n0, n0_logerr=0.3, nsamp=2000, rng=None,
                       cooling=None, comp=None, T0=1e4):
    """Propaga incertidumbres con el mismo forward model hidrodinámico que rankine_hugoniot."""
    rng = rng or np.random.default_rng(0)
    comp = comp or Composition(); cool = cooling or CoolingCurve()
    v_kms_arr = rng.normal(v_kms, max(v_err, 1e-3), nsamp)
    n = n0 * 10 ** rng.normal(0.0, n0_logerr, nsamp)
    mu0 = comp.mu("H+He+"); mu2 = comp.mu("H+He++")
    v = np.maximum(v_kms_arr, 1e-3) * C.km
    cs0 = math.sqrt(C.gamma * C.k_B * T0 / (mu0 * C.m_p))
    M = np.maximum(v / cs0, 1.000001)
    r = (C.gamma + 1.0) * M*M / ((C.gamma - 1.0) * M*M + 2.0)
    T_ratio = ((2.0*C.gamma*M*M - (C.gamma-1.0)) * ((C.gamma-1.0)*M*M + 2.0) / ((C.gamma+1.0)**2 * M*M))
    T2 = np.maximum(T_ratio * T0 * (mu2/mu0), 1.0)
    nH2 = n * r
    ne2 = nH2 * comp.chi_e("H+He++")
    nt2 = nH2 * comp.chi_tot("H+He++")
    P_ram = comp.mass_per_H * n * v * v
    # Integrate cooling on a normalized temperature coordinate, matching rankine_hugoniot.
    u = np.geomspace(1e-3, 1.0, 120)
    Tg = np.maximum(T2[:, None] * u[None, :], 1.0e4)
    valid = (T2 > 1.05e4) & (T2 <= 10**cool.logT[-1])
    t_cool = np.zeros(nsamp, float); L_cool = np.zeros(nsamp, float)
    if np.any(valid):
        tv = T2[valid]; nv = nt2[valid]; nev = ne2[valid]; nHv = nH2[valid]; rv = r[valid]; vv = v[valid]
        Tgv = Tg[valid]
        # The Rankine-Hugoniot cooling calculation is valid only inside the supplied table domain.
        Tgv = np.maximum(Tgv, 10**cool.logT[0])
        Lam = cool(Tgv)
        fe = nev/nv; fH = nHv/nv
        dtdT = 2.5*C.k_B / ((fe[:,None]*fH[:,None]) * (nv[:,None]*tv[:,None]/Tgv) * Lam)
        t_v = trapezoid(dtdT, Tgv, axis=1)
        vT = (vv[:,None]/rv[:,None]) * (Tgv/tv[:,None])
        L_v = trapezoid(vT*dtdT, Tgv, axis=1)
        t_cool[valid] = t_v; L_cool[valid] = L_v
    def pct(a):
        p = np.nanpercentile(a, [16, 50, 84])
        return float(p[1]), float(p[1]-p[0]), float(p[2]-p[1])
    return {"T_post_K": pct(T2), "P_ram_dyn_cm2": pct(P_ram),
            "t_cool_isobaric_integrated_yr": pct(t_cool/C.yr),
            "L_cool_isobaric_integrated_pc": pct(L_cool/C.pc),
            "v_s_kms": pct(v_kms_arr), "n0_cm3": pct(n)}


AGE_ETA = {"free_expansion": 1.0, "sedov_taylor": 0.4, "pressure_driven_snowplow": 2.0 / 7.0}


def dynamical_ages(R_pc, v_kms):
    if not (math.isfinite(R_pc) and math.isfinite(v_kms)) or v_kms <= 0:
        return {k: float("nan") for k in AGE_ETA}
    t_free = R_pc * C.pc / (v_kms * C.km) / C.yr
    return {k: eta * t_free for k, eta in AGE_ETA.items()}


# ====================================================================
# GRILLAS
# ====================================================================
@dataclass
class GridSolution:
    modes: list
    degenerate: bool
    n_nodes_used: int
    ratio_range: tuple
    note: str
    sigma_obs_dex: float = float("nan")
    sigma_model_dex: float = float("nan")
    sigma_total_dex: float = float("nan")


class ShockGrid:
    def __init__(self, v_kms, ratio, n0=None, name="grid"):
        v_arr=np.asarray(v_kms,float); r_arr=np.asarray(ratio,float)
        if v_arr.ndim!=1 or r_arr.ndim!=1 or v_arr.size!=r_arr.size:
            raise ValueError("Grilla: velocidad y ratio deben ser vectores 1D de igual longitud")
        n_arr=None if n0 is None else np.asarray(n0,float)
        if n_arr is not None and (n_arr.ndim!=1 or n_arr.size!=v_arr.size):
            raise ValueError("Grilla: n0 debe tener la misma longitud que velocidad/ratio")
        m=np.isfinite(v_arr)&np.isfinite(r_arr)&(r_arr>0)
        self.v=v_arr[m]; self.r=r_arr[m]
        self.n0=None if n_arr is None else n_arr[m]
        self.name=name
        self.log_ratio=np.log10(self.r)

    @classmethod
    def from_csv(cls, path):
        rows = list(csv.DictReader(open(path, newline="")))
        cols = {k.lower().strip(): k for k in rows[0].keys()}
        vk = cols.get("v_kms") or cols.get("v") or cols.get("velocity")
        rk = cols.get("ratio") or cols.get("oiii_ha") or cols.get("oiii/ha")
        if not vk or not rk:
            raise ValueError(f"CSV sin v_kms/ratio: {list(rows[0].keys())}")
        nk = cols.get("n0") or cols.get("n") or cols.get("density")
        v = np.array([float(r[vk]) for r in rows])
        ra = np.array([float(r[rk]) for r in rows])
        n0 = np.array([float(r[nk]) for r in rows]) if nk else None
        return cls(v, ra, n0, name=Path(path).name)

    @classmethod
    def builtin(cls):
        rows = list(csv.DictReader(io.StringIO(DEFAULT_SHOCK_GRID_CSV)))
        v = np.array([float(r["v_kms"]) for r in rows])
        ra = np.array([float(r["ratio"]) for r in rows])
        n0 = np.array([float(r["n0"]) for r in rows])
        return cls(v, ra, n0, name="heuristic_demo_grid")

    def invert(self, ratio, ratio_err, n0=None, n0_logtol=0.35, grid_model_logerr=0.15):
        rng_r = (float(self.r.min()), float(self.r.max()))
        if not (math.isfinite(ratio) and ratio > 0):
            return GridSolution([], False, 0, rng_r, "cociente no válido")
        lr = math.log10(ratio)
        le = max(ratio_err / (ratio * math.log(10)) if ratio_err > 0 else 0.05, 0.02)
        sig_tot = math.sqrt(le * le + grid_model_logerr ** 2)
        sel = np.ones(self.v.size, bool)
        if n0 is not None and self.n0 is not None:
            sel = np.abs(np.log10(self.n0) - math.log10(n0)) <= n0_logtol
            if not sel.any():
                return GridSolution([], False, 0, rng_r, "n0 solicitado fuera del dominio del grid", sigma_obs_dex=le, sigma_model_dex=grid_model_logerr, sigma_total_dex=sig_tot)
        v, lg = self.v[sel], self.log_ratio[sel]
        order = np.argsort(v)
        v, lg = v[order], lg[order]
        w = np.exp(-0.5 * (lg - lr) ** 2 / sig_tot ** 2)
        w_obs = np.exp(-0.5 * (lg - lr) ** 2 / le ** 2)
        if w.sum() <= 1e-300 or w.max() < 1e-3:
            return GridSolution([], False, int(sel.sum()), rng_r,
                                "cociente fuera de grilla (>3σ)",
                                sigma_obs_dex=le, sigma_model_dex=grid_model_logerr,
                                sigma_total_dex=sig_tot)
        def interval(vv, ww):
            if ww.sum() <= 1e-300:
                return float("nan"), float("nan")
            cw = np.cumsum(ww) / ww.sum()
            return float(np.interp(0.16, cw, vv)), float(np.interp(0.84, cw, vv))
        modes = []
        active = w > 0.05 * w.max()
        i = 0
        while i < v.size:
            if not active[i]:
                i += 1; continue
            j = i
            while j + 1 < v.size and (active[j + 1] or (j + 2 < v.size and active[j + 2])):
                j += 1
            vv, ww, wo = v[i:j + 1], w[i:j + 1], w_obs[i:j + 1]
            lo, hi = interval(vv, ww)
            lo_o, hi_o = interval(vv, wo)
            modes.append({"v_kms": float(np.sum(vv * ww) / ww.sum()),
                          "v_lo": lo, "v_hi": hi, "v_lo_obs": lo_o, "v_hi_obs": hi_o,
                          "weight": float(ww.sum() / w.sum())})
            i = j + 1
        return GridSolution(sorted(modes, key=lambda m: -m["weight"]),
                            degenerate=len(modes) > 1, n_nodes_used=int(sel.sum()),
                            ratio_range=rng_r,
                            note="degenerado" if len(modes) > 1 else "",
                            sigma_obs_dex=le, sigma_model_dex=grid_model_logerr,
                            sigma_total_dex=sig_tot)


# ====================================================================
# GESTIÓN DE GRILLAS Y CACHÉ
# ====================================================================
class GridManager:
    REQUIRED_ALIASES={"velocity":("v_kms","v","velocity","velocity_kms","vs_kms","vshock"),
                      "ratio":("ratio","oiii_ha","o3_ha","o3/ha")}
    def __init__(self, cache_dir=None):
        self.cache_dir=Path(cache_dir or (Path.home()/".astrophysics_suite"/"grids")); self.cache_dir.mkdir(parents=True,exist_ok=True)
        self.last_manifest={}
    def validate(self,grid:ShockGrid):
        if grid.v.size<3: raise ValueError("Grilla insuficiente: se requieren >=3 nodos")
        if np.any(~np.isfinite(grid.v)) or np.any(~np.isfinite(grid.r)) or np.any(grid.v<=0) or np.any(grid.r<=0):
            raise ValueError("Grilla con valores no válidos: velocidad/ratio deben ser finitos y >0")
        if grid.n0 is not None:
            if np.any(~np.isfinite(grid.n0)) or np.any(grid.n0<=0):
                raise ValueError("Grilla con n0 no válido: densidades deben ser finitas y >0")
        # Duplicate coordinates are ambiguous for inversion and usually indicate a malformed export.
        if grid.n0 is None:
            keys=list(zip(np.round(grid.v,10), np.round(grid.r,12)))
        else:
            keys=list(zip(np.round(grid.v,10), np.round(grid.r,12), np.round(grid.n0,10)))
        if len(set(keys)) != len(keys):
            raise ValueError("Grilla con nodos duplicados")
        monotonic_by_n0={}
        groups=[(None,np.ones(grid.v.size,bool))]
        if grid.n0 is not None:
            groups=[]
            for n in np.unique(grid.n0): groups.append((float(n), np.isclose(grid.n0,n,rtol=0,atol=1e-12)))
        for n,mask in groups:
            vv=grid.v[mask]
            if len(vv)>1 and np.any(np.diff(np.sort(vv))<=0):
                raise ValueError("Grilla con velocidades duplicadas dentro de una rama")
            if n is not None: monotonic_by_n0[str(n)]=int(mask.sum())
        self.last_manifest={"name":grid.name,"n_nodes":int(grid.v.size),"v_range_kms":[float(grid.v.min()),float(grid.v.max())],"ratio_range":[float(grid.r.min()),float(grid.r.max())],"extrapolation":"blocked","monotonicity_by_n0":monotonic_by_n0}
        return grid
    def load(self,path):
        p=Path(path)
        if not p.is_file(): raise FileNotFoundError(str(p))
        ext=p.suffix.lower()
        if ext in (".csv",".ecsv",".tsv"):
            if ext==".ecsv":
                try:
                    if HAS_ASTROPY:
                        tab=_ascii.read(str(p),format="ecsv")
                        rows=[{k:row[k] for k in tab.colnames} for row in tab]
                    else: raise RuntimeError("astropy ausente para ECSV")
                except Exception as exc: raise ValueError(f"ECSV inválido: {exc}")
                grid=self._from_rows(rows,p.name)
            else:
                grid=ShockGrid.from_csv(p)
        elif ext==".json":
            data=json.load(open(p,encoding="utf-8")); rows=data.get("rows",data) if isinstance(data,dict) else data; grid=self._from_rows(rows,p.name)
        else:
            raise ValueError("Formato de grilla no soportado: use CSV/ECSV/JSON")
        self.validate(grid); self.last_manifest.update({"source_file":str(p.resolve()),"sha256":sha256_file(p),"version":"file-1"}); return grid
    def _from_rows(self,rows,name):
        if not rows: raise ValueError("Grilla vacía")
        cols={str(k).strip().lower():k for k in rows[0].keys()}
        vk=next((cols[k] for k in self.REQUIRED_ALIASES["velocity"] if k in cols),None); rk=next((cols[k] for k in self.REQUIRED_ALIASES["ratio"] if k in cols),None)
        if vk is None or rk is None: raise ValueError(f"Faltan columnas obligatorias velocidad/ratio: {list(rows[0].keys())}")
        nk=cols.get("n0") or cols.get("density") or cols.get("n")
        v=[]; r=[]; n=[]
        for row in rows:
            try: vv=float(row[vk]); rr=float(row[rk])
            except (TypeError,ValueError): continue
            if math.isfinite(vv) and math.isfinite(rr) and rr>0: v.append(vv); r.append(rr); n.append(float(row[nk]) if nk and str(row[nk]).strip() not in ("","None") else np.nan)
        if len(v)<3: raise ValueError("Menos de 3 modelos válidos")
        return ShockGrid(np.asarray(v),np.asarray(r),np.asarray(n) if nk else None,name=name)
    def embedded(self):
        g=ShockGrid.builtin(); g.name="heuristic_demo_grid"; self.last_manifest={"name":g.name,"source":"embedded","approximate":True,"extrapolation":"blocked"}; return g

# ====================================================================
# ML
# ====================================================================
ML_FEATURES = ["ridge_response", "anisotropy", "scale_px", "snr_pix", "peak_snr_ha",
               "peak_snr_oiii", "peak_sigma_ha_px", "offset_err_px", "chi2_red_ha"]


class ViabilityModel:
    def __init__(self, seed=0, threshold=0.5, exploration_fraction=0.1):
        self.seed, self.threshold, self.exploration_fraction = seed, threshold, exploration_fraction
        self.model = None

    @staticmethod
    def load_labels(path):
        rows = list(csv.DictReader(open(path, newline="")))
        return [{"x": float(r["x"]), "y": float(r["y"]), "label": int(r["label"]),
                 "group": r.get("group", "0")} for r in rows]

    @staticmethod
    def attach_labels(cands, labels, radius_px=4.0):
        if not labels:
            return 0
        L = np.array([[l["x"], l["y"]] for l in labels])
        n = 0
        for c in cands:
            d = np.hypot(L[:, 0] - c["x"], L[:, 1] - c["y"])
            k = int(np.argmin(d))
            if d[k] <= radius_px:
                c["label"], c["group"] = labels[k]["label"], labels[k]["group"]
                n += 1
        return n

    def fit(self, cands):
        if not HAS_SKLEARN:
            return None
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import GroupKFold, StratifiedKFold
        from sklearn.metrics import roc_auc_score, brier_score_loss
        from sklearn.calibration import CalibratedClassifierCV
        lab = [c for c in cands if "label" in c]
        if len(lab) < 40 or sum(c["label"] for c in lab) < 10 or sum(1 - c["label"] for c in lab) < 10:
            return None
        X = np.array([[finite(c.get(f), 0.0) for f in ML_FEATURES] for c in lab])
        y = np.array([c["label"] for c in lab])
        g = np.array([str(c.get("group", "0")) for c in lab])
        n_groups = len(set(g))
        rf = RandomForestClassifier(n_estimators=300, min_samples_leaf=3,
                                    class_weight="balanced", random_state=self.seed, n_jobs=1)
        oof = np.full(len(y), np.nan)
        if n_groups >= 3:
            for tr, te in GroupKFold(n_splits=min(5, n_groups)).split(X, y, g):
                rf.fit(X[tr], y[tr])
                oof[te] = rf.predict_proba(X[te])[:, 1]
        else:
            for tr, te in StratifiedKFold(5, shuffle=True, random_state=self.seed).split(X, y):
                rf.fit(X[tr], y[tr])
                oof[te] = rf.predict_proba(X[te])[:, 1]
        rf.fit(X, y)
        try:
            from sklearn.frozen import FrozenEstimator
            cal = CalibratedClassifierCV(FrozenEstimator(rf), method="sigmoid")
        except Exception:
            cal = CalibratedClassifierCV(rf, cv=3, method="sigmoid")
        cal.fit(X, y)
        self.model = cal
        return {"n_train": len(y), "n_pos": int(y.sum()),
                "cv_auc": float(roc_auc_score(y, oof)) if len(set(y)) == 2 else float("nan"),
                "brier": float(brier_score_loss(y, oof)) if len(set(y)) == 2 else float("nan")}

    def score(self, cands, rng):
        if self.model is None:
            for c in cands:
                c["p_viable"], c["keep"], c["keep_reason"] = float("nan"), True, "no-ml"
            return
        X = np.array([[finite(c.get(f), 0.0) for f in ML_FEATURES] for c in cands])
        p = self.model.predict_proba(X)[:, 1]
        explore = rng.random(len(cands)) < self.exploration_fraction
        for c, pi, ex in zip(cands, p, explore):
            c["p_viable"] = float(pi)
            c["keep"] = bool(pi >= self.threshold or ex)
            c["keep_reason"] = "p>=thr" if pi >= self.threshold else ("exploration" if ex else "rejected")


def cluster_fronts(cands, seed=0, max_k=6):
    rows = [c for c in cands if math.isfinite(finite(c.get("log_ratio")))
            and math.isfinite(finite(c.get("offset_px")))]
    if not HAS_SKLEARN or len(rows) < 12:
        return {"k": 0, "note": "sklearn ausente o <12 candidatos"}
    from sklearn.mixture import GaussianMixture
    from sklearn.preprocessing import StandardScaler
    X = np.array([[c["log_ratio"], c.get("offset_px", 0.0),
                   math.log10(max(c.get("peak_snr_ha", 1.0), 1.0))] for c in rows])
    Xs = StandardScaler().fit_transform(X)
    best, best_bic = None, np.inf
    for k in range(1, min(max_k, len(rows) // 6) + 1):
        gm = GaussianMixture(k, covariance_type="full", random_state=seed, n_init=2).fit(Xs)
        b = gm.bic(Xs)
        if b < best_bic - 2.0:
            best, best_bic = gm, b
    lab = best.predict(Xs)
    for c, l in zip(rows, lab):
        c["cluster"] = int(l)
    return {"k": int(best.n_components), "bic": float(best_bic), "n": len(rows)}


# ====================================================================
# SECTION 31: ASTRODISCOVERY AI v33
# ====================================================================
# v33: IA persistente y verificable para descubrimiento científico.
# Importante: esto NO pretende declarar descubrimientos automáticamente.
# Combina:
#   (1) red neuronal MLP para clasificación de fenómenos conocidos,
#   (2) IsolationForest para novedad/outliers,
#   (3) validación agrupada por objeto para evitar fugas entre imágenes del mismo objeto,
#   (4) explicaciones heurísticas por desviación de variables.
AI_MODEL_FORMAT_VERSION = 38
AI_IMAGE_FEATURES = [
    "log_flux_ha", "log_flux_oiii", "log_ratio", "offset_arcsec", "ratio_err",
    "peak_snr_ha", "peak_snr_oiii", "peak_sigma_ha_px", "peak_sigma_oiii_px",
    "anisotropy", "ridge_response", "profile_completeness", "chi2_red_ha",
    "chi2_red_oiii", "lqef_line_structure", "lqef_continuum_index",
]
AI_CLASS_LABELS = {
    0: "desconocido/no etiquetado", 1: "SNR", 2: "nebulosa_emision",
    3: "nebulosa_reflexion", 4: "nebulosa_planetaria", 5: "galaxia",
    6: "cumulo", 7: "estrella_variable", 8: "otro",
}


def _ai_vector(row):
    """Vector de features de IA conservando NaN para imputación ajustada en entrenamiento."""
    vals=[]
    for f in AI_IMAGE_FEATURES:
        vals.append(finite(row.get(f), float("nan")))
    return np.asarray(vals, dtype=float)


def _ai_feature_rows_from_catalog(rows):
    out=[]
    for r in rows:
        if not isinstance(r, dict):
            continue
        rr=dict(r)
        aliases={"flux_ha":"log_flux_ha","flux_oiii":"log_flux_oiii",
                 "ratio":"log_ratio","offset":"offset_arcsec",
                 "snr_ha":"peak_snr_ha","snr_oiii":"peak_snr_oiii",
                 "line_structure":"lqef_line_structure",
                 "continuum_index":"lqef_continuum_index"}
        for a,b in aliases.items():
            if b not in rr and a in rr: rr[b]=rr[a]
        try: label=int(rr.get("label", rr.get("class_id", 0)))
        except Exception: label=0
        rr["label"]=label
        rr["group"]=str(rr.get("group", rr.get("object", rr.get("target_name", "0"))))
        try: rr["sample_weight"]=max(float(rr.get("sample_weight",1.0)),0.0)
        except Exception: rr["sample_weight"]=1.0
        out.append(rr)
    return out


class _PersistedMedianImputer:
    """Imputador mínimo y estable para modelos persistidos entre versiones de sklearn."""
    def __init__(self, statistics):
        self.statistics_=np.asarray(statistics,float).ravel()
        self.n_features_in_=int(self.statistics_.size)
    def transform(self,X):
        X=np.asarray(X,float)
        if X.ndim==1: X=X[None,:]
        if X.shape[1]!=self.n_features_in_: raise ValueError("Dimensión de features incompatible con el modelo persistido")
        out=np.array(X,copy=True,dtype=float)
        inds=~np.isfinite(out)
        if inds.any():
            out[inds]=np.take(self.statistics_,np.where(inds)[1])
        return out


class AstroDiscoveryAI:
    """Motor local de IA científica: clasificación neuronal + novedad + explicación.

    No es un modelo de píxeles tipo CNN. Trabaja con observables físicos extraídos por
    la suite. Esto hace que sea más auditable y exige que la física/mediciones previas
    sean razonables antes de confiar en el ranking.
    """
    def __init__(self, seed=0, contamination=0.02):
        self.seed=int(seed)
        self.contamination=float(np.clip(contamination,1e-4,0.25))
        self.classifier=None
        self.scaler=None
        self.imputer=None
        self.outlier_model=None
        self._novelty_train_X=np.empty((0,len(AI_IMAGE_FEATURES)),float)
        self.feature_center=None
        self.feature_scale=None
        self.training_meta={}
        self.model_format_version=AI_MODEL_FORMAT_VERSION

    def fit(self, rows, min_rows=80):
        if not HAS_SKLEARN:
            return {"state":"NO DISPONIBLE","reason":"scikit-learn no instalado"}
        rows=_ai_feature_rows_from_catalog(rows)
        if len(rows)<int(min_rows):
            return {"state":"NO DISPONIBLE","reason":f"se requieren ≥{int(min_rows)} registros reales; hay {len(rows)}"}
        from sklearn.preprocessing import StandardScaler
        from sklearn.impute import SimpleImputer
        from sklearn.neural_network import MLPClassifier
        from sklearn.ensemble import IsolationForest
        from sklearn.model_selection import GroupShuffleSplit
        from sklearn.metrics import balanced_accuracy_score, log_loss

        # Sólo pesos finitos y no negativos.
        weights=np.asarray([r.get("sample_weight",1.0) for r in rows],float)
        weights[~np.isfinite(weights)]=1.0; weights=np.clip(weights,0.0,None)
        X=np.vstack([_ai_vector(r) for r in rows])
        self.imputer=SimpleImputer(strategy="median", keep_empty_features=True)
        Ximp=self.imputer.fit_transform(X)
        self.scaler=StandardScaler().fit(Ximp)
        Xs=self.scaler.transform(Ximp)
        self.feature_center=np.asarray(self.scaler.mean_,float)
        self.feature_scale=np.where(np.asarray(self.scaler.scale_,float)>1e-12,np.asarray(self.scaler.scale_,float),1.0)

        labelled=[i for i,r in enumerate(rows) if int(r.get("label",0))>0]
        metrics={"n_rows_real":len(rows),"n_labelled":len(labelled),"classes":{}}

        # La detección de novedad usa SOLO ejemplos conocidos/etiquetados cuando hay suficientes.
        # Así evitamos que la propia población "desconocida" defina el baseline.
        novelty_idx=labelled if len(labelled)>=max(30,int(min_rows//2)) else list(range(len(rows)))
        self._novelty_train_X=np.asarray(Xs[novelty_idx],float)
        self.outlier_model=IsolationForest(n_estimators=500,contamination=self.contamination,
                                            random_state=self.seed,n_jobs=1,
                                            max_samples=min(256,len(novelty_idx)))
        self.outlier_model.fit(self._novelty_train_X)
        metrics["n_novelty_baseline"]=len(novelty_idx)
        metrics["novelty_baseline"]="labelled_known" if novelty_idx==labelled else "all_real_rows_fallback"

        # Clasificador neuronal sólo si hay al menos dos clases y suficiente soporte.
        if len(labelled)>=40:
            yl=np.asarray([int(rows[i]["label"]) for i in labelled],int)
            unique,counts=np.unique(yl,return_counts=True)
            if len(unique)>=2 and int(counts.min())>=3:
                Xl=Xs[labelled]
                groups=np.asarray([str(rows[i].get("group","0")) for i in labelled])
                splitter=GroupShuffleSplit(n_splits=1,test_size=0.25,random_state=self.seed)
                tr,te=next(splitter.split(Xl,yl,groups)) if len(set(groups))>=2 else (None,None)
                if tr is None or len(np.unique(yl[tr]))<2 or len(np.unique(yl[te]))<2:
                    # Fallback estratificado si no hay suficientes grupos por clase.
                    from sklearn.model_selection import train_test_split
                    tr,te=train_test_split(np.arange(len(yl)),test_size=0.25,random_state=self.seed,stratify=yl)
                clf=MLPClassifier(hidden_layer_sizes=(64,32),activation="relu",solver="adam",
                                  alpha=3e-4,batch_size=min(32,len(tr)),learning_rate_init=7e-4,
                                  max_iter=1000,early_stopping=True,validation_fraction=0.2,
                                  n_iter_no_change=35,random_state=self.seed)
                try:
                    clf.fit(Xl[tr],yl[tr],sample_weight=weights[labelled][tr])
                except TypeError:
                    clf.fit(Xl[tr],yl[tr])
                pred=clf.predict(Xl[te]); prob=clf.predict_proba(Xl[te])
                bacc=float(balanced_accuracy_score(yl[te],pred))
                try: ll=float(log_loss(yl[te],prob,labels=list(clf.classes_)))
                except Exception: ll=float("nan")
                metrics["classes"]={str(int(k)):int(v) for k,v in zip(unique,counts)}
                metrics["validation_balanced_accuracy"]=bacc
                metrics["validation_log_loss"]=ll
                metrics["epochs"]=int(getattr(clf,"n_iter_",0) or 0)
                # QA gate: a classifier that does not beat chance by a meaningful margin
                # is NOT activated. The novelty detector remains usable.
                if math.isfinite(bacc) and bacc >= max(0.55, 1.0/len(unique) + 0.10):
                    self.classifier=clf
                    metrics["classifier_accepted"]=True
                else:
                    self.classifier=None
                    metrics["classifier_accepted"]=False
                    metrics["classifier_rejection_reason"]="validación insuficiente; se desactiva clasificación para evitar falsos descubrimientos"
            else:
                self.classifier=None
                metrics["classifier_state"]="insuficiente soporte por clase"
        else:
            metrics["classifier_state"]="insuficientes etiquetas"

        self.training_meta={
            "model_format_version":AI_MODEL_FORMAT_VERSION,
            "features":list(AI_IMAGE_FEATURES),"seed":self.seed,**metrics,
            "training_policy":"datos reales; validación agrupada por objeto cuando es posible",
            "novelty_policy":"IsolationForest sobre baseline conocido; no es prueba de descubrimiento",
            "classifier":"MLPClassifier 64-32 ReLU" if self.classifier is not None else "none",
        }
        return {"state":"ENTRENADA CON DATOS DE ENTRENAMIENTO APORTADOS","metrics":metrics}

    def _explain(self, x):
        if self.feature_center is None or self.feature_scale is None:
            return []
        x=np.asarray(x,float)
        z=np.full(len(AI_IMAGE_FEATURES),np.nan,float)
        finite_mask=np.isfinite(x)
        z[finite_mask]=np.abs((x[finite_mask]-self.feature_center[finite_mask])/self.feature_scale[finite_mask])
        order=np.argsort(np.nan_to_num(z,nan=-np.inf))[::-1][:5]
        return [{"feature":AI_IMAGE_FEATURES[int(i)],"abs_z":float(z[int(i)])} for i in order if math.isfinite(z[int(i)])]

    def score(self, rows):
        if self.scaler is None or self.outlier_model is None:
            return [{"novelty_score":float("nan"),"novelty_state":"NO DISPONIBLE",
                     "ai_class_id":0,"ai_class":"desconocido/no etiquetado",
                     "ai_class_probability":float("nan"),"ai_explanation":[]} for _ in rows]
        X=np.vstack([_ai_vector(r) for r in rows]) if rows else np.empty((0,len(AI_IMAGE_FEATURES)))
        Ximp=self.imputer.transform(X) if self.imputer is not None else X
        Xs=self.scaler.transform(Ximp)
        dec=np.asarray(self.outlier_model.decision_function(Xs),float)
        pred=self.outlier_model.predict(Xs)
        novelty=1.0/(1.0+np.exp(np.clip(4.0*dec,-60,60)))
        out=[]
        for i in range(len(rows)):
            rec={"novelty_score":float(novelty[i]),
                 "novelty_state":"OUTLIER" if pred[i]<0 else "DISTRIBUCION_CONOCIDA",
                 "ai_class_id":0,"ai_class":"desconocido/no etiquetado",
                 "ai_class_probability":float("nan"),"ai_explanation":self._explain(X[i])}
            if self.classifier is not None:
                pr=self.classifier.predict_proba(Xs[i:i+1])[0]
                j=int(np.argmax(pr)); cls=int(self.classifier.classes_[j])
                rec.update({"ai_class_id":cls,"ai_class":AI_CLASS_LABELS.get(cls,str(cls)),
                            "ai_class_probability":float(pr[j]),
                            "ai_class_probabilities":{str(int(c)):float(v) for c,v in zip(self.classifier.classes_,pr)}})
            out.append(rec)
        return out

    def save(self,path):
        if self.imputer is None or self.scaler is None or self.outlier_model is None: raise ValueError("Modelo IA incompleto")
        target=Path(path); target.parent.mkdir(parents=True,exist_ok=True)
        if target.suffix.lower() not in {".apsai",".zip"}: target=target.with_suffix(".apsai")
        tmp=target.with_suffix(target.suffix+".tmp")
        meta={"model_format_version":AI_MODEL_FORMAT_VERSION,"seed":self.seed,"contamination":self.contamination,"training_meta":self.training_meta,"classifier_present":self.classifier is not None,"classifier_architecture":list(getattr(self.classifier,"hidden_layer_sizes",())) if self.classifier is not None else []}
        arrays={"imputer_statistics":np.asarray(self.imputer.statistics_,float),"scaler_mean":np.asarray(self.scaler.mean_,float),"scaler_scale":np.asarray(self.scaler.scale_,float),"novelty_train_X":np.asarray(getattr(self,"_novelty_train_X",np.empty((0,len(AI_IMAGE_FEATURES)))),float)}
        if self.classifier is not None:
            arrays["classes"]=np.asarray(self.classifier.classes_)
            for i,c in enumerate(self.classifier.coefs_): arrays[f"coef_{i}"]=np.asarray(c,float)
            for i,b in enumerate(self.classifier.intercepts_): arrays[f"intercept_{i}"]=np.asarray(b,float)
        with zipfile.ZipFile(tmp,"w",compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("metadata.json",json.dumps(json_sanitize(meta),ensure_ascii=False,indent=2))
            for k,v in arrays.items():
                b=io.BytesIO(); np.save(b,v,allow_pickle=False); z.writestr(f"arrays/{k}.npy",b.getvalue())
        os.replace(tmp,target); return str(target)

    @staticmethod
    def load(path):
        with zipfile.ZipFile(path,"r") as z:
            meta=json.loads(z.read("metadata.json").decode("utf-8"))
            if int(meta.get("model_format_version",0))!=AI_MODEL_FORMAT_VERSION: raise ValueError("Formato IA incompatible")
            def arr(n): return np.load(io.BytesIO(z.read(f"arrays/{n}.npy")),allow_pickle=False)
            obj=AstroDiscoveryAI(seed=int(meta.get("seed",0)),contamination=float(meta.get("contamination",0.02)))
            from sklearn.impute import SimpleImputer
            from sklearn.preprocessing import StandardScaler
            obj.imputer=_PersistedMedianImputer(arr("imputer_statistics"))
            obj.scaler=StandardScaler(); obj.scaler.mean_=arr("scaler_mean"); obj.scaler.scale_=arr("scaler_scale"); obj.scaler.var_=obj.scaler.scale_**2; obj.scaler.n_features_in_=len(obj.scaler.mean_); obj.scaler.n_samples_seen_=1
            obj.feature_center=obj.scaler.mean_; obj.feature_scale=np.where(obj.scaler.scale_>1e-12,obj.scaler.scale_,1.0); obj._novelty_train_X=arr("novelty_train_X")
            from sklearn.ensemble import IsolationForest
            if len(obj._novelty_train_X)<8: raise ValueError("Baseline de novedad insuficiente")
            obj.outlier_model=IsolationForest(n_estimators=500,contamination=obj.contamination,random_state=obj.seed,n_jobs=1,max_samples=min(256,len(obj._novelty_train_X))).fit(obj._novelty_train_X)
            if bool(meta.get("classifier_present")):
                from sklearn.neural_network import MLPClassifier
                clf=MLPClassifier(hidden_layer_sizes=tuple(int(x) for x in meta.get("classifier_architecture",[])),activation="relu",solver="adam",random_state=obj.seed)
                names=set(z.namelist()); coefs=[]; intercepts=[]; i=0
                while f"arrays/coef_{i}.npy" in names: coefs.append(arr(f"coef_{i}")); intercepts.append(arr(f"intercept_{i}")); i+=1
                classes=arr("classes"); clf.coefs_=coefs; clf.intercepts_=intercepts; clf.n_layers_=len(coefs)+1; clf.n_iter_=0; clf.t_=0; clf.n_features_in_=coefs[0].shape[0]; clf.n_outputs_=1 if len(classes)<=2 else len(classes); clf.classes_=classes; clf.out_activation_="logistic" if len(classes)==2 else "softmax"; obj.classifier=clf
            obj.training_meta=dict(meta.get("training_meta",{})); return obj


def _load_ai_training_rows(path, sheet_preference=("TRAINING","CANDIDATES","LIGHTS","Sheet1")):
    """Carga entrenamiento desde JSON/CSV/XLSX. Para XLSX busca una hoja de entrenamiento usable."""
    p=Path(path)
    if not p.is_file(): raise FileNotFoundError(str(p))
    ext=p.suffix.lower()
    if ext==".json":
        data=json.loads(p.read_text(encoding="utf-8")); return data.get("rows",[]) if isinstance(data,dict) else data
    if ext in (".csv",".txt"):
        with open(p,newline="",encoding="utf-8") as f: return list(csv.DictReader(f))
    if ext==".xlsx":
        if not HAS_OPENPYXL:
            raise RuntimeError("openpyxl no está disponible para leer entrenamiento Excel")
        from openpyxl import load_workbook
        wb=load_workbook(p,read_only=True,data_only=True)
        selected=None
        for name in sheet_preference:
            if name in wb.sheetnames:
                selected=wb[name]; break
        if selected is None: selected=wb[wb.sheetnames[0]]
        vals=selected.iter_rows(values_only=True)
        try: headers=[str(x).strip() if x is not None else "" for x in next(vals)]
        except StopIteration: return []
        rows=[]
        for row in vals:
            if not any(x is not None and str(x).strip()!="" for x in row): continue
            d={headers[i]: row[i] if i < len(row) else None for i in range(len(headers)) if headers[i]}
            rows.append(d)
        return rows
    raise ValueError(f"Formato de entrenamiento no soportado: {ext}")


def train_discovery_ai(training_path, model_path, seed=0, min_rows=80, contamination=0.02):
    p=Path(training_path)
    if not p.is_file(): raise FileNotFoundError(str(p))
    rows=_load_ai_training_rows(p)
    ai=AstroDiscoveryAI(seed=seed,contamination=contamination)
    report=ai.fit(rows,min_rows=min_rows)
    if report.get("state")=="ENTRENADA CON DATOS REALES":
        ai.save(model_path); report["model_path"]=str(model_path)
    return report


def discovery_ai_from_rows(rows, model_path="", training_path="", seed=0, min_rows=80, contamination=0.02):
    ai=None; source="none"
    if model_path and Path(model_path).is_file():
        try: ai=AstroDiscoveryAI.load(model_path); source="persisted_model"
        except Exception as exc: LOG.warning("No se pudo cargar modelo IA: %s",exc)
    if ai is None and training_path and Path(training_path).is_file():
        try:
            ai=AstroDiscoveryAI(seed=seed,contamination=contamination)
            p=Path(training_path)
            tr=_load_ai_training_rows(p)
            rep=ai.fit(tr,min_rows=min_rows)
            if rep.get("state")=="ENTRENADA CON DATOS REALES":
                source="trained_this_run"
                if model_path: ai.save(model_path)
            else: return {"state":"NO DISPONIBLE","reason":rep.get("reason","entrenamiento no disponible"),"candidates":rows}
        except Exception as exc:
            LOG.warning("Entrenamiento IA omitido: %s",exc)
    if ai is None:
        return {"state":"NO DISPONIBLE","reason":"sin modelo/entrenamiento real","candidates":rows}
    scores=ai.score(rows)
    enriched=[{**r,**s} for r,s in zip(rows,scores)]
    ranked=sorted(enriched,key=lambda r:(-finite(r.get("novelty_score"),-1.0),-finite(r.get("ai_class_probability"),-1.0)))
    return {"state":"ACTIVA","source":source,"model_format_version":AI_MODEL_FORMAT_VERSION,
            "training":dict(ai.training_meta),"candidates":ranked,
            "n_outliers":int(sum(r.get("novelty_state")=="OUTLIER" for r in ranked)),
            "n_candidates":len(ranked)}


def discovery_visual_ai(candidates, ha_img, o3_img, broadband_img=None, model_path="", training_dir="", seed=0, epochs=12, batch_size=8):
    if not HAS_TORCH:
        return {"state":"NO DISPONIBLE","reason":"PyTorch no instalado"}
    ai=None; source="none"
    try:
        if model_path and Path(model_path).is_file():
            ai=AstroVisionAI.load(model_path); source="persisted_visual_model"
        elif training_dir and Path(training_dir).is_dir():
            ai=AstroVisionAI(seed=seed)
            rep=ai.fit_from_directory(training_dir,epochs=epochs,batch_size=batch_size)
            if not rep.get('state','').startswith('ENTRENADA'):
                return rep
            source="trained_this_run"
            if model_path: ai.save(model_path)
        else:
            return {"state":"NO DISPONIBLE","reason":"sin modelo visual persistente ni directorio de entrenamiento"}
        pair=[]
        H=np.asarray(ha_img.data if hasattr(ha_img,'data') else ha_img)
        O=np.asarray(o3_img.data if hasattr(o3_img,'data') else o3_img)
        B=np.asarray(broadband_img.data if hasattr(broadband_img,'data') else broadband_img) if broadband_img is not None else None
        scored=ai.score_candidate_patches(H,O,B,candidates)
        byid={id(c):sc for c,sc in scored}
        for c in candidates:
            sc=byid.get(id(c))
            if sc: c.update(sc)
        return {"state":"ACTIVA","source":source,"training":dict(ai.training_meta),
                "n_visual_candidates":len(scored),"n_visual_outliers":sum(s.get('visual_novelty_state')=='OUTLIER_VISUAL' for _,s in scored),
                "human_validation_required":True}
    except Exception as exc:
        return {"state":"NO DISPONIBLE","reason":f"{type(exc).__name__}: {exc}"}


class DiscoverySession:
    """Sesión persistente dentro del proceso: carga/entrena una IA y permite analizar muchos catálogos.

    La sesión NO lanza procesos ocultos ni termina el programa. El GUI/servicio decide cuándo cerrar.
    """
    def __init__(self, model_path="", training_path="", seed=0, min_rows=80, contamination=0.02):
        self.model_path=str(model_path or "")
        self.training_path=str(training_path or "")
        self.seed=int(seed); self.min_rows=int(min_rows); self.contamination=float(contamination)
        self.ai=None; self.state="INICIALIZANDO"; self.last_error=""
        self.load_or_train()

    def load_or_train(self):
        try:
            if self.model_path and Path(self.model_path).is_file():
                self.ai=AstroDiscoveryAI.load(self.model_path); self.state="ACTIVA"; return self.state
            if self.training_path and Path(self.training_path).is_file():
                p=Path(self.training_path)
                rows=_load_ai_training_rows(p)
                ai=AstroDiscoveryAI(seed=self.seed,contamination=self.contamination)
                rep=ai.fit(rows,min_rows=self.min_rows)
                if rep.get("state")=="ENTRENADA CON DATOS REALES":
                    self.ai=ai; self.state="ACTIVA"
                    if self.model_path: ai.save(self.model_path)
                    return self.state
                self.state="NO DISPONIBLE"; self.last_error=rep.get("reason",""); return self.state
            self.state="NO DISPONIBLE"; self.last_error="No hay modelo persistente ni datos de entrenamiento reales"; return self.state
        except Exception as exc:
            self.state="ERROR"; self.last_error=f"{type(exc).__name__}: {exc}"; return self.state

    def analyze(self, rows):
        if self.ai is None: raise RuntimeError(self.last_error or "IA no disponible")
        return self.ai.score(rows)


# ====================================================================
# SECTION 31B: ASTROVISION AI v34 — visión real de las imágenes
# ====================================================================
# Esta capa SÍ mira los píxeles. No declara descubrimientos por sí sola.
# Aprende una representación visual mediante un autoencoder convolucional
# entrenado con imágenes FITS astronómicas reales proporcionadas por el usuario.
# El espacio latente se usa para detectar novedad visual y para complementar
# los observables físicos de AstroDiscoveryAI.
VISION_MODEL_FORMAT_VERSION = 38
VISION_IMAGE_SIZE = 128
VISION_LATENT_DIM = 128


class _AstroConvAutoencoder(nn.Module if HAS_TORCH else object):
    if HAS_TORCH:
        def __init__(self, latent_dim=VISION_LATENT_DIM):
            super().__init__()
            self.encoder_net = nn.Sequential(
                nn.Conv2d(3, 32, 5, stride=2, padding=2), nn.ReLU(inplace=True),
                nn.Conv2d(32, 64, 5, stride=2, padding=2), nn.ReLU(inplace=True),
                nn.Conv2d(64, 96, 3, stride=2, padding=1), nn.ReLU(inplace=True),
                nn.Conv2d(96, 128, 3, stride=2, padding=1), nn.ReLU(inplace=True),
                nn.AdaptiveAvgPool2d((1,1)), nn.Flatten())
            self.fc = nn.Linear(128, latent_dim)
            self.decoder_fc = nn.Linear(latent_dim, 128*8*8)
            self.decoder = nn.Sequential(
                nn.ConvTranspose2d(128, 96, 4, 2, 1), nn.ReLU(inplace=True),
                nn.ConvTranspose2d(96, 64, 4, 2, 1), nn.ReLU(inplace=True),
                nn.ConvTranspose2d(64, 32, 4, 2, 1), nn.ReLU(inplace=True),
                nn.ConvTranspose2d(32, 3, 4, 2, 1), nn.Sigmoid())
        def encode(self,x):
            return self.fc(self.encoder_net(x))
        def forward(self,x):
            z=self.encode(x)
            y=self.decoder_fc(z).view(-1,128,8,8)
            return self.decoder(y), z


def _robust_image_scale(arr):
    a=np.asarray(arr,np.float32)
    finite_mask=np.isfinite(a)
    if not finite_mask.any(): return np.zeros_like(a,np.float32)
    vals=a[finite_mask]
    lo,hi=np.percentile(vals,[1.0,99.5])
    if not math.isfinite(float(lo)) or not math.isfinite(float(hi)) or hi<=lo:
        lo=float(np.median(vals)); hi=float(np.max(vals))
    if hi<=lo: hi=lo+1.0
    x=np.nan_to_num(a,nan=lo,posinf=hi,neginf=lo)
    x=np.clip((x-lo)/(hi-lo),0,1)
    # asinh keeps faint structure while preserving bright cores
    x=np.arcsinh(8.0*x)/np.arcsinh(8.0)
    return np.asarray(x,np.float32)


def _vision_channels_from_arrays(ha, o3, lqef=None):
    chans=[_robust_image_scale(o3),_robust_image_scale(ha),
           _robust_image_scale(lqef) if lqef is not None else np.zeros_like(np.asarray(ha,np.float32))]
    return np.stack(chans,axis=0).astype(np.float32)


def _vision_resize(chw, size=VISION_IMAGE_SIZE):
    if not HAS_TORCH: raise RuntimeError('PyTorch no instalado')
    x=torch.from_numpy(np.asarray(chw,np.float32))[None,...]
    return F.interpolate(x,size=(size,size),mode='bilinear',align_corners=False)[0].numpy().astype(np.float32)


def _iter_fits_paths(root):
    p=Path(root)
    if p.is_file(): return [p]
    if not p.is_dir(): return []
    exts={'.fits','.fit','.fts','.fz'}
    return sorted([x for x in p.rglob('*') if x.is_file() and x.suffix.lower() in exts])


class AstroVisionAI:
    """Red convolucional para ver imágenes y construir un espacio visual astronómico.

    Entrenamiento no supervisado: aprende a reconstruir imágenes astronómicas reales.
    La utilidad científica proviene de usar su embedding latente para detectar casos
    visualmente extraños respecto a un archivo de entrenamiento real.
    """
    def __init__(self, seed=0, latent_dim=VISION_LATENT_DIM, device=None):
        if not HAS_TORCH:
            raise RuntimeError('PyTorch no está instalado; se requiere para AstroVisionAI')
        self.seed=int(seed); self.latent_dim=int(latent_dim)
        self.device=str(device or ('cuda' if torch.cuda.is_available() else 'cpu'))
        torch.manual_seed(self.seed)
        self.net=_AstroConvAutoencoder(self.latent_dim).to(self.device)
        self.training_meta={"model_format_version":VISION_MODEL_FORMAT_VERSION}
        self.baseline_center=None; self.baseline_scale=None
        self.outlier_model=None
        self._vision_train_Z=np.empty((0,self.latent_dim),np.float32)

    @staticmethod
    def _load_single_image(path):
        """Carga una muestra visual conservando hasta tres bandas reales del FITS.

        Para un FITS 2D repite el mismo canal sólo como compatibilidad. Para cubos 3D/4D,
        cuando Astropy está disponible, usa los tres primeros planos 2D como canales independientes.
        """
        if HAS_ASTROPY:
            with _fits.open(path, memmap=True) as hdul:
                planes=[]
                for hdu in hdul:
                    data=getattr(hdu,"data",None)
                    if data is None: continue
                    a=np.asarray(data)
                    if a.ndim==2:
                        planes.append(np.asarray(a))
                    elif a.ndim==3:
                        planes.extend([np.asarray(a[i]) for i in range(min(a.shape[0],3))])
                    elif a.ndim==4:
                        planes.extend([np.asarray(a[i,0]) for i in range(min(a.shape[0],3))])
                    if len(planes)>=3: break
                if not planes: raise ValueError("FITS sin planos 2D utilizables")
        else:
            im=load_fits(path)
            a=np.asarray(im.data)
            if a.ndim==2: planes=[a]
            else: raise AmbiguousCubeError("Sin Astropy no se seleccionan planos de cubo; use FITS 2D o instale Astropy.")
        chans=[_robust_image_scale(x) for x in planes[:3]]
        while len(chans)<3: chans.append(chans[-1].copy())
        return np.stack(chans,axis=0).astype(np.float32)

    def _training_tensors(self, paths, max_images=256):
        xs=[]
        for path in paths[:int(max_images)]:
            try:
                chw=self._load_single_image(path)
                xs.append(_vision_resize(chw))
            except Exception as exc:
                LOG.warning('AstroVision: omite %s: %s',path,exc)
        if not xs: raise ValueError('No se pudo leer ninguna imagen FITS de entrenamiento')
        return np.stack(xs).astype(np.float32)

    def fit_from_directory(self, directory, epochs=12, batch_size=8, max_images=256, lr=1e-3):
        paths=_iter_fits_paths(directory)
        if len(paths)<8:
            return {"state":"NO DISPONIBLE","reason":f"se requieren al menos 8 FITS reales; hay {len(paths)}"}
        X=self._training_tensors(paths,max_images=max_images)
        ds=TensorDataset(torch.from_numpy(X),torch.from_numpy(X))
        dl=DataLoader(ds,batch_size=max(1,min(int(batch_size),len(ds))),shuffle=True)
        opt=torch.optim.AdamW(self.net.parameters(),lr=float(lr),weight_decay=1e-4)
        self.net.train(); losses=[]
        for ep in range(max(1,int(epochs))):
            ep_loss=0.0
            for xb,_ in dl:
                xb=xb.to(self.device)
                pred,_=self.net(xb)
                loss=F.smooth_l1_loss(pred,xb)
                opt.zero_grad(set_to_none=True); loss.backward(); opt.step()
                ep_loss+=float(loss.detach().cpu())*len(xb)
            losses.append(ep_loss/len(ds))
        Z=self.embed_arrays(X)
        self._fit_outlier(Z)
        self.training_meta={"model_format_version":VISION_MODEL_FORMAT_VERSION,
                            "n_images":int(len(X)),"epochs":int(epochs),"batch_size":int(batch_size),
                            "final_reconstruction_loss":float(losses[-1]),"device":self.device,
                            "training_source":"FITS astronómicos proporcionados por el usuario; la validez científica depende de que el conjunto sea real y representativo",
                            "task":"self-supervised visual representation + novelty"}
        return {"state":"ENTRENADA CON IMÁGENES REALES","metrics":dict(self.training_meta),"loss_history":losses}

    def embed_arrays(self, X):
        self.net.eval(); zs=[]
        with torch.no_grad():
            for i in range(0,len(X),32):
                xb=torch.from_numpy(np.asarray(X[i:i+32],np.float32)).to(self.device)
                _,z=self.net(xb); zs.append(z.detach().cpu().numpy())
        return np.vstack(zs) if zs else np.empty((0,self.latent_dim),np.float32)

    def _fit_outlier(self,Z):
        from sklearn.ensemble import IsolationForest
        self.baseline_center=np.median(Z,axis=0)
        mad=np.median(np.abs(Z-self.baseline_center),axis=0)
        self.baseline_scale=np.where(mad>1e-6,1.4826*mad,1.0)
        self._vision_train_Z=np.asarray(Z,np.float32)
        self.outlier_model=IsolationForest(n_estimators=400,contamination=0.02,random_state=self.seed,n_jobs=1,max_samples=min(256,len(Z))).fit((Z-self.baseline_center)/self.baseline_scale)

    def score_arrays(self, X):
        if self.outlier_model is None:
            return []
        Z=self.embed_arrays(X); Zn=(Z-self.baseline_center)/self.baseline_scale
        dec=self.outlier_model.decision_function(Zn); pred=self.outlier_model.predict(Zn)
        nov=1.0/(1.0+np.exp(np.clip(4.0*dec,-60,60)))
        return [{"visual_novelty_score":float(nov[i]),
                 "visual_novelty_state":"OUTLIER_VISUAL" if pred[i]<0 else "VISUAL_DISTRIBUCION_CONOCIDA",
                 "visual_embedding_norm":float(np.linalg.norm(Zn[i]))} for i in range(len(Z))]

    def score_fits(self,path):
        if Path(path).suffix.lower()==".xisf":
            arr,_meta=_xisf_read_uncompressed(path)
            chw=np.asarray(arr,np.float32)
            while chw.shape[0]<3: chw=np.concatenate([chw,chw[-1:]],axis=0)
            chw=chw[:3]
            chw=np.stack([_robust_image_scale(c) for c in chw],axis=0).astype(np.float32)
            X=_vision_resize(chw)[None,...]
            return self.score_arrays(X)[0]
        chw=self._load_single_image(path); X=_vision_resize(chw)[None,...]
        return self.score_arrays(X)[0]

    def score_candidate_patches(self, ha_array, o3_array, lqef_array, candidates, half_size=64):
        if self.outlier_model is None: return []
        H=np.asarray(ha_array); O=np.asarray(o3_array); B=np.asarray(lqef_array) if lqef_array is not None else None
        patches=[]; refs=[]
        h,w=H.shape[-2],H.shape[-1]
        for c in candidates or []:
            x=finite(c.get('x'),np.nan); y=finite(c.get('y'),np.nan)
            if not (math.isfinite(x) and math.isfinite(y)): continue
            xi,yi=int(round(x)),int(round(y)); x0=max(0,xi-half_size); x1=min(w,xi+half_size); y0=max(0,yi-half_size); y1=min(h,yi+half_size)
            if x1-x0<16 or y1-y0<16: continue
            ch=_vision_channels_from_arrays(H[y0:y1,x0:x1],O[y0:y1,x0:x1],B[y0:y1,x0:x1] if B is not None else None)
            patches.append(_vision_resize(ch)); refs.append(c)
        scored=self.score_arrays(np.stack(patches).astype(np.float32)) if patches else []
        return [(refs[i],scored[i]) for i in range(len(scored))]

    def save(self,path):
        if self.outlier_model is None: raise ValueError("AstroVision sin baseline entrenado")
        target=Path(path); target.parent.mkdir(parents=True,exist_ok=True)
        if target.suffix.lower() not in {".apsvision",".zip"}: target=target.with_suffix(".apsvision")
        tmp=target.with_suffix(target.suffix+".tmp"); b=io.BytesIO(); torch.save(self.net.state_dict(),b)
        with zipfile.ZipFile(tmp,"w",compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("metadata.json",json.dumps(json_sanitize({"model_format_version":VISION_MODEL_FORMAT_VERSION,"seed":self.seed,"latent_dim":self.latent_dim,"training_meta":self.training_meta}),ensure_ascii=False,indent=2)); z.writestr("state_dict.pt",b.getvalue())
            for n,v in (("baseline_center",self.baseline_center),("baseline_scale",self.baseline_scale),("train_Z",getattr(self,"_vision_train_Z",np.empty((0,self.latent_dim),np.float32)))):
                q=io.BytesIO(); np.save(q,np.asarray(v),allow_pickle=False); z.writestr(f"arrays/{n}.npy",q.getvalue())
        os.replace(tmp,target); return str(target)

    @staticmethod
    def load(path):
        if not HAS_TORCH: raise RuntimeError("PyTorch no instalado")
        with zipfile.ZipFile(path,"r") as z:
            meta=json.loads(z.read("metadata.json").decode("utf-8"))
            if int(meta.get("model_format_version",0))!=VISION_MODEL_FORMAT_VERSION: raise ValueError("Formato AstroVision incompatible")
            obj=AstroVisionAI(seed=int(meta.get("seed",0)),latent_dim=int(meta.get("latent_dim",VISION_LATENT_DIM)),device="cpu")
            state=torch.load(io.BytesIO(z.read("state_dict.pt")),map_location="cpu",weights_only=True); obj.net.load_state_dict(state); obj.net.eval(); obj.training_meta=dict(meta.get("training_meta",{}))
            obj.baseline_center=np.load(io.BytesIO(z.read("arrays/baseline_center.npy")),allow_pickle=False); obj.baseline_scale=np.load(io.BytesIO(z.read("arrays/baseline_scale.npy")),allow_pickle=False); obj._vision_train_Z=np.load(io.BytesIO(z.read("arrays/train_Z.npy")),allow_pickle=False)
            from sklearn.ensemble import IsolationForest
            if len(obj._vision_train_Z)<8: raise ValueError("Baseline visual insuficiente")
            sc=np.where(obj.baseline_scale>1e-6,obj.baseline_scale,1.0); obj.outlier_model=IsolationForest(n_estimators=400,contamination=0.02,random_state=obj.seed,n_jobs=1,max_samples=min(256,len(obj._vision_train_Z))).fit((obj._vision_train_Z-obj.baseline_center)/sc)
            return obj


def train_vision_ai(training_dir, model_path, seed=0, epochs=12, batch_size=8, max_images=256):
    ai=AstroVisionAI(seed=seed)
    rep=ai.fit_from_directory(training_dir,epochs=epochs,batch_size=batch_size,max_images=max_images)
    if rep.get('state','').startswith('ENTRENADA'):
        ai.save(model_path); rep['model_path']=str(model_path)
    return rep



# ====================================================================
# v35: BANCO REAL PÚBLICO + MOTOR FÍSICO MULTIOBJETO
# ====================================================================
REAL_VISION_SEED_OBJECTS = [
    # Galaxias cercanas/brillantes. Se emplean para preentrenamiento visual
    # auto-supervisado: no se asigna una clase física artificial.
    ("M31", 10.6847, 41.2687), ("M33", 23.4621, 30.6602),
    ("M51", 202.4696, 47.1952), ("M81", 148.8882, 69.0653),
    ("M82", 148.9685, 69.6797), ("M101", 210.8023, 54.3489),
    ("M63", 198.9554, 42.0293), ("M64", 194.1822, 21.6833),
    ("M94", 192.7219, 41.1201), ("M106", 184.7400, 47.3081),
    ("M95", 160.9900, 11.7036), ("M96", 161.6900, 11.8199),
    ("M65", 169.7334, 13.0920), ("M66", 170.0626, 12.9910),
    ("M87", 187.7059, 12.3911), ("NGC253", 11.8881, -25.2881),
    ("NGC1365", 53.4017, -36.1408), ("NGC2403", 114.2141, 65.6026),
    ("NGC2903", 143.0425, 21.5008), ("NGC3628", 170.0706, 13.5897),
    ("NGC4258", 184.7400, 47.3081), ("NGC4565", 189.0866, 25.9875),
    ("NGC4631", 190.5333, 32.5414), ("NGC4725", 192.6015, 25.5004),
    ("NGC4826", 194.1822, 21.6833), ("NGC5055", 199.0000, 42.0290),
    ("NGC5194", 202.4696, 47.1952), ("NGC5195", 202.4960, 47.2660),
    ("NGC5457", 210.8023, 54.3489), ("NGC6946", 308.7186, 60.1539),
    ("NGC7331", 339.2670, 34.4150), ("NGC1068", 40.6699, -0.0133),
]


def _safe_urlretrieve(url, destination, timeout=30):
    req=urllib.request.Request(url, headers={"User-Agent":"AstroPhysicsSuite/35.0 scientific training client"})
    with urllib.request.urlopen(req, timeout=int(timeout)) as r, open(destination,'wb') as f:
        shutil.copyfileobj(r,f)
    return destination


def build_real_vision_manifest(out_json, *, layer="ls-dr10", pixscale=0.55, size=256,
                               bands="griz", max_objects=None):
    """Crea un manifiesto reproducible de cutouts FITS de cielo real del Legacy Survey DR10.

    Esto no es un dataset etiquetado de todos los tipos: es un corpus real de preentrenamiento
    visual. La red aprende morfología sin imponer etiquetas falsas. Las etiquetas científicas
    posteriores proceden de catálogos/objetos de referencia o del usuario.
    """
    items=REAL_VISION_SEED_OBJECTS[: int(max_objects) if max_objects else None]
    rec=[]
    for name,ra,dec in items:
        q=urllib.parse.urlencode({"ra":ra,"dec":dec,"layer":layer,"pixscale":float(pixscale),"bands":bands,"size":int(size)})
        url=f"https://www.legacysurvey.org/viewer/fits-cutout?{q}"
        rec.append({"object":name,"ra_deg":ra,"dec_deg":dec,"url":url,"survey":layer,
                    "bands":bands,"pixscale_arcsec":float(pixscale),"size":int(size)})
    payload={"schema":"APS_REAL_VISION_CORPUS_V1","created_utc":datetime.now(timezone.utc).isoformat(),
             "source":"DESI Legacy Surveys DR10 public FITS cutouts","items":rec}
    Path(out_json).parent.mkdir(parents=True,exist_ok=True)
    Path(out_json).write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8')
    return payload


def download_real_vision_corpus(manifest_or_dir, out_dir, overwrite=False, timeout=60):
    """Descarga el corpus real desde el servicio público del Legacy Survey."""
    if isinstance(manifest_or_dir,(str,Path)) and Path(manifest_or_dir).is_file():
        manifest=json.loads(Path(manifest_or_dir).read_text(encoding='utf-8'))
    else:
        manifest=build_real_vision_manifest(manifest_or_dir)
    root=Path(out_dir); root.mkdir(parents=True,exist_ok=True)
    done=[]; failed=[]
    for item in manifest.get('items',[]):
        name=re.sub(r'[^A-Za-z0-9_.-]+','_',str(item['object']))+'.fits'
        dst=root/name
        try:
            if dst.exists() and not overwrite:
                done.append(str(dst)); continue
            _safe_urlretrieve(item['url'],dst,timeout=timeout)
            # Validación rápida de que realmente es FITS y no HTML/error.
            if dst.stat().st_size < 1024 or dst.read_bytes()[:6] != b'SIMPLE':
                raise ValueError('la respuesta descargada no parece un FITS válido')
            done.append(str(dst))
        except Exception as exc:
            failed.append({'object':item.get('object'),'url':item.get('url'),'error':f'{type(exc).__name__}: {exc}'})
            try:
                dst.unlink(missing_ok=True)
            except (OSError, FileNotFoundError) as exc:
                LOG.debug("No se pudo eliminar descarga parcial %s: %s", dst, exc)
    return {'state':'OK' if done else 'NO DISPONIBLE','n_downloaded':len(done),
            'n_failed':len(failed),'files':done,'failed':failed,
            'scientific_status':'CORPUS REAL PÚBLICO; PREENTRENAMIENTO VISUAL NO ETIQUETADO'}


def train_real_visual_seed(training_dir, model_path, *, epochs=18, batch_size=8, max_images=512, seed=20260915):
    """Descarga/entrena sobre imágenes FITS reales ya obtenidas; no crea datos sintéticos."""
    if not Path(training_dir).is_dir():
        return {'state':'NO DISPONIBLE','reason':'directorio de entrenamiento inexistente'}
    ai=AstroVisionAI(seed=seed)
    rep=ai.fit_from_directory(training_dir,epochs=epochs,batch_size=batch_size,max_images=max_images)
    if rep.get('state','').startswith('ENTRENADA'):
        rep['metrics']['training_source']='Legacy Survey DR10: FITS reales públicos, preentrenamiento visual auto-supervisado'
        ai.training_meta=rep['metrics']; ai.save(model_path); rep['model_path']=str(model_path)
    return rep


class MultiObjectPhysicsEngine:
    """Capa física agnóstica al tipo de objeto.

    No asigna una naturaleza física por decreto. Calcula observables y separa medida,
    corrección e inferencia. Los módulos especializados pueden añadir modelos válidos
    (choques, fotoionización, galaxias, PNe, variables, etc.) cuando existan los datos.
    """
    def __init__(self, distance_pc=None, distance_err_pc=None, ebv=0.0, pixel_scale_arcsec=None):
        self.distance_pc=finite(distance_pc,float('nan'))
        self.distance_err_pc=finite(distance_err_pc,float('nan'))
        self.ebv=max(0.0,finite(ebv,0.0))
        self.pixel_scale_arcsec=finite(pixel_scale_arcsec,float('nan'))

    @staticmethod
    def _log_ratio(a,b,ea=float('nan'),eb=float('nan')):
        a=finite(a,float('nan')); b=finite(b,float('nan'))
        if not (math.isfinite(a) and math.isfinite(b) and a>0 and b>0): return None
        val=math.log10(a/b)
        ea=abs(finite(ea,0.0)); eb=abs(finite(eb,0.0))
        err=(1/math.log(10))*math.sqrt((ea/a)**2+(eb/b)**2) if (ea or eb) else float('nan')
        return {'value':float(val),'err':float(err),'linear':float(a/b)}

    def diagnose_row(self,row):
        r=dict(row)
        fha=finite(r.get('flux_ha_adu',r.get('flux_ha')),float('nan'))
        fo3=finite(r.get('flux_oiii_adu',r.get('flux_oiii')),float('nan'))
        eha=finite(r.get('flux_ha_err_adu',r.get('flux_ha_err')),float('nan'))
        eo3=finite(r.get('flux_oiii_err_adu',r.get('flux_oiii_err')),float('nan'))
        lr=self._log_ratio(fo3,fha,eo3,eha)
        if lr:
            r['phys_log10_oiii_over_ha']=lr['value']; r['phys_log10_oiii_over_ha_err']=lr['err']
        else:
            r['phys_log10_oiii_over_ha']=r['phys_log10_oiii_over_ha_err']=float('nan')
        pix_area=finite(r.get('aperture_area_pix',r.get('area_pix')),float('nan'))
        if math.isfinite(self.pixel_scale_arcsec) and self.pixel_scale_arcsec>0 and math.isfinite(fha) and math.isfinite(pix_area) and pix_area>0:
            area_arcsec2=pix_area*self.pixel_scale_arcsec**2
            r['ha_surface_brightness_adu_arcsec2']=float(fha/area_arcsec2)
        if math.isfinite(self.distance_pc) and self.distance_pc>0:
            off_arc=finite(r.get('offset_arcsec'),float('nan'))
            if math.isfinite(off_arc):
                r['physical_offset_pc']=float(off_arc/3600*np.pi/180*self.distance_pc)
                if math.isfinite(self.distance_err_pc) and self.distance_err_pc>0:
                    r['physical_offset_err_pc']=float(abs(r['physical_offset_pc'])*math.sqrt((finite(r.get('offset_err_arcsec'),0.0)/max(abs(off_arc),1e-12))**2+(self.distance_err_pc/self.distance_pc)**2))
        r['physics_data_quality']=self._quality(r)
        return r

    @staticmethod
    def _quality(r):
        checks=0; good=0
        for key in ('ratio','ratio_err','offset_arcsec','peak_snr_ha','peak_snr_oiii','lqef_line_structure'):
            if key in r:
                checks+=1
                try:
                    if math.isfinite(float(r[key])): good+=1
                except (TypeError, ValueError):
                    LOG.debug("Observable no numérico: %s=%r", key, r.get(key))
        if checks==0: return {'score':0.0,'state':'SIN_OBSERVABLES'}
        score=good/checks
        return {'score':float(score),'state':'ALTA' if score>=0.8 else ('MEDIA' if score>=0.5 else 'BAJA')}

    def summarize(self, rows):
        vals=[self.diagnose_row(r) for r in rows]
        def med(key):
            a=np.asarray([finite(x.get(key),np.nan) for x in vals],float); return float(np.nanmedian(a)) if np.isfinite(a).any() else float('nan')
        return {'n_rows':len(vals),'median_log10_oiii_over_ha':med('phys_log10_oiii_over_ha'),
                'median_surface_brightness_ha':med('ha_surface_brightness_adu_arcsec2'),
                'median_physical_offset_pc':med('physical_offset_pc'),'rows':vals,
                'principle':'observables first; model-dependent quantities must identify their model'}

# ====================================================================
# v36: MOTOR DE ANOMALÍAS FÍSICAS MULTIPARÁMETRO
# ====================================================================
SCIENCE_PARAMETER_DEFINITIONS = {
    "ratio": ("line_ratio", "dimensionless"),
    "log_ratio": ("line_ratio_log10", "dex"),
    "offset_arcsec": ("spatial_offset", "arcsec"),
    "peak_snr_ha": ("detection_snr_ha", "1"),
    "peak_snr_oiii": ("detection_snr_oiii", "1"),
    "chi2_red_ha": ("fit_goodness_ha", "1"),
    "chi2_red_oiii": ("fit_goodness_oiii", "1"),
    "ridge_response": ("ridge_response", "relative"),
    "anisotropy": ("anisotropy", "relative"),
    "lqef_line_structure": ("broadband_line_structure_proxy", "relative"),
    "lqef_continuum_index": ("broadband_continuum_proxy", "relative"),
}

def _robust_location_scale(values):
    a=np.asarray([finite(v,np.nan) for v in values],float)
    a=a[np.isfinite(a)]
    if len(a)==0: return float("nan"),float("nan")
    med=float(np.median(a)); mad=float(np.median(np.abs(a-med)))*1.4826
    if not math.isfinite(mad) or mad<=1e-12:
        mad=float(np.std(a,ddof=1)) if len(a)>1 else 0.0
    return med, max(mad,1e-12) if len(a) else (float("nan"),float("nan"))

def physical_anomaly_engine(rows, *, target_name="", literature=None, visual_scores=None, snr_gate=4.0, z_threshold=5.0, min_points_trend=8):
    """Detecta tensiones multiparámetro tras separar tendencia espacial y fallos de medida.

    Si hay suficientes coordenadas x/y, cada parámetro se contrasta contra una tendencia
    plana del campo antes del z-score. Esto evita convertir un gradiente astrofísico coherente
    en cientos de "anomalías". Los umbrales son parámetros explícitos y quedan registrados.
    """
    rows=[dict(r) for r in (rows or [])]
    if not rows: return {"state":"NO DISPONIBLE","n_anomalies":0,"rows":[]}
    excluded_numeric={"id","det_id","x","y","class_id","label","group","nx","ny","row_id"}
    excluded_numeric.update({"novelty_score","visual_novelty_score","ai_class_probability","physical_score","visual_score","priority","model_score","ref_score"})
    keys=set(SCIENCE_PARAMETER_DEFINITIONS)|{"flux_ha_adu","flux_oiii_adu","peak_flux_ha","peak_flux_oiii","surface_brightness_ha","surface_brightness_oiii"}
    for rr in rows:
        for kk,vv in rr.items():
            kk=str(kk)
            if kk in excluded_numeric or kk.startswith("_"): continue
            try:
                if math.isfinite(float(vv)): keys.add(kk)
            except (TypeError,ValueError):
                pass
    x=np.asarray([finite(r.get("x"),np.nan) for r in rows],float); y=np.asarray([finite(r.get("y"),np.nan) for r in rows],float)
    spatial_ok=int(np.sum(np.isfinite(x)&np.isfinite(y)))>=int(min_points_trend)
    stats={}; baselines={}
    for key in sorted(keys):
        vals=np.asarray([finite(r.get(key),np.nan) for r in rows],float); m=np.isfinite(vals)
        if int(m.sum())<3: continue
        if spatial_ok and int(np.sum(m&np.isfinite(x)&np.isfinite(y)))>=int(min_points_trend):
            mm=m&np.isfinite(x)&np.isfinite(y); A=np.column_stack([np.ones(int(mm.sum())),x[mm],y[mm]])
            try:
                coef=np.linalg.lstsq(A,vals[mm],rcond=None)[0]; pred=np.full(len(vals),np.nan); pred[mm]=np.column_stack([np.ones(int(mm.sum())),x[mm],y[mm]])@coef
                resid=vals-pred; center,scale=_robust_location_scale(resid[np.isfinite(resid)]); stats[key]=(resid,center,scale); baselines[key]={"method":"spatial_plane","coefficients":[float(z) for z in coef],"scale":float(scale)}; continue
            except (np.linalg.LinAlgError,ValueError,TypeError,OverflowError): LOG.debug("Tendencia espacial no disponible para %s",key,exc_info=True)
        center,scale=_robust_location_scale(vals[m]); stats[key]=(vals,center,scale); baselines[key]={"method":"field_robust_baseline","median":float(center),"scale":float(scale)}
    out=[]
    for i,r in enumerate(rows):
        anomalies=[]; components=[]; snr=max(finite(r.get("peak_snr_ha"),0),finite(r.get("peak_snr_oiii"),0))
        for key,(arr,center,scale) in stats.items():
            v=arr[i] if i<len(arr) else np.nan
            if not (math.isfinite(v) and math.isfinite(scale) and scale>0): continue
            z=(v-center)/scale
            if abs(z)>=float(z_threshold) and snr>=float(snr_gate) and key not in {"chi2_red_ha","chi2_red_oiii"}:
                label,unit=SCIENCE_PARAMETER_DEFINITIONS.get(key,("observed_parameter","unknown")); anomalies.append({"kind":"field_anomaly","parameter":key,"label":label,"unit":unit,"value":finite(r.get(key),np.nan),"baseline_residual":float(v),"robust_z":float(z),"baseline":baselines[key]}); components.append(min(abs(z)/float(z_threshold),3.0))
            if key.startswith("chi2_red_") and finite(r.get(key),np.nan)>4: anomalies.append({"kind":"measurement_issue","parameter":key,"value":float(r[key]),"reason":"chi2 reducido elevado"})
        snrs=[finite(r.get("peak_snr_ha"),np.nan),finite(r.get("peak_snr_oiii"),np.nan)]
        if any(math.isfinite(q) and q<3 for q in snrs): anomalies.append({"kind":"measurement_issue","parameter":"line_detection","reason":"S/N insuficiente"})
        ratio=finite(r.get("ratio"),np.nan)
        if math.isfinite(ratio) and ratio<=0: anomalies.append({"kind":"measurement_issue","parameter":"ratio","reason":"ratio no físico"})
        visual=finite((visual_scores or {}).get(str(r.get("id")),np.nan),np.nan) if visual_scores else np.nan
        physical_score=float(min(1.0,np.mean(components)/2.0)) if components else 0.0
        independent=bool(math.isfinite(visual) and physical_score>=0.75 and visual>=0.75)
        if independent: anomalies.append({"kind":"novel_candidate","parameter":"multimodal_consistency","reason":"anomalía física y visual independiente"})
        out.append({"row_id":r.get("id",i),"anomaly_score":float(min(3.0,physical_score+(0.25*visual if math.isfinite(visual) else 0))),"physical_score":physical_score,"visual_score":float(visual) if math.isfinite(visual) else None,"anomalies":anomalies,"state":"CANDIDATO_ANOMALO" if anomalies else "SIN_ANOMALIA_EVIDENTE"})
    return {"state":"ACTIVA","n_anomalies":int(sum(bool(z["anomalies"]) for z in out)),"rows":out,"parameters_tested":sorted(stats),"baseline":baselines,"thresholds":{"snr_gate":float(snr_gate),"z_threshold":float(z_threshold),"min_points_trend":int(min_points_trend)},"policy":"tendencia espacial antes del z-score; measurement_issue separado; no declara descubrimientos"}


def system_integrity_audit(im_ha=None, im_o3=None, im_broadband=None, calibration=None, scale=None):
    issues=[]; warnings=[]
    for name,im in (("ha",im_ha),("oiii",im_o3),("lqef",im_broadband)):
        if im is None: continue
        hdr=im.header or {}
        cfa=hdr.get("BAYERPAT") or hdr.get("XBAYROFF") is not None or hdr.get("YBAYROFF") is not None
        if cfa:
            warnings.append(f"{name}: FITS parece CFA/Bayer; la respuesta efectiva por canal debe conocerse antes de fotometría absoluta de líneas.")
        bunit=str(hdr.get("BUNIT","")).lower()
        if bunit and not any(k in bunit for k in ("adu","electron","count","dn")):
            warnings.append(f"{name}: BUNIT={hdr.get('BUNIT')} no reconocido como unidad de detector por el motor.")
        if not math.isfinite(finite(hdr.get("EXPTIME"),float("nan"))) or finite(hdr.get("EXPTIME"),float("nan"))<=0:
            warnings.append(f"{name}: EXPTIME ausente/no positivo; no se puede comparar flujo por segundo de forma trazable.")
    if scale is None or not math.isfinite(float(scale)) or float(scale)<=0:
        warnings.append("Escala angular desconocida: resultados geométricos quedan en píxeles.")
    if calibration is not None and getattr(calibration,"calibrated",False):
        if not getattr(calibration,"photometric_calibrated",False):
            warnings.append("La bandera calibrated está activa sin fotometría absoluta documentada; se degradará a estado proxy.")
    return {"state":"PASS" if not issues else "FAIL","issues":issues,"warnings":warnings}


# ====================================================================
# PIPELINE
# ====================================================================
@dataclass
class AnalysisParams:
    daofind_threshold_sigma: float = 5.0
    daofind_sharplo: float = 0.2
    daofind_sharphi: float = 1.2
    daofind_roundlo: float = -0.8
    daofind_roundhi: float = 0.8
    sigmas: tuple = (1.0, 1.5, 2.2, 3.2, 4.6)
    snr_min: float = 4.0
    summary_snr_factor: float = SUMMARY_SNR_FACTOR  # corte extra (sobre snr_min) solo para
                                                      # la mediana TITULAR del resumen; ver
                                                      # quality_gated_median() más arriba
    min_separation_px: float = 8.0
    max_candidates: int = 2000
    bkg_box: int = 64
    half_length_px: int = 20
    profile_width_px: int = 7
    fwhm_px: float = 3.0
    distance_pc: float = 725.0
    distance_err_pc: float = 15.0
    n0: float = 6.0
    n0_logerr: float = 0.3
    remnant_radius_pc: float = float("nan")
    remnant_center_ra: float = float("nan")
    remnant_center_dec: float = float("nan")
    mc_samples: int = 1500
    seed: int = 20260910
    workers: int = 3
    use_processes: bool = True
    register: str = "auto"
    starless: bool = False
    light_path: str = ""
    pixel_scale_override: float = float("nan")
    target_name: str = ""
    broadband_path: str = ""
    camera_model: str = "ZWO ASI533MC Pro"
    camera_profile_version: str = "ZWO official nominal profile"
    calibration: LineCalibration = field(default_factory=LineCalibration)
    psf_match_sigma_px: float = 0.0
    flux_n_sigma: float = 2.5
    grid_model_logerr: float = 0.15
    shift_order: int = 3
    accumulate: bool = True
    star_mask_fwhm: float = 3.0
    star_candidate_exclusion_fwhm: float = 4.0
    oiii_filter: str = FILTER_DEFAULT
    ha_filter: str = FILTER_DEFAULT
    oiii_starless_path: str = ""
    ha_starless_path: str = ""
    oiii_stars_path: str = ""
    ha_stars_path: str = ""
    oiii_plane: object = None   # int/tupla explícita si oiii_path es un cubo 3D/4D; ver AmbiguousCubeError
    ha_plane: object = None     # ídem para ha_path
    offline: bool = False
    filter_curve_oiii: str = ""
    filter_curve_ha: str = ""
    export_products: bool = True
    export_ecsv: bool = False
    export_html: bool = False
    output_png_dpi: int = 300
    max_star_profiles: int = 300
    max_shock_profiles: int = 24
    bias_oiii_path: str = ""
    bias_ha_path: str = ""
    dark_oiii_path: str = ""
    dark_ha_path: str = ""
    flat_oiii_path: str = ""
    flat_ha_path: str = ""
    filament_strategy: str = "hessian"
    filament_min_component: int = 24
    grid_path: str = ""
    object_profile_config: dict = field(default_factory=dict)
    ai_enabled: bool = True
    ai_model_path: str = ""
    ai_training_path: str = ""
    ai_min_training_rows: int = 50
    ai_anomaly_contamination: float = 0.02
    ai_vision_enabled: bool = True
    ai_vision_model_path: str = ""
    ai_vision_training_dir: str = ""
    ai_vision_epochs: int = 12
    ai_vision_batch_size: int = 8
    ai_min_rows: int = 80
    ai_session_persistent: bool = True


class AnalysisCancelled(RuntimeError):
    pass


_SHARED = {}


def _worker_init(paths, shape, meta):
    _SHARED.clear()
    for k, p in paths.items():
        _SHARED[k] = np.memmap(p, dtype=np.float32, mode="r", shape=shape)
    _SHARED["params"] = meta["params"]
    _SHARED["bkg_box"] = meta["box"]


def _bkg_view(name):
    return Background(_SHARED[f"bkg_{name}_map"], _SHARED[f"rms_{name}"], _SHARED["bkg_box"])


def _analyze_candidate(c):
    P = _SHARED["params"]
    ha, oiii = _SHARED["ha"], _SHARED["oiii"]
    bha, bo3 = _bkg_view("ha"), _bkg_view("oiii")
    out = dict(c)
    if out.get("candidate_type") == "star":
        out["status"] = "rejected_star"
        out["reason"] = "fuente puntual: excluida del análisis de frentes"
        return out
    out["status"], out["reason"] = "ok", ""
    out["profile_truncated"] = False
    try:
        kw = dict(half_length=P.half_length_px, width=P.profile_width_px,
                  psf_sigma_px=P.psf_match_sigma_px)
        pr_ha = extract_profile(ha, bha, c["x"], c["y"], c["nx"], c["ny"], **kw)
        pr_o3 = extract_profile(oiii, bo3, c["x"], c["y"], c["nx"], c["ny"], **kw)
        n_valid_ha = int(np.sum(np.isfinite(pr_ha.y)))
        n_valid_o3 = int(np.sum(np.isfinite(pr_o3.y)))
        out["profile_valid_ha"] = n_valid_ha
        out["profile_valid_o3"] = n_valid_o3
        if n_valid_ha < 0.75 * len(pr_ha.y) or n_valid_o3 < 0.75 * len(pr_o3.y):
            out["profile_truncated"] = True
        f_ha = fit_peak(pr_ha); f_o3 = fit_peak(pr_o3)
        g_ha, g_o3 = fit_peak(pr_ha, step=False), fit_peak(pr_o3, step=False)
        sys_px = abs((f_o3.center - f_ha.center) - (g_o3.center - g_ha.center)) \
            if (f_ha.ok and f_o3.ok and g_ha.ok and g_o3.ok) else 0.0
        out["offset_model_sys_px"] = sys_px
        out.update({"peak_ha_px": f_ha.center, "peak_ha_err_px": f_ha.center_err,
                    "peak_snr_ha": f_ha.snr, "peak_sigma_ha_px": f_ha.sigma,
                    "chi2_red_ha": f_ha.chi2_red, "fit_method_ha": f_ha.method,
                    "peak_oiii_px": f_o3.center, "peak_oiii_err_px": f_o3.center_err,
                    "peak_snr_oiii": f_o3.snr, "peak_sigma_oiii_px": f_o3.sigma,
                    "chi2_red_oiii": f_o3.chi2_red, "fit_method_oiii": f_o3.method})
        if f_ha.ok and f_o3.ok:
            off = f_o3.center - f_ha.center
            off_err_stat = math.hypot(f_o3.center_err, f_ha.center_err)
            off_err = math.hypot(off_err_stat, c.get("reg_err_px", 0.0), sys_px)
        else:
            off, off_err_stat, off_err = float("nan"), float("nan"), float("nan")
            reasons = []
            if not f_ha.ok:
                reasons.append(f"Hα no fiable ({f_ha.method}, SNR={f_ha.snr:.2f})")
            if not f_o3.ok:
                reasons.append(f"[O III] no fiable ({f_o3.method}, SNR={f_o3.snr:.2f})")
            out["status"] = "ok_truncated" if out["profile_truncated"] else "rejected_measurement"
            out["reason"] = "; ".join(reasons)
        out["offset_px"] = off
        out["offset_err_px"] = off_err
        out["offset_err_stat_px"] = off_err_stat
        m_o3 = measure_line_flux(pr_o3, f_o3.center, f_o3.sigma if math.isfinite(f_o3.sigma) else 3.0, P.flux_n_sigma)
        m_ha = measure_line_flux(pr_ha, f_ha.center, f_ha.sigma if math.isfinite(f_ha.sigma) else 3.0, P.flux_n_sigma)
        if m_o3.ok and m_ha.ok:
            fo, eo, fh, eh = m_o3.flux, m_o3.flux_err, m_ha.flux, m_ha.flux_err
            flux_method = m_ha.method
        else:
            fo, eo = integrated_line_flux(pr_o3, f_o3, P.flux_n_sigma)
            fh, eh = integrated_line_flux(pr_ha, f_ha, P.flux_n_sigma)
            flux_method = "fit-baseline+diag"
        out.update({"flux_oiii_adu": fo, "flux_oiii_err_adu": eo,
                    "flux_ha_adu": fh, "flux_ha_err_adu": eh,
                    "flux_method": flux_method,
                    "chi2_red_bkg_ha": m_ha.chi2_red_bkg, "chi2_red_bkg_oiii": m_o3.chi2_red_bkg,
                    "centroid_ha_px": m_ha.centroid, "centroid_ha_err_px": m_ha.centroid_err,
                    "centroid_oiii_px": m_o3.centroid, "centroid_oiii_err_px": m_o3.centroid_err})
        if math.isfinite(m_ha.centroid) and math.isfinite(m_o3.centroid):
            out["offset_centroid_px"] = m_o3.centroid - m_ha.centroid
            out["offset_centroid_err_px"] = math.hypot(m_o3.centroid_err, m_ha.centroid_err,
                                                        c.get("reg_err_px", 0.0))
        else:
            out["offset_centroid_px"] = out["offset_centroid_err_px"] = float("nan")
        lr = line_ratio(fo, eo, fh, eh, P.calibration)
        out.update({"ratio": lr.value, "ratio_err": lr.err,
                    "log_ratio": lr.log10, "log_ratio_err": lr.log10_err,
                    "log_ratio_err_stat": lr.log10_err_stat, "log_ratio_err_sys": lr.log10_err_sys,
                    "ratio_calibrated": lr.calibrated, "ratio_method": lr.method})
        if out["status"] == "ok" and not math.isfinite(lr.value):
            out["status"] = "ok_no_ratio"
            out["reason"] = f"cociente no medible ({lr.method})"
        out["_profile_key"] = profile_key_of(c["x"], c["y"])
        out["profiles"] = {"t": pr_ha.t, "ha": pr_ha.y, "ha_err": pr_ha.yerr,
                           "oiii": pr_o3.y, "oiii_err": pr_o3.yerr}
        del pr_ha, pr_o3, f_ha, f_o3, g_ha, g_o3, m_ha, m_o3
    except Exception as exc:
        out["status"], out["reason"] = "error", f"{type(exc).__name__}: {exc}"
    return out


def _dump_memmap(arr, path):
    mm = np.memmap(path, dtype=np.float32, mode="w+", shape=arr.shape)
    mm[:] = np.asarray(arr, np.float32)
    mm.flush()
    del mm
    return str(path)


def _analyze_batch(batch):
    return [_analyze_candidate(c) for c in batch]


# ====================================================================
# CALIBRACIÓN CCD/CMOS: bias, dark y flat opcionales
# ====================================================================
def apply_calibration_frames(im: FitsImage, bias_path="", dark_path="", flat_path=""):
    """Aplica bias/dark/flat validando forma y exposición.
    Devuelve (imagen_corregida, informe). El flat se normaliza por mediana robusta.
    """
    arr=np.asarray(im.data,np.float32).copy(); report={"applied":[],"warnings":[]}
    def load_aux(path,role):
        if not path: return None
        p=Path(path)
        if not p.is_file(): raise FileNotFoundError(f"{role} no existe: {path}")
        aux=load_fits(p)
        if aux.shape!=im.shape: raise ValueError(f"{role} forma {aux.shape} incompatible con ciencia {im.shape}")
        report["applied"].append({"role":role,"path":str(p.resolve()),"sha256":sha256_file(p),"shape":list(aux.shape)})
        return aux
    bias=load_aux(bias_path,"bias")
    dark=load_aux(dark_path,"dark")
    flat=load_aux(flat_path,"flat")
    if bias is not None:
        arr=arr-np.asarray(bias.data,np.float32); report["bias"]="subtract"
    if dark is not None:
        dark_exp=finite(dark.exptime,float("nan")); sci_exp=finite(im.exptime,float("nan"))
        scale=1.0
        if math.isfinite(dark_exp) and dark_exp>0 and math.isfinite(sci_exp) and sci_exp>0:
            scale=sci_exp/dark_exp
        elif math.isfinite(dark_exp) and dark_exp>0:
            report["warnings"].append("EXPTIME ciencia ausente: dark aplicado sin escalado temporal.")
        else:
            report["warnings"].append("EXPTIME del dark ausente: dark aplicado sin escalado temporal.")
        arr=arr-np.asarray(dark.data,np.float32)*float(scale); report["dark_scale"]=float(scale)
    if flat is not None:
        f=np.asarray(flat.data,np.float32)
        med,sig=robust_stats(f)
        if not math.isfinite(med) or med<=0: raise ValueError("Flat inválido: mediana no positiva")
        fn=f/float(med); bad=~np.isfinite(fn)|(fn<=0)
        if bad.mean()>0.02: raise ValueError(f"Flat inválido: {bad.mean()*100:.1f}% de píxeles no positivos/no finitos")
        fn=np.where(bad,1.0,fn)
        arr=arr/fn; report["flat_median"]=float(med); report["flat_bad_fraction"]=float(bad.mean())
    return replace(im,data=np.asarray(arr,np.float32)), report



# ====================================================================
# v30: CONFIGURACION Y SELECCION DE PERFILES SEGUN OBJETO
# ====================================================================
OBJECT_PROFILE_PRESETS = {
    "veil": {"geometry":"filamentary", "half_length_px":28, "profile_width_px":9,
             "sigmas":(0.8,1.2,1.8,2.6,3.8), "min_separation_px":10, "snr_min":4.0,
             "selection":"balanced_offset_snr"},
    "cas_a": {"geometry":"shell", "half_length_px":22, "profile_width_px":11,
              "sigmas":(0.9,1.4,2.0,3.0,4.2), "min_separation_px":12, "snr_min":5.0,
              "selection":"shell_completeness"},
    "tycho": {"geometry":"shell", "half_length_px":22, "profile_width_px":11,
              "sigmas":(0.9,1.4,2.0,3.0,4.2), "min_separation_px":12, "snr_min":5.0,
              "selection":"shell_completeness"},
    "kepler": {"geometry":"shell", "half_length_px":22, "profile_width_px":11,
               "sigmas":(0.9,1.4,2.0,3.0,4.2), "min_separation_px":12, "snr_min":5.0,
               "selection":"shell_completeness"},
    "sn1006": {"geometry":"shell", "half_length_px":24, "profile_width_px":11,
               "sigmas":(0.9,1.4,2.0,3.0,4.2), "min_separation_px":12, "snr_min":5.0,
               "selection":"shell_completeness"},
    "vela": {"geometry":"shell", "half_length_px":24, "profile_width_px":11,
             "sigmas":(0.9,1.4,2.0,3.0,4.2), "min_separation_px":12, "snr_min":5.0,
             "selection":"shell_completeness"},
    "ic443": {"geometry":"interaction_filamentary", "half_length_px":30, "profile_width_px":11,
              "sigmas":(0.8,1.2,1.8,2.6,3.8), "min_separation_px":9, "snr_min":4.5,
              "selection":"high_contrast"},
    "w44": {"geometry":"interaction_filamentary", "half_length_px":30, "profile_width_px":11,
            "sigmas":(0.8,1.2,1.8,2.6,3.8), "min_separation_px":9, "snr_min":4.5,
            "selection":"high_contrast"},
}


def get_object_profile_config(target_name: str) -> dict:
    """Devuelve parámetros de perfil adaptados al objeto; usa DB local y SIMBAD cuando procede."""
    lit = find_literature(target_name or "")
    if lit and lit.get("key") in OBJECT_PROFILE_PRESETS:
        cfg = dict(OBJECT_PROFILE_PRESETS[lit["key"]])
        cfg.update({"object_key":lit["key"], "matched_alias":lit.get("matched_alias",""),
                    "canonical":lit.get("canonical",target_name or ""), "config_source":"local_literature"})
        return cfg
    base={"object_key":"generic_snr", "matched_alias":"", "canonical":target_name or "Objeto no identificado",
          "geometry":"filamentary", "half_length_px":26, "profile_width_px":9,
          "sigmas":(0.9,1.3,1.9,2.7,3.8), "min_separation_px":10, "snr_min":4.0,
          "selection":"balanced_offset_snr", "config_source":"generic"}
    if target_name and HAS_SIMBAD:
        try:
            sb=Simbad(); sb.ROW_LIMIT=1
            try:
                sb.add_votable_fields("otype")
            except (AttributeError, TypeError, ValueError) as exc:
                LOG.debug("SIMBAD otype no disponible: %s", exc)
            tab=sb.query_object(target_name)
            if tab is not None and len(tab):
                names=[str(c) for c in tab.colnames]
                oc=next((c for c in ("otype","OTYPE") if c in names),None)
                otype=str(tab[oc][0]).lower() if oc else ""
                if "snr" in otype:
                    base.update({"geometry":"shell","half_length_px":24,"profile_width_px":11,
                                 "sigmas":(0.9,1.4,2.0,3.0,4.2),"min_separation_px":12,
                                 "snr_min":5.0,"selection":"shell_completeness","object_type":otype,
                                 "config_source":"SIMBAD"})
                elif any(k in otype for k in ("hii","rneb","pn","neb")):
                    base.update({"geometry":"filamentary","half_length_px":28,"profile_width_px":9,
                                 "sigmas":(0.8,1.2,1.8,2.6,3.8),"min_separation_px":10,
                                 "snr_min":4.0,"selection":"balanced_offset_snr","object_type":otype,
                                 "config_source":"SIMBAD"})
                else:
                    base["object_type"]=otype
        except (KeyError, ValueError, TypeError, AttributeError, OSError) as exc:
            LOG.debug("SIMBAD no pudo enriquecer la configuración del objeto %r: %s", target_name, exc)
    return base


def _profile_selection_score(c, cfg):
    def f(k, d=0.0): return finite(c.get(k), d)
    snr = min(max(f("peak_snr_ha"),0),100) + min(max(f("peak_snr_oiii"),0),100)
    oe = max(f("offset_err_px", np.nan), 1e-6)
    osig = abs(f("offset_px")) / oe if np.isfinite(oe) else 0.0
    n_expected = 2.0 * cfg.get("half_length_px",26) / 0.5 + 1.0
    completeness = min(f("profile_valid_ha",0), f("profile_valid_o3",0)) / max(1.0,n_expected)
    completeness = max(0.0,min(1.0,completeness))
    aniso = f("anisotropy",0.5)
    shape = max(0.0, 1.0 - abs(aniso-0.25)/0.75)
    ridge = max(0.0,f("ridge_response"))
    quality = 0.0 if c.get("profile_truncated") else 1.0
    star_dist = f("source_distance_px",np.inf)
    star_penalty = 1.0 if not np.isfinite(star_dist) else min(1.0,star_dist/max(1.0,cfg.get("min_separation_px",10)))
    mode=cfg.get("selection")
    if mode=="shell_completeness": return 3*snr+5*completeness+1.5*osig+2*shape+quality+star_penalty
    if mode=="high_contrast": return 4*snr+3*osig+2*ridge+2*completeness+quality+star_penalty
    return 3*snr+3*osig+3*completeness+1.5*shape+quality+star_penalty


def select_optimal_profile_candidates(cands, target_name, max_profiles=24):
    cfg=get_object_profile_config(target_name)
    usable=[]; rejected=[]
    for c in cands or []:
        if c.get("candidate_type","shock")=="star":
            c["status"]="rejected_star"; c["reason"]="fuente puntual identificada en las imágenes normales"; rejected.append(c); continue
        if not c.get("keep",True): rejected.append(c); continue
        if not np.isfinite(finite(c.get("snr_pix"),np.nan)) or finite(c.get("snr_pix"),0)<cfg["snr_min"]:
            c["status"]="rejected_profile_selection"; c["reason"]="SNR inferior al umbral optimizado para el objeto"; rejected.append(c); continue
        c["profile_selection_score"]=float(_profile_selection_score(c,cfg)); usable.append(c)
    usable.sort(key=lambda x:(-finite(x.get("profile_selection_score"),-np.inf),-finite(x.get("snr_pix"),-np.inf),int(x.get("id",0))))
    n=max(1,int(max_profiles)); selected=usable[:n]
    for c in usable[n:]:
        c["status"]="rejected_profile_selection"; c["reason"]=f"fuera del top-{n} optimizado para {cfg['canonical']}"; rejected.append(c)
    for rank,c in enumerate(selected,1):
        c["profile_rank"]=rank; c["profile_selection"]=cfg["selection"]; c["profile_geometry"]=cfg["geometry"]; c["profile_object"]=cfg["canonical"]
        _off = finite(c.get("offset_px"), float("nan"))
        _oe = max(finite(c.get("offset_err_px"), float("nan")), 1e-6)
        _snr_sum = min(max(finite(c.get("peak_snr_ha"), 0), 100) + min(max(finite(c.get("peak_snr_oiii"), 0), 100), 100), 200)
        _comp = min(finite(c.get("profile_valid_ha"),0), finite(c.get("profile_valid_o3"),0)) / max(1.0, 2.0*cfg.get("half_length_px",26)/0.5+1.0)
        c["profile_score_components"]={"snr":float(_snr_sum), "offset_significance":float(abs(_off)/_oe) if np.isfinite(_off) else 0.0, "completeness":float(max(0.0,min(1.0,_comp)))}
    return selected,rejected,cfg


# ====================================================================
# PIPELINE PRINCIPAL
# ====================================================================
def analyze_pair_core(oiii_path, ha_path, out_dir, P, grid=None, labels_path=None,
                 progress=None, cancel=None):
    t0 = time.time()
    # v31: la medición de perfiles de nebulosa requiere obligatoriamente
    # una pareja OIII/Hα starless. Las imágenes normales quedan reservadas
    # a registro, astrometría y caracterización estelar.
    if not (P.oiii_starless_path and P.ha_starless_path and
            Path(P.oiii_starless_path).is_file() and Path(P.ha_starless_path).is_file()):
        raise ValueError("v30: se requieren las dos imágenes starless (OIII y Hα) para generar perfiles científicos.")
    P.starless = True
    P.register = "stars"
    obj_cfg = get_object_profile_config(P.target_name)
    P.object_profile_config = dict(obj_cfg)
    P.half_length_px = obj_cfg["half_length_px"]
    P.profile_width_px = obj_cfg["profile_width_px"]
    P.sigmas = tuple(obj_cfg["sigmas"])
    P.min_separation_px = float(obj_cfg["min_separation_px"])
    P.snr_min = float(obj_cfg["snr_min"])
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)

    def report(frac, msg):
        if progress is not None:
            try:
                progress(float(frac), str(msg))
            except Exception:
                pass

    def check_cancel():
        if cancel is not None and cancel.is_set():
            raise AnalysisCancelled("cancelado por el usuario")

    P.workers = _safe_worker_count(P.workers)
    LOG.info("Workers: %d (RAM libre ≈ %.1f GB)", P.workers, _available_ram_gb())

    report(0.0, "Cargando imágenes")
    rng = np.random.default_rng(P.seed)
    man = RunManifest(seed=P.seed)
    man.collect_versions()
    man.add_input("oiii", oiii_path)
    man.add_input("ha", ha_path)
    man.add_input("oiii_starless", P.oiii_starless_path)
    man.add_input("ha_starless", P.ha_starless_path)
    if labels_path:
        man.add_input("labels", labels_path)

    im_o3 = load_fits(oiii_path, plane=P.oiii_plane)
    im_ha = load_fits(ha_path, plane=P.ha_plane)
    im_o3_starless = load_fits(P.oiii_starless_path, plane=P.oiii_plane)
    im_ha_starless = load_fits(P.ha_starless_path, plane=P.ha_plane)
    if im_o3_starless.shape != im_o3.shape or im_ha_starless.shape != im_ha.shape:
        raise ValueError("Las imágenes starless deben tener exactamente la misma forma que las normales.")
    for tag, im in (("oiii", im_o3), ("ha", im_ha)):
        if im.original_ndim > 2:
            man.fits_metadata[f"{tag}_original_shape"] = list(im.original_shape)
            man.fits_metadata[f"{tag}_selected_plane"] = list(im.selected_plane)
            man.warnings.append(
                f"{tag}: FITS de entrada era un cubo {im.original_shape}; se usó el plano "
                f"{im.selected_plane} ({'explícito' if im.cube_plane_is_explicit else 'POR DEFECTO, revisar'}).")
    if im_o3.shape != im_ha.shape:
        raise ValueError(f"Formas distintas {im_o3.shape} vs {im_ha.shape}")

    # v37: los masters CCD sí se aplican cuando llegan por CLI/API; no son entradas
    # fotográficas de ciencia del selector GUI. Las imágenes stars-only permanecen fuera.
    cal_frames = {}
    if any((P.bias_oiii_path, P.dark_oiii_path, P.flat_oiii_path)):
        im_o3, cal_frames["oiii"] = apply_calibration_frames(im_o3, P.bias_oiii_path, P.dark_oiii_path, P.flat_oiii_path)
        for item in cal_frames["oiii"].get("applied", []): man.add_input(item["role"]+"_oiii", item["path"])
    if any((P.bias_ha_path, P.dark_ha_path, P.flat_ha_path)):
        im_ha, cal_frames["ha"] = apply_calibration_frames(im_ha, P.bias_ha_path, P.dark_ha_path, P.flat_ha_path)
        for item in cal_frames["ha"].get("applied", []): man.add_input(item["role"]+"_ha", item["path"])
    if cal_frames:
        man.background["ccd_calibration_frames"] = cal_frames
        for side,rep in cal_frames.items():
            for w in rep.get("warnings", []): man.warnings.append(f"Calibración CCD {side}: {w}")

    # v31: las stars-only ya no forman parte del flujo científico; se derivan de las normales.
    im_o3_stars = im_ha_stars = None
    im_broadband = None
    if P.broadband_path and Path(P.broadband_path).is_file():
        im_broadband = load_fits(P.broadband_path)
        man.add_input("broadband_lqef", P.broadband_path)
        LOG.info("Banda ancha L-QEF: %s", im_broadband.shape)
        if im_broadband.shape != im_ha.shape:
            raise ValueError("La imagen L-QEF debe estar registrada a la misma malla que Hα/OIII antes del análisis.")
        bs = im_broadband.pixel_scale_arcsec; hs = im_ha.pixel_scale_arcsec
        if bs is not None and hs is not None and hs > 0 and abs(float(bs) / float(hs) - 1.0) > 0.01:
            raise ValueError("L-QEF y Hα tienen escalas de píxel incompatibles (>1%); no se permite comparar intensidades/morfología sin remuestreo trazable.")
    use_starless = True

    if P.light_path and Path(P.light_path).is_file():
        man.add_input("light", P.light_path)
        m_wcs, m_scale, m_src = load_light_wcs(P.light_path, P.target_name)
        if m_wcs is not None:
            if im_ha.wcs is None:
                im_ha.wcs = m_wcs
                im_ha.wcs_source = f"WCS light ({Path(P.light_path).name})"
            if im_o3.wcs is None:
                im_o3.wcs = m_wcs
                im_o3.wcs_source = f"WCS light ({Path(P.light_path).name})"
        if m_scale is not None:
            if im_ha.pixel_scale_arcsec is None:
                im_ha.pixel_scale_arcsec = m_scale
            if im_o3.pixel_scale_arcsec is None:
                im_o3.pixel_scale_arcsec = m_scale
        LOG.info("Light WCS: %s", m_src)
        man.warnings.append(f"Light frame: {m_src}")

    scale = im_ha.pixel_scale_arcsec or im_o3.pixel_scale_arcsec
    if scale is None and math.isfinite(P.pixel_scale_override) and P.pixel_scale_override > 0:
        scale = float(P.pixel_scale_override)
        im_ha.pixel_scale_arcsec = scale
        im_o3.pixel_scale_arcsec = scale
        man.warnings.append(f"Escala manual: {scale:.4f}″/px")
    elif scale is None:
        man.warnings.append("Sin WCS ni escala: desfases en px")

    LOG.info("Imágenes %s; escala=%s ″/px; WCS(Hα)=%s; starless=%s",
             im_ha.shape, scale, im_ha.wcs is not None, P.starless)
    man.parameters = json_sanitize(dataclasses.asdict(P))
    man.configuration_sha256 = analysis_signature(P, man)
    man.inputs["configuration_sha256"] = man.configuration_sha256
    for tag,im in (("ha",im_ha),("oiii",im_o3)):
        man.fits_metadata[tag]=fits_metadata_summary(im)
        man.fits_metadata[tag]["wcs_quality"]=wcs_quality_report(im)
        man.fits_metadata[tag]["quality_mask_pixels"]=int(build_quality_mask(im).sum())
        man.fits_metadata[tag]["offline"]=bool(P.offline)
    man.warnings.append("Registro: dx, dy es el desplazamiento aplicado a la imagen [O III] para alinearla con H-alpha.")
    if P.offline: man.warnings.append("Modo offline: Gaia/SIMBAD no se consultan.")

    report(0.05, "Estimando fondo")
    bkg_ha = estimate_background(im_ha.data, P.bkg_box)
    bkg_o3 = estimate_background(im_o3.data, P.bkg_box)
    if use_starless:
        bkg_ha_n = estimate_background(im_ha_starless.data, P.bkg_box)
        bkg_o3_n = estimate_background(im_o3_starless.data, P.bkg_box)
    else:
        bkg_ha_n, bkg_o3_n = bkg_ha, bkg_o3
    bkg_ha_s, bkg_o3_s = bkg_ha, bkg_o3

    reg = None
    o3_reg = im_o3.data
    reg_mode = P.register
    if reg_mode == "auto":
        reg_mode = "none" if P.starless else "stars"
    if reg_mode == "stars":
        reg = register_on_stars(im_o3.data, im_ha.data, bkg_o3, bkg_ha, P.fwhm_px)
        if reg.n_stars < 5:
            man.warnings.append(f"Pocas estrellas ({reg.n_stars}); cae a fase")
    elif reg_mode == "phase":
        reg = _register_phase_fallback(im_o3.data, im_ha.data, bkg_o3, bkg_ha, note="modo phase")
        man.warnings.append("Registro por fase: puede absorber desfase científico")
    else:
        reg = Registration(dx=0.0, dy=0.0, dx_err=0.0, dy_err=0.0, n_stars=0,
                           method="none", residual_rms_px=0.0,
                           notes="Sin registro (asume alineación)")
    if reg is not None:
        LOG.info("Registro: %s dx=%.3f±%.3f dy=%.3f±%.3f n=%d",
                 reg.method, reg.dx, reg.dx_err, reg.dy, reg.dy_err, reg.n_stars)
        if (abs(reg.dx) > 0.05 or abs(reg.dy) > 0.05) and reg.method != "none":
            o3_reg = apply_shift(im_o3.data, reg.dx, reg.dy, order=P.shift_order)
            bkg_o3 = estimate_background(o3_reg, P.bkg_box)
            man.warnings.append(RESAMPLING_WARNING)
    reg_err_px = math.hypot(finite(reg.dx_err, 0.0), finite(reg.dy_err, 0.0)) if reg else 0.0
    lqef_reg = None
    if im_broadband is not None:
        try:
            bb = estimate_background(im_broadband.data, P.bkg_box)
            lqef_reg = register_on_stars(im_broadband.data, im_ha.data, bb, bkg_ha, P.fwhm_px, search_radius_px=12.0)
            if abs(lqef_reg.dx) > 0.05 or abs(lqef_reg.dy) > 0.05:
                im_broadband = replace(im_broadband, data=apply_shift(im_broadband.data, lqef_reg.dx, lqef_reg.dy, order=P.shift_order))
                man.warnings.append(RESAMPLING_WARNING)
            man.registration["lqef"] = dataclasses.asdict(lqef_reg)
        except Exception as exc:
            man.warnings.append(f"Registro L-QEF no disponible: {type(exc).__name__}: {exc}")

    check_cancel()
    report(0.15, "Preparando máscaras y detectando crestas")

    gaia_wcs_check = None
    stellar_catalog = []
    stellar_highlights = []
    # v30: estrellas siempre desde las imágenes NORMALES.
    # Los ficheros stars-only quedan fuera del flujo científico.
    srcs = detect_point_sources(im_ha.data, bkg_ha, P.fwhm_px,
                                threshold_sigma=6.0, max_sources=1500)
    LOG.info("Estrellas detectadas: %d", len(srcs))
    gaia_tab = None
    if P.offline:
        stellar_catalog, stellar_highlights = _build_stellar_catalog(
            im_ha, srcs, gaia_tab=None, simbad_objects=None, match_arcsec=5.0)
        metric_rows = enrich_star_rows(im_ha, srcs, bkg_ha)
        by_id={int(r.get("det_id",0)):r for r in stellar_catalog}
        for mr in metric_rows: by_id.setdefault(int(mr["det_id"]),{}).update(mr)
        stellar_catalog=list(by_id.values())
        LOG.info("Offline: Gaia/SIMBAD omitidos")
    elif im_ha.wcs is not None and HAS_GAIA and srcs is not None and len(srcs) >= 5:
        report(0.17, "Verificando WCS y caracterizando estrellas con Gaia DR3…")
        gaia_wcs_check = verify_wcs_with_gaia(im_ha, srcs, max_match_arcsec=3.0)
        if gaia_wcs_check:
            LOG.info("Gaia WCS check: %d coincidencias, RMS=%.2f″, offset=%.2f″",
                     gaia_wcs_check.get("n_matched", 0),
                     finite(gaia_wcs_check.get("rms_arcsec"), float("nan")),
                     finite(gaia_wcs_check.get("offset_arcsec"), float("nan")))
        try:
            Hs, Ws = im_ha.data.shape
            ra_c0, dec_c0 = im_ha.pixel_to_world(np.array([Ws / 2]), np.array([Hs / 2]))
            rdeg = min(0.9, math.hypot(Hs, Ws) * (im_ha.pixel_scale_arcsec or 1.0) / 3600.0 / 2.0 + 0.05)
            gaia_tab = query_gaia_sources(float(ra_c0[0]), float(dec_c0[0]), rdeg, mag_limit=18.0, max_rows=3000)
            simbad_objs = query_simbad_field(float(ra_c0[0]), float(dec_c0[0]), rdeg, max_rows=500)
            stellar_catalog, stellar_highlights = _build_stellar_catalog(
                im_ha, srcs, gaia_tab=gaia_tab, simbad_objects=simbad_objs, match_arcsec=5.0)
            metric_rows = enrich_star_rows(im_ha, srcs, bkg_ha)
            by_id={int(r.get("det_id",0)):r for r in stellar_catalog}
            for mr in metric_rows:
                by_id.setdefault(int(mr["det_id"]),{}).update(mr)
            stellar_catalog=list(by_id.values())
            stsum = stellar_summary(stellar_catalog)
            LOG.info("Estrellas: %d detectadas · %d cruzadas con Gaia · %d interesantes",
                     len(srcs), stsum.get("n_matched", 0), stsum.get("n_interesting", 0))
            LOG.info("SIMBAD: %d objetos en el campo · %d destacados", len(simbad_objs), len(stellar_highlights))
        except Exception as exc:
            LOG.warning("Caracterización estelar: %s", exc)
    else:
        # WCS/servicios remotos no disponibles: mantener catálogo local de estrellas.
        stellar_catalog = _build_stellar_catalog(im_ha, srcs, gaia_tab=None, simbad_objects=None, match_arcsec=5.0)[0]
        metric_rows = enrich_star_rows(im_ha, srcs, bkg_ha)
        by_id={int(r.get("det_id",0)):r for r in stellar_catalog}
        for mr in metric_rows: by_id.setdefault(int(mr["det_id"]),{}).update(mr)
        stellar_catalog=list(by_id.values())
        LOG.warning("Gaia/SIMBAD no disponibles o WCS ausente; se conserva caracterización local.")
    # Segunda pasada de fondo: las fuentes puntuales conocidas se excluyen del estimador
    # para evitar que estrellas/halos sesguen el fondo espacial.
    if len(srcs):
        provisional_star_mask = make_star_mask(im_ha.data.shape, srcs, P.fwhm_px)
        bkg_ha = estimate_background(im_ha.data, P.bkg_box, mask=provisional_star_mask)
        bkg_o3 = estimate_background(o3_reg, P.bkg_box, mask=provisional_star_mask)
        if use_starless:
            bkg_ha_n = estimate_background(im_ha_starless.data, P.bkg_box)
            bkg_o3_n = estimate_background(im_o3_starless.data, P.bkg_box)
    mask_radius = max(3.0, P.star_mask_fwhm * P.fwhm_px)
    ha_m = mask_point_sources(im_ha.data, srcs, mask_radius)
    o3_m = mask_point_sources(o3_reg, srcs, mask_radius)
    LOG.info("%d fuentes puntuales enmascaradas (r=%.1f px)", len(srcs), mask_radius)
    if use_starless:
        LOG.info("Crestas sobre imagen STARLESS")
        det_image = im_ha_starless.data
        det_bkg = bkg_ha_n
    else:
        det_image = ha_m
        det_bkg = bkg_ha
    det_variance_image = im_ha_starless if use_starless else im_ha
    var_det, var_det_method = build_variance_map(det_variance_image, det_bkg)
    strategy_name = str(P.filament_strategy or "hessian").lower()
    strategy = CannyFilamentStrategy() if strategy_name.startswith("canny") else HessianFilamentStrategy()
    det_result = strategy.detect(det_image, var_det, {"background": det_bkg, "star_mask": (None if P.starless else (np.isnan(ha_m)))}, P)
    rm = det_result.ridge_map
    cands_all = det_result.candidates
    filament_response_map = np.asarray(rm.response, np.float32).copy()
    man.detection["filament_strategy"] = det_result.strategy
    man.detection["filament_metrics"] = det_result.metrics
    man.detection["variance_method"] = var_det_method
    del rm, det_result
    gc.collect()
    grad = np.gradient(ndi.gaussian_filter(np.nan_to_num(bkg_ha.subtract(ha_m)), 25.0))
    for c in cands_all:
        c["nx"], c["ny"] = outward_normal(grad, c["x"], c["y"], c["nx"], c["ny"])
        c["reg_err_px"] = reg_err_px
    del grad
    gc.collect()

    # v30: estrellas/choques se clasifican usando EXCLUSIVAMENTE estrellas
    # detectadas en las imágenes normales, aunque la cresta proceda de starless.
    annotate_point_source_proximity(
        cands_all, srcs, max(8.0, P.star_candidate_exclusion_fwhm * P.fwhm_px))
    n_star_cands = sum(1 for c in cands_all if c.get("candidate_type") == "star")
    LOG.info("%d candidatos de cresta (bruto) · %d estelares",
             len(cands_all), n_star_cands)

    seen_path = out / "seen.json"
    cell = int(max(6, P.min_separation_px))
    prev_profiles_path = out / "profiles.json"
    reuse_previous = False
    if P.accumulate and (out / "catalog.json").is_file() and prev_profiles_path.is_file():
        try:
            old_payload=json.load(open(out / "catalog.json",encoding="utf-8"))
            old_manifest=old_payload.get("manifest") or {}
            old_sig=old_manifest.get("configuration_sha256") or (old_manifest.get("inputs") or {}).get("configuration_sha256")
            reuse_previous=bool(old_sig and old_sig==man.configuration_sha256)
            if not reuse_previous:
                man.warnings.append("La firma de análisis cambió: perfiles/seen previos no se reutilizan.")
        except (OSError,json.JSONDecodeError,TypeError) as exc:
            man.warnings.append(f"No se pudo validar la firma del catálogo previo: {type(exc).__name__}: {exc}")
    prev_profiles = load_previous_profiles(prev_profiles_path) if reuse_previous else {}
    seen_cells = load_seen(seen_path, cell) if reuse_previous else set()
    skip_cells = set()
    if P.accumulate and seen_cells and prev_profiles:
        for k in prev_profiles.keys():
            if k.startswith("star_"):
                continue
            try:
                xi, yi = k.split("_")
                skip_cells.add((int(xi) // cell, int(yi) // cell))
            except Exception:
                continue
        skip_cells &= seen_cells
    if skip_cells:
        before = len(cands_all)
        cands = [c for c in cands_all
                 if (int(c["x"] // cell), int(c["y"] // cell)) not in skip_cells]
        LOG.info("Acumulación: %d nuevos, %d ya con perfil (de %d vistos)",
                 len(cands), before - len(cands), len(seen_cells))
    else:
        cands = cands_all

    rejected_star = []
    if not P.starless:
        nonstar = []
        for c in cands:
            if c.get("candidate_type") == "star":
                rejected_star.append(dict(
                    c, status="rejected_star",
                    reason=(f"fuente puntual a {finite(c.get('source_distance_px'), 0.0):.1f} px; "
                            "excluida del análisis de frentes")))
            else:
                nonstar.append(c)
        cands = nonstar
        if rejected_star:
            LOG.info("%d candidatas estelares excluidas del análisis", len(rejected_star))

    # v30: SPCC-style spectrophotometric colour calibration from NORMAL images + Gaia XP.
    _spcc_curve_o3 = _spcc_curve_ha = None
    if getattr(P, "filter_curve_oiii", ""):
        _spcc_curve_o3, _ = load_filter_curve(P.filter_curve_oiii)
        if getattr(P, "filter_curve_ha", "") and P.filter_curve_ha != P.filter_curve_oiii:
            _spcc_curve_ha, _ = load_filter_curve(P.filter_curve_ha)
        else:
            _spcc_curve_ha = _spcc_curve_o3
    spcc = spectrophotometric_color_calibration(
        im_ha, replace(im_o3, data=o3_reg), bkg_ha, bkg_o3, stellar_catalog,
        ha_filter=P.ha_filter or FILTER_DEFAULT, oiii_filter=P.oiii_filter or FILTER_DEFAULT,
        ha_curve=_spcc_curve_ha, oiii_curve=_spcc_curve_o3)
    P.calibration.spcc_ratio_factor = float(spcc.get("spcc_ratio_factor", 1.0)) if spcc.get("state") == "RESULTADO CALIBRADO" else 1.0
    if spcc.get("state") == "RESULTADO CALIBRADO":
        P.calibration.calibrated = True
        P.calibration.calibration_basis = "gaia_spcc_relative"
        P.calibration.calibration_warning = spcc.get("note", "")
    else:
        if spcc.get("spcc_ratio_factor") is not None:
            P.calibration.calibration_warning = spcc.get("note", "")
        man.warnings.append("SPCC: corrección de color disponible como proxy si se usan respuestas nominales; calibración trazable requiere T(lambda) medida.")

    ml = ViabilityModel(seed=P.seed)
    ml_report = None
    if labels_path:
        ViabilityModel.attach_labels(cands, ViabilityModel.load_labels(labels_path))
        ml_report = ml.fit(cands)
    ml.score(cands, rng)
    for i, c in enumerate(cands):
        c["id"] = i
    todo = [c for c in cands if c["keep"]]
    todo, rejected_profile, obj_cfg = select_optimal_profile_candidates(
        todo, P.target_name, max_profiles=P.max_shock_profiles)
    rejected_ml = [dict(c, status="rejected_ml",
                        reason=f"filtro ML: p={finite(c.get('p_viable')):.2f}")
                   for c in cands if not c["keep"]]
    check_cancel()

    report(0.25, f"Analizando {len(todo)} candidatos nuevos")
    shape = im_ha.shape
    if use_starless:
        ha_for_profiles = im_ha_starless.data.astype(np.float32)
        o3_for_profiles = im_o3_starless.data.astype(np.float32)
        bkg_ha_for_profiles = bkg_ha_n
        bkg_o3_for_profiles = bkg_o3_n
    else:
        ha_for_profiles = ha_m
        o3_for_profiles = o3_m
        bkg_ha_for_profiles = bkg_ha
        bkg_o3_for_profiles = bkg_o3
    tmp = out / "_shm"; tmp.mkdir(exist_ok=True)
    paths = {
        "ha": _dump_memmap(ha_for_profiles, tmp / "ha.f32"),
        "oiii": _dump_memmap(o3_for_profiles, tmp / "oiii.f32"),
        "bkg_ha_map": _dump_memmap(bkg_ha_for_profiles.bkg, tmp / "bha.f32"),
        "rms_ha": _dump_memmap(bkg_ha_for_profiles.rms, tmp / "rha.f32"),
        "bkg_oiii_map": _dump_memmap(bkg_o3_for_profiles.bkg, tmp / "bo3.f32"),
        "rms_oiii": _dump_memmap(bkg_o3_for_profiles.rms, tmp / "ro3.f32"),
    }
    meta = {"box": P.bkg_box, "params": P}
    try:
        results = []
        n_todo = max(len(todo), 1)

        if P.use_processes and P.workers > 1 and len(todo) > 20 and cancel is None:
            try:
                chunk = max(1, len(todo) // (4 * P.workers))
                batches = [todo[i:i + chunk] for i in range(0, len(todo), chunk)]
                LOG.info("ProcessPool: %d workers, %d lotes", P.workers, len(batches))
                with ProcessPoolExecutor(max_workers=P.workers, initializer=_worker_init,
                                         initargs=(paths, shape, meta)) as ex:
                    futs = [ex.submit(_analyze_batch, b) for b in batches]
                    for fut in as_completed(futs):
                        results.extend(fut.result())
                        report(0.25 + 0.55 * len(results) / n_todo,
                               f"Analizados {len(results)}/{len(todo)}")
                results.sort(key=lambda r: r["id"])
            except (OSError, MemoryError, RuntimeError) as exc:
                LOG.warning("ProcessPool falló (%s): secuencial", exc)
                man.warnings.append("ProcessPool falló: secuencial")
                results = []
                _worker_init(paths, shape, meta)
                for i, c in enumerate(todo):
                    check_cancel()
                    results.append(_analyze_candidate(c))
                    if (i + 1) % 25 == 0 or i + 1 == len(todo):
                        report(0.25 + 0.55 * (i + 1) / n_todo, f"Analizados {i+1}/{len(todo)}")
        elif P.workers > 1 and len(todo) > 1:
            _worker_init(paths, shape, meta)
            executor = ThreadPoolExecutor(max_workers=P.workers, thread_name_prefix="aps-candidate")
            futs = []
            try:
                futs = [executor.submit(_analyze_candidate, c) for c in todo]
                for fut in as_completed(futs):
                    check_cancel()
                    results.append(fut.result())
                    report(0.25 + 0.55 * len(results) / n_todo,
                           f"Analizados {len(results)}/{len(todo)}")
            except AnalysisCancelled:
                for fut in futs:
                    fut.cancel()
                executor.shutdown(wait=True, cancel_futures=True)
                raise
            except Exception:
                for fut in futs:
                    fut.cancel()
                executor.shutdown(wait=True, cancel_futures=True)
                raise
            else:
                executor.shutdown(wait=True, cancel_futures=True)
                results.sort(key=lambda r: r["id"])
        else:
            _worker_init(paths, shape, meta)
            for i, c in enumerate(todo):
                check_cancel()
                results.append(_analyze_candidate(c))
                if (i + 1) % 25 == 0 or i + 1 == len(todo):
                    report(0.25 + 0.55 * (i + 1) / n_todo, f"Analizados {i+1}/{len(todo)}")

    finally:
        _SHARED.clear()
        shutil.rmtree(tmp, ignore_errors=True)
        gc.collect()



    if P.accumulate and results:
        try:
            save_seen(seen_path, results, cell)
        except Exception as exc:
            LOG.warning("No se pudo guardar seen.json: %s", exc)

    prof_path = out / "profiles.json"
    profiles = load_previous_profiles(prof_path) if P.accumulate else {}
    for k in list(profiles.keys()):
        if k.startswith("star_"):
            profiles.pop(k, None)
    n_new_prof = 0
    for r in results:
        pr = r.pop("profiles", None)
        key = r.pop("_profile_key", None) or profile_key(r)
        if pr is not None and key is not None:
            profiles[key] = pr
            n_new_prof += 1
    LOG.info("Perfiles de nebulosa: %d previos + %d nuevos = %d totales",
             len(profiles) - n_new_prof, n_new_prof, len(profiles))

    report(0.82, "Física y clasificación")
    d_pc = P.distance_pc
    for r in results:
        off_px = finite(r.get("offset_px"))
        if scale and math.isfinite(off_px):
            r["offset_arcsec"] = off_px * scale
            r["offset_err_arcsec"] = finite(r.get("offset_err_px")) * scale
            r["offset_pc"] = r["offset_arcsec"] / C.arcsec_per_rad * d_pc
            if r["offset_arcsec"] != 0:
                r["offset_err_pc"] = abs(r["offset_pc"]) * math.sqrt(
                    (r["offset_err_arcsec"] / r["offset_arcsec"]) ** 2
                    + (P.distance_err_pc / d_pc) ** 2)
            else:
                r["offset_err_pc"] = float("nan")
            r["offset_units"] = "arcsec"
        else:
            r["offset_arcsec"] = r["offset_err_arcsec"] = float("nan")
            r["offset_pc"] = r["offset_err_pc"] = float("nan")
            r["offset_units"] = "px"
        off_cls = r["offset_arcsec"] if math.isfinite(finite(r.get("offset_arcsec"))) else off_px
        err_cls = (r["offset_err_arcsec"] if math.isfinite(finite(r.get("offset_err_arcsec")))
                   else finite(r.get("offset_err_px")))
        units_cls = "arcsec" if math.isfinite(finite(r.get("offset_arcsec"))) else "px"
        lr = LineRatio(finite(r.get("ratio")), finite(r.get("ratio_err")),
                       finite(r.get("log_ratio")), finite(r.get("log_ratio_err")),
                       bool(r.get("ratio_calibrated", False)),
                       finite(r.get("flux_oiii_adu")), finite(r.get("flux_ha_adu")))
        r["front_class"], r["front_class_reason"] = classify_front(off_cls, err_cls, lr, units=units_cls)
        if im_ha.wcs is not None:
            try:
                ra, dec = im_ha.pixel_to_world(np.array([r["x"]]), np.array([r["y"]]))
                r["ra_deg"], r["dec_deg"] = float(ra[0]), float(dec[0])
            except (ValueError, TypeError, IndexError) as exc:
                LOG.debug("WCS: no se pudo asociar candidato a coordenadas: %s", exc)
        if grid is not None and math.isfinite(lr.value) and lr.calibrated and P.calibration.calibration_basis in {"validated_photometric", "user_curve_relative", "gaia_spcc_relative"}:
            sol = grid.invert(lr.value, lr.err, n0=P.n0, grid_model_logerr=P.grid_model_logerr)
            r["v_modes"] = sol.modes
            r["v_degenerate"] = sol.degenerate
            r["grid_sigma_obs_dex"] = sol.sigma_obs_dex
            r["grid_sigma_model_dex"] = sol.sigma_model_dex
            r["grid_note"] = sol.note
            if sol.modes:
                m0 = sol.modes[0]
                r["v_kms"] = m0["v_kms"]
                r["v_err_kms"] = 0.5 * (m0["v_hi"] - m0["v_lo"])
                r["v_err_kms_obs_only"] = 0.5 * (m0["v_hi_obs"] - m0["v_lo_obs"])
                mc = shock_monte_carlo(r["v_kms"], max(r["v_err_kms"], 5.0), P.n0,
                                       P.n0_logerr, P.mc_samples, rng)
                for k, v in mc.items():
                    r[f"mc_{k}"] = v
        elif math.isfinite(lr.value):
            r["v_modes"] = []
            r["v_degenerate"] = False
            r["v_kms"] = float("nan")
            r["v_err_kms"] = float("nan")
            r["v_err_kms_obs_only"] = float("nan")
            r["grid_note"] = "ratio sin calibración fotométrica"
            r["velocity_source"] = "disabled_un_calibrated_ratio"

    clus = cluster_fronts(results, P.seed)
    v_all = np.array([finite(r.get("v_kms")) for r in results])
    v_med = float(np.nanmedian(v_all)) if np.isfinite(v_all).any() else float("nan")

    r_pc_used = float("nan")
    r_arcsec_used = float("nan")
    r_arcsec_err_used = float("nan")
    r_arcsec_boot_sd = float("nan")
    center_source = ""
    remnant_center = {"ra_deg": float("nan"), "dec_deg": float("nan")}
    is_snr_target = bool(find_literature(P.target_name) and find_literature(P.target_name).get("key") in {"veil","cas_a","tycho","kepler","sn1006","vela","ic443","w44"})
    if is_snr_target and math.isfinite(P.remnant_radius_pc):
        r_pc_used = float(P.remnant_radius_pc)
        center_source = "radio manual del usuario"
        # El usuario no proporciona σ aquí; no se inventa.
        r_arcsec_err_used = float("nan")
    elif is_snr_target:
        ra_c, dec_c = P.remnant_center_ra, P.remnant_center_dec
        if not math.isfinite(ra_c) or not math.isfinite(dec_c):
            ra_hint = dec_hint = None
            if im_ha.wcs is not None:
                try:
                    H_, W_ = im_ha.data.shape
                    ra_h, dec_h = im_ha.pixel_to_world(np.array([W_ / 2]), np.array([H_ / 2]))
                    if math.isfinite(ra_h[0]) and math.isfinite(dec_h[0]):
                        ra_hint, dec_hint = float(ra_h[0]), float(dec_h[0])
                except (ValueError, TypeError, IndexError) as exc:
                    LOG.debug("WCS hint centro: %s", exc)
            if P.offline:
                ra_s, dec_s, src = (None, None, "offline: centro remoto no consultado")
            else:
                ra_s, dec_s, src = resolve_object_center(P.target_name, ra_hint, dec_hint)
            if ra_s is not None and dec_s is not None:
                ra_c, dec_c, center_source = ra_s, dec_s, src
            else:
                center_source = f"no resuelto ({src})"
                man.warnings.append(f"Centro no resuelto: {src}")
        else:
            center_source = "RA/Dec manual"
        if math.isfinite(ra_c) and math.isfinite(dec_c):
            remnant_center = {"ra_deg": float(ra_c), "dec_deg": float(dec_c)}
            r_pc_used, r_arcsec_used = compute_remnant_radius_from_center(
                im_ha, results, ra_c, dec_c, d_pc)
    elif not is_snr_target:
        center_source = "no aplicado: el objetivo no está clasificado como SNR en la base local"

    ages = dynamical_ages(r_pc_used if math.isfinite(r_pc_used) else float("nan"), v_med)

    all_rows = sorted(results + rejected_ml + rejected_star + rejected_profile,
                      key=lambda r: (r.get("candidate_type") == "star", abs(r.get("id", 0))))
    status_counts = {k: sum(r.get("status") == k for r in all_rows)
                     for k in sorted(set(r.get("status") for r in all_rows))}
    units_used = set()
    for r in results:
        if math.isfinite(finite(r.get("offset_arcsec"))):
            units_used.add("arcsec")
        elif math.isfinite(finite(r.get("offset_px"))):
            units_used.add("px")

    n_profiles_shock = sum(
        1 for r in all_rows if r.get("candidate_type", "shock") != "star"
        and profile_key(r) in profiles)

    # Corte de calidad para las medianas titulares del resumen (ver quality_gated_median):
    # excluye detecciones marginales (snr_pix cercano al snr_min de entrada) de la cifra
    # que más se va a citar, sin perder esos candidatos del catálogo completo.
    min_snr_summary = P.snr_min * P.summary_snr_factor
    off_px_q = quality_gated_median(results, "offset_px", min_snr_summary)
    off_arc_q = quality_gated_median(results, "offset_arcsec", min_snr_summary)
    ratio_q = quality_gated_median(results, "ratio", min_snr_summary)
    for etiqueta, q in (("desfase (px)", off_px_q), ("cociente [O III]/Hα", ratio_q)):
        if q["n_total"] == 0:
            continue
        if q["fallback_to_all"]:
            man.warnings.append(
                f"Resumen de {etiqueta}: menos de {SUMMARY_MIN_N} candidatos con "
                f"snr_pix≥{min_snr_summary:.1f}; la mediana titular usa el catálogo completo "
                f"({q['n_total']} candidatos, incluye detecciones marginales de baja SNR).")
        else:
            frac_baja = 1.0 - q["n_used"] / max(q["n_total"], 1)
            if frac_baja > 0.3:
                man.warnings.append(
                    f"Resumen de {etiqueta}: {frac_baja * 100:.0f}% de los candidatos analizados "
                    f"tenían snr_pix<{min_snr_summary:.1f} y se excluyeron de la mediana titular "
                    f"({q['n_used']}/{q['n_total']} usados; siguen en el catálogo completo).")

    integrity_audit = system_integrity_audit(im_ha, im_o3, im_broadband, P.calibration, scale)
    summary = {
        "n_candidates": len(cands_all), "n_new_candidates": len(cands),
        "n_analyzed": len(results),
        "n_ok": sum(r.get("status") == "ok" for r in results),
        "n_ok_no_ratio": sum(r.get("status") == "ok_no_ratio" for r in results),
        "n_truncated": sum(bool(r.get("profile_truncated")) for r in results),
        "n_rejected_ml": len(rejected_ml),
        "n_rejected_star": len(rejected_star),
        "n_rejected_profile_selection": len(rejected_profile),
        "profile_selection": {"object": obj_cfg.get("canonical",P.target_name), "geometry": obj_cfg.get("geometry"),
                              "strategy": obj_cfg.get("selection"), "max_profiles": int(P.max_shock_profiles)},
        "n_stars_detected": int(len(srcs)) if (srcs is not None) else 0,
        "stellar_summary": stellar_summary(stellar_catalog),
        "n_stellar_highlights": len(stellar_highlights),
        "status_counts": status_counts,
        "offset_units": "arcsec" if "arcsec" in units_used else ("px" if "px" in units_used else "none"),
        "n_offset_measured": int(sum(
            math.isfinite(finite(r.get("offset_arcsec", float("nan"))))
            or math.isfinite(finite(r.get("offset_px", float("nan"))))
            for r in results)),
        "offset_px_median": off_px_q["median"],
        "offset_px_median_n_used": off_px_q["n_used"],
        "offset_px_median_n_total": off_px_q["n_total"],
        "offset_px_median_min_snr": off_px_q["min_snr_applied"],
        "offset_arcsec_median": off_arc_q["median"],
        "offset_arcsec_median_err_approx": off_arc_q["stderr_approx"],
        "offset_arcsec_median_n_used": off_arc_q["n_used"],
        "offset_arcsec_median_n_total": off_arc_q["n_total"],
        "ratio_median": ratio_q["median"],
        "ratio_median_err_approx": ratio_q["stderr_approx"],
        "ratio_median_n_used": ratio_q["n_used"],
        "ratio_median_n_total": ratio_q["n_total"],
        "class_counts": {k: sum(r.get("front_class") == k for r in results)
                         for k in set(r.get("front_class") for r in results)},
        "v_kms_median": v_med, "ages_yr": ages, "clustering": clus,
        "registration": dataclasses.asdict(reg) if reg else None,
        "ml": ml_report,
        "runtime_s": time.time() - t0,
        "pixel_scale_arcsec": scale,
        "distance_pc": d_pc, "distance_err_pc": float(P.distance_err_pc),
        "starless": bool(P.starless),
        "accumulate": bool(P.accumulate),
        "n_profiles_total": n_profiles_shock,
        "n_profiles_storage": len(profiles),
        "grid_name": grid.name if grid else None,
        "grid_manifest": {"name": grid.name, "approximate": grid.name == "heuristic_demo_grid"} if grid else None,
        "calibration": dataclasses.asdict(P.calibration),
        "spcc_calibration": spcc,
        "calibration_status": "calibrated_flux" if P.calibration.calibrated else "instrumental_only",
        "instrument": {
            "camera": P.camera_model,
            "profile_version": P.camera_profile_version,
            "sensor": "Sony IMX533",
            "format": "1 inch",
            "resolution_px": [3008,3008],
            "pixel_size_um": 3.76,
            "adc_bits": 14,
            "full_well_e": 50000,
            "qe_peak_nominal": 0.80,
            "note": "valores nominales del fabricante; no sustituyen una curva QE medida del sistema"
        },
        "lqef_broadband": broadband_context_diagnostics(im_broadband, im_ha, im_o3, im_ha_starless, im_o3_starless) if im_broadband is not None else {"state":"NO DISPONIBLE","reason":"No se proporcionó toma Optolong L-Quad Enhance"},
        "system_integrity_audit": integrity_audit,
        "scientific_scope": "multi-object astrophysical inference from user imaging",
        "oiii_filter": P.oiii_filter,
        "ha_filter": P.ha_filter,
        "profile_source": "starless_only",
        "stellar_source": "normal_images_only",
        "gaia_wcs_check": gaia_wcs_check,
        "wcs_source_ha": im_ha.wcs_source,
        "wcs_source_oiii": im_o3.wcs_source,
        "has_wcs": im_ha.wcs is not None,
        "target_name": P.target_name,
        "remnant_radius_pc": r_pc_used if math.isfinite(r_pc_used) else None,
        "remnant_radius_arcsec": r_arcsec_used if math.isfinite(r_arcsec_used) else None,
        "remnant_radius_arcsec_err": r_arcsec_err_used if math.isfinite(r_arcsec_err_used) else None,
        "remnant_radius_arcsec_bootstrap_sd": r_arcsec_boot_sd if math.isfinite(r_arcsec_boot_sd) else None,
        "remnant_center": remnant_center,
        "remnant_center_source": center_source,
    }

    # v32: capa de descubrimiento IA. No altera el resultado físico determinista; sólo prioriza
    # candidatos según una distribución aprendida de observaciones reales.
    ai_payload = {"state":"DESACTIVADA"}
    if getattr(P,"ai_enabled",True):
        try:
            ai_payload = discovery_ai_from_rows(results, getattr(P,"ai_model_path",""), getattr(P,"ai_training_path",""),
                                               seed=P.seed, min_rows=getattr(P,"ai_min_training_rows",getattr(P,"ai_min_rows",80)),
                                               contamination=getattr(P,"ai_anomaly_contamination",0.02))
            for rr, airow in zip(results, ai_payload.get("candidates",[])):
                rr["novelty_score"]=airow.get("novelty_score")
                rr["novelty_state"]=airow.get("novelty_state")
                rr["ai_class"]=airow.get("ai_class")
                rr["ai_class_probability"]=airow.get("ai_class_probability")
            summary["discovery_ai"] = {k:v for k,v in ai_payload.items() if k!="candidates"}
        except Exception as exc:
            ai_payload={"state":"NO DISPONIBLE","reason":str(exc)}
            summary["discovery_ai"]=ai_payload

    # v34: IA visual que mira directamente patches de las imágenes starless.
    visual_ai_payload = {"state":"DESACTIVADA"}
    if getattr(P,"ai_vision_enabled",False):
        try:
            visual_ai_payload = discovery_visual_ai(
                results, im_ha_starless, im_o3_starless, im_broadband,
                model_path=getattr(P,"ai_vision_model_path",""),
                training_dir=getattr(P,"ai_vision_training_dir",""),
                seed=P.seed, epochs=getattr(P,"ai_vision_epochs",12), batch_size=getattr(P,"ai_vision_batch_size",8))
            summary["discovery_visual_ai"] = visual_ai_payload
        except Exception as exc:
            visual_ai_payload={"state":"NO DISPONIBLE","reason":str(exc)}; summary["discovery_visual_ai"]=visual_ai_payload

    # v36: análisis físico/estadístico multiparámetro independiente de la IA.
    try:
        visual_map={str(r.get("id")): finite(r.get("visual_novelty_score"),np.nan) for r in results}
        phys_anom=physical_anomaly_engine(results,target_name=P.target_name,visual_scores=visual_map)
        summary["physical_anomalies"]={k:v for k,v in phys_anom.items() if k!="rows"}
        byid={str(x.get("row_id")):x for x in phys_anom.get("rows",[])}
        for rr in results:
            ar=byid.get(str(rr.get("id")))
            if ar:
                rr["physical_anomaly_score"]=ar.get("anomaly_score")
                rr["physical_anomaly_state"]=ar.get("state")
                rr["physical_anomalies"]=ar.get("anomalies",[])
    except Exception as exc:
        summary["physical_anomalies"]={"state":"NO DISPONIBLE","reason":f"{type(exc).__name__}: {exc}"}

    lit_cmp = build_literature_comparison(summary, P.target_name, user_distance_pc=d_pc)
    if not P.calibration.calibrated:
        lit_cmp = dict(lit_cmp)
        lit_cmp["rows"] = [rr for rr in lit_cmp.get("rows", [])
                           if rr.get("quantity") != "V_shock mediana"]
        lit_cmp["verdict"] = "Comparación parcial: velocidad no inferida sin calibración."
    summary["literature_comparison"] = lit_cmp

    LOG.info("v33: caracterización estelar exclusivamente desde imágenes normales")
    stellar_profiles = build_stellar_profiles(
        im_ha, im_o3, bkg_ha, bkg_o3,
        stellar_catalog, max_profiles=300)
    summary["stellar_profiles"] = len(stellar_profiles)

    # ------------------------------------------------------------------
    # Productos cuantitativos derivados de la pareja registrada.
    # ------------------------------------------------------------------
    quality_ha = build_quality_mask(im_ha)
    # La máscara de [O III] incluye explícitamente bordes invalidados por el remuestreo.
    im_o3_registered = replace(im_o3, data=o3_reg)
    quality_o3 = build_quality_mask(im_o3_registered)
    variance_ha, variance_method_ha = build_variance_map(im_ha, bkg_ha)
    variance_o3, variance_method_o3 = build_variance_map(im_o3_registered, bkg_o3)
    # v30: all quantitative nebular products are derived from the strict starless pair.
    quality_ha_profile = build_quality_mask(im_ha_starless)
    quality_o3_profile = build_quality_mask(im_o3_starless)
    variance_ha_profile, variance_method_ha_profile = build_variance_map(im_ha_starless, bkg_ha_n)
    variance_o3_profile, variance_method_o3_profile = build_variance_map(im_o3_starless, bkg_o3_n)
    products = quantitative_ratio_products(
        im_ha_starless.data, im_o3_starless.data, bkg_ha_n, bkg_o3_n, [], filament_response_map,
        P.calibration, quality_ha_profile, quality_o3_profile, variance_ha_profile, variance_o3_profile)
    man.background["variance_ha"] = variance_method_ha
    man.background["variance_oiii"] = variance_method_o3
    product_files = []
    if P.export_products:
        try:
            product_files = export_quantitative_products(out, products, wcs=im_ha.wcs)
        except Exception as exc:
            man.warnings.append(f"Exportación de productos FITS omitida: {type(exc).__name__}: {exc}")
    summary["product_files"] = product_files
    summary["map_interpretation"] = (
        "Proxy de régimen de excitación/enfriamiento: log10(H-alpha/[O III]); "
        "no es temperatura, densidad, tiempo de enfriamiento ni velocidad de choque.")

    # ------------------------------------------------------------------
    # Manifiesto reproducible y payload final.
    # ------------------------------------------------------------------
    man.filters = {
        "oiii_filter": P.oiii_filter, "ha_filter": P.ha_filter,
        "filter_curve_oiii": P.filter_curve_oiii, "filter_curve_ha": P.filter_curve_ha}
    man.calibration = dataclasses.asdict(P.calibration)
    man.registration = dataclasses.asdict(reg) if reg else {}
    man.background = {
        "box": P.bkg_box,
        "method": "photutils.Background2D" if HAS_PHOTUTILS and Background2D is not None else "robust_tile_fallback"}
    man.detection = {
        "stellar_sources": int(len(srcs)),
        "ridge_candidates": int(len(cands_all)),
        "star_exclusion_radius_px": max(8.0, P.star_candidate_exclusion_fwhm * P.fwhm_px)}
    flags = []
    if not P.calibration.calibrated:
        flags.append("instrumental_or_relative_ratio")
    if P.offline:
        flags.append("offline_no_remote_catalogues")
    if im_ha.wcs is None:
        flags.append("no_celestial_wcs")
    man.quality_flags = list(dict.fromkeys(flags))
    man.profiles = {
        "shock_profiles": int(len(profiles)),
        "stellar_profiles": int(len(stellar_profiles)),
        "max_shock_profiles": int(P.max_shock_profiles),
        "max_star_profiles": int(P.max_star_profiles)}
    man.grid = {
        "name": grid.name if grid else None,
        "approximate": bool(grid is not None and grid.name == "heuristic_demo_grid")}
    if grid is not None and P.grid_path and Path(P.grid_path).is_file():
        try:
            man.grid.update({"source_file": str(Path(P.grid_path).resolve()), "sha256": sha256_file(P.grid_path)})
        except OSError as exc:
            man.warnings.append(f"No se pudo registrar hash de grilla: {exc}")

    payload = {
        "manifest": manifest_dict(man),
        "summary": summary,
        "candidates": all_rows,
        "profiles": profiles,
        "stars": stellar_catalog,
        "stellar_profiles": stellar_profiles,
        "stellar_highlights": stellar_highlights,
        "product_interpretation": summary["map_interpretation"],
        "inputs": {
            "oiii": str(oiii_path), "ha": str(ha_path), "out_dir": str(out),
            "target": P.target_name, "light": P.light_path,
            "oiii_filter": P.oiii_filter, "ha_filter": P.ha_filter}}

    # Hash de configuración y curvas: separados de los FITS de entrada.
    config_payload = json.dumps(json_sanitize(dataclasses.asdict(P)), sort_keys=True, ensure_ascii=False).encode("utf-8")
    man.parameters_sha256 = hashlib.sha256(config_payload).hexdigest()
    curve_hashes = {}
    for role, path in (("oiii", P.filter_curve_oiii), ("ha", P.filter_curve_ha)):
        if path:
            try:
                curve_hashes[role] = sha256_file(path)
            except Exception as exc:
                man.warnings.append(f"No se pudo calcular SHA256 de curva {role}: {exc}")
    man.filter_curve_sha256 = curve_hashes
    man.configuration_sha256 = analysis_signature(P, man)

    # Acumulación: fusiona candidatos sin permitir que el ID científico de una corrida
    # vuelva a colisionar con el de otra.
    if P.accumulate and (out / "catalog.json").is_file() and not P.starless:
        try:
            old_payload = json.load(open(out / "catalog.json", encoding="utf-8"))
            old_rows = old_payload.get("candidates") or []
            annotate_existing_catalog_stars(
                old_rows, srcs, max(8.0, P.star_candidate_exclusion_fwhm * P.fwhm_px))
            old_payload["candidates"] = old_rows
            atomic_json_dump(old_payload, out / "catalog.json")
        except Exception as exc:
            LOG.warning("No se pudo actualizar el catálogo acumulado: %s", exc)
    if P.accumulate and (out / "catalog.json").is_file():
        try:
            payload = merge_catalogs(out / "catalog.json", payload)
            LOG.info("Catálogo fusionado: %d candidatos totales", len(payload.get("candidates", [])))
        except Exception as exc:
            LOG.warning("Fusión de catálogos falló: %s", exc)

    payload["manifest"] = manifest_dict(man)
    atomic_json_dump(payload, out / "catalog.json")
    write_catalog_csv(payload["candidates"], out / "catalog.csv")
    if P.export_ecsv:
        write_catalog_ecsv(payload["candidates"], out / "catalog.ecsv")
    atomic_json_dump({"schema_version": SCHEMA_VERSION, "profiles": profiles,
                      "stellar_profiles": stellar_profiles}, out / "profiles.json")
    figure_files=[]
    if P.export_products:
        figure_files.extend(export_visual_products(out,payload,ha_image=im_ha.data,o3_image=o3_reg,dpi=P.output_png_dpi))
        rd=export_registration_diagnostic(out,im_ha.data,im_o3.data,o3_reg,reg,stars=stellar_catalog,dpi=P.output_png_dpi)
        if rd: figure_files.append(rd)
    summary["figure_files"]=figure_files
    if P.export_html:
        try:
            write_html_report(payload,out/"report.html",ha_image=im_ha.data,o3_image=o3_reg)
        except Exception as exc:
            man.warnings.append(f"HTML omitido: {type(exc).__name__}: {exc}")
    payload["manifest"]=manifest_dict(man)
    atomic_json_dump(payload,out/"catalog.json")
    LOG.info("Guardado %s (%.1f s): %s",out/"catalog.json",summary["runtime_s"],status_counts)
    report(1.0,"Análisis terminado")
    return payload


def manifest_dict(man:RunManifest):
    d=dataclasses.asdict(man)
    return {"software_version":d.get("software",__version__),"schema_version":d.get("schema_version",SCHEMA_VERSION),"created_utc":d.get("created_utc"),"python_version":d.get("python"),"platform":d.get("platform"),"dependencies":d.get("packages",{}),"random_seed":d.get("seed"),"input_files":d.get("inputs",{}),"input_sha256":{k:v.get("sha256") for k,v in d.get("inputs",{}).items() if isinstance(v,dict) and v.get("sha256")},"fits_metadata":d.get("fits_metadata",{}),"selected_hdu":{k:v.get("hdu") for k,v in d.get("fits_metadata",{}).items() if isinstance(v,dict)},"selected_cube_plane":{k:v.get("selected_plane") for k,v in d.get("fits_metadata",{}).items() if isinstance(v,dict) and v.get("selected_plane") is not None},"filters":d.get("filters",{}),"filter_curve_sha256":d.get("filter_curve_sha256",{}),"configuration_sha256":d.get("configuration_sha256") or (d.get("inputs",{}) or {}).get("configuration_sha256"),"calibration":d.get("calibration",{}),"registration":d.get("registration",{}),"background":d.get("background",{}),"detection":d.get("detection",{}),"profiles":d.get("profiles",{}),"grid":d.get("grid",{}),"warnings":d.get("warnings",[]),"quality_flags":d.get("quality_flags",[]),"parameters":d.get("parameters",{})}

def make_star_mask(shape, sources, fwhm_px=3.0, brightness_scale=True):
    """Construye máscara estelar aceptando tanto Nx3 como el catálogo dict de estrellas."""
    m=np.zeros(shape,bool)
    if sources is None: return m
    H,W=shape
    if isinstance(sources, (list, tuple)) and sources and isinstance(sources[0], dict):
        seq=((r.get("x_px"), r.get("y_px"), r.get("flux_adu", r.get("flux", r.get("peak_adu", r.get("peak", 1.0))))) for r in sources)
    else:
        seq=np.asarray(sources,float)
    for item in seq:
        try:
            x,y,flux=map(float,item)
        except (TypeError,ValueError):
            continue
        if not (math.isfinite(x) and math.isfinite(y)): continue
        if brightness_scale:
            rr=max(3.0, fwhm_px*(1.8+0.35*math.log10(max(abs(flux),1.0))))
        else: rr=max(3.0,3*fwhm_px)
        r=int(math.ceil(min(rr,max(H,W)/6)))
        yy,xx=np.ogrid[-r:r+1,-r:r+1]; disk=(xx*xx+yy*yy)<=rr*rr
        xi,yi=int(round(x)),int(round(y)); y0=max(0,yi-r); y1=min(H,yi+r+1); x0=max(0,xi-r); x1=min(W,xi+r+1)
        if x1<=x0 or y1<=y0: continue
        sub=disk[(y0-(yi-r)):(y1-(yi-r)),(x0-(xi-r)):(x1-(xi-r))]
        m[y0:y1,x0:x1] |= sub
    return m


def quantitative_ratio_products(ha_image,o3_image,bh,bo,stars,filament_response=None,cal=None,quality_ha=None,quality_o3=None,variance_ha=None,variance_o3=None):
    ha=np.asarray(ha_image,np.float32); o3=np.asarray(o3_image,np.float32)
    hs=ha-np.asarray(bh.bkg,np.float32); os=o3-np.asarray(bo.bkg,np.float32)
    star_mask=make_star_mask(hs.shape,stars,3.0)
    var_ha = np.asarray(variance_ha if variance_ha is not None else np.maximum(bh.rms**2,1e-12),np.float32)
    var_o3 = np.asarray(variance_o3 if variance_o3 is not None else np.maximum(bo.rms**2,1e-12),np.float32)
    sig_ha=np.sqrt(np.maximum(var_ha,1e-12)); sig_o3=np.sqrt(np.maximum(var_o3,1e-12))
    valid=(np.isfinite(hs)&np.isfinite(os)&(hs>0)&(os>0)&(hs>=2*sig_ha)&(os>=2*sig_o3)&(~star_mask))
    if quality_ha is not None: valid &= ~np.asarray(quality_ha,bool)
    if quality_o3 is not None: valid &= ~np.asarray(quality_o3,bool)
    coverage=np.isfinite(ha)&np.isfinite(o3)&(~np.isnan(ha))&(~np.isnan(o3))
    corr = 1.0; cfrac = 0.0
    if cal is not None:
        try:
            corr, cfrac = cal.ratio_correction()
        except Exception:
            corr, cfrac = 1.0, 0.0
    with np.errstate(divide="ignore",invalid="ignore"):
        raw_ratio=np.full(hs.shape,np.nan,np.float32); raw_ratio[valid]=os[valid]/hs[valid]
        ratio=np.full(hs.shape,np.nan,np.float32); ratio[valid]=corr*raw_ratio[valid]
        log=np.full(hs.shape,np.nan,np.float32); log[valid]=np.log10(ratio[valid])
        stat_err=np.full(hs.shape,np.nan,np.float32); stat_err[valid]=ratio[valid]*np.sqrt((sig_ha[valid]/hs[valid])**2+(sig_o3[valid]/os[valid])**2)
        err=np.full(hs.shape,np.nan,np.float32); err[valid]=ratio[valid]*np.sqrt((stat_err[valid]/np.maximum(ratio[valid],1e-30))**2 + cfrac**2)
        snr=np.full(hs.shape,np.nan,np.float32); snr[valid]=np.minimum(hs[valid]/np.maximum(sig_ha[valid],1e-12),os[valid]/np.maximum(sig_o3[valid],1e-12))
    cooling=np.full(hs.shape,np.nan,np.float32); cooling[valid]=-log[valid]
    return {"ratio_linear":ratio,"ratio_log10":log,"ratio_error":err,"ratio_snr":snr,
            "valid_mask":valid.astype(np.uint8),"coverage_mask":coverage.astype(np.uint8),
            "background_ha":np.asarray(bh.bkg,np.float32),"background_oiii":np.asarray(bo.bkg,np.float32),
            "rms_ha":np.asarray(bh.rms,np.float32),"rms_oiii":np.asarray(bo.rms,np.float32),
            "filament_response":np.asarray(filament_response,np.float32) if filament_response is not None else np.zeros_like(hs),
            "star_mask":star_mask.astype(np.uint8),"cooling_proxy_log10_ha_over_oiii":cooling}

def _write_product_fits(path,array,wcs=None,bunit="",product=""):
    if not HAS_ASTROPY: return False
    hdr=None
    try: hdr=wcs.to_header(relax=True) if wcs is not None else None
    except Exception: hdr=None
    hdu=_fits.PrimaryHDU(np.asarray(array),header=hdr)
    hdu.header["APS_VER"]=(__version__,"AstroPhysics Suite")
    hdu.header["APS_PROD"]=(product[:68],"AstroPhysics product")
    if bunit: hdu.header["BUNIT"]=(bunit[:68],"Units / interpretation")
    hdu.writeto(path,overwrite=True); return True

def export_quantitative_products(out_dir,products,wcs=None,prefix=""):
    out=Path(out_dir); out.mkdir(parents=True,exist_ok=True); written=[]
    names={"ratio_linear":"ratio_linear.fits","ratio_log10":"ratio_log10.fits","ratio_error":"ratio_error.fits","ratio_snr":"ratio_snr.fits",
           "valid_mask":"valid_mask.fits","coverage_mask":"coverage_mask.fits","background_ha":"background_ha.fits","background_oiii":"background_oiii.fits",
           "rms_ha":"rms_ha.fits","rms_oiii":"rms_oiii.fits","filament_response":"filament_response.fits","star_mask":"star_mask.fits",
           "cooling_proxy_log10_ha_over_oiii":"cooling_proxy.fits"}
    units={"ratio_linear":"relative","ratio_log10":"dex","ratio_error":"relative","ratio_snr":"1","cooling_proxy_log10_ha_over_oiii":"dex"}
    for key,fn in names.items():
        p=out/fn
        ok=_write_product_fits(p,products[key],wcs=wcs,bunit=units.get(key,"mask"),product=key)
        if ok: written.append(str(p))
    # Compatibilidad con el nombre solicitado en la especificación: validad_mask.fits
    if HAS_ASTROPY:
        alias=out/"validad_mask.fits"
        try:
            _write_product_fits(alias,products["valid_mask"],wcs=wcs,bunit="mask",product="valid_mask_alias")
            written.append(str(alias))
        except (OSError, ValueError, TypeError) as exc:
            LOG.warning("No se pudo escribir alias de producto %s: %s", alias, exc)
    atomic_json_dump({"files":written,"interpretation":"Ratios/masks are observational relative products unless calibration_status says calibrated_flux."},out/"products_manifest.json")
    return written

def _figure_png_bytes(fig,dpi=300):
    buf=io.BytesIO(); fig.savefig(buf,format="png",dpi=int(dpi),bbox_inches="tight"); return buf.getvalue()

def _state_css_class(state: str) -> str:
    """Maps scientific state labels to CSS classes defined in the HTML report."""
    s = (state or "").upper().strip()
    if s.startswith("OBSERVABLE"):
        return "obs"
    if s.startswith("PROXY"):
        return "proxy"
    if s.startswith("INFERENCIA"):
        return "inf"
    if s.startswith("RESULTADO CALIBRADO"):
        return "cal"
    if s.startswith("RESULTADO EXTRAPOLADO"):
        return "proxy"
    if s.startswith("NO DISPONIBLE"):
        return "na"
    return "na"


def write_html_report(payload,path,ha_image=None,o3_image=None):
    if not HAS_MPL: return None
    import base64, html as _html
    s=payload.get("summary",{}); parts=[]
    fig=Figure(figsize=(10,7)); _plot_map(fig,ha_image,o3_image,1,payload.get("candidates",[]),mode="ratio",star_sources=payload.get("stars")); parts.append(("Ratio [O III]/Hα",_figure_png_bytes(fig,200)))
    fig=Figure(figsize=(10,7)); _plot_map(fig,ha_image,o3_image,1,payload.get("candidates",[]),mode="cooling",star_sources=payload.get("stars")); parts.append(("Proxy Hα/[O III]",_figure_png_bytes(fig,200)))
    body=["<!doctype html><meta charset='utf-8'><title>AstroPhysics Suite report</title>",
          "<style>body{font-family:monospace;margin:20px;max-width:1200px}h1{color:#1a5276}h2{color:#2471a3;border-bottom:2px solid #d5dbdb;padding-bottom:5px}table{border-collapse:collapse;width:100%;margin:10px 0}th,td{border:1px solid #ccc;padding:4px 8px;text-align:left;font-size:13px}th{background:#eaf2f8}.warn{color:#e74c3c;font-weight:bold}.ok{color:#27ae60;font-weight:bold}.state{display:inline-block;padding:2px 6px;border-radius:3px;font-size:11px;font-weight:bold}.obs{background:#d5f5e3;color:#0e6655}.proxy{background:#fdebd0;color:#7e5109}.inf{background:#fadbd8;color:#922b21}.cal{background:#d4efdf;color:#196f3d}.na{background:#e8e8e8;color:#555}</style>",
          f"<h1>AstroPhysics Suite {__version__}</h1><pre>{_html.escape(json.dumps(json_sanitize(s),indent=2,ensure_ascii=False))}</pre>"]
    for title,data in parts: body.append(f"<h2>{_html.escape(title)}</h2><img style='max-width:100%' src='data:image/png;base64,{base64.b64encode(data).decode('ascii')}'>")
    
    # v29: Scientific consistency block
    sc = payload.get("scientific_consistency")
    if sc:
        body.append("<h2>Verificación de Consistencia Científica</h2>")
        body.append(f"<p><b>Estado:</b> {'<span class=\"ok\">PASS</span>' if sc.get('passed') else '<span class=\"warn\">FAIL</span>'}</p>")
        if sc.get("warnings"):
            body.append("<h3>Advertencias</h3><ul>")
            for w in sc["warnings"]:
                body.append(f"<li class=\"warn\">{_html.escape(str(w))}</li>")
            body.append("</ul>")
        if sc.get("errors"):
            body.append("<h3>Errores</h3><ul>")
            for e in sc["errors"]:
                body.append(f"<li class=\"warn\">{_html.escape(str(e))}</li>")
            body.append("</ul>")
        if sc.get("states"):
            body.append("<h3>Estados científicos por magnitud</h3><table><tr><th>Magnitud</th><th>Estado</th><th>Justificación</th></tr>")
            for k, v in sc["states"].items():
                state = v.get("state", "N/A")
                cls = _state_css_class(state)
                body.append(f"<tr><td>{_html.escape(k)}</td><td><span class=\"state {cls}\">{_html.escape(state)}</span></td><td>{_html.escape(v.get('justification', ''))}</td></tr>")
            body.append("</table>")
    
    # v29: QC summary block
    qc = payload.get("qc_summary")
    if qc:
        body.append("<h2>Quality Control Summary</h2>")
        body.append(f"<p><b>Nivel global:</b> {_html.escape(qc.get('overall_level', 'N/A'))}</p>")
        if qc.get("checks"):
            body.append("<table><tr><th>Check</th><th>Estado</th><th>Detalle</th></tr>")
            for chk in qc["checks"]:
                level = chk.get("level", "N/A")
                cls = "ok" if level == "PASS" else ("warn" if level in ("WARNING", "MEDIUM") else "")
                body.append(f"<tr><td>{_html.escape(chk.get('name',''))}</td><td class=\"{cls}\">{_html.escape(level)}</td><td>{_html.escape(chk.get('detail',''))}</td></tr>")
            body.append("</table>")
    
    # v29: Uncertainty budget block
    ub = payload.get("uncertainty_budget")
    if ub:
        body.append("<h2>Presupuesto de Incertidumbre</h2>")
        body.append("<table><tr><th>Componente</th><th>Valor</th><th>Estado</th></tr>")
        for b in ub:
            state = b.get("state", "N/A")
            cls = _state_css_class(state)
            body.append(f"<tr><td>{_html.escape(b.get('component',''))}</td><td>{b.get('value','—')}</td><td><span class=\"state {cls}\">{_html.escape(state)}</span></td></tr>")
        body.append("</table>")
    
    # v29: Anomalies block
    anomalies = payload.get("anomalies")
    if anomalies:
        body.append("<h2>Detección de Anomalías</h2>")
        body.append(f"<p>Total detectadas: {len(anomalies)}</p>")
        if anomalies:
            body.append("<table><tr><th>Tipo</th><th>Severidad</th><th>Descripción</th></tr>")
            for a in anomalies:
                body.append(f"<tr><td>{_html.escape(a.get('type',''))}</td><td class=\"warn\">{_html.escape(a.get('severity',''))}</td><td>{_html.escape(a.get('description',''))}</td></tr>")
            body.append("</table>")
        body.append("<p class=\"warn\">NOTA: Las anomalías no constituyen descubrimientos astronómicos.</p>")
    
    # v29: Provenance block
    prov = payload.get("provenance")
    if prov:
        body.append("<h2>Cadena de Provenance</h2>")
        body.append(f"<p><b>Versión software:</b> {_html.escape(prov.get('software_version',''))}</p>")
        body.append(f"<p><b>Config SHA256:</b> {_html.escape(prov.get('configuration_sha256','')[:32])}...</p>")
        if prov.get("pipeline_steps"):
            body.append("<table><tr><th>Paso</th><th>Duración (s)</th><th>Estado</th></tr>")
            for step in prov["pipeline_steps"]:
                body.append(f"<tr><td>{_html.escape(step.get('step',''))}</td><td>{step.get('duration_s','—')}</td><td>{_html.escape(step.get('status',''))}</td></tr>")
            body.append("</table>")
    
    # v29: Literature comparison block
    lit_comp = payload.get("literature_zscores") or payload.get("literature_comparison")
    if isinstance(lit_comp, dict):
        lit_comp = lit_comp.get("rows", [])
    if lit_comp:
        body.append("<h2>Comparación con Literatura (z-score)</h2>")
        body.append("<table><tr><th>Cantidad</th><th>Valor obs.</th><th>Valor lit.</th><th>z-score</th><th>Acuerdo</th></tr>")
        for c in lit_comp:
            agree = c.get("agreement", c.get("flag", "N/A"))
            cls = "ok" if "AGREE" in str(agree).upper() else ("warn" if "DISAGREE" in str(agree).upper() else "")
            body.append(f"<tr><td>{_html.escape(c.get('quantity',''))}</td><td>{c.get('observed_value','—')}</td><td>{c.get('literature_value','—')}</td><td>{c.get('z_score','—')}</td><td class=\"{cls}\">{_html.escape(agree)}</td></tr>")
        body.append("</table>")
    
    target=Path(path); target.parent.mkdir(parents=True,exist_ok=True)
    tmp=target.with_suffix(target.suffix+".tmp"); tmp.write_text("\n".join(body),encoding="utf-8")
    os.replace(tmp,target); return str(target)

CSV_COLUMNS = ["id", "status", "reason", "x", "y", "ra_deg", "dec_deg", "nx", "ny",
               "scale_px", "ridge_response", "anisotropy", "snr_pix", "p_viable", "keep_reason",
               "candidate_type", "source_distance_px",
               "profile_truncated", "profile_valid_ha", "profile_valid_o3",
               "peak_ha_px", "peak_ha_err_px", "peak_snr_ha", "peak_oiii_px", "peak_oiii_err_px",
               "peak_snr_oiii", "offset_px", "offset_err_stat_px", "offset_err_px",
               "offset_model_sys_px", "offset_centroid_px", "offset_centroid_err_px",
               "offset_arcsec", "offset_err_arcsec", "offset_pc", "offset_err_pc", "offset_units",
               "flux_oiii_adu", "flux_oiii_err_adu", "flux_ha_adu", "flux_ha_err_adu", "flux_method",
               "ratio", "ratio_err", "log_ratio", "log_ratio_err_stat", "log_ratio_err_sys",
               "log_ratio_err", "ratio_calibrated", "front_class", "front_class_reason",
               "v_kms", "v_err_kms_obs_only", "v_err_kms", "grid_sigma_obs_dex",
               "grid_sigma_model_dex", "v_degenerate", "cluster", "physical_anomaly_score", "physical_anomaly_state"]


def write_catalog_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            out_row = {}
            for k in CSV_COLUMNS:
                v = r.get(k)
                if isinstance(v, float) and not math.isfinite(v):
                    out_row[k] = ""
                else:
                    out_row[k] = v
            w.writerow(out_row)



def write_catalog_ecsv(rows,path):
    """Escribe ECSV UTF-8 de forma determinista y compatible con Windows.

    No delegamos la escritura a astropy.io.ascii porque en algunas versiones
    recientes el argumento ``encoding`` termina siendo reenviado al constructor
    del writer ECSV y provoca TypeError. El ECSV generado aquí es texto UTF-8
    estándar, legible por Astropy y por herramientas de texto/CSV.
    """
    p=Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    cols=CSV_COLUMNS if "CSV_COLUMNS" in globals() else sorted({k for r in rows for k in r})
    with p.open("w",encoding="utf-8",newline="") as fh:
        fh.write("# %ECSV 1.0\n# ---\n# datatype:\n")
        for c in cols:
            fh.write(f"# - {{name: {c}, datatype: string}}\n")
        w=csv.writer(fh); w.writerow(cols)
        for r in rows:
            w.writerow([json_sanitize(r.get(c)) for c in cols])
    return str(p)

# ====================================================================
# UTILIDADES DE IMAGEN
# ====================================================================
def _asinh_stretch(img, lo_pct=2.0, hi_pct=99.5, gain=12.0):
    a = np.asarray(img, np.float64)
    fin = a[np.isfinite(a)]
    if fin.size == 0:
        return np.zeros_like(a, dtype=np.float32)
    lo, hi = np.percentile(fin, [lo_pct, hi_pct])
    z = np.clip((a - lo) / max(hi - lo, 1e-12), 0, 1)
    return np.asarray(np.arcsinh(gain * z) / np.arcsinh(gain), np.float32)


def _prepare_line_map(ha_image,o3_image,mask_stars=True,smooth_px=1.0,snr_min=2.5,combined_floor_pct=30.0):
    if ha_image is None or o3_image is None:return None
    ha=np.asarray(ha_image,np.float32); o3=np.asarray(o3_image,np.float32)
    if ha.shape!=o3.shape or ha.ndim!=2:return None
    bh=estimate_background(ha,box=max(48,min(96,min(ha.shape)//5)))
    bo=estimate_background(o3,box=max(48,min(96,min(o3.shape)//5)))
    hs=ha-bh.bkg; os=o3-bo.bkg
    star_mask=np.zeros(hs.shape,bool)
    if mask_stars:
        src=detect_point_sources(ha,bh,fwhm_px=3.0,threshold_sigma=6.0,max_sources=3000)
        star_mask=make_star_mask(hs.shape,src,3.0)
        hs=hs.copy(); os=os.copy(); hs[star_mask]=np.nan; os[star_mask]=np.nan
    if smooth_px>0:
        # Smooth numerator/denominator consistently only for display; quantitative FITS products are not smoothed.
        hfill=np.nan_to_num(hs,nan=0.0); ofill=np.nan_to_num(os,nan=0.0)
        good=(np.isfinite(hs)&np.isfinite(os)).astype(np.float32)
        hsm=ndi.gaussian_filter(hfill,smooth_px); osm=ndi.gaussian_filter(ofill,smooth_px); gsm=np.maximum(ndi.gaussian_filter(good,smooth_px),1e-3)
        hs=hsm/gsm; os=osm/gsm
    sn_h=hs/np.maximum(bh.rms,1e-12); sn_o=os/np.maximum(bo.rms,1e-12)
    mask=np.isfinite(hs)&np.isfinite(os)&(sn_h>=float(snr_min))&(sn_o>=float(snr_min))&(hs>0)&(os>0)&(~star_mask)
    # Keep extended structures, not isolated noise speckles.
    mask=ndi.binary_opening(mask,iterations=1)
    mask=ndi.binary_closing(mask,iterations=2)
    lab,n=ndi.label(mask)
    if n:
        sizes=np.bincount(lab.ravel()); keep=np.flatnonzero(sizes>=max(16,int(0.00002*mask.size))); keep=keep[keep!=0]; mask=np.isin(lab,keep)
    return hs,os,bh,bo,mask

def _ratio_bounds(vals, default=1.5):
    vals=np.asarray(vals,float); vals=vals[np.isfinite(vals)]
    if vals.size<30:return -default,default
    lo,hi=np.percentile(vals,[3,97]); lim=max(abs(float(lo)),abs(float(hi)),0.4); return -min(lim,default),min(lim,default)

def _make_ratio_map(ha_image,o3_image):
    p=_prepare_line_map(ha_image,o3_image)
    if p is None:return None,None
    hs,os,bh,bo,mask=p; out=np.full(hs.shape,np.nan,np.float32)
    valid=mask&(hs>0)&(os>0)
    with np.errstate(divide="ignore",invalid="ignore"): out[valid]=np.log10(os[valid]/hs[valid])
    lo,hi=_ratio_bounds(out,1.6); out=np.clip(out,lo,hi); return out,valid

def _make_cooling_map(ha_image,o3_image):
    p=_prepare_line_map(ha_image,o3_image)
    if p is None:return None,None
    hs,os,bh,bo,mask=p; out=np.full(hs.shape,np.nan,np.float32)
    valid=mask&(hs>0)&(os>0)
    with np.errstate(divide="ignore",invalid="ignore"): out[valid]=np.log10(hs[valid]/os[valid])
    lo,hi=_ratio_bounds(out,1.6); out=np.clip(out,lo,hi); return out,valid


def _downsample_for_display(img, max_side=1024):
    f = int(max(1, math.ceil(max(img.shape) / max_side)))
    if f == 1:
        return np.asarray(img, np.float32), 1
    H, W = img.shape
    h, w = H // f, W // f
    a = np.asarray(img[:h * f, :w * f], np.float32).reshape(h, f, w, f)
    with np.errstate(invalid="ignore"):
        small = np.nanmean(np.nanmean(a, axis=3), axis=1)
    return small, f


def _make_rgb_ha_oiii(ha_image, o3_image):
    if ha_image is None and o3_image is None:
        return None
    h = ha_image.shape[0] if ha_image is not None else o3_image.shape[0]
    w = ha_image.shape[1] if ha_image is not None else o3_image.shape[1]
    rgb = np.zeros((h, w, 3), dtype=np.float32)
    ha_s = _asinh_stretch(ha_image) if ha_image is not None else np.zeros((h, w), np.float32)
    o3_s = _asinh_stretch(o3_image) if o3_image is not None else np.zeros((h, w), np.float32)
    if ha_s.shape != (h, w):
        ha_s = np.zeros((h, w), np.float32)
    if o3_s.shape != (h, w):
        o3_s = np.zeros((h, w), np.float32)
    rgb[..., 0] = np.clip(ha_s*1.10,0,1)
    rgb[..., 2] = np.clip(o3_s*1.05,0,1)
    rgb[..., 1] = np.clip(0.45*ha_s + 0.70*o3_s,0,1)
    return np.clip(rgb, 0, 1)


# ====================================================================
# PLOTS
# ====================================================================
def _draw_cutout(ax, image, row, factor, label, cut_px=60, marker=True):
    if image is None:
        ax.axis("off")
        ax.text(0.5, 0.5, f"{label}: sin imagen", ha="center", va="center",
                transform=ax.transAxes, fontsize=8, family="monospace")
        return
    f = max(1.0, float(factor))
    try:
        cx_full = float(row["x"]); cy_full = float(row["y"])
    except Exception:
        ax.axis("off"); return
    cx = cx_full / f; cy = cy_full / f
    r = cut_px / 2
    H, W = image.shape[:2]
    x0 = int(max(0, cx - r)); x1 = int(min(W, cx + r))
    y0 = int(max(0, cy - r)); y1 = int(min(H, cy + r))
    if x1 <= x0 or y1 <= y0:
        ax.axis("off"); return
    cut = np.asarray(image[y0:y1, x0:x1], np.float32)
    cut_s = _asinh_stretch(cut)
    ax.imshow(cut_s, origin="lower", cmap="gray", interpolation="nearest",
              extent=(x0, x1, y0, y1), aspect="equal")
    if marker:
        ax.plot([cx], [cy], "o", mfc="none", mec="cyan", ms=10, mew=1.2)
        nx = finite(row.get("nx"), 0.0); ny = finite(row.get("ny"), 0.0)
        if math.isfinite(nx) and math.isfinite(ny) and (abs(nx) + abs(ny) > 0):
            L = cut_px * 0.35
            ax.plot([cx - nx * L, cx + nx * L], [cy - ny * L, cy + ny * L],
                    "-", color="yellow", lw=1.0, alpha=0.9)
    ax.set_title(label, fontsize=8, family="monospace")
    ax.set_xticks([]); ax.set_yticks([])


def _draw_star_cutout(ax, image, star_row, factor, label, cut_px=60):
    if image is None:
        ax.axis("off")
        ax.text(0.5, 0.5, f"{label}: sin imagen", ha="center", va="center",
                transform=ax.transAxes, fontsize=8, family="monospace")
        return
    f = max(1.0, float(factor))
    cx_full = finite(star_row.get("x_px"), float("nan"))
    cy_full = finite(star_row.get("y_px"), float("nan"))
    if not (math.isfinite(cx_full) and math.isfinite(cy_full)):
        ax.axis("off"); return
    cx = cx_full / f; cy = cy_full / f
    r = cut_px / 2
    H, W = image.shape[:2]
    x0 = int(max(0, cx - r)); x1 = int(min(W, cx + r))
    y0 = int(max(0, cy - r)); y1 = int(min(H, cy + r))
    if x1 <= x0 or y1 <= y0:
        ax.axis("off"); return
    cut = np.asarray(image[y0:y1, x0:x1], np.float32)
    cut_s = _asinh_stretch(cut)
    ax.imshow(cut_s, origin="lower", cmap="gray", interpolation="nearest",
              extent=(x0, x1, y0, y1), aspect="equal")
    ax.plot([cx], [cy], "o", mfc="none", mec="cyan", ms=10, mew=1.2)
    ax.set_title(label, fontsize=8, family="monospace")
    ax.set_xticks([]); ax.set_yticks([])


def _plot_stellar_profile(fig, sp, ha_image=None, o3_image=None, factor=1):
    fig.clear()
    has_preview = (ha_image is not None or o3_image is not None) and \
                  math.isfinite(finite(sp.get("x_px"), float("nan"))) and \
                  math.isfinite(finite(sp.get("y_px"), float("nan")))
    if has_preview:
        gs = fig.add_gridspec(2, 2, height_ratios=[1.2, 1.0], hspace=0.45, wspace=0.15)
        ax_ha_prev = fig.add_subplot(gs[0, 0])
        ax_o3_prev = fig.add_subplot(gs[0, 1])
        ax = fig.add_subplot(gs[1, :])
        _draw_star_cutout(ax_ha_prev, ha_image, sp, factor, "Hα (preview)")
        _draw_star_cutout(ax_o3_prev, o3_image, sp, factor, "[O III] (preview)")
    else:
        ax = fig.add_subplot(111)
    t = np.asarray(sp.get("r_px") or [], float)
    ha = np.asarray(sp.get("ha") or [], float)
    o3 = np.asarray(sp.get("oiii") or [], float)
    ha_e = np.asarray(sp.get("ha_err") or [], float)
    o3_e = np.asarray(sp.get("oiii_err") or [], float)
    n = min(t.size, ha.size, o3.size)
    if n == 0:
        ax.text(0.5, 0.5, "Sin perfil estelar", ha="center", va="center",
                transform=ax.transAxes); ax.axis("off")
        fig.tight_layout(); return
    t, ha, o3 = t[:n], ha[:n], o3[:n]
    if ha_e.size != n:
        ha_e = np.zeros(n)
    else:
        ha_e = ha_e[:n]
    if o3_e.size != n:
        o3_e = np.zeros(n)
    else:
        o3_e = o3_e[:n]
    ax.fill_between(t, ha - ha_e, ha + ha_e, color="tab:red", alpha=0.2)
    ax.fill_between(t, o3 - o3_e, o3 + o3_e, color="tab:blue", alpha=0.2)
    ax.plot(t, ha, color="tab:red", lw=1.2, label="Hα")
    ax.plot(t, o3, color="tab:blue", lw=1.2, label="[O III]")
    ax.axvline(0, color="k", lw=0.5, alpha=0.4)
    ax.set_xlabel("radio (px)")
    ax.set_ylabel("ADU − fondo")
    ax.legend(fontsize=8, loc="upper right")
    title = str(sp.get("simbad_main_id") or sp.get("source_id") or "estrella")
    extra = f" · {sp.get('spectral_class_est','?')} {sp.get('luminosity_class_est','')}"
    interest = sp.get("interest", "")
    ax.set_title(title + extra + "\n" + interest, fontsize=9)
    fig.subplots_adjust(top=0.82,bottom=0.15,left=0.08,right=0.98)


def _plot_profiles(fig, payload, key, ha_image=None, o3_image=None, factor=1):
    fig.clear()
    prof = payload.get("profiles", {}).get(str(key))
    row = None
    for r in payload.get("candidates", []):
        if profile_key(r) == str(key):
            row = r
            break

    def _clean(arr):
        if arr is None:
            return np.array([])
        try:
            return np.array([finite(v) for v in arr], dtype=float)
        except Exception:
            return np.array([])

    if row is None:
        ax = fig.add_subplot(111); ax.axis("off")
        ax.text(0.5, 0.5, f"Sin candidato con clave {key}",
                ha="center", va="center", family="monospace", fontsize=10)
        return

    if prof is None:
        if ha_image is not None or o3_image is not None:
            gs = fig.add_gridspec(1, 2, wspace=0.15)
            ax_ha = fig.add_subplot(gs[0, 0]); ax_o3 = fig.add_subplot(gs[0, 1])
            _draw_cutout(ax_ha, ha_image, row, factor, f"Hα  {key}")
            _draw_cutout(ax_o3, o3_image, row, factor, f"[O III]  {key}")
            fig.suptitle(f"Candidato {key}: sin perfil guardado",
                         fontsize=10, family="monospace")
        else:
            ax = fig.add_subplot(111); ax.axis("off")
            ax.text(0.5, 0.5, f"Candidato {key}: sin perfil ni imagen",
                    ha="center", va="center", family="monospace")
        fig.tight_layout()
        return

    t = _clean(prof.get("t"))
    y_ha = _clean(prof.get("ha"))
    y_o3 = _clean(prof.get("oiii"))
    e_ha = _clean(prof.get("ha_err"))
    e_o3 = _clean(prof.get("oiii_err"))

    n = min([a.size for a in (t, y_ha, y_o3) if a.size > 0], default=0)
    if n:
        t, y_ha, y_o3 = t[:n], y_ha[:n], y_o3[:n]
        e_ha = e_ha[:n] if e_ha.size == n else np.zeros(n)
        e_o3 = e_o3[:n] if e_o3.size == n else np.zeros(n)
    has_data = (n > 0 and (np.isfinite(y_ha).any() or np.isfinite(y_o3).any()))
    has_preview = (ha_image is not None or o3_image is not None)

    if has_preview:
        gs = fig.add_gridspec(3, 2, height_ratios=[1.4, 1.0, 1.0],
                              hspace=0.55, wspace=0.15)
        ax_ha_prev = fig.add_subplot(gs[0, 0]); ax_o3_prev = fig.add_subplot(gs[0, 1])
        ax_ha = fig.add_subplot(gs[1, :]); ax_o3 = fig.add_subplot(gs[2, :])
        _draw_cutout(ax_ha_prev, ha_image, row, factor, "Hα (preview)")
        _draw_cutout(ax_o3_prev, o3_image, row, factor, "[O III] (preview)")
    else:
        ax_ha = fig.add_subplot(2, 1, 1); ax_o3 = fig.add_subplot(2, 1, 2)

    if not has_data:
        for ax in (ax_ha, ax_o3):
            ax.axis("off")
        ax_ha.text(0.5, 0.5, "Perfil sin datos válidos",
                   ha="center", va="center", transform=ax_ha.transAxes,
                   family="monospace", fontsize=10)
    else:
        for ax, y, e, key2, label, color in (
                (ax_ha, y_ha, e_ha, "ha", "Hα", "tab:red"),
                (ax_o3, y_o3, e_o3, "oiii", "[O III]", "tab:blue")):
            m = np.isfinite(y)
            if m.any():
                y_low = y - np.nan_to_num(e, nan=0.0)
                y_high = y + np.nan_to_num(e, nan=0.0)
                ax.fill_between(t, y_low, y_high, color=color, alpha=0.25,
                                where=m, interpolate=False, label="±1σ")
                ax.plot(t[m], y[m], color=color, lw=1.2, label=label)
            c = finite(row.get(f"peak_{key2}_px"))
            if math.isfinite(c):
                ax.axvline(c, color="k", lw=0.8, ls="--", label=f"centro {c:+.2f}")
            cc = finite(row.get(f"centroid_{key2}_px"))
            if math.isfinite(cc):
                ax.axvline(cc, color="gray", lw=0.8, ls=":", label=f"centroide {cc:+.2f}")
            ax.axvline(0, color="k", lw=0.5, alpha=0.4)
            ax.set_ylabel("ADU − fondo")
            ax.legend(fontsize=7, loc="upper right")
            try:
                ymin = float(np.nanmin(y - e)); ymax = float(np.nanmax(y + e))
                span = max(ymax - ymin, 1e-12)
                ax.set_ylim(ymin - 0.1 * span, ymax + 0.1 * span)
            except Exception:
                pass
        ax_o3.set_xlabel("t (px sobre la normal; + hacia fuera)")

    off = finite(row.get("offset_px"))
    oe = finite(row.get("offset_err_px"))
    ratio = finite(row.get("ratio"))
    title = (f"Candidato {key} @ ({finite(row.get('x')):.0f},{finite(row.get('y')):.0f})  "
             f"status={row.get('status')}  Δ={off:+.2f}±{oe:.2f} px")
    if math.isfinite(ratio):
        title += f"  R={ratio:.2f}"
    fig.suptitle(title, fontsize=9, family="monospace")
    fig.subplots_adjust(top=0.90,bottom=0.10,left=0.08,right=0.99,hspace=0.55)


def _plot_map(fig,ha_image,o3_image,factor,rows,mode="ratio",show_candidates=False,star_sources=None):
    fig.clear(); ax=fig.add_subplot(111)
    if mode=="ratio": arr,mask=_make_ratio_map(ha_image,o3_image) if ha_image is not None and o3_image is not None else (None,None); title="[O III]/Hα · log10 (proxy observacional)"; cmap_name="RdBu_r"; cbl="log10([O III]/Hα)"
    elif mode=="cooling": arr,mask=_make_cooling_map(ha_image,o3_image) if ha_image is not None and o3_image is not None else (None,None); title="Proxy de régimen de excitación/enfriamiento · log10(Hα/[O III])"; cmap_name="Spectral_r"; cbl="log10(Hα/[O III]) · + = Hα relativa"
    else:
        rgb=_make_rgb_ha_oiii(ha_image,o3_image) if (ha_image is not None or o3_image is not None) else None
        if rgb is None: ax.axis("off"); ax.text(0.5,0.5,"Sin imagen",ha="center",va="center",transform=ax.transAxes); return
        h,w=rgb.shape[:2]; ax.imshow(rgb,origin="lower",interpolation="bilinear",extent=(-0.5,w*factor-0.5,-0.5,h*factor-0.5),aspect="equal")
        ax.set_title("Composición Hα (rojo/naranja) + [O III] (cian/azul)"); ax.set_xlabel("x (px)"); ax.set_ylabel("y (px)");
        if show_candidates:_overlay_candidates(ax,rows)
        fig.tight_layout(); return
    if arr is None: ax.axis("off"); ax.text(0.5,0.5,"Mapa no calculable: señal insuficiente o sin par válido",ha="center",va="center",transform=ax.transAxes); fig.tight_layout(); return
    h,w=arr.shape; cmap=plt.get_cmap(cmap_name).with_extremes(bad=(0,0,0,0)); finite_vals=arr[np.isfinite(arr)]; vmin,vmax=_ratio_bounds(finite_vals,1.6)
    # Soft grayscale context, but never from raw values: asinh stretched.
    context=None
    try:
        context_img=np.maximum(np.asarray(ha_image,np.float32),0)+np.maximum(np.asarray(o3_image,np.float32),0)
        if star_sources is not None and len(star_sources):
            sm=make_star_mask(context_img.shape,star_sources,3.0)
            context_img=context_img.copy(); context_img[sm]=np.nan
        context=_asinh_stretch(context_img,1,99.7,8)
        if context.shape==arr.shape: ax.imshow(context,origin="lower",interpolation="bilinear",extent=(-0.5,w*factor-0.5,-0.5,h*factor-0.5),cmap="gray",vmin=0,vmax=1,alpha=0.18,aspect="equal")
    except (ValueError, TypeError, IndexError) as exc:
        LOG.debug("Contexto visual no disponible: %s", exc)
    im=ax.imshow(arr,origin="lower",interpolation="bilinear",extent=(-0.5,w*factor-0.5,-0.5,h*factor-0.5),cmap=cmap,vmin=vmin,vmax=vmax,aspect="equal",alpha=0.92)
    fig.colorbar(im,ax=ax,label=cbl,shrink=0.86)
    ax.set_title(title,fontsize=11); ax.set_xlabel("x (px)"); ax.set_ylabel("y (px)")
    ax.text(0.01,0.99,"Negro/transparente = inválido · suavizado solo visual · ratio físico requiere calibración trazable",transform=ax.transAxes,va="top",fontsize=7,bbox=dict(facecolor="white",alpha=0.7,edgecolor="none"))
    if show_candidates:_overlay_candidates(ax,rows)
    fig.tight_layout()


def _overlay_candidates(ax, rows):
    ok = [r for r in rows if str(r.get("status", "")).startswith("ok")
          and r.get("candidate_type", "shock") != "star"]
    rej = [r for r in rows if (not str(r.get("status", "")).startswith("ok"))
           and r.get("candidate_type", "shock") != "star"]
    if rej:
        ax.scatter([r["x"] for r in rej], [r["y"] for r in rej], s=14, marker="x",
                   c="0.5", lw=0.8, label=f"rechazados ({len(rej)})")
    if ok:
        ax.scatter([r["x"] for r in ok], [r["y"] for r in ok], s=18, marker="o",
                   facecolors="none", edgecolors="white", lw=0.7,
                   label=f"medidos ({len(ok)})")
    ax.legend(fontsize=8, loc="upper right")


def _plot_diagram(fig, rows, scale):
    fig.clear()
    ax = fig.add_subplot(111)
    key, ekey, unit = ("offset_arcsec", "offset_err_arcsec", "″") if scale else ("offset_px", "offset_err_px", "px")
    rows_ok = [r for r in rows if r.get("candidate_type", "shock") != "star"]
    classes = sorted(set(str(r.get("front_class")) for r in rows_ok
                         if math.isfinite(finite(r.get(key))) and math.isfinite(finite(r.get("log_ratio")))))
    n = 0
    for cl in classes:
        sel = [r for r in rows_ok if str(r.get("front_class")) == cl
               and math.isfinite(finite(r.get(key))) and math.isfinite(finite(r.get("log_ratio")))]
        if not sel:
            continue
        n += len(sel)
        ax.errorbar([finite(r[key]) for r in sel], [finite(r["log_ratio"]) for r in sel],
                    xerr=[finite(r.get(ekey), 0.0) for r in sel],
                    yerr=[finite(r.get("log_ratio_err"), 0.0) for r in sel],
                    fmt="o", ms=4, lw=0.6, alpha=0.8, label=f"{cl} ({len(sel)})")
    ax.axvline(0, color="k", lw=0.8)
    ax.set_xlabel(f"Δ [O III]−Hα ({unit})")
    ax.set_ylabel("log10 [O III]/Hα")
    ax.set_title(f"Diagnóstico morfológico (n={n})")
    if classes:
        ax.legend(fontsize=7)
    else:
        ax.text(0.5, 0.5, "Sin candidatos con desfase y cociente medidos",
                ha="center", va="center", transform=ax.transAxes)
    fig.tight_layout()


def _wrap_cell(text, width=22):
    return "\n".join(textwrap.wrap(str(text), width))


def _pdf_literature_page(pdf, summary):
    lit = summary.get("literature_comparison") or {}
    fig = Figure(figsize=(8.27, 11.69), facecolor="white")
    ax = fig.add_subplot(111); ax.axis("off")
    if not lit.get("found"):
        ax.text(0.5, 0.7,
                "COMPARACIÓN CON LITERATURA\n\nNo hay objeto identificado.\n"
                "Añade --target-name \"NGC 6960\" al comando.",
                ha="center", va="center", family="monospace", fontsize=11)
        pdf.savefig(fig); return
    ax.text(0.5, 0.965, "COMPARACIÓN CON LITERATURA", ha="center", va="top",
            fontsize=14, weight="bold", family="monospace")
    ax.text(0.5, 0.935, f"Objeto: {lit['target']}", ha="center", va="top",
            fontsize=10, style="italic", family="monospace")
    ax.text(0.5, 0.912,
            f"Canónico: {lit.get('canonical', '')} | Alias: '{lit.get('matched_alias', '')}'",
            ha="center", va="top", fontsize=8, style="italic", family="monospace")
    headers = ["Cantidad", "Observado", "Literatura", "Δ", "Fuente"]
    col_widths = [0.18, 0.17, 0.17, 0.16, 0.30]
    x_starts = [0.01]
    for w in col_widths[:-1]:
        x_starts.append(x_starts[-1] + w + 0.005)
    y = 0.875
    for x, h_, w in zip(x_starts, headers, col_widths):
        ax.add_patch(Rectangle((x, y - 0.008), w, 0.028, transform=ax.transAxes,
                                facecolor="#d0d0d0", edgecolor="black", linewidth=0.5))
        ax.text(x + 0.005, y + 0.005, h_, transform=ax.transAxes,
                fontsize=8, weight="bold", family="monospace", va="bottom")
    y -= 0.032
    for row in lit["rows"]:
        cells = [_wrap_cell(row["quantity"], 16), _wrap_cell(row["observed"], 16),
                 _wrap_cell(row["literature"], 16), _wrap_cell(row["delta"], 14),
                 _wrap_cell(row["source"], 28)]
        n_lines = max(len(c.split("\n")) for c in cells)
        row_h = max(0.024, 0.013 * n_lines + 0.012)
        for x, c, w in zip(x_starts, cells, col_widths):
            ax.add_patch(Rectangle((x, y - row_h + 0.008), w, row_h, transform=ax.transAxes,
                                    facecolor="white", edgecolor="#808080", linewidth=0.3))
            ax.text(x + 0.005, y - 0.002, c, transform=ax.transAxes,
                    fontsize=7, family="monospace", va="top", ha="left")
        y -= row_h + 0.003
    y -= 0.025
    verdict = lit.get("verdict", "")
    color = ("#006000" if "Consistente con" in verdict
             else "#800000" if "discrepancia" in verdict.lower() else "#404040")
    ax.text(0.02, y, f"Veredicto: {verdict}", va="top",
            fontsize=10, weight="bold", family="monospace", color=color)
    y -= 0.040
    notes = lit.get("notes", "")
    if notes:
        wrapped_notes = "\n".join(textwrap.wrap(f"Notas: {notes}", 100))
        ax.text(0.02, y, wrapped_notes, va="top", fontsize=8, family="monospace")
        y -= 0.015 * (wrapped_notes.count("\n") + 2)
    y -= 0.015
    warns = ("ADVERTENCIAS METODOLÓGICAS:\n"
             "• Los cocientes [O III]/Hα son INSTRUMENTALES si no se ha calibrado el flujo.\n"
             "• Las velocidades requieren una grilla de modelos de shock (MAPPINGS/3MdB).\n"
             "• Las edades dinámicas requieren el radio del remanente (o RA/Dec del centro).\n"
             "• Distancias: si el FITS no trae WCS, se usa la adoptada por el usuario.")
    ax.text(0.02, y, warns, va="top", fontsize=7.5, family="monospace")
    y -= 0.10
    refs = lit.get("references", {})
    ref_text = "REFERENCIAS:\n" + "\n".join(f"  • {k}: {v}" for k, v in list(refs.items())[:8])
    ax.text(0.02, y, ref_text, va="top", fontsize=6.5, family="monospace")
    pdf.savefig(fig)


def write_report_pdf(payload, path, ha_image=None, o3_image=None, max_profiles=12):
    if not HAS_MPL:
        return None
    s, rows = payload["summary"], payload["candidates"]
    scale = s.get("pixel_scale_arcsec")
    profiles = payload.get("profiles") or {}
    stellar_profiles = payload.get("stellar_profiles") or {}
    ha_small = o3_small = None
    factor_small = 1
    if ha_image is not None:
        ha_small, factor_small = _downsample_for_display(ha_image, 1024)
    if o3_image is not None:
        o3_small, _ = _downsample_for_display(o3_image, 1024)
    reg = s.get("registration") or {}
    cal = s.get("calibration") or {}
    lit = s.get("literature_comparison") or {}
    with PdfPages(str(path)) as pdf:
        fig = Figure(figsize=(8.27, 11.69), facecolor="white")
        ax = fig.add_subplot(111); ax.axis("off")
        calibrated = bool(s.get("calibration_status") == "calibrated_flux")
        lines = [
            f"AstroPhysics Suite {__version__} — Informe científico",
            f"Target: {s.get('target_name') or '(sin nombre)'}",
            f"Filtro OIII: {s.get('oiii_filter','—')}",
            f"Filtro Hα:  {s.get('ha_filter','—')}",
            f"Candidatos: {s.get('n_candidates')} · analizados: {s.get('n_analyzed')} · "
            f"estrellas detectadas: {s.get('n_stars_detected')} · estrellas excluidas: {s.get('n_rejected_star',0)}",
            f"Perfiles nebulosa: {s.get('n_profiles_total')} · perfiles estelares: {len(stellar_profiles)}",
            f"Escala: {scale:.5f} arcsec/px" if isinstance(scale, (int, float)) and math.isfinite(scale) else "Escala: no disponible",
            "",
            "REGISTRO O III ↔ Hα",
            f"Método: {reg.get('method','—')} · estrellas usadas: {reg.get('n_stars',0)}",
            f"Δx={reg.get('dx')} px · Δy={reg.get('dy')} px · RMS={reg.get('residual_rms_px')} px",
            "",
            "CALIBRACIÓN",
            f"Estado: {'FLUJO CALIBRADO' if calibrated else 'SOLO INSTRUMENTAL'}",
            f"Transmisión OIII/Ha: {cal.get('oiii_transmission',1)} / {cal.get('ha_transmission',1)}",
            f"NII/Hα={cal.get('nii_over_ha',0)} · E(B−V)={cal.get('ebv',0)}",
        ]
        ratio_med = finite(s.get('ratio_median'), float('nan'))
        if math.isfinite(ratio_med):
            lines.append(f"[O III]/Hα mediano: {ratio_med:.3f}")
        if calibrated and math.isfinite(finite(s.get('v_kms_median'), float('nan'))):
            lines.append(f"V_s mediana (grilla): {finite(s.get('v_kms_median')):.1f} km/s")
        else:
            lines.append("V_s: NO INFERIDA — falta calibración de flujo.")
        lines.append("")
        lines.append("EDADES DINÁMICAS")
        for k, v in (s.get("ages_yr") or {}).items():
            lines.append(f"  {k}: {v:.0f} yr" if isinstance(v, (int, float)) and math.isfinite(v) else f"  {k}: no calculada")
        lines += ["", "CONCLUSIÓN LITERATURA", lit.get('verdict', '')]
        if not calibrated:
            lines.append("Velocidad no comparada con literatura sin calibración.")
        wrapped = "\n".join(textwrap.wrap("\n".join(lines), 110))
        # Matplotlib PDF: keep scientific Unicode where supported, but force ASCII fallback
        # only if the selected font backend cannot encode a glyph.
        try:
            ax.text(0.04, 0.97, wrapped, va="top", family="monospace", fontsize=7.5)
        except UnicodeEncodeError:
            wrapped_ascii = wrapped.translate(str.maketrans({"Δ":"delta", "α":"alpha", "β":"beta", "μ":"mu", "−":"-", "±":"+/-", "°":"deg", "″":"arcsec", "₀":"0", "₁":"1", "₂":"2", "₃":"3", "₄":"4", "₅":"5", "₆":"6", "₇":"7", "₈":"8", "₉":"9"}))
            ax.text(0.04, 0.97, wrapped_ascii, va="top", family="monospace", fontsize=7.5)
        pdf.savefig(fig)
        _pdf_literature_page(pdf, s)
        # v29: QC / consistency / provenance page
        fig_qc = Figure(figsize=(8.27, 11.69), facecolor="white")
        ax_qc = fig_qc.add_subplot(111); ax_qc.axis("off")
        qc_lines = ["QUALITY CONTROL Y TRAZABILIDAD CIENTÍFICA", ""]
        sc = payload.get("scientific_consistency")
        if sc:
            qc_lines.append("CONSISTENCIA CIENTÍFICA")
            qc_lines.append(f"  Passed: {sc.get('passed', 'N/A')}")
            for w in (sc.get("warnings") or [])[:5]:
                qc_lines.append(f"  [WARN] {w}")
            for e in (sc.get("errors") or [])[:5]:
                qc_lines.append(f"  [ERR]  {e}")
            states = sc.get("states") or {}
            if states:
                qc_lines.append("")
                qc_lines.append("  Estados por magnitud:")
                for k, v in list(states.items())[:8]:
                    qc_lines.append(f"    {k}: {v.get('state','N/A')} - {v.get('justification','')[:60]}")
        qc_lines.append("")
        qc = payload.get("qc_summary")
        if qc:
            qc_lines.append("QC SUMMARY")
            qc_lines.append(f"  Nivel global: {qc.get('overall_level', 'N/A')}")
            for chk in (qc.get("checks") or [])[:8]:
                qc_lines.append(f"  [{chk.get('level','?')}] {chk.get('name','')}: {chk.get('detail','')[:60]}")
        qc_lines.append("")
        ub = payload.get("uncertainty_budget")
        if ub:
            qc_lines.append("PRESUPUESTO DE INCERTIDUMBRE")
            for b in ub[:8]:
                qc_lines.append(f"  {b.get('component','')}: {b.get('value','—')} [{b.get('state','N/A')}]")
        qc_lines.append("")
        anomalies = payload.get("anomalies")
        if anomalies:
            qc_lines.append(f"ANOMALÍAS DETECTADAS: {len(anomalies)}")
            for a in anomalies[:5]:
                qc_lines.append(f"  [{a.get('severity','?')}] {a.get('type','')}: {a.get('description','')[:60]}")
            qc_lines.append("  NOTA: Las anomalías no constituyen descubrimientos.")
        qc_lines.append("")
        prov = payload.get("provenance")
        if prov:
            qc_lines.append("PROVENANCE")
            qc_lines.append(f"  Software: {prov.get('software_version','')}")
            qc_lines.append(f"  Config SHA256: {str(prov.get('configuration_sha256',''))[:32]}...")
            for step in (prov.get("pipeline_steps") or [])[:8]:
                qc_lines.append(f"  {step.get('step','')}: {step.get('duration_s','—')}s [{step.get('status','')}]")
        wrapped_qc = "\n".join(textwrap.wrap("\n".join(qc_lines), 110))
        try:
            ax_qc.text(0.04, 0.97, wrapped_qc, va="top", family="monospace", fontsize=7.0)
        except UnicodeEncodeError:
            wrapped_qc_ascii = wrapped_qc.translate(str.maketrans({"Δ":"delta", "α":"alpha", "β":"beta", "μ":"mu", "−":"-", "±":"+/-", "°":"deg", "″":"arcsec"}))
            ax_qc.text(0.04, 0.97, wrapped_qc_ascii, va="top", family="monospace", fontsize=7.0)
        pdf.savefig(fig_qc)
        fig = Figure(figsize=(8.27, 6)); ax = fig.add_subplot(111); ax.axis("off")
        diag = ["DIAGNÓSTICO DE REGISTRO Y WCS",
                json.dumps({"registration": reg,
                            "gaia_wcs_check": s.get("gaia_wcs_check"),
                            "wcs_quality_ha": s.get("wcs_quality_ha"),
                            "wcs_quality_oiii": s.get("wcs_quality_oiii"),
                            "wcs_source_ha": s.get("wcs_source_ha"),
                            "wcs_source_oiii": s.get("wcs_source_oiii")},
                           indent=2, ensure_ascii=False),
                "",
                "USO DE ESTRELLAS",
                f"Detectadas: {s.get('n_stars_detected',0)} · cruzadas Gaia: "
                f"{(s.get('stellar_summary') or {}).get('n_matched',0)} · "
                f"perfiles PSF: {len(stellar_profiles)}"]
        ax.text(0.03, 0.97, "\n".join(diag), va="top", family="monospace", fontsize=8)
        pdf.savefig(fig)
        if ha_small is not None and o3_small is not None:
            try:
                ha_v=_asinh_stretch(ha_small,1,99.7,8); o3_v=_asinh_stretch(o3_small,1,99.7,8)
                fig=Figure(figsize=(11.69,4.8))
                for j,(ttl,img) in enumerate((("Hα",ha_v),("[O III] registrado",o3_v))):
                    aa=fig.add_subplot(1,2,j+1); aa.imshow(img,origin="lower",cmap="gray",vmin=0,vmax=1); aa.set_title(ttl,fontsize=9); aa.set_xticks([]); aa.set_yticks([])
                fig.suptitle(f"Resultado visual del registro · dx={finite(reg.get('dx')):+.3f} px, dy={finite(reg.get('dy')):+.3f} px",fontsize=10)
                pdf.savefig(fig)
            except Exception as exc:
                LOG.warning("Página visual de registro omitida: %s",exc)
        fig = Figure(figsize=(8.27, 6)); _plot_diagram(fig, rows, scale); pdf.savefig(fig)
        if ha_small is not None and o3_small is not None:
            try:
                dx = float(reg.get("dx", 0) or 0); dy = float(reg.get("dy", 0) or 0)
                if abs(dx) > 0 or abs(dy) > 0:
                    o3_small = ndi.shift(o3_small, shift=(dy/factor_small, dx/factor_small),
                                        order=1, mode="nearest", prefilter=False)
            except Exception:
                pass
            for mode in ("ratio", "cooling", "rgb"):
                fig = Figure(figsize=(11.69, 8.27))
                _plot_map(fig, ha_small, o3_small, factor_small, rows, mode=mode, star_sources=payload.get("stars"))
                pdf.savefig(fig)
        good = [r for r in rows if r.get("candidate_type", "shock") != "star"
                and profile_key(r) in profiles]
        good.sort(key=lambda r: -finite(r.get("peak_snr_ha"), 0.0))
        for r in good[:max_profiles]:
            fig = Figure(figsize=(8.27, 8.5))
            _plot_profiles(fig, payload, profile_key(r),
                           ha_image=ha_small, o3_image=o3_small, factor=factor_small)
            pdf.savefig(fig)
        for key, sp in list(stellar_profiles.items())[:min(8, len(stellar_profiles))]:
            fig = Figure(figsize=(8.27, 6.5))
            _plot_stellar_profile(fig, sp, ha_image=ha_small, o3_image=o3_small,
                                  factor=factor_small)
            pdf.savefig(fig)
    return str(path)


# ====================================================================
# EXPORTACIÓN VISUAL
# ====================================================================
def export_visual_products(out_dir, payload, ha_image=None, o3_image=None, dpi=300):
    """Exporta PNG de alta resolución de los productos visuales principales."""
    if not HAS_MPL or ha_image is None or o3_image is None:
        return []
    out=Path(out_dir); out.mkdir(parents=True,exist_ok=True); written=[]
    rows=payload.get("candidates",[]); stars=payload.get("stars") or []
    for mode,name in (("ratio","ratio_map.png"),("cooling","cooling_proxy.png"),("rgb","ha_oiii_rgb.png")):
        try:
            fig=Figure(figsize=(11.69,8.27))
            _plot_map(fig,ha_image,o3_image,1,rows,mode=mode,show_candidates=(mode=="rgb"),star_sources=stars)
            path=out/name; fig.savefig(path,dpi=int(dpi),bbox_inches="tight"); written.append(str(path))
        except Exception as exc:
            LOG.warning("PNG %s omitido: %s",mode,exc)
    return written


def export_registration_diagnostic(out_dir, ha_image, o3_before, o3_after, reg, stars=None, dpi=300):
    if not HAS_MPL or ha_image is None or o3_before is None or o3_after is None:
        return None
    try:
        out=Path(out_dir); out.mkdir(parents=True,exist_ok=True)
        ha=_asinh_stretch(ha_image,1,99.7,8); before=_asinh_stretch(o3_before,1,99.7,8); after=_asinh_stretch(o3_after,1,99.7,8)
        residual=np.asarray(ha,dtype=np.float32)-np.asarray(after,dtype=np.float32)
        fig=Figure(figsize=(12,4))
        titles=["Hα", "[O III] antes", "[O III] registrado · residuo Hα−[O III]"]
        for j,(title,img) in enumerate(zip(titles,(ha,before,residual))):
            ax=fig.add_subplot(1,3,j+1)
            if j<2: ax.imshow(img,origin="lower",cmap="gray",vmin=0,vmax=1)
            else:
                lim=float(np.nanpercentile(np.abs(img),98)) if np.isfinite(img).any() else 1.0
                ax.imshow(img,origin="lower",cmap="RdBu_r",vmin=-max(lim,1e-6),vmax=max(lim,1e-6))
            ax.set_title(title,fontsize=9); ax.set_xticks([]); ax.set_yticks([])
        fig.suptitle(f"Registro: dx={reg.dx:+.3f} px, dy={reg.dy:+.3f} px · desplazar [O III] para alinearla con Hα",fontsize=10)
        path=out/"registration_diagnostic.png"; fig.savefig(path,dpi=int(dpi),bbox_inches="tight"); return str(path)
    except Exception as exc:
        LOG.warning("Diagnóstico de registro PNG omitido: %s",exc); return None


# ====================================================================
# AUTO-PAIR
# ====================================================================
def auto_pair_directory(directory):
    """Detecta un par normal Hα/OIII de forma robusta, sin confundir starless.
    Busca recursivamente y puntúa por FILTER + nombre + ausencia de "starless".
    Devuelve (oiii, ha).
    """
    import re
    root=Path(directory)
    files=sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in (".fits",".fit",".fts",".fz"))
    re_o3=re.compile(r"(^|[^a-z0-9])(oiii|o\s*iii|o3|o_iii|o-iii|oxygen[_ -]?iii|5007)([^a-z0-9]|$)",re.I)
    re_ha=re.compile(r"(^|[^a-z0-9])(ha|h\s*alpha|halpha|h_alpha|h-alpha|halfa|6563)([^a-z0-9]|$)",re.I)
    def score(p, kind):
        low=p.stem.lower().replace(" ","_").replace("-","_")
        if "starless" in low or "star_less" in low:
            return -10_000
        filt=""
        if HAS_ASTROPY:
            try: filt=str(_fits.getheader(str(p), memmap=False).get("FILTER", "")).lower()
            except Exception: filt=""
        sc=0
        if kind=="o3":
            if "oiii" in filt or "o3" in filt or "5007" in filt: sc+=300
            if re_o3.search(low): sc+=220
        else:
            if "ha" in filt or "h-alpha" in filt or "halpha" in filt or "6563" in filt: sc+=300
            if re_ha.search(low): sc+=220
        if "denoise" in low: sc+=10
        if "stars" in low: sc+=20
        return sc
    o3=max((p for p in files if score(p,"o3")>-1000), key=lambda p:score(p,"o3"), default=None)
    ha=max((p for p in files if score(p,"ha")>-1000), key=lambda p:score(p,"ha"), default=None)
    return (str(o3) if o3 else None, str(ha) if ha else None)


def read_fits_exptime(path):
    """Lee EXPTIME sin seleccionar silenciosamente un plano de un cubo."""
    path = str(path)
    if HAS_ASTROPY:
        with _fits.open(path, memmap=True, lazy_load_hdus=True) as hdul:
            for h in hdul:
                if getattr(h, "is_image", False) and h.header.get("EXPTIME") is not None:
                    v = finite(h.header.get("EXPTIME"), float("nan"))
                    return v if math.isfinite(v) and v > 0 else 1.0
            return 1.0
    try:
        _, header = _read_primary_fits_minimal(path)
        v = finite(header.get("EXPTIME"), float("nan"))
        return v if math.isfinite(v) and v > 0 else 1.0
    except Exception:
        return 1.0


# ====================================================================
# GUI
# ====================================================================
class _QueueLogHandler(logging.Handler):
    def __init__(self, q):
        super().__init__(level=logging.INFO)
        self.q = q
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
    def emit(self, record):
        try:
            self.q.put(("log", self.format(record)))
        except Exception:
            pass


def launch_gui_legacy(oiii=None, ha=None, _test_hook=None):
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
        from tkinter.scrolledtext import ScrolledText
    except Exception as exc:
        raise SystemExit(f"Tkinter no disponible ({exc})")
    import queue
    import threading
    import traceback

    tk_canvas_cls = None
    if HAS_MPL:
        try:
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg as tk_canvas_cls
        except Exception:
            tk_canvas_cls = None

    class App:
        TABLE_COLS = ["id", "status", "x", "y", "candidate_type", "offset_px",
                      "offset_err_px", "offset_arcsec", "ratio", "log_ratio",
                      "log_ratio_err", "front_class", "v_kms", "novelty_score",
                      "novelty_state", "ai_class", "ai_class_probability", "reason"]

        def __init__(self, root):
            self.root = root
            root.title(f"AstroPhysics Suite {__version__} — [O III]/Hα")
            root.geometry("1550x980")
            self.q = queue.Queue()
            self.cancel = threading.Event()
            self.worker = None
            self.payload = None
            self.image = None
            self.image_o3 = None
            self.image_starless = None
            self.image_o3_starless = None
            self.image_factor = 1
            self.profile_keys = []
            self.profile_pos = 0
            self._tree_rows = {}
            default_workers = max(1, min(4, (os.cpu_count() or 2) - 1))
            self.vars = {
                "oiii": tk.StringVar(value=oiii or ""),
                "ha": tk.StringVar(value=ha or ""),
                "broadband": tk.StringVar(value=""),
                "science_ha": tk.StringVar(value=""),
                "science_oiii": tk.StringVar(value=""),
                "science_broadband": tk.StringVar(value=""),
                "out": tk.StringVar(value=str(Path.cwd() / "gui_run")),
                "light": tk.StringVar(value=""),
                "grid": tk.StringVar(value=""),
                "target_name": tk.StringVar(value=""),
                "pixel_scale": tk.StringVar(value=""),
                "distance": tk.StringVar(value="725"),
                "n0": tk.StringVar(value="6.0"),
                "snr": tk.StringVar(value="4.0"),
                "maxc": tk.StringVar(value="2000"),
                "mins": tk.StringVar(value="8"),
                "workers": tk.StringVar(value=str(default_workers)),
                "starless": tk.BooleanVar(value=False),
                "register_stars": tk.BooleanVar(value=True),
                "register_phase": tk.BooleanVar(value=False),
                "processes": tk.BooleanVar(value=True),
                "offline": tk.BooleanVar(value=False),
        "discovery_snr": tk.StringVar(value="5"),
        "discovery_max": tk.StringVar(value="2000"),
                "accumulate": tk.BooleanVar(value=True),
                "cal_nii_ha": tk.StringVar(value="0.0"),
                "cal_ebv": tk.StringVar(value="0.0"),
                "cal_ebv_err": tk.StringVar(value="0.0"),
                "cal_frac_err": tk.StringVar(value="0.0"),
                "oiii_filter": tk.StringVar(value=FILTER_DEFAULT),
                "ha_filter": tk.StringVar(value=FILTER_DEFAULT),
                "oiii_curve": tk.StringVar(value=""),
                "ha_curve": tk.StringVar(value=""),
                "photometric_calibrated": tk.BooleanVar(value=False),
                "oiii_zp_factor": tk.StringVar(value="1.0"),
                "ha_zp_factor": tk.StringVar(value="1.0"),
                "r_v": tk.StringVar(value="3.1"),
                "zeropoint_source": tk.StringVar(value=""),
                "zeropoint_error_mag": tk.StringVar(value=""),
                "calibration_id": tk.StringVar(value=""),
                "profile_mode": tk.StringVar(value="Nebulosa / frentes"),
                "oiii_starless": tk.StringVar(value=""),
                "ha_starless":   tk.StringVar(value=""),
                "oiii_stars":    tk.StringVar(value=""),
                "ha_stars":      tk.StringVar(value=""),
                "bias_oiii": tk.StringVar(value=""),
                "bias_ha": tk.StringVar(value=""),
                "dark_oiii": tk.StringVar(value=""),
                "dark_ha": tk.StringVar(value=""),
                "flat_oiii": tk.StringVar(value=""),
                "flat_ha": tk.StringVar(value=""),
                "filament_strategy": tk.StringVar(value="Hessian multiescala"),
                "oiii_plane": tk.StringVar(value=""),
                "ha_plane": tk.StringVar(value=""),
                "ai_model": tk.StringVar(value=str(Path.cwd() / "astrodiscovery_v33.pkl")),
                "ai_training": tk.StringVar(value=""),
                "ai_min_rows": tk.StringVar(value="80"),
                "ai_contamination": tk.StringVar(value="0.02"),
                "ai_vision_model": tk.StringVar(value=str(Path.cwd() / "astrovision_v34.pt")),
                "ai_vision_training": tk.StringVar(value=""),
                "ai_vision_epochs": tk.StringVar(value="12"),
            }
            self.ai_session = None
            self._build()
            self._log_handler = _QueueLogHandler(self.q)
            root_log = logging.getLogger()
            if root_log.level > logging.INFO or root_log.level == logging.NOTSET:
                root_log.setLevel(logging.INFO)
            root_log.addHandler(self._log_handler)
            root.after(100, self._poll)
            root.protocol("WM_DELETE_WINDOW", self._close)

        def _build(self):
            top = ttk.Frame(self.root, padding=6); top.pack(fill="x")
            r = 0
            for key, label in (("oiii", "NORMAL · FITS [O III]"), ("ha", "NORMAL · FITS Hα"),
                               ("broadband", "BANDA ANCHA · FITS Optolong L-Quad Enhance (opcional)"),
                               ("out", "Carpeta de salida"),
                               ("grid", "Grilla física (opcional; necesaria para inferencias de modelo)")):
                ttk.Label(top, text=label, width=26).grid(row=r, column=0, sticky="w")
                ttk.Entry(top, textvariable=self.vars[key], width=70).grid(row=r, column=1, sticky="we", padx=4)
                ttk.Button(top, text="…", width=3, command=lambda k=key: self._pick(k)).grid(row=r, column=2)
                r += 1
            ttk.Button(top, text="Directorio con el par…", command=self._pick_dir).grid(row=0, column=3, padx=6)
            sci = ttk.LabelFrame(top, text="MAPAS CIENTÍFICOS APILADOS · sin metadata obligatoria · píxel a píxel", padding=4)
            sci.grid(row=r, column=0, columnspan=4, sticky="we", pady=4)
            for key, label in (("science_ha", "Hα apilada"), ("science_oiii", "OIII apilada"), ("science_broadband", "Banda ancha/RGB (opcional)")):
                ttk.Label(sci, text=label).pack(side="left", padx=(5,2))
                ttk.Entry(sci, textvariable=self.vars[key], width=30).pack(side="left", padx=3)
                ttk.Button(sci, text="...", width=3, command=lambda k=key: self._pick(k)).pack(side="left", padx=(0,7))
            ttk.Button(sci, text="Analizar píxel a píxel", command=self._start_pixel_science).pack(side="left", padx=8)
            r += 1
            ttk.Label(top, text="Plano OIII / Hα (cubo, opcional):").grid(row=r, column=0, sticky="w")
            ttk.Entry(top, textvariable=self.vars["oiii_plane"], width=12).grid(row=r, column=1, sticky="w", padx=4)
            ttk.Entry(top, textvariable=self.vars["ha_plane"], width=12).grid(row=r, column=1, sticky="e", padx=4)
            ttk.Label(top, text="formato: 0 o 0,1 para 4D").grid(row=r, column=2, columnspan=2, sticky="w")
            r += 1
            ttk.Label(top, text="Objeto (literatura):").grid(row=r, column=0, sticky="w")
            ttk.Entry(top, textvariable=self.vars["target_name"], width=40).grid(row=r, column=1, sticky="we", padx=4)
            r += 1
            aux_frame = ttk.LabelFrame(top, text="STARLESS · única fuente de perfiles científicos", padding=4)
            aux_frame.grid(row=r, column=0, columnspan=4, sticky="we", pady=4)
            for key, label in (("oiii_starless", "STARLESS [O III]"), ("ha_starless", "STARLESS Hα")):
                ttk.Label(aux_frame, text=label, width=18).pack(side="left", padx=(6, 2))
                ttk.Entry(aux_frame, textvariable=self.vars[key], width=34).pack(side="left", padx=(0, 4))
                ttk.Button(aux_frame, text="...", width=3, command=lambda k=key: self._pick(k)).pack(side="left", padx=(0, 12))
            ttk.Label(aux_frame, text="Las normales alimentan estrellas/registro; las starless alimentan exclusivamente perfiles y crestas.").pack(side="left", padx=6)
            r += 1
            ttk.Label(top, text="v30: bias/dark/flat y stars-only se han retirado del selector científico; use masters previos o el flujo de calibración externo del observatorio.").grid(row=r, column=0, columnspan=4, sticky="w", pady=2)
            r += 1
            fil = ttk.LabelFrame(top, text="Sistema óptico permitido", padding=4)
            fil.grid(row=r, column=0, columnspan=4, sticky="we", pady=4)
            ttk.Label(fil, text="Filtro óptico:").pack(side="left", padx=(6, 4))
            ttk.Combobox(fil, textvariable=self.vars["oiii_filter"], state="readonly",
                         values=FILTER_NARROWBAND_VISIBLE, width=38).pack(side="left", padx=4)
            ttk.Label(fil, text="SV220 para ambos canales Hα/OIII · L-QEF se carga aparte como broadband · Color: Gaia DR3 XP / SPCC-compatible").pack(side="left", padx=12)
            r += 1
            ttk.Label(top, text="Nota: los presets identifican el filtro; la calibración espectrofotométrica exige respuesta T(λ) real y Gaia XP.").grid(row=r,column=0,columnspan=4,sticky="w",pady=2)
            r += 1
            resp = ttk.Frame(top); resp.grid(row=r,column=0,columnspan=4,sticky="w",pady=2)
            ttk.Label(resp,text="Curva T(λ) medida del filtro (opcional):").pack(side="left",padx=(6,2))
            ttk.Entry(resp,textvariable=self.vars["oiii_curve"],width=58).pack(side="left",padx=4)
            ttk.Button(resp,text="…",width=3,command=lambda:self._pick("oiii_curve")).pack(side="left",padx=(0,8))
            ttk.Label(resp,text="una sola curva se usa para ambos canales").pack(side="left")
            r += 1
            par = ttk.Frame(top); par.grid(row=r, column=0, columnspan=4, sticky="w", pady=4)
            for key, label in (("distance", "d (pc)"), ("n0", "n0 (cm⁻³)"),
                               ("snr", "SNR mín"), ("maxc", "máx. cand."),
                               ("mins", "sep. mín (px)"),
                               ("workers", "workers"), ("pixel_scale", "escala ″/px")):
                ttk.Label(par, text=label).pack(side="left")
                ttk.Entry(par, textvariable=self.vars[key], width=8).pack(side="left", padx=(2, 10))
            r += 1
            mode = ttk.Frame(top); mode.grid(row=r, column=0, columnspan=4, sticky="w", pady=4)
            ttk.Label(mode, text="Modo científico v30: NORMAL → estrellas/registro  |  STARLESS → perfiles/crestas").pack(side="left", padx=6)
            ttk.Checkbutton(mode, text="Usar procesos", variable=self.vars["processes"]).pack(side="left", padx=10)
            ttk.Checkbutton(mode, text="Modo offline (sin Gaia/SIMBAD)", variable=self.vars["offline"]).pack(side="left", padx=6)
            ttk.Checkbutton(mode, text="Acumular candidatos", variable=self.vars["accumulate"]).pack(side="left", padx=6)
            ttk.Label(mode,text="Detección:").pack(side="left",padx=(12,2))
            ttk.Combobox(mode,textvariable=self.vars["filament_strategy"],state="readonly",width=20,
                         values=["Hessian multiescala","Canny adaptativo"]).pack(side="left",padx=3)
            r += 1
            top.columnconfigure(1, weight=1)

            bar = ttk.Frame(self.root, padding=(6, 0)); bar.pack(fill="x")
            self.btn_run = ttk.Button(bar, text="Analizar", command=self._start)
            self.btn_run.pack(side="left")
            self.btn_cancel = ttk.Button(bar, text="Cancelar", command=self._cancel, state="disabled")
            self.btn_cancel.pack(side="left", padx=4)
            ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
            ttk.Button(bar, text="Abrir catalog.json…", command=self._open_catalog).pack(side="left")
            ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
            ttk.Button(bar, text="Ejecutar script…", command=self._run_script).pack(side="left")
            ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
            self.btn_export = []
            for label, fn in (("Exportar JSON", self._export_json),
                              ("Exportar CSV", self._export_csv),
                              ("Exportar PDF", self._export_pdf),
                              ("Exportar HTML", self._export_html)):
                b = ttk.Button(bar, text=label, command=fn, state="disabled")
                b.pack(side="left", padx=2); self.btn_export.append(b)
            self.progress = ttk.Progressbar(bar, mode="determinate", maximum=1.0, length=260)
            self.progress.pack(side="right", padx=6)
            self.status = ttk.Label(bar, text="Listo"); self.status.pack(side="right")

            ai_frame = ttk.LabelFrame(self.root, text="ASTRODISCOVERY AI v34 · visión + física · sesión persistente", padding=4)
            ai_frame.pack(fill="x", padx=6, pady=(0, 4))
            ttk.Label(ai_frame, text="Modelo .pkl:").pack(side="left", padx=(4,2))
            ttk.Entry(ai_frame, textvariable=self.vars["ai_model"], width=42).pack(side="left", padx=3)
            ttk.Button(ai_frame, text="…", width=3, command=lambda:self._pick("ai_model")).pack(side="left")
            ttk.Label(ai_frame, text="Entrenamiento CSV/JSON:").pack(side="left", padx=(10,2))
            ttk.Entry(ai_frame, textvariable=self.vars["ai_training"], width=42).pack(side="left", padx=3)
            ttk.Button(ai_frame, text="…", width=3, command=lambda:self._pick("ai_training")).pack(side="left")
            ttk.Button(ai_frame, text="Cargar / entrenar IA física", command=self._ai_prepare).pack(side="left", padx=8)
            ttk.Label(ai_frame, text="CNN visual .pt:").pack(side="left", padx=(10,2))
            ttk.Entry(ai_frame, textvariable=self.vars["ai_vision_model"], width=34).pack(side="left", padx=3)
            ttk.Button(ai_frame, text="…", width=3, command=lambda:self._pick("ai_vision_model")).pack(side="left")
            ttk.Label(ai_frame, text="Directorio de imágenes reales:").pack(side="left", padx=(10,2))
            ttk.Entry(ai_frame, textvariable=self.vars["ai_vision_training"], width=34).pack(side="left", padx=3)
            ttk.Button(ai_frame, text="…", width=3, command=lambda:self._pick("ai_vision_training")).pack(side="left")
            ttk.Button(ai_frame, text="Entrenar visión", command=self._ai_vision_prepare).pack(side="left", padx=8)
            self.ai_status = ttk.Label(ai_frame, text="IA no cargada")
            self.ai_status.pack(side="left", padx=8)

            self.nb = ttk.Notebook(self.root); self.nb.pack(fill="both", expand=True, padx=6, pady=6)
            tab = ttk.Frame(self.nb); self.nb.add(tab, text="Catálogo")
            fl = ttk.Frame(tab); fl.pack(fill="x")
            ttk.Label(fl, text="Filtro:").pack(side="left")
            self.filter_var = tk.StringVar(value="todos")
            cb = ttk.Combobox(fl, textvariable=self.filter_var,
                              values=["todos", "frentes (shock)", "estrellas", "ok", "rechazados/error"],
                              width=20, state="readonly")
            cb.pack(side="left", padx=4)
            cb.bind("<<ComboboxSelected>>", lambda e: self._fill_table())
            self.summary_lbl = ttk.Label(fl, text=""); self.summary_lbl.pack(side="left", padx=10)
            self.tree = ttk.Treeview(tab, columns=self.TABLE_COLS, show="headings", selectmode="browse")
            for c in self.TABLE_COLS:
                self.tree.heading(c, text=c)
                self.tree.column(c, width=70 if c not in ("reason", "front_class", "status",
                                                          "candidate_type") else 170,
                                 anchor="center")
            ys = ttk.Scrollbar(tab, orient="vertical", command=self.tree.yview)
            xs = ttk.Scrollbar(tab, orient="horizontal", command=self.tree.xview)
            self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
            self.tree.pack(side="left", fill="both", expand=True)
            ys.pack(side="right", fill="y"); xs.pack(side="bottom", fill="x")
            self.tree.bind("<<TreeviewSelect>>", self._on_select)
            stars_tab = ttk.Frame(self.nb); self.nb.add(stars_tab, text="Estrellas")
            self.stars_summary = ttk.Label(stars_tab, text="Sin caracterización estelar")
            self.stars_summary.pack(fill="x", padx=6, pady=4)
            self.stars_notes = ScrolledText(stars_tab, height=7, wrap="word",
                                            font=("TkDefaultFont", 9))
            self.stars_notes.pack(fill="x", padx=6, pady=(0, 4))
            star_cols = ("source_id", "g_mag", "bp_rp", "teff_k", "spectral_class_est",
                         "luminosity_class_est", "pm_total_masyr", "distance_pc",
                         "simbad_main_id", "simbad_otype", "interest")
            self.star_tree = ttk.Treeview(stars_tab, columns=star_cols, show="headings")
            for c in star_cols:
                self.star_tree.heading(c, text=c)
                self.star_tree.column(c,
                    width=95 if c not in ("interest", "simbad_main_id", "simbad_otype") else 240,
                    anchor="center")
            star_ys = ttk.Scrollbar(stars_tab, orient="vertical", command=self.star_tree.yview)
            self.star_tree.configure(yscrollcommand=star_ys.set)
            self.star_tree.pack(side="left", fill="both", expand=True)
            star_ys.pack(side="right", fill="y")
            self.star_tree.bind("<Double-1>", self._on_star_select)
            self.figs = {}; self.canvases = {}
            for name, title in (("profiles", "Perfiles"), ("ratio", "Ratio [OIII]/Hα"),
                                ("cooling", "Enfriamiento Hα/[OIII]"),
                                ("map", "Composición"), ("diagram", "Diagrama")):
                t = ttk.Frame(self.nb); self.nb.add(t, text=title)
                if name == "profiles":
                    nav = ttk.Frame(t); nav.pack(fill="x")
                    ttk.Label(nav, text="Mostrar:").pack(side="left")
                    pcb = ttk.Combobox(nav, textvariable=self.vars["profile_mode"],
                                       state="readonly", width=22,
                                       values=["Perfiles científicos de nebulosa"])
                    pcb.pack(side="left", padx=5)
                    pcb.bind("<<ComboboxSelected>>", lambda e: self._set_profile_mode())
                    ttk.Button(nav, text="◀ anterior", command=lambda: self._step_profile(-1)).pack(side="left")
                    ttk.Button(nav, text="siguiente ▶", command=lambda: self._step_profile(+1)).pack(side="left", padx=4)
                    self.prof_lbl = ttk.Label(nav, text="—"); self.prof_lbl.pack(side="left", padx=10)
                if HAS_MPL and tk_canvas_cls is not None:
                    fig = Figure(figsize=(9, 6.5), dpi=96)
                    cv = tk_canvas_cls(fig, master=t)
                    cv.get_tk_widget().pack(fill="both", expand=True)
                    self.figs[name], self.canvases[name] = fig, cv
                else:
                    ttk.Label(t, text="matplotlib no disponible").pack(expand=True)
            t = ttk.Frame(self.nb); self.nb.add(t, text="Resumen")
            self.summary_txt = ScrolledText(t, wrap="word", font=("TkFixedFont", 9))
            self.summary_txt.pack(fill="both", expand=True)
            t = ttk.Frame(self.nb); self.nb.add(t, text="Log")
            self.log_txt = ScrolledText(t, wrap="word", height=10, font=("TkFixedFont", 9))
            self.log_txt.pack(fill="both", expand=True)

        def _auto_exptimes(self, o3, h):
            def exptime(p):
                try:
                    return read_fits_exptime(p)
                except Exception:
                    return 1.0
            self._oiii_exptime = exptime(o3)
            self._ha_exptime = exptime(h)

        def _show_calibration(self):
            try:
                o3 = self.vars["oiii"].get().strip()
                h = self.vars["ha"].get().strip()
                if o3 and h and Path(o3).is_file() and Path(h).is_file():
                    self._auto_exptimes(o3, h)
                else:
                    self._oiii_exptime = 1.0; self._ha_exptime = 1.0
                cal, corr, ok = calibrate_from_filters(
                    self.vars["oiii_filter"].get(), self.vars["ha_filter"].get(),
                    exptime_oiii=self._oiii_exptime, exptime_ha=self._ha_exptime,
                    nii_over_ha=float(self.vars["cal_nii_ha"].get() or 0.0),
                    ebv=float(self.vars["cal_ebv"].get() or 0.0),
                    ebv_err=float(self.vars["cal_ebv_err"].get() or 0.0),
                    oiii_curve=(load_filter_curve(self.vars["oiii_curve"].get())[0] if self.vars["oiii_curve"].get().strip() else None),
                    ha_curve=(load_filter_curve(self.vars["ha_curve"].get())[0] if self.vars["ha_curve"].get().strip() else None),
                    photometric_calibrated=bool(self.vars["photometric_calibrated"].get()),
                    oiii_zp_factor=float(self.vars["oiii_zp_factor"].get() or 1.0),
                    ha_zp_factor=float(self.vars["ha_zp_factor"].get() or 1.0),
                    r_v=float(self.vars["r_v"].get() or 3.1),
                    zeropoint_source=self.vars["zeropoint_source"].get().strip(),
                    zeropoint_error_mag=float(self.vars["zeropoint_error_mag"].get() or "nan"),
                    calibration_id=self.vars["calibration_id"].get().strip())
                msg = (f"Calibración automática\n"
                       f"Filtro OIII: {self.vars['oiii_filter'].get()}\n"
                       f"Filtro Hα:  {self.vars['ha_filter'].get()}\n"
                       f"EXPTIME OIII/Hα: {self._oiii_exptime:.2f} / {self._ha_exptime:.2f} s\n"
                       f"Transmisión OIII: {cal.oiii_transmission:.3f}\n"
                       f"Transmisión Hα:  {cal.ha_transmission:.3f}\n"
                       f"Factor de corrección al ratio: {corr:.4f}\n"
                       f"Estado: {'CALIBRACIÓN FOTOMÉTRICA VALIDADA' if cal.calibration_basis == 'validated_photometric' else ('CORRECCIÓN RELATIVA (curva propia)' if cal.calibration_basis == 'user_curve_relative' else 'INSTRUMENTAL / PRESET APROXIMADO')}\n"
                       f"NII/Hα: {cal.nii_over_ha} · E(B−V): {cal.ebv}")
                messagebox.showinfo("Calibración", msg)
            except Exception as exc:
                messagebox.showerror("Calibración", f"Error: {exc}")

        def _pick(self, key):
            if key == "out":
                p = filedialog.askdirectory(title="Carpeta de salida")
            elif key == "grid":
                p = filedialog.askopenfilename(filetypes=[("Grillas", "*.csv *.ecsv *.json *.txt"), ("Todos", "*")])
            elif key in ("oiii_curve", "ha_curve"):
                p = filedialog.askopenfilename(filetypes=[("Curvas", "*.csv *.dat *.json *.txt"), ("Todos", "*")])
            elif key == "light":
                p = filedialog.askopenfilename(filetypes=[("FITS", "*.fits *.fit *.fts *.fz"), ("Todos", "*")])
            elif key == "ai_model":
                p = filedialog.askopenfilename(filetypes=[("Modelo IA", "*.pkl"), ("Todos", "*")])
            elif key == "ai_training":
                p = filedialog.askopenfilename(filetypes=[("Datos IA", "*.csv *.json"), ("Todos", "*")])
            elif key == "ai_vision_model":
                p = filedialog.askopenfilename(filetypes=[("Modelo visual", "*.pt *.pth"), ("Todos", "*")])
            elif key == "ai_vision_training":
                p = filedialog.askdirectory(title="Directorio de FITS astronómicos reales para entrenar visión")
            elif key in ("oiii_starless", "ha_starless", "oiii_stars", "ha_stars",
                         "bias_oiii", "bias_ha", "dark_oiii", "dark_ha", "flat_oiii", "flat_ha"):
                p = filedialog.askopenfilename(filetypes=[("FITS", "*.fits *.fit *.fts *.fz"), ("Todos", "*")])
            else:
                p = filedialog.askopenfilename(filetypes=[("FITS", "*.fits *.fit *.fts *.fz"), ("Todos", "*")])
            if p:
                self.vars[key].set(p)

        def _pick_dir(self):
            d = filedialog.askdirectory(title="Directorio con el par FITS")
            if not d:
                return
            o3, h = auto_pair_directory(d)
            if o3:
                self.vars["oiii"].set(o3)
            if h:
                self.vars["ha"].set(h)
            self.vars["out"].set(str(Path(d) / "run"))
            self._append_log(f"Directorio {d}: [O III]={o3 or 'NO'}  Hα={h or 'NO'}")
            if not (o3 and h):
                messagebox.showwarning("Par incompleto", "No se identificaron ambos filtros.")

        @staticmethod
        def _parse_plane_text(text):
            text = str(text or "").strip()
            if not text:
                return None
            try:
                parts = tuple(int(x.strip()) for x in text.split(",") if x.strip() != "")
            except ValueError as exc:
                raise ValueError(f"Plano inválido '{text}': use 0 o 0,1") from exc
            if len(parts) == 1:
                return parts[0]
            if len(parts) >= 2:
                return parts
            return None

        def _params(self):
            f = lambda k, d: float(self.vars[k].get() or d)
            px_str = self.vars["pixel_scale"].get().strip()
            px_scale = float(px_str) if px_str else float("nan")
            target = self.vars["target_name"].get().strip()
            curve_path = self.vars["oiii_curve"].get().strip()
            # v30: un único modo científico: normales para estrellas/registro,
            # starless para detección y perfiles de nebulosa.
            if not self.vars["oiii_starless"].get().strip() or not self.vars["ha_starless"].get().strip():
                raise ValueError("Debe seleccionar OIII starless y Hα starless.")
            o3f = self.vars["oiii_filter"].get() or FILTER_DEFAULT
            haf = o3f
            self.vars["ha_filter"].set(o3f)
            cal = LineCalibration(
                oiii_exptime_s=getattr(self, "_oiii_exptime", 1.0),
                ha_exptime_s=getattr(self, "_ha_exptime", 1.0),
                calibrated=False, calibration_basis="instrumental",
                calibration_warning="v33: la calibración fotométrica absoluta no se declara desde un preset.",
                oiii_filter=o3f, ha_filter=haf,
                filter_curve_oiii=curve_path, filter_curve_ha=curve_path,
                ebv=f("cal_ebv", 0.0), ebv_err=f("cal_ebv_err", 0.0),
                nii_over_ha=f("cal_nii_ha", 0.0), r_v=f("r_v", 3.1),
                zeropoint_source=self.vars["zeropoint_source"].get().strip(),
                zeropoint_error_mag=f("zeropoint_error_mag", float("nan")) if self.vars["zeropoint_error_mag"].get().strip() else float("nan"),
                calibration_id=self.vars["calibration_id"].get().strip(),
                validation_evidence={"gui_flag":bool(self.vars["photometric_calibrated"].get())})
            return AnalysisParams(
                snr_min=f("snr", 4.0), max_candidates=int(f("maxc", 2000)),
                min_separation_px=f("mins", 8.0), distance_pc=f("distance", 725.0),
                n0=f("n0", 6.0), workers=max(1, int(f("workers", 1))),
                use_processes=bool(self.vars["processes"].get()), register="stars",
                starless=True, light_path="", pixel_scale_override=px_scale, target_name=target,
                accumulate=bool(self.vars["accumulate"].get()), calibration=cal,
                oiii_filter=o3f, ha_filter=haf,
                oiii_starless_path=self.vars["oiii_starless"].get().strip(),
                ha_starless_path=self.vars["ha_starless"].get().strip(),
                oiii_stars_path="", ha_stars_path="", offline=bool(self.vars["offline"].get()),
                export_products=True, export_ecsv=True, export_html=False,
                filament_strategy=("canny" if self.vars["filament_strategy"].get().startswith("Canny") else "hessian"),
                oiii_plane=self._parse_plane_text(self.vars["oiii_plane"].get()),
                ha_plane=self._parse_plane_text(self.vars["ha_plane"].get()),
                broadband_path=self.vars["broadband"].get().strip(),
                grid_path=self.vars["grid"].get().strip(),
                ai_enabled=True, ai_model_path=self.vars["ai_model"].get().strip(),
                ai_training_path=self.vars["ai_training"].get().strip(),
                ai_min_training_rows=max(10,int(f("ai_min_rows",80))),
                ai_anomaly_contamination=min(0.25,max(0.0001,f("ai_contamination",0.02))),
                ai_vision_enabled=HAS_TORCH, ai_vision_model_path=self.vars["ai_vision_model"].get().strip(),
                ai_vision_training_dir=self.vars["ai_vision_training"].get().strip(),
                ai_vision_epochs=max(1,int(f("ai_vision_epochs",12))), ai_vision_batch_size=8)

        def _ai_prepare(self):
            """Carga el modelo persistente o entrena una sola vez; la sesión queda viva en GUI."""
            if self.ai_session is not None and self.ai_session.state == "ACTIVA":
                self.ai_status.configure(text="IA activa · sesión persistente")
                return
            model=self.vars["ai_model"].get().strip(); training=self.vars["ai_training"].get().strip()
            try:
                self.ai_session=DiscoverySession(model_path=model, training_path=training, seed=20260915,
                                                 min_rows=max(10,int(self.vars["ai_min_rows"].get() or 80)),
                                                 contamination=float(self.vars["ai_contamination"].get() or 0.02))
                if self.ai_session.state == "ACTIVA":
                    src=self.ai_session.ai.training_meta.get("n_rows_real", "?")
                    self.ai_status.configure(text=f"IA activa · {src} registros de referencia")
                    self._append_log("AstroDiscovery AI v33: sesión persistente activa; clasificación neuronal + detector de novedad.")
                else:
                    self.ai_status.configure(text=f"IA: {self.ai_session.state}")
                    messagebox.showwarning("AstroDiscovery AI", self.ai_session.last_error or "No se pudo preparar la IA.")
            except Exception as exc:
                self.ai_session=None; self.ai_status.configure(text="IA: error")
                messagebox.showerror("AstroDiscovery AI", f"No se pudo preparar la IA:\n{type(exc).__name__}: {exc}")

        def _ai_vision_prepare(self):
            if not HAS_TORCH:
                messagebox.showwarning("AstroVision AI", "PyTorch no está instalado.")
                return
            model=self.vars["ai_vision_model"].get().strip(); training=self.vars["ai_vision_training"].get().strip()
            try:
                if model and Path(model).is_file():
                    va=AstroVisionAI.load(model); src="modelo persistente"
                elif training and Path(training).is_dir():
                    va=AstroVisionAI(seed=20260915)
                    rep=va.fit_from_directory(training,epochs=max(1,int(self.vars["ai_vision_epochs"].get() or 12)))
                    if not rep.get("state","").startswith("ENTRENADA"):
                        raise RuntimeError(rep.get("reason","entrenamiento no disponible"))
                    if model: va.save(model)
                    src=str(rep.get("metrics",{}).get("n_images","?"))+" imágenes reales"
                else:
                    raise RuntimeError("Seleccione un modelo .pt existente o un directorio con FITS reales.")
                self.ai_vision_session=va
                self.ai_status.configure(text=f"IA activa · física + visión ({src})")
                self._append_log("AstroVision AI v34: CNN convolucional activa; ve píxeles mediante embeddings + detección visual de novedad.")
            except Exception as exc:
                self.ai_vision_session=None
                messagebox.showerror("AstroVision AI", f"No se pudo preparar la IA visual:\n{type(exc).__name__}: {exc}")

        def _start_pixel_science(self):
            ha = self.vars["science_ha"].get().strip(); o3 = self.vars["science_oiii"].get().strip(); bb = self.vars["science_broadband"].get().strip()
            if not (ha and o3 and Path(ha).is_file() and Path(o3).is_file()):
                messagebox.showerror("Mapas científicos", "Seleccione Hα y OIII apiladas válidas."); return
            try:
                out = self.vars["out"].get().strip() or str(Path.cwd()/"science_pixel_products")
                st = self.vars["pixel_scale"].get().strip(); scale = float(st) if st else float("nan")
                ebv = float(self.vars["cal_ebv"].get() or 0.0); rv = float(self.vars["r_v"].get() or 3.1)
                nii = float(self.vars["cal_nii_ha"].get() or 0.0); snr = float(self.vars["snr"].get() or 4.0)
            except ValueError as exc:
                messagebox.showerror("Mapas científicos", f"Parámetro inválido: {exc}"); return
            self.status.set("Analizando mapas píxel a píxel…")
            def work():
                try:
                    rep = analyze_pixel_science_images(ha, o3, bb, pixel_scale_arcsec=scale, ebv=ebv, r_v=rv, nii_over_ha=nii, snr_min=snr, output_dir=out, plane_ha=parse_plane_arg(self.vars["ha_plane"].get()), plane_oiii=parse_plane_arg(self.vars["oiii_plane"].get()))
                    self.q.put(("log", "PIXEL SCIENCE v51\n" + f"píxeles válidos: {rep['valid_pixels']}/{rep['total_pixels']}\n" + f"ratio mediano: {rep['ratio_statistics']['median']}\n" + f"regiones: {rep['regions']['count']}\n" + f"salida: {rep['products']['npz']}"))
                    self.root.after(0, lambda: self.status.set("Análisis píxel a píxel terminado"))
                except (OSError, ValueError, TypeError, RuntimeError) as exc:
                    self.q.put(("error", f"pixel-science: {type(exc).__name__}: {exc}")); self.root.after(0, lambda: self.status.set("Error en mapas científicos"))
            self.worker = threading.Thread(target=work, daemon=True); self.worker.start()

        def _start(self):
            if self.worker is not None and self.worker.is_alive():
                return
            o3 = self.vars["oiii"].get().strip()
            h = self.vars["ha"].get().strip()
            out = self.vars["out"].get().strip()
            if not (o3 and h and out):
                messagebox.showerror("Entradas", "Seleccione FITS y carpeta de salida."); return
            if not (Path(o3).is_file() and Path(h).is_file()):
                messagebox.showerror("Entradas", "Algún FITS normal no existe."); return
            so3 = self.vars["oiii_starless"].get().strip(); sha = self.vars["ha_starless"].get().strip()
            if not (so3 and sha and Path(so3).is_file() and Path(sha).is_file()):
                messagebox.showerror("Entradas", "Seleccione OIII starless y Hα starless. Los perfiles científicos solo pueden salir de esas imágenes."); return
            try:
                self._auto_exptimes(o3, h)
                P = self._params()
            except ValueError as exc:
                messagebox.showerror("Parámetros", f"Parámetro inválido: {exc}"); return
            grid_path = self.vars["grid"].get().strip() or None
            self.cancel.clear(); self.payload = None; self.image = None; self.image_o3 = None; self.image_o3_raw = None; self.image_starless = None; self.image_o3_starless = None
            for b in self.btn_export:
                b.configure(state="disabled")
            self.btn_run.configure(state="disabled")
            self.btn_cancel.configure(state="normal")
            self.progress["value"] = 0.0; self.status.configure(text="Iniciando…")
            self.tree.delete(*self.tree.get_children())

            def work():
                try:
                    grid, grid_meta = load_scientific_grid(
                        grid_path, allow_demo=True, context="GUI analyze")
                    if grid_path:
                        self.q.put(("log", f"Grilla validada por MappingsGridLoader: {grid_path}"))
                    else:
                        self.q.put(("log", "Grilla heuristic_demo_grid embebida (solo demostración; no es MAPPINGS/3MdB)"))
                    try:
                        img_ha = load_fits(h, plane=P.ha_plane)  # los cubos requieren plano explícito
                        small_ha, fct = _downsample_for_display(img_ha.data, 2048)
                        self.q.put(("image_ha", small_ha, fct))
                        try:
                            img_o3 = load_fits(o3, plane=P.oiii_plane)  # los cubos requieren plano explícito
                            small_o3, _ = _downsample_for_display(img_o3.data, 2048)
                            self.q.put(("image_o3", small_o3, fct))
                        except (OSError, ValueError, AmbiguousCubeError) as exc:
                            LOG.debug("Preview OIII no disponible: %s", exc)
                        try:
                            img_hs = load_fits(P.ha_starless_path, plane=P.ha_plane)
                            small_hs, sf = _downsample_for_display(img_hs.data, 2048)
                            self.q.put(("image_ha_starless", small_hs, sf))
                            img_os = load_fits(P.oiii_starless_path, plane=P.oiii_plane)
                            small_os, _ = _downsample_for_display(img_os.data, 2048)
                            self.q.put(("image_o3_starless", small_os, sf))
                        except (OSError, ValueError, AmbiguousCubeError) as exc:
                            LOG.debug("Preview OIII starless no disponible: %s", exc)
                    except (OSError, ValueError, AmbiguousCubeError) as exc:
                        self.q.put(("log", f"Imagen preview: {exc}"))
                    payload = analyze_pair(o3, h, out, P, grid, None,
                                           progress=lambda fr, msg: self.q.put(("progress", fr, msg)),
                                           cancel=self.cancel)
                    self.q.put(("done", payload))
                except AnalysisCancelled:
                    self.q.put(("cancelled",))
                except AmbiguousCubeError as exc:
                    self.q.put(("error", f"FITS de entrada ambiguo (cubo 3D/4D):\n{exc}"))
                except Exception:
                    self.q.put(("error", traceback.format_exc()))

            self.worker = threading.Thread(target=work, name="analyze_pair", daemon=True)
            self.worker.start()

        def _cancel(self):
            if self.worker is None or not self.worker.is_alive():
                return
            self.cancel.set()
            self.btn_cancel.configure(state="disabled")
            self.status.configure(text="Cancelando…")

        def _open_catalog(self):
            p = filedialog.askopenfilename(filetypes=[("JSON", "catalog.json"), ("Todos", "*")])
            if not p:
                return
            try:
                payload = json.load(open(p, encoding="utf-8"))
                prof = Path(p).with_name("profiles.json")
                if prof.exists():
                    payload["profiles"] = json.load(open(prof, encoding="utf-8")).get("profiles", {})
                else:
                    payload["profiles"] = {}
            except Exception as exc:
                messagebox.showerror("Catálogo", f"No se pudo leer: {exc}"); return
            self.image = None; self.image_o3 = None; self.image_o3_raw = None
            selected = (payload.get("manifest") or {}).get("selected_cube_plane") or {}
            hp = (payload.get("inputs") or {}).get("ha")
            if hp and Path(hp).is_file():
                try:
                    self.image, self.image_factor = _downsample_for_display(
                        load_fits(hp, plane=selected.get("ha")).data, 2048)  # plano guardado en manifiesto
                except Exception as exc:
                    self._append_log(f"Imagen Hα: {exc}")
            op = (payload.get("inputs") or {}).get("oiii")
            if op and Path(op).is_file():
                try:
                    self.image_o3_raw, _ = _downsample_for_display(
                        load_fits(op, plane=selected.get("oiii")).data, 2048)
                    self.image_o3 = self.image_o3_raw.copy()
                except Exception:
                    self.image_o3 = None
            self._set_payload(payload)

        def _run_script(self):
            """v29: Ejecutar script Python externo (plugin) sobre el payload actual.

            No es un sandbox seguro: solo ejecutar scripts de confianza.
            El resultado se marca externo/no validado y no reemplaza estados
            científicos de la suite.
            """
            p = filedialog.askopenfilename(
                title="Seleccionar script externo (.py)",
                filetypes=[("Python", "*.py"), ("Todos", "*")])
            if not p:
                return
            if not messagebox.askyesno(
                "Confirmar ejecución",
                f"Va a ejecutar código Python arbitrario:\n{p}\n\n"
                "Esto NO es un entorno aislado (sandbox). Solo ejecute scripts "
                "de confianza. ¿Continuar?"):
                return
            out_dir = str(Path(p).parent)
            result = run_external_script(p, payload=self.payload or {}, out_dir=out_dir)
            self._append_log(f"Script externo: {p} -> estado={result['state']}")
            if result.get("stdout"):
                self._append_log(f"[script stdout]\n{result['stdout']}")
            if result.get("error"):
                messagebox.showerror("Script externo", f"Error:\n{result['error']}")
            else:
                messagebox.showinfo(
                    "Script externo",
                    f"Ejecutado correctamente.\nResultado (no validado por la suite):\n"
                    f"{json.dumps(json_sanitize(result['result']), indent=2, ensure_ascii=False)[:800]}")

        def _export(self, kind):
            if not self.payload:
                return
            ext = {"json": ".json", "csv": ".csv", "pdf": ".pdf", "html": ".html"}[kind]
            p = filedialog.asksaveasfilename(defaultextension=ext,
                                             filetypes=[(kind.upper(), "*" + ext)],
                                             initialfile=f"catalog{ext}")
            if not p:
                return
            payload = self.payload; image = self.image; image_o3 = self.image_o3
            self.status.configure(text=f"Exportando {kind.upper()}…")
            def work():
                try:
                    if kind == "json":
                        atomic_json_dump({k: v for k, v in payload.items() if k != "profiles"}, p)
                    elif kind == "csv":
                        write_catalog_csv(payload["candidates"], Path(p))
                    elif kind == "pdf":
                        if not HAS_MPL:
                            raise RuntimeError("matplotlib no disponible")
                        write_report_pdf(payload, p, ha_image=image, o3_image=image_o3)
                    else:
                        write_html_report(payload, p, ha_image=image, o3_image=image_o3)
                    self.q.put(("log", f"Exportado {p}"))
                    self.q.put(("status", "Exportación completada"))
                except Exception as exc:
                    self.q.put(("log", f"ERROR al exportar: {exc}"))
                    self.q.put(("status", "Error al exportar"))
            threading.Thread(target=work, daemon=True).start()

        def _export_json(self): self._export("json")
        def _export_csv(self): self._export("csv")
        def _export_pdf(self): self._export("pdf")
        def _export_html(self): self._export("html")

        def _poll(self):
            try:
                for _ in range(200):
                    try:
                        msg = self.q.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        self._handle_msg(msg)
                    except Exception as exc:
                        self._append_log(f"[poll] Error manejando mensaje: {exc}")
                        self._append_log(traceback.format_exc())
            finally:
                self.root.after(100, self._poll)

        def _handle_msg(self, msg):
            kind = msg[0]
            if kind == "log":
                self._append_log(msg[1])
            elif kind == "progress":
                self.progress["value"] = max(0.0, min(1.0, msg[1]))
                self.status.configure(text=msg[2])
            elif kind == "status":
                self.status.configure(text=msg[1])
            elif kind == "image_ha":
                self.image, self.image_factor = msg[1], msg[2]
            elif kind == "image_o3":
                self.image_o3_raw = np.asarray(msg[1], np.float32).copy()
                self.image_o3 = self.image_o3_raw.copy()
            elif kind == "image_ha_starless":
                self.image_starless = np.asarray(msg[1], np.float32).copy()
            elif kind == "image_o3_starless":
                self.image_o3_starless = np.asarray(msg[1], np.float32).copy()
            elif kind == "done":
                self._finish()
                try:
                    self._set_payload(msg[1])
                except Exception as exc:
                    self._append_log(f"Error mostrando payload: {exc}")
                    self._append_log(traceback.format_exc())
                self.status.configure(text="Análisis terminado")
            elif kind == "cancelled":
                self._finish(); self.status.configure(text="Cancelado")
            elif kind == "error":
                self._finish(); self.status.configure(text="Error")
                self._append_log(msg[1])
                messagebox.showerror("Error", msg[1].strip().splitlines()[-1])

        def _finish(self):
            self.btn_run.configure(state="normal")
            self.btn_cancel.configure(state="disabled")
            if self.worker is not None and not self.worker.is_alive():
                self.worker = None

        def _append_log(self, text):
            self.log_txt.insert("end", text + "\n"); self.log_txt.see("end")

        def _set_payload(self, payload):
            self.payload = payload
            for b in self.btn_export:
                b.configure(state="normal")
            s = payload.get("summary", {})
            rows_now = payload.get("candidates", [])
            prof_now = payload.get("profiles") or {}
            n_prof = sum(1 for r in rows_now
                         if r.get("candidate_type", "shock") != "star"
                         and profile_key(r) in prof_now)
            stellar = payload.get("stellar_profiles") or {}
            self.summary_lbl.configure(
                text=(f"brutos {s.get('n_candidates')} · nuevos {s.get('n_new_candidates')} · "
                      f"analizados {s.get('n_analyzed')} · ok {s.get('n_ok')} · "
                      f"frentes con perfil {n_prof} · estrellas detectadas {s.get('n_stars_detected',0)} · "
                      f"perfiles estelares {len(stellar)}"))
            self.summary_txt.delete("1.0", "end")
            summary_display = {"summary": s, "manifest": payload.get("manifest")}
            # v29: Add QC, consistency, provenance to GUI summary
            if payload.get("scientific_consistency"):
                summary_display["scientific_consistency"] = payload["scientific_consistency"]
            if payload.get("qc_summary"):
                summary_display["qc_summary"] = payload["qc_summary"]
            if payload.get("provenance"):
                summary_display["provenance"] = payload["provenance"]
            self.summary_txt.insert("end", json.dumps(json_sanitize(
                summary_display), indent=1, ensure_ascii=False))
            self._fill_table()
            self._fill_stars()
            self._align_display_o3()
            rows = payload.get("candidates", [])
            self.profile_pos = 0
            self._set_profile_mode()
            if "ratio" in self.figs:
                _plot_map(self.figs["ratio"], self.image, self.image_o3,
                          self.image_factor, rows, mode="ratio", star_sources=self.payload.get("stars"))
                self.canvases["ratio"].draw_idle()
            if "cooling" in self.figs:
                _plot_map(self.figs["cooling"], self.image, self.image_o3,
                          self.image_factor, rows, mode="cooling", star_sources=self.payload.get("stars"))
                self.canvases["cooling"].draw_idle()
            if "map" in self.figs:
                _plot_map(self.figs["map"], self.image, self.image_o3,
                          self.image_factor, rows, mode="rgb")
                self.canvases["map"].draw_idle()
            if "diagram" in self.figs:
                _plot_diagram(self.figs["diagram"], rows, s.get("pixel_scale_arcsec"))
                self.canvases["diagram"].draw_idle()
            self._show_profile()

        def _fill_stars(self):
            if not hasattr(self, "star_tree"):
                return
            self.star_tree.delete(*self.star_tree.get_children())
            stars = (self.payload or {}).get("stars") or []
            self._star_rows = {}
            for i, r in enumerate(stars):
                vals = []
                for c in ("source_id", "g_mag", "bp_rp", "teff_k", "spectral_class_est",
                          "luminosity_class_est", "pm_total_masyr", "distance_pc",
                          "simbad_main_id", "simbad_otype", "interest"):
                    v = r.get(c)
                    if isinstance(v, float):
                        vals.append(f"{v:.3g}" if math.isfinite(v) else "")
                    else:
                        vals.append("" if v is None else str(v))
                iid = f"star_{i}"
                self._star_rows[iid] = r
                self.star_tree.insert("", "end", iid=iid, values=vals)
            ss = (self.payload or {}).get("summary", {}).get("stellar_summary", {})
            types = ss.get("types", {}) or {}
            type_txt = ", ".join(f"{k}:{v}" for k, v in sorted(types.items())) if types else "sin tipos"
            hi = (self.payload or {}).get("stellar_highlights") or []
            self.stars_summary.configure(text=(f"Estrellas cruzadas con Gaia: {ss.get('n_matched',0)} · "
                                              f"interesantes: {ss.get('n_interesting',0)} · "
                                              f"tipos: {type_txt} · "
                                              f"objetos SIMBAD destacados: {len(hi)}"))
            self.stars_notes.delete("1.0", "end")
            if hi:
                self.stars_notes.insert("end", "OBJETOS DE INTERÉS EN EL CAMPO (Gaia DR3 + SIMBAD)\n")
                for o in hi[:25]:
                    oid = str(o.get("main_id") or "objeto sin nombre")
                    typ = str(o.get("type_pretty") or o.get("otype") or "tipo no disponible")
                    self.stars_notes.insert("end",
                        f"• {oid}: {typ}. Catálogo conocido; no constituye descubrimiento propio.\n")
            else:
                self.stars_notes.insert("end",
                    "No se encontraron objetos de SIMBAD con tipos destacados en el campo.\n"
                    "Las propiedades de cada estrella se infieren de Gaia DR3 (paralaje, Teff, "
                    "magnitudes, movimiento propio) y se muestran en la tabla.\n"
                    "Para más detalle abre SIMBAD con el nombre del objeto.\n")
            bright = ss.get("brightest") or {}
            if bright.get("source_id") is not None:
                self.stars_notes.insert("end",
                    f"\nEstrella más brillante detectada: Gaia DR3 {bright.get('source_id')} · "
                    f"G={bright.get('g_mag')} · tipo estimado={bright.get('spectral_class_est')}.\n")

        def _align_display_o3(self):
            try:
                if self.image_o3_raw is None:
                    return
                reg = (self.payload or {}).get("summary", {}).get("registration") or {}
                dx = float(reg.get("dx", 0) or 0); dy = float(reg.get("dy", 0) or 0)
                f = float(self.image_factor or 1)
                if abs(dx) > 1e-6 or abs(dy) > 1e-6:
                    self.image_o3 = ndi.shift(np.asarray(self.image_o3_raw, np.float32),
                                              shift=(dy/f, dx/f), order=1,
                                              mode="nearest", prefilter=False).astype(np.float32)
                else:
                    self.image_o3 = self.image_o3_raw.copy()
            except (TypeError, ValueError, RuntimeError) as exc:
                self._append_log(f"Alineación preview: {exc}")

        def _fill_table(self):
            self.tree.delete(*self.tree.get_children())
            self._tree_rows = {}
            if not self.payload:
                return
            flt = self.filter_var.get()
            for idx, r in enumerate(self.payload.get("candidates", [])):
                st = str(r.get("status", ""))
                ctype = r.get("candidate_type", "shock")
                if flt == "frentes (shock)" and ctype == "star":
                    continue
                if flt == "estrellas" and ctype != "star":
                    continue
                if flt == "ok" and not st.startswith("ok"):
                    continue
                if flt == "rechazados/error" and (st.startswith("ok") or ctype == "star"):
                    continue
                vals = []
                for c in self.TABLE_COLS:
                    v = r.get(c)
                    if isinstance(v, float):
                        vals.append(f"{v:.3g}" if math.isfinite(v) else "")
                    elif v is None:
                        vals.append("")
                    else:
                        vals.append(str(v))
                iid = f"row_{idx}"
                self._tree_rows[iid] = r
                self.tree.insert("", "end", iid=iid, values=vals)

        def _on_select(self, _evt):
            sel = self.tree.selection()
            if not sel or not self.payload:
                return
            iid = sel[0]
            row = self._tree_rows.get(iid)
            if row is None:
                return
            key = profile_key(row)
            if row.get("candidate_type", "shock") == "star":
                self.prof_lbl.configure(text=f"Candidato {key}: fuente estelar")
                self.vars["profile_mode"].set("Estrellas / PSF"); self._set_profile_mode()
                return
            profiles = self.payload.get("profiles") or {}
            if key in profiles:
                try:
                    self.profile_pos = self.profile_keys.index(key)
                except ValueError:
                    self.profile_pos = 0
                self.vars["profile_mode"].set("Nebulosa / frentes")
                self._set_profile_mode()
                self.nb.select(1)
            else:
                self.prof_lbl.configure(text=f"Candidato {key}: sin perfil guardado")

        def _set_profile_mode(self):
            self.profile_pos = 0
            self.prof_lbl.configure(text="Cargando perfiles…") if hasattr(self, "prof_lbl") else None
            if self.vars["profile_mode"].get().startswith("Estrellas"):
                sp = (self.payload or {}).get("stellar_profiles") or {}
                self.profile_keys = list(sp.keys())
            else:
                prof = (self.payload or {}).get("profiles") or {}
                rows = (self.payload or {}).get("candidates") or []
                keys = []
                for r in rows:
                    if r.get("candidate_type", "shock") == "star":
                        continue
                    k = profile_key(r)
                    if k is None:
                        continue
                    if k in prof and not str(k).startswith("star_"):
                        keys.append(k)
                seen = set()
                self.profile_keys = [k for k in keys if not (k in seen or seen.add(k))]
            self._show_profile()

        def _on_star_select(self, _evt):
            sel = self.star_tree.selection()
            if not sel or not self.payload:
                return
            star = self._star_rows.get(sel[0])
            if star is None:
                return
            key = star_profile_key(int(star.get("det_id", 0)))
            self.vars["profile_mode"].set("Estrellas / PSF"); self._set_profile_mode()
            if key in self.profile_keys:
                self.profile_pos = self.profile_keys.index(key)
                self._show_profile()
                for tab_id in self.nb.tabs():
                    if self.nb.tab(tab_id, "text") == "Perfiles":
                        self.nb.select(tab_id); break

        def _step_profile(self, d):
            if self.profile_keys:
                self.profile_pos = (self.profile_pos + d) % len(self.profile_keys)
                self._show_profile()

        def _show_profile(self):
            if not self.payload:
                self.prof_lbl.configure(text="Sin datos"); return
            if self.vars["profile_mode"].get().startswith("Estrellas"):
                profiles = self.payload.get("stellar_profiles") or {}
                if not self.profile_keys:
                    self.prof_lbl.configure(text="Sin perfiles estelares"); return
                key = self.profile_keys[self.profile_pos]
                sp = profiles.get(key, {})
                ident = sp.get("simbad_main_id") or sp.get("source_id") or key
                self.prof_lbl.configure(
                    text=f"Estrella {ident}  ({self.profile_pos+1}/{len(self.profile_keys)})")
                if "profiles" in self.figs:
                    _plot_stellar_profile(self.figs["profiles"], sp,
                                          ha_image=self.image, o3_image=self.image_o3,
                                          factor=self.image_factor)
                    self.canvases["profiles"].draw_idle()
                return
            if not self.profile_keys:
                self.prof_lbl.configure(text="Sin perfiles de nebulosa"); return
            key = self.profile_keys[self.profile_pos]
            self.prof_lbl.configure(
                text=f"Frente {key}  ({self.profile_pos+1}/{len(self.profile_keys)})")
            if "profiles" in self.figs:
                _plot_profiles(self.figs["profiles"], self.payload, key,
                               ha_image=(self.image_starless if self.image_starless is not None else self.image),
                               o3_image=(self.image_o3_starless if self.image_o3_starless is not None else self.image_o3),
                               factor=self.image_factor)
                self.canvases["profiles"].draw_idle()

        def _close(self):
            self.cancel.set()
            logging.getLogger().removeHandler(self._log_handler)
            self.root.destroy()

    root = tk.Tk()
    app = App(root)
    if _test_hook is not None:
        root.after(200, lambda: _test_hook(root, app))
    root.mainloop()


# ====================================================================
# SECTION 49: SCIENTIFIC SCHEMA CONTRACT / NORMALIZATION
# ====================================================================
SCIENCE_SCHEMA_VERSION = 1

def normalize_scientific_payload(payload: dict) -> dict:
    """Adapta exclusivamente alias históricos al esquema que produce el pipeline real.

    No inventa datos: sólo resuelve nombres equivalentes ya presentes. Además expone
    un campo ``schema_diagnostics`` para detectar drift de contrato.
    """
    p = dict(payload or {})
    summary = dict(p.get("summary") or {})
    manifest = dict(p.get("manifest") or {})
    candidates = [dict(r) for r in (p.get("candidates") or [])]

    # Pipeline actual -> nombres canónicos de QC.
    for r in candidates:
        if "ratio_oiii_ha" not in r and r.get("ratio") is not None:
            r["ratio_oiii_ha"] = r.get("ratio")
        if "velocity_km_s" not in r and r.get("v_kms") is not None:
            r["velocity_km_s"] = r.get("v_kms")
        if "velocity_err_km_s" not in r and r.get("v_err_kms") is not None:
            r["velocity_err_km_s"] = r.get("v_err_kms")
        if "temperature_k" not in r:
            for k in ("mc_T_post_K", "T_post_K"):
                if r.get(k) is not None:
                    r["temperature_k"] = r.get(k); break
        if "flux_erg_cm2_s" not in r and r.get("flux_adu") is not None:
            r["flux_erg_cm2_s"] = None  # explícitamente no calibrado
        # El S/N del cociente puede venir de cualquiera de los términos si existe.
        if r.get("snr") is None:
            sn = [finite(r.get("snr_ha"), float("nan")), finite(r.get("snr_oiii"), float("nan"))]
            if all(np.isfinite(x) for x in sn): r["snr"] = float(min(sn))

    # Summary: alias reales actuales.
    if summary.get("radius_arcsec") is None and summary.get("remnant_radius_arcsec") is not None:
        summary["radius_arcsec"] = summary.get("remnant_radius_arcsec")
    if summary.get("radius_err_arcsec") is None and summary.get("remnant_radius_arcsec_err") is not None:
        summary["radius_err_arcsec"] = summary.get("remnant_radius_arcsec_err")
    if summary.get("velocity_km_s") is None and summary.get("v_kms_median") is not None:
        summary["velocity_km_s"] = summary.get("v_kms_median")
    if summary.get("velocity_err_km_s") is None and summary.get("v_kms_median_err") is not None:
        summary["velocity_err_km_s"] = summary.get("v_kms_median_err")
    if summary.get("age_yr") is None:
        ages = summary.get("ages_yr") or {}
        if isinstance(ages, dict) and ages.get("sedov_taylor") is not None:
            summary["age_yr"] = ages.get("sedov_taylor")
    # Registration real payload stores px, not arcsec. Convert only if scale exists.
    reg = dict(summary.get("registration") or {})
    if reg.get("residual_rms_arcsec") is None and reg.get("residual_rms_px") is not None:
        scale = finite(summary.get("pixel_scale_arcsec"), float("nan"))
        rr = finite(reg.get("residual_rms_px"), float("nan"))
        reg["residual_rms_arcsec"] = float(rr * scale) if np.isfinite(rr) and np.isfinite(scale) and scale > 0 else None
    if reg.get("phase_fallback") is None:
        reg["phase_fallback"] = "phase" in str(reg.get("method", "")).lower()
    if reg.get("may_absorb_scientific_filament_shift") is None:
        reg["may_absorb_scientific_filament_shift"] = bool(reg.get("phase_fallback"))
    summary["registration"] = reg

    # El manifest real usa grid/grid_manifest, no grid_info.
    grid_info = manifest.get("grid_info")
    if not isinstance(grid_info, dict):
        grid_info = manifest.get("grid") or summary.get("grid_manifest") or {}
    if not isinstance(grid_info, dict): grid_info = {}
    manifest["grid_info"] = dict(grid_info)

    # Error de calibración: usar un error explícito si existe; no inventar 0.05 mag.
    cal = dict(summary.get("calibration") or {})
    if cal.get("zp_error") is None:
        for k in ("calib_frac_err", "zeropoint_error_mag", "zero_point_error_mag"):
            if cal.get(k) is not None: cal["zp_error"]=cal.get(k); break
    cal.setdefault("zeropoint_source",cal.get("source","")); cal.setdefault("zeropoint_error_mag",cal.get("zp_error",float("nan"))); cal.setdefault("calibration_id",""); cal.setdefault("validation_evidence",{})
    cal["validated_evidence"]=bool(cal.get("calibrated") and str(cal.get("zeropoint_source","")).strip() and math.isfinite(finite(cal.get("zeropoint_error_mag"),float("nan"))) and finite(cal.get("zeropoint_error_mag"),0)>0)
    summary["calibration"]=cal

    p["summary"] = summary
    p["manifest"] = manifest
    p["candidates"] = candidates
    p["schema_diagnostics"] = {
        "schema_version": SCIENCE_SCHEMA_VERSION,
        "source_schema_version": p.get("schema_version", SCHEMA_VERSION),
        "normalized": True,
        "candidate_count": len(candidates),
    }
    return p

# ====================================================================
# SECTION 49: SCIENTIFIC CONSISTENCY CHECK
# ====================================================================
@dataclass
class ScientificConsistencyReport:
    """Resultado de la verificación de consistencia científica del payload."""
    passed: bool
    n_warnings: int
    n_errors: int
    issues: list  # list of dicts: {severity, category, message, candidate_key?}
    result_states: dict  # key -> state label

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

def check_scientific_consistency(payload: dict) -> ScientificConsistencyReport:
    """
    Verifica que el payload no contenga inferencias físicas no justificadas.

    REGLA CIENTÍFICA ABSOLUTA: Nunca presentar como medida directa una
    magnitud que los datos no permitan obtener.

    Estados de resultado:
      - OBSERVABLE: magnitud directamente medible de los datos
      - PROXY OBSERVACIONAL: aproximación derivada de los datos con supuestos
      - INFERENCIA DE MODELO: depende de un modelo físico (grid, cooling curve)
      - RESULTADO CALIBRADO: requiere calibración instrumental absoluta
      - RESULTADO EXTRAPOLADO: extrapolación más allá del rango válido

    Devuelve un informe con warnings/errors que debe integrarse en el payload.
    """
    payload = normalize_scientific_payload(payload)
    issues = []
    result_states = {}
    summary = payload.get("summary", {})
    cal = summary.get("calibration", {})
    calibrated = cal.get("calibrated", False)
    candidates = payload.get("candidates", [])
    manifest = payload.get("manifest", {})
    if candidates and not any((r.get("ratio") is not None or r.get("ratio_oiii_ha") is not None or r.get("status") in {"rejected_star", "rejected_ml", "rejected_profile_selection"}) for r in candidates):
        issues.append({"severity":"error","category":"schema","message":"El catálogo contiene candidatos pero no expone campos observacionales reconocibles por el contrato científico."})

    # 1. Verificar que ratio OIII/Hα es OBSERVABLE (siempre, con SNR válido)
    for r in candidates:
        key = profile_key(r) or str(r.get("det_id", "?"))
        if r.get("candidate_type", "shock") == "star":
            result_states[key] = "OBSERVABLE"
            continue
        ratio = r.get("ratio", r.get("ratio_oiii_ha"))
        if ratio is not None and math.isfinite(float(ratio)):
            result_states[key] = "OBSERVABLE"
            # Verificar que el ratio tiene SNR válido
            snr = r.get("snr")
            if snr is not None and float(snr) < 3.0:
                issues.append({
                    "severity": "warning",
                    "category": "snr",
                    "message": f"Candidato {key}: SNR={snr:.1f} por debajo del umbral de detección robusta",
                    "candidate_key": key
                })
        else:
            result_states[key] = "NO DISPONIBLE"

    # 2. Verificar que la temperatura NO se presenta como medida directa
    for r in candidates:
        key = profile_key(r) or str(r.get("det_id", "?"))
        if r.get("candidate_type", "shock") == "star":
            continue
        if any(k in r for k in ("temperature_k","T_post","mc_T_post_K","T_post_K")):
            t = r.get("temperature_k", r.get("mc_T_post_K", r.get("T_post_K", r.get("T_post"))))
            if t is not None and math.isfinite(float(t)):
                if not calibrated:
                    issues.append({
                        "severity": "error",
                        "category": "temperature",
                        "message": f"Candidato {key}: temperatura presentada sin calibración absoluta; debe ser PROXY o INFERENCIA DE MODELO",
                        "candidate_key": key
                    })
                    result_states[key] = "INFERENCIA DE MODELO"
                else:
                    result_states[key] = "RESULTADO CALIBRADO"

    # 3. Verificar que la velocidad NO se deriva del ratio OIII/Hα solo
    for r in candidates:
        key = profile_key(r) or str(r.get("det_id", "?"))
        if r.get("candidate_type", "shock") == "star":
            continue
        if any(k in r for k in ("velocity_km_s","v_kms")):
            v = r.get("velocity_km_s", r.get("v_kms"))
            if v is not None and math.isfinite(float(v)):
                grid_used = r.get("grid_solution") or r.get("v_modes") or summary.get("grid_solution") or summary.get("grid_manifest")
                if not grid_used or not grid_used.get("grid_validated", False):
                    issues.append({
                        "severity": "error",
                        "category": "velocity",
                        "message": f"Candidato {key}: velocidad inferida sin grid MAPPINGS/3MdB validado; debe marcarse como INFERENCIA DE MODELO no publicable",
                        "candidate_key": key
                    })
                    result_states[key] = "INFERENCIA DE MODELO"
                else:
                    result_states[key] = "INFERENCIA DE MODELO"

    # 4. Verificar que la edad NO se presenta sin radio+distancia+velocidad
    if "age_yr" in summary or isinstance(summary.get("ages_yr"),dict):
        age = summary.get("age_yr") if summary.get("age_yr") is not None else (summary.get("ages_yr") or {}).get("sedov_taylor")
        if age is not None and math.isfinite(float(age)):
            radius = summary.get("radius_arcsec")
            distance = summary.get("distance_pc")
            velocity = summary.get("velocity_km_s")
            if not (radius and distance and velocity):
                issues.append({
                    "severity": "error",
                    "category": "age",
                    "message": "Edad del remanente presentada sin radio, distancia y velocidad simultáneos; resultado no inferible",
                })
                result_states["age"] = "RESULTADO EXTRAPOLADO"
            else:
                result_states["age"] = "INFERENCIA DE MODELO"

    # 5. Verificar que el cooling proxy está correctamente etiquetado
    cooling = summary.get("cooling_proxy")
    if cooling is not None:
        cooling_label = summary.get("cooling_label", "")
        if "Proxy" not in cooling_label and "proxy" not in cooling_label.lower():
            issues.append({
                "severity": "warning",
                "category": "cooling_label",
                "message": "Cooling proxy no etiquetado como 'Proxy de régimen de excitación/enfriamiento'",
            })
        result_states["cooling"] = "PROXY OBSERVACIONAL"

    # 6. Verificar que el flujo no se presenta como absoluto sin calibración
    for r in candidates:
        key = profile_key(r) or str(r.get("det_id", "?"))
        if r.get("candidate_type", "shock") == "star":
            continue
        if r.get("flux_erg_cm2_s") is not None and not calibrated:
            issues.append({
                "severity": "warning",
                "category": "flux",
                "message": f"Candidato {key}: flujo presentado en ADU no calibrado; debe marcarse como OBSERVABLE (no calibrado)",
                "candidate_key": key
            })
            result_states[key] = "OBSERVABLE"

    # 7. Verificar registro phase_fallback
    reg = summary.get("registration", {})
    if reg.get("phase_fallback") and reg.get("may_absorb_scientific_filament_shift"):
        issues.append({
            "severity": "warning",
            "category": "registration",
            "message": "Registro por fase: puede absorber desplazamiento científico del filamento; interpretar resultados con cautela",
        })

    # 8. Verificar que no hay log10 de datos sin máscara
    # (verificación estructural: el código ya usa np.log10 con np.where, pero verificamos payload)
    for r in candidates:
        key = profile_key(r) or str(r.get("det_id", "?"))
        if r.get("candidate_type", "shock") == "star":
            continue
        # Si hay valores negativos o cero en datos de ratio, marcar
        ratio = r.get("ratio_oiii_ha")
        if ratio is not None and float(ratio) <= 0:
            issues.append({
                "severity": "warning",
                "category": "ratio_negative",
                "message": f"Candidato {key}: ratio OIII/Hα <= 0; verificar máscara de no-detección",
                "candidate_key": key
            })

    # 9. Verificar grid provenance
    grid_info = manifest.get("grid_info") or manifest.get("grid") or summary.get("grid_manifest") or {}
    if grid_info:
        if grid_info.get("model_family", "") == "heuristic_demo_grid" or grid_info.get("model_family", "") == "unknown":
            issues.append({
                "severity": "warning",
                "category": "grid",
                "message": "Grid heurístico de demostración en uso; no es MAPPINGS/3MdB; resultados de inferencia no publicables",
            })
        if not grid_info.get("sha256"):
            issues.append({
                "severity": "warning",
                "category": "grid_provenance",
                "message": "Grid sin hash SHA256; reproducibilidad no garantizada",
            })

    n_errors = sum(1 for i in issues if i["severity"] == "error")
    n_warnings = sum(1 for i in issues if i["severity"] == "warning")
    passed = n_errors == 0

    return ScientificConsistencyReport(
        passed=passed,
        n_warnings=n_warnings,
        n_errors=n_errors,
        issues=issues,
        result_states=result_states
    )


# ====================================================================
# SECTION 37: MAPPINGS/3MdB GRID LOADER/VALIDATOR
# ====================================================================
@dataclass
class MappingsGridMetadata:
    """Metadatos de un grid MAPPINGS/3MdB real."""
    model_family: str  # "MAPPINGS-V" o "3MdB" o "heuristic_demo_grid"
    version: str
    reference: str  # referencia bibliográfica
    sha256: str  # hash del archivo para reproducibilidad
    n_points: int
    columns: list  # lista de nombres de columnas
    cooling_table: str  # tabla de cooling utilizada
    abundance_set: str  # set de abundancias

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

class MappingsGridLoader:
    """
    Loader y validador de grids MAPPINGS/3MdB externos.

    Formato esperado (CSV/ECSV/JSON):
    - Columnas requeridas: velocity_km_s, n0_cm3, T_post_K, log_q, [OIII]_Hb, Ha_Hb, [NII]_Ha, [SII]_Ha
    - Metadatos opcionales en comentarios (#) o JSON embebido

    Si no se proporciona un grid externo, se usa heuristic_demo_grid marcado como DEMO.
    """
    REQUIRED_COLUMNS = ["velocity_km_s", "n0_cm3", "T_post_K"]
    OPTIONAL_COLUMNS = ["log_q", "OIII_Hb", "Ha_Hb", "NII_Ha", "SII_Ha"]

    def __init__(self, trusted_hashes=None, trust_registry_path=None):
        self._metadata = None
        self.trusted_hashes=set(str(x).strip().lower() for x in (trusted_hashes or []) if str(x).strip())
        self.trust_registry_path=Path(trust_registry_path) if trust_registry_path else None
        if self.trust_registry_path and self.trust_registry_path.is_file():
            try:
                reg=json.loads(self.trust_registry_path.read_text(encoding="utf-8"))
                self.trusted_hashes.update(str(x).strip().lower() for x in reg.get("trusted_sha256",[]) if str(x).strip())
            except (OSError,ValueError,TypeError):
                LOG.warning("Registro de grids confiables inválido: %s",self.trust_registry_path)

    def load(self, path: str) -> ShockGrid:
        """Carga un grid MAPPINGS/3MdB desde archivo externo."""
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"Grid no encontrado: {path}")

        # Calcular SHA256 para reproducibilidad
        import hashlib
        sha = hashlib.sha256(p.read_bytes()).hexdigest()

        # Determinar formato
        if p.suffix in (".csv", ".ecsv", ".dat", ".txt"):
            grid = self._load_text(p, sha)
        elif p.suffix == ".json":
            grid = self._load_json(p, sha)
        else:
            raise ValueError(f"Formato de grid no soportado: {p.suffix}")

        self._metadata = MappingsGridMetadata(
            model_family=getattr(grid, "name", "unknown"),
            version=getattr(grid, "version", "unknown"),
            reference=getattr(grid, "reference", "unknown"),
            sha256=sha,
            n_points=len(grid.v),
            columns=getattr(grid, "columns", ["v_kms", "ratio", "n0"]),
            cooling_table=getattr(grid, "cooling_table", "not specified"),
            abundance_set=getattr(grid, "abundance_set", "not specified")
        )
        return grid

    def _parse_metadata_comments(self, lines: list) -> dict:
        """Extrae metadatos de comentarios # al inicio del archivo."""
        meta = {}
        for line in lines:
            line = line.strip()
            if not line.startswith("#"):
                break
            content = line[1:].strip()
            if ":" in content:
                key, val = content.split(":", 1)
                meta[key.strip().lower()] = val.strip()
        return meta

    def _load_text(self, path: Path, sha: str) -> ShockGrid:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        meta = self._parse_metadata_comments(lines)

        # Determinar separador
        data_lines = [l for l in lines if not l.strip().startswith("#") and l.strip()]
        if not data_lines:
            raise ValueError("Grid vacío: sin filas de datos")

        header = data_lines[0]
        sep = "," if "," in header else None  # None = whitespace
        cols = [c.strip() for c in (header.split(sep) if sep else header.split())]

        # Verificar columnas requeridas
        missing = [c for c in self.REQUIRED_COLUMNS if c not in cols]
        if missing:
            raise ValueError(f"Grid MAPPINGS/3MdB: faltan columnas requeridas: {missing}")

        # Parsear filas
        rows = []
        for line in data_lines[1:]:
            parts = line.split(sep) if sep else line.split()
            if len(parts) != len(cols):
                continue
            try:
                vals = [float(v) for v in parts]
                rows.append(vals)
            except ValueError:
                continue

        if not rows:
            raise ValueError("Grid MAPPINGS/3MdB: sin filas numéricas válidas")

        arr = np.array(rows, dtype=float)
        col_idx = {c: i for i, c in enumerate(cols)}

        velocities = arr[:, col_idx["velocity_km_s"]]
        n0s = arr[:, col_idx["n0_cm3"]]

        # Construir ratio OIII/Hα a partir de columnas opcionales
        ratio = None
        if "OIII_Hb" in col_idx and "Ha_Hb" in col_idx:
            oiii_hb = arr[:, col_idx["OIII_Hb"]]
            ha_hb = arr[:, col_idx["Ha_Hb"]]
            # ratio = (OIII/Hb) / (Hα/Hb) = OIII/Hα
            valid = ha_hb > 0
            ratio = np.full(len(velocities), np.nan)
            ratio[valid] = oiii_hb[valid] / ha_hb[valid]
        elif "OIII_Ha" in col_idx:
            ratio = arr[:, col_idx["OIII_Ha"]]
        elif "ratio" in col_idx:
            ratio = arr[:, col_idx["ratio"]]
        else:
            raise ValueError(
                "Grid MAPPINGS/3MdB: no se encontró columna de ratio. "
                "Se requiere una de: 'OIII_Hb'+'Ha_Hb', 'OIII_Ha', o 'ratio'. "
                "No se permite inferir ratio desde T_post_K."
            )

        # Filtrar NaNs
        mask = np.isfinite(velocities) & np.isfinite(ratio) & (ratio > 0)
        velocities = velocities[mask]
        ratio = ratio[mask]
        n0s = n0s[mask] if n0s is not None else None

        if len(velocities) == 0:
            raise ValueError("Grid MAPPINGS/3MdB: sin filas válidas tras filtrar")

        model_family = meta.get("model_family", "MAPPINGS/3MdB")
        version = meta.get("version", "unknown")
        reference = meta.get("reference", "See original publication")
        cooling_table = meta.get("cooling_table", "not specified")
        abundance_set = meta.get("abundance_set", "not specified")

        grid = ShockGrid(velocities, ratio, n0s, name=model_family)
        grid.version = version
        grid.reference = reference
        grid.cooling_table = cooling_table
        grid.abundance_set = abundance_set
        grid.columns = cols
        ref_ok=bool(str(reference).strip()) and str(reference).strip().lower() not in {"unknown","see original publication"}
        tpost=arr[:, col_idx["T_post_K"]][mask] if "T_post_K" in col_idx else None
        coherence=self._physics_coherence(velocities,n0s,tpost)
        trusted=sha.lower() in self.trusted_hashes
        grid.validated_model_grid=bool(trusted and ref_ok and coherence)
        grid.validation_status="trusted_external_grid" if grid.validated_model_grid else ("untrusted_external_grid" if not trusted else "physics_coherence_failed")
        grid.inference_ready=grid.validated_model_grid
        grid.validation_evidence={"sha256_trusted":trusted,"reference_present":ref_ok,"physics_coherence":coherence}

        # Validar
        GridManager().validate(grid)
        return grid

    def _load_json(self, path: Path, sha: str) -> ShockGrid:
        data = json.loads(path.read_text(encoding="utf-8"))
        meta = data.get("metadata", {})
        points = data.get("points", [])
        if not points:
            raise ValueError("Grid JSON: sin puntos")

        velocities = np.array([p["velocity_km_s"] for p in points], dtype=float)
        n0s = np.array([p.get("n0_cm3", np.nan) for p in points], dtype=float)

        # Construir ratio
        ratio = None
        if all("OIII_Hb" in p and "Ha_Hb" in p for p in points):
            oiii_hb = np.array([p["OIII_Hb"] for p in points], dtype=float)
            ha_hb = np.array([p["Ha_Hb"] for p in points], dtype=float)
            ratio = np.full(len(velocities), np.nan)
            valid = ha_hb > 0
            ratio[valid] = oiii_hb[valid] / ha_hb[valid]
        elif all("OIII_Ha" in p for p in points):
            ratio = np.array([p["OIII_Ha"] for p in points], dtype=float)
        elif all("ratio" in p for p in points):
            ratio = np.array([p["ratio"] for p in points], dtype=float)
        else:
            raise ValueError(
                "Grid JSON: no se encontró columna de ratio. "
                "Se requiere una de: 'OIII_Hb'+'Ha_Hb', 'OIII_Ha', o 'ratio'. "
                "No se permite inferir ratio desde T_post_K."
            )

        mask = np.isfinite(velocities) & np.isfinite(ratio) & (ratio > 0)
        velocities = velocities[mask]
        ratio = ratio[mask]
        n0s_filtered = n0s[mask] if n0s is not None else None

        grid = ShockGrid(velocities, ratio, n0s_filtered, name=meta.get("model_family", "MAPPINGS/3MdB"))
        grid.version = meta.get("version", "unknown")
        grid.reference = meta.get("reference", "See original publication")
        grid.cooling_table = meta.get("cooling_table", "not specified")
        grid.abundance_set = meta.get("abundance_set", "not specified")
        grid.columns = list(points[0].keys()) if points else []
        ref_ok=bool(str(grid.reference).strip()) and str(grid.reference).strip().lower() not in {"unknown","see original publication"}
        tpost=np.asarray([p.get("T_post_K",np.nan) for p in points],float)[mask] if any("T_post_K" in p for p in points) else None
        coherence=self._physics_coherence(velocities,n0s_filtered,tpost)
        trusted=sha.lower() in self.trusted_hashes
        grid.validated_model_grid=bool(trusted and ref_ok and coherence)
        grid.validation_status="trusted_external_grid" if grid.validated_model_grid else ("untrusted_external_grid" if not trusted else "physics_coherence_failed")
        grid.inference_ready=grid.validated_model_grid
        grid.validation_evidence={"sha256_trusted":trusted,"reference_present":ref_ok,"physics_coherence":coherence}

        GridManager().validate(grid)
        return grid

    @staticmethod
    def _physics_coherence(v,n0,tpost):
        if tpost is None: return False
        v=np.asarray(v,float); n0=np.asarray(n0,float); tpost=np.asarray(tpost,float)
        if len(v)<3 or len(tpost)!=len(v): return False
        total=good=0
        for nv in np.unique(n0[np.isfinite(n0)]):
            m=np.isfinite(v)&np.isfinite(tpost)&np.isclose(n0,nv,rtol=0,atol=max(1e-12,1e-8*max(abs(nv),1)))
            if m.sum()<3: continue
            o=np.argsort(v[m]); dv=np.diff(v[m][o]); dt=np.diff(tpost[m][o]); ok=dv>0
            if ok.any(): total+=1; good+=int(float(np.mean(dt[ok]>=-1e-10))>=0.8)
        return bool(total>0 and good==total)

    @property
    def metadata(self) -> Optional[MappingsGridMetadata]:
        return self._metadata

    def has_real_mappings_grid(self) -> bool:
        """True si se ha cargado un grid MAPPINGS/3MdB real (no heurístico)."""
        if self._metadata is None:
            return False
        return self._metadata.model_family not in ("heuristic_demo_grid", "unknown")


def load_mappings_grid(path: str, trust_registry_path: str = "") -> tuple:
    """
    Carga un grid MAPPINGS/3MdB y devuelve (grid, metadata).
    Si path es None o vacío, devuelve (None, None).
    """
    if not path:
        return None, None
    loader = MappingsGridLoader(trust_registry_path=(trust_registry_path or None))
    grid = loader.load(path)
    return grid, loader.metadata


def register_trusted_grid(grid_path: str, registry_path: str, *, reference: str = "") -> dict:
    """Registra explícitamente el SHA256 de un grid que el usuario ha auditado.

    El acto de confianza es deliberado: la suite no certifica que el contenido sea
    físicamente correcto; sólo hace reproducible qué archivo exacto fue autorizado.
    """
    gp=Path(grid_path); rp=Path(registry_path)
    if not gp.is_file(): raise FileNotFoundError(str(gp))
    sha=hashlib.sha256(gp.read_bytes()).hexdigest()
    data={"schema_version":1,"trusted_sha256":[],"entries":{}}
    if rp.is_file():
        raw=json.loads(rp.read_text(encoding="utf-8"))
        if isinstance(raw,dict):
            data.update(raw)
            data["trusted_sha256"]=list(raw.get("trusted_sha256",[]))
            data["entries"]=dict(raw.get("entries",{}))
    vals={str(x).lower() for x in data["trusted_sha256"] if str(x).strip()}
    vals.add(sha.lower()); data["trusted_sha256"]=sorted(vals)
    data["entries"][sha]={"file":str(gp.resolve()),"reference":str(reference or ""),"registered_utc":datetime.now(timezone.utc).isoformat()}
    rp.parent.mkdir(parents=True,exist_ok=True); atomic_json_dump(data,rp)
    return {"state":"TRUSTED_HASH_REGISTERED","sha256":sha,"registry":str(rp),"reference":str(reference or "")}


def load_scientific_grid(
    path: Optional[str],
    allow_demo: bool = True,
    context: str = "",
    trust_registry_path: str = "",
) -> tuple:
    """
    Función común para cargar grillas científicas en CLI, GUI y tests.

    - Si path se proporciona y es válido: usa MappingsGridLoader (grid validado).
    - Si path falla: ABORTA (no fallback silencioso a DEMO).
    - Si path es None/"" y allow_demo=True: usa grid DEMO embebido (con advertencia).
    - Si path es None/"" y allow_demo=False: devuelve (None, None).

    Returns: (grid, metadata) donde metadata puede ser None para DEMO.
    """
    if path:
        loader = MappingsGridLoader(trust_registry_path=(trust_registry_path or os.environ.get("APS_TRUSTED_GRID_REGISTRY") or None))
        try:
            grid = loader.load(path)
            LOG.info("Grid MAPPINGS/3MdB cargado (%s): %s, %d puntos, SHA256=%s...",
                     context, grid.name, len(grid.v), loader.metadata.sha256[:16])
            return grid, loader.metadata
        except Exception as exc:
            LOG.error("No se pudo cargar grid MAPPINGS/3MdB (%s): %s. Abortando (no fallback a DEMO).",
                      context, exc)
            raise
    elif allow_demo:
        gm = GridManager()
        grid = gm.embedded()
        LOG.warning("Usando grid heurístico DEMO (no publicable). Use --grid para MAPPINGS/3MdB.")
        return grid, None
    return None, None


# ====================================================================
# SECTION 40: UNCERTAINTY BUDGET
# ====================================================================
@dataclass
class UncertaintyBudget:
    """Presupuesto de incertidumbre estructurado para un resultado."""
    component: str
    value: float  # valor de la incertidumbre (1 sigma)
    unit: str
    source: str  # fuente de la incertidumbre
    method: str  # método de estimación
    state: str  # OBSERVABLE, PROXY, INFERENCIA, etc.

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

def compute_uncertainty_budget(payload: dict) -> list:
    """
    Calcula el presupuesto de incertidumbre estructurado para los resultados del análisis.

    Componentes:
    1. Ruido de lectura (si RDNOISE en header)
    2. Photon shot noise
    3. Ruido de fondo (background RMS)
    4. Incertidumbre de registro (dx, dy residuals)
    5. Incertidumbre de calibración (si calibrado)
    6. Incertidumbre de modelo (grid, si aplicable)
    7. Incertidumbre de distancia

    Cada componente se etiqueta con su estado científico.
    """
    payload = normalize_scientific_payload(payload)
    budget = []
    summary = payload.get("summary", {})
    cal = summary.get("calibration", {})
    reg = summary.get("registration", {})
    manifest = payload.get("manifest", {})

    # 1. Ruido de lectura
    rdnoise = manifest.get("rdnoise_e", None)
    if rdnoise is None:
        rdnoise = summary.get("rdnoise_e", None)
    if rdnoise is not None and math.isfinite(float(rdnoise)):
        budget.append(UncertaintyBudget(
            component="read_noise",
            value=float(rdnoise),
            unit="e-",
            source="FITS header RDNOISE",
            method="directo del header",
            state="OBSERVABLE"
        ))

    # 2. Background RMS
    bg_rms = summary.get("background_rms", None)
    if bg_rms is not None and math.isfinite(float(bg_rms)):
        budget.append(UncertaintyBudget(
            component="background_rms",
            value=float(bg_rms),
            unit="ADU",
            source="estimate_background",
            method="mediana local robusta",
            state="OBSERVABLE"
        ))

    # 3. Registro residuals
    reg_rms = reg.get("residual_rms_arcsec", None)
    if reg_rms is not None and math.isfinite(float(reg_rms)):
        budget.append(UncertaintyBudget(
            component="registration",
            value=float(reg_rms),
            unit="arcsec",
            source="register_on_stars",
            method="RMS de residuales de matching",
            state="OBSERVABLE"
        ))

    # 4. Calibración
    zp_err = cal.get("zp_error")
    if zp_err is None:
        for _k in ("zeropoint_error_mag", "zero_point_error_mag", "calib_frac_err"):
            if cal.get(_k) is not None:
                zp_err = cal.get(_k)
                break
    if cal.get("calibrated", False) and zp_err is not None and math.isfinite(float(zp_err)) and float(zp_err) > 0:
        budget.append(UncertaintyBudget(
            component="calibration",
            value=float(zp_err),
            unit="mag",
            source="zero-point",
            method="error del zeropoint instrumental",
            state="RESULTADO CALIBRADO"
        ))
    else:
        budget.append(UncertaintyBudget(
            component="calibration",
            value=float("nan"),
            unit="mag",
            source="no calibrado",
            method="N/A - solo ADU relativos",
            state="NO DISPONIBLE"
        ))

    # 5. Modelo grid
    grid_info = manifest.get("grid_info") or manifest.get("grid") or summary.get("grid_manifest") or {}
    if grid_info:
        model_err = grid_info.get("model_logerr", 0.15)
        model_fam = grid_info.get("model_family", "unknown")
        budget.append(UncertaintyBudget(
            component="model_grid",
            value=float(model_err),
            unit="dex",
            source=model_fam,
            method="error intrínseco del modelo",
            state="INFERENCIA DE MODELO"
        ))

    # 6. Distancia
    dist = summary.get("distance_pc", None)
    dist_err = summary.get("distance_err_pc", None)
    if dist is not None and dist_err is not None:
        if math.isfinite(float(dist)) and math.isfinite(float(dist_err)):
            budget.append(UncertaintyBudget(
                component="distance",
                value=float(dist_err),
                unit="pc",
                source="entrada del usuario",
                method="error proporcionado",
                state="PROXY OBSERVACIONAL"
            ))

    # 7. Extinción
    ebv = cal.get("ebv", 0.0)
    if ebv > 0:
        # Error típico de extinción: ~10% de E(B-V) si no hay medición directa
        budget.append(UncertaintyBudget(
            component="extinction",
            value=0.1 * float(ebv),
            unit="mag E(B-V)",
            source="mapa de polvo (proxy)",
            method="~10% de E(B-V) sin medición directa",
            state="PROXY OBSERVACIONAL"
        ))

    return budget


# ====================================================================
# SECTION 44: LITERATURE COMPARISON WITH Z-SCORE
# ====================================================================
def compare_with_literature_zscore(payload: dict) -> list:
    """
    Compara los resultados con la literatura usando z-score y intervalos de confianza.

    NUNCA usar solo 'X% de diferencia'.
    Siempre reportar z-score = (valor - literatura) / sigma_total.

    La literatura usa formato de tupla: (valor, error, referencia).

    Devuelve lista de comparaciones con:
    - z_score: número de sigmas de desviación
    - confidence_interval: intervalo de confianza del resultado
    - agreement: 'consistent' (|z|<2), 'marginal' (2<=|z|<3), 'discrepant' (|z|>=3)
    - literature_value, literature_ref
    - result_value, result_sigma
    """
    comparisons = []
    summary = payload.get("summary", {})
    target = summary.get("target_name", "")

    if not target:
        return comparisons

    lit = find_literature(target)
    if lit is None:
        return comparisons

    def _extract_lit(field):
        """Extrae (valor, error, ref) de un campo de literatura.
        Las tuplas pueden ser (valor, error, ref) o (low, high, ref) para rangos.
        Para rangos, usamos el punto medio como valor y (high-low)/2 como error.
        """
        val = lit.get(field)
        if val is None:
            return None, None, None
        if isinstance(val, (tuple, list)) and len(val) >= 3:
            v1, v2, ref = float(val[0]), float(val[1]), str(val[2])
            # Detectar si es rango (low, high) o valor±error
            # Si ambos son positivos y v2 > v1, podría ser rango o valor+error
            # Tratamos como (valor, error) si v2 es pequeño respecto a v1
            # Si v2 > v1, tratamos como rango (low, high)
            if v2 > v1 and v1 > 0:
                # Rango: usar punto medio y semi-ancho
                mid = (v1 + v2) / 2.0
                half_range = (v2 - v1) / 2.0
                return mid, half_range, ref
            else:
                # valor, error, ref
                return v1, v2, ref
        elif isinstance(val, (tuple, list)) and len(val) == 2:
            return float(val[0]), float(val[1]), "literature"
        elif isinstance(val, (int, float)):
            return float(val), float(val) * 0.1, "literature"
        return None, None, None

    # Radio (usar radius_pc de la literatura si disponible)
    lit_r, lit_r_err, lit_r_ref = _extract_lit("radius_pc")
    obs_r = summary.get("radius_arcsec")
    if lit_r is not None and obs_r is not None:
        # Convertir radio angular a pc si hay distancia
        dist = summary.get("distance_pc")
        if dist:
            obs_r_pc = float(obs_r) / 3600.0 * float(dist) * np.pi / 180.0
            r_err = float(summary.get("radius_err_arcsec", summary.get("remnant_radius_arcsec_err", obs_r * 0.1)))
            r_err_pc = r_err / 3600.0 * float(dist) * np.pi / 180.0
            if r_err_pc > 0:
                sigma_total = math.sqrt(r_err_pc**2 + lit_r_err**2)
                z = (obs_r_pc - lit_r) / sigma_total
                comparisons.append({
                    "quantity": "radius_pc",
                    "literature_value": lit_r,
                    "literature_ref": lit_r_ref,
                    "result_value": obs_r_pc,
                    "result_sigma": r_err_pc,
                    "z_score": z,
                    "agreement": "consistent" if abs(z) < 2 else ("marginal" if abs(z) < 3 else "discrepant"),
                    "confidence_interval": [obs_r_pc - 2*r_err_pc, obs_r_pc + 2*r_err_pc],
                    "state": "PROXY OBSERVACIONAL"
                })

    # Distancia
    lit_d, lit_d_err, lit_d_ref = _extract_lit("distance_pc")
    obs_d = summary.get("distance_pc")
    if lit_d is not None and obs_d is not None:
        d_err = float(summary.get("distance_err_pc", obs_d * 0.05))
        if d_err > 0:
            sigma_total = math.sqrt(d_err**2 + lit_d_err**2)
            z = (float(obs_d) - lit_d) / sigma_total
            comparisons.append({
                "quantity": "distance_pc",
                "literature_value": lit_d,
                "literature_ref": lit_d_ref,
                "result_value": float(obs_d),
                "result_sigma": d_err,
                "z_score": z,
                "agreement": "consistent" if abs(z) < 2 else ("marginal" if abs(z) < 3 else "discrepant"),
                "confidence_interval": [float(obs_d) - 2*d_err, float(obs_d) + 2*d_err],
                "state": "PROXY OBSERVACIONAL"
            })

    # Velocidad (solo si hay grid validado)
    grid_info = ((payload.get("manifest", {}) or {}).get("grid_info") or (payload.get("manifest", {}) or {}).get("grid") or (payload.get("summary", {}) or {}).get("grid_manifest") or {})
    lit_v, lit_v_err, lit_v_ref = _extract_lit("v_shock_kms")
    obs_v = summary.get("velocity_km_s")
    if lit_v is not None and obs_v is not None:
        v_err = float(summary.get("velocity_err_km_s", abs(obs_v) * 0.15))
        if v_err > 0:
            sigma_total = math.sqrt(v_err**2 + lit_v_err**2)
            z = (float(obs_v) - lit_v) / sigma_total
            state = "INFERENCIA DE MODELO"
            if grid_info.get("model_family", "heuristic_demo_grid") == "heuristic_demo_grid":
                state = "INFERENCIA DE MODELO / DEMO (no publicable)"
            comparisons.append({
                "quantity": "velocity_km_s",
                "literature_value": lit_v,
                "literature_ref": lit_v_ref,
                "result_value": float(obs_v),
                "result_sigma": v_err,
                "z_score": z,
                "agreement": "consistent" if abs(z) < 2 else ("marginal" if abs(z) < 3 else "discrepant"),
                "confidence_interval": [float(obs_v) - 2*v_err, float(obs_v) + 2*v_err],
                "state": state
            })

    # Edad (solo si hay radio + distancia + velocidad)
    lit_a, lit_a_err, lit_a_ref = _extract_lit("age_yr")
    obs_a = summary.get("age_yr")
    if lit_a is not None and obs_a is not None:
        a_err = float(summary.get("age_err_yr", abs(obs_a) * 0.3))
        if a_err > 0:
            sigma_total = math.sqrt(a_err**2 + lit_a_err**2)
            z = (float(obs_a) - lit_a) / sigma_total
            comparisons.append({
                "quantity": "age_yr",
                "literature_value": lit_a,
                "literature_ref": lit_a_ref,
                "result_value": float(obs_a),
                "result_sigma": a_err,
                "z_score": z,
                "agreement": "consistent" if abs(z) < 2 else ("marginal" if abs(z) < 3 else "discrepant"),
                "confidence_interval": [float(obs_a) - 2*a_err, float(obs_a) + 2*a_err],
                "state": "INFERENCIA DE MODELO"
            })

    return comparisons


# ====================================================================
# SECTION 42: ANOMALY DETECTION
# ====================================================================
def detect_anomalies(payload: dict) -> list:
    """
    Detecta anomalías estadísticas en los resultados del análisis.

    NUNCA marcar como 'descubrimiento' una coincidencia anómala.
    Etiquetas conservadoras: 'anomaly_candidate', 'outlier', 'statistical_fluctuation'.

    Criterios:
    1. Ratio OIII/Hα que excede el rango típico de choques radiativos
    2. Perfiles con anchos anómalos (FWHM fuera de rango esperado)
    3. Candidatos con SNR muy alto pero sin contrapartida estelar
    4. Estructuras no catalogadas (sin coincidencia Gaia/SIMBAD)
    """
    payload = normalize_scientific_payload(payload)
    anomalies = []
    candidates = payload.get("candidates", [])

    # Ratios típicos de choques radiativos: OIII/Hα ~ 0.5 - 10
    # (rango conservador; fuera de esto es anómalo pero NO descubrimiento)
    RATIO_LOW = 0.1
    RATIO_HIGH = 20.0

    ratios = []
    for r in candidates:
        if r.get("candidate_type", "shock") == "star":
            continue
        ratio = r.get("ratio_oiii_ha")
        if ratio is not None and math.isfinite(float(ratio)) and float(ratio) > 0:
            ratios.append(float(ratio))

    if not ratios:
        return anomalies

    median_ratio = float(np.median(ratios))
    std_ratio = float(np.std(ratios)) if len(ratios) > 1 else 0.0

    for r in candidates:
        if r.get("candidate_type", "shock") == "star":
            continue
        key = profile_key(r) or str(r.get("det_id", "?"))
        ratio = r.get("ratio_oiii_ha")
        if ratio is None or not math.isfinite(float(ratio)):
            continue
        ratio = float(ratio)

        # 1. Ratio anómalo
        if ratio > RATIO_HIGH or ratio < RATIO_LOW:
            anomalies.append({
                "type": "anomaly_candidate",
                "subtype": "extreme_ratio",
                "candidate_key": key,
                "description": f"Ratio OIII/Hα={ratio:.2f} fuera del rango típico de choques radiativos ({RATIO_LOW}-{RATIO_HIGH})",
                "state": "OBSERVABLE",
                "is_discovery": False,
                "note": "Anomalía estadística; NO constituye descubrimiento astronómico"
            })

        # 2. Outlier estadístico (z-score > 3 respecto a la mediana)
        if std_ratio > 0 and abs(ratio - median_ratio) > 3 * std_ratio:
            anomalies.append({
                "type": "outlier",
                "subtype": "ratio_outlier",
                "candidate_key": key,
                "description": f"Ratio OIII/Hα={ratio:.2f} es outlier estadístico (z>3 respecto a mediana={median_ratio:.2f})",
                "state": "OBSERVABLE",
                "is_discovery": False,
                "note": "Outlier estadístico; requiere investigación adicional antes de cualquier conclusión"
            })

        # 3. FWHM anómala
        fwhm = r.get("fwhm_px")
        if fwhm is not None and math.isfinite(float(fwhm)):
            fwhm = float(fwhm)
            if fwhm < 1.0 or fwhm > 30.0:
                anomalies.append({
                    "type": "anomaly_candidate",
                    "subtype": "anomalous_fwhm",
                    "candidate_key": key,
                    "description": f"FWHM={fwhm:.2f} px fuera del rango esperado (1-30 px)",
                    "state": "OBSERVABLE",
                    "is_discovery": False,
                    "note": "FWHM anómala; posible artefacto o fuente no resuelta"
                })

    # 4. Estructuras sin contrapartida catalogada
    stars = payload.get("stars", [])
    n_uncatalogued = sum(1 for s in stars if not s.get("simbad_main_id"))
    if n_uncatalogued > len(stars) * 0.5 and len(stars) > 5:
        anomalies.append({
            "type": "statistical_fluctuation",
            "subtype": "many_uncatalogued",
            "description": f"{n_uncatalogued}/{len(stars)} fuentes estelares sin contrapartida SIMBAD; puede indicar campo poco estudiado o problemas de matching",
            "state": "OBSERVABLE",
            "is_discovery": False,
            "note": "Falta de catálogo no implica descubrimiento; puede ser limitación de SIMBAD"
        })

    return anomalies


# ====================================================================
# SECTION 46: QC SUMMARY
# ====================================================================
def generate_qc_summary(payload: dict) -> dict:
    """
    Genera un resumen unificado de control de calidad (QC).
    Incluye: SNR maps, cobertura espacial, flags de calibración, estado de resultados.
    """
    payload = normalize_scientific_payload(payload)
    summary = payload.get("summary", {})
    manifest = payload.get("manifest", {})
    cal = summary.get("calibration", {})
    reg = summary.get("registration", {})
    grid_info = manifest.get("grid_info") or manifest.get("grid") or summary.get("grid_manifest") or {}

    # Consistencia científica
    consistency = check_scientific_consistency(payload)

    # Presupuesto de incertidumbre
    budget = compute_uncertainty_budget(payload)

    # Comparación con literatura
    canonical_lit = payload.get("literature_comparison") or summary.get("literature_comparison")
    lit_comparisons = canonical_lit if isinstance(canonical_lit, dict) else build_literature_comparison(summary, summary.get("target_name", ""), user_distance_pc=summary.get("distance_pc"))
    lit_zscores = compare_with_literature_zscore(payload)

    # Anomalías
    anomalies = detect_anomalies(payload)

    # Estado de calibración
    calibration_status = {
        "photometric_calibrated": cal.get("calibrated", False),
        "atmospheric_corrected": False,  # Nunca sin coeficiente local
        "absolute_flux": cal.get("calibrated", False),
        "state": "RESULTADO CALIBRADO" if cal.get("calibrated", False) else "OBSERVABLE (no calibrado)"
    }

    # Estado del grid
    grid_status = {
        "model_family": grid_info.get("model_family", "heuristic_demo_grid"),
        "is_real_mappings": grid_info.get("model_family", "heuristic_demo_grid") not in ("heuristic_demo_grid", "unknown"),
        "sha256": grid_info.get("sha256", None),
        "state": "INFERENCIA DE MODELO" if grid_info.get("model_family", "heuristic_demo_grid") != "heuristic_demo_grid" else "DEMO (no publicable)"
    }

    # Estado de registro
    registration_status = {
        "method": reg.get("method", "unknown"),
        "phase_fallback": reg.get("phase_fallback", False),
        "may_absorb_scientific_shift": reg.get("may_absorb_scientific_filament_shift", False),
        "residual_rms": reg.get("residual_rms_arcsec", reg.get("residual_rms_px")),
        "residual_unit": "arcsec" if reg.get("residual_rms_arcsec") is not None else "px",
        "state": "OBSERVABLE"
    }

    return {
        "version": __version__,
        "scientific_consistency": consistency.to_dict(),
        "uncertainty_budget": [b.to_dict() for b in budget],
        "literature_comparison": lit_comparisons,
        "literature_zscores": lit_zscores,
        "anomalies": anomalies,
        "calibration_status": calibration_status,
        "grid_status": grid_status,
        "registration_status": registration_status,
        "result_states": consistency.result_states,
        "n_candidates": len(payload.get("candidates", [])),
        "n_warnings": consistency.n_warnings,
        "n_errors": consistency.n_errors,
        "overall_pass": consistency.passed
    }


# ====================================================================
# SECTION 38: FORWARD MODELING
# ====================================================================
def simulate_observation(
    shape: tuple,
    n_filaments: int = 1,
    n_stars: int = 10,
    offset_px: float = 4.0,
    bg_level: float = 100.0,
    noise_sigma: float = 5.0,
    snr_target: float = 10.0,
    seed: int = 42
) -> dict:
    """
    Forward model: simula una observación de par [OIII]/Hα con filamentos y estrellas.

    Genera imágenes sintéticas con control de SNR, posición de filamentos,
    offset conocido entre canales, y ruido realista.

    Devuelve dict con: ha_array, oiii_array, true_offset, true_positions, metadata
    """
    rng = np.random.default_rng(seed)
    H, W = shape
    yy, xx = np.mgrid[0:H, 0:W]

    # Background con gradiente suave
    bg = bg_level + 0.03 * xx + 0.02 * yy
    ha = bg.copy().astype(np.float32)
    o3 = bg.copy().astype(np.float32)

    # Filamentos sinusoidales
    true_positions = []
    for i in range(n_filaments):
        amp_ha = rng.uniform(300, 600)
        amp_o3 = amp_ha * rng.uniform(0.5, 0.9)
        y_offset = rng.uniform(20, H - 20)
        curve_amp = rng.uniform(5, 15)
        curve_period = rng.uniform(30, 60)
        sigma_ha = rng.uniform(2.0, 3.0)
        sigma_o3 = rng.uniform(2.5, 3.5)
        curve = y_offset + curve_amp * np.sin((xx - 50) / curve_period)
        ha += amp_ha * np.exp(-0.5 * ((yy - curve) / sigma_ha) ** 2)
        o3 += amp_o3 * np.exp(-0.5 * ((yy - (curve + offset_px)) / sigma_o3) ** 2)
        true_positions.append({
            "y_center": float(y_offset),
            "amplitude_ha": float(amp_ha),
            "amplitude_o3": float(amp_o3),
            "sigma_ha": float(sigma_ha),
            "sigma_o3": float(sigma_o3)
        })

    # Estrellas
    star_positions = []
    for _ in range(n_stars):
        x = rng.integers(10, W - 10)
        y = rng.integers(10, H - 10)
        amp = rng.uniform(500, 1500)
        ps = amp * np.exp(-0.5 * ((xx - x) ** 2 + (yy - y) ** 2) / (2.0 ** 2))
        ha += ps
        o3 += ps
        star_positions.append({"x": int(x), "y": int(y), "amplitude": float(amp)})

    # Ruido gaussiano
    ha += rng.normal(0, noise_sigma, ha.shape)
    o3 += rng.normal(0, noise_sigma, o3.shape)

    return {
        "ha_array": ha,
        "oiii_array": o3,
        "true_offset_px": offset_px,
        "true_filament_positions": true_positions,
        "true_star_positions": star_positions,
        "metadata": {
            "shape": list(shape),
            "bg_level": bg_level,
            "noise_sigma": noise_sigma,
            "n_filaments": n_filaments,
            "n_stars": n_stars,
            "seed": seed,
            "state": "OBSERVABLE (sintético)"
        }
    }


# ====================================================================
# SECTION 39: SHOCK VELOCITY ESTIMATION (grid-only)
# ====================================================================
def estimate_shock_velocity(
    ratio_oiii_ha: float,
    ratio_err: float,
    grid: Optional[ShockGrid],
    n0: Optional[float] = None,
    grid_model_logerr: float = 0.15
) -> dict:
    """
    Estima una velocidad de choque *modelodependiente* a partir del ratio [OIII]/Hα usando un grid validado.

    Esto NO es una medida de velocidad radial espectroscópica.


    REGLA: NUNCA inferir velocidad del ratio desnudo sin modelo físico.
    Solo se permite mediante inversión de un grid MAPPINGS/3MdB validado.

    Si el grid es heurístico (demo), el resultado se marca como no publicable.
    Si no hay grid, devuelve 'no inferible'.
    """
    if grid is None:
        return {
            "velocity_km_s": None,
            "velocity_err_km_s": None,
            "state": "NO DISPONIBLE",
            "method": "Sin grid de modelo",
            "note": "No se puede inferir velocidad sin un grid MAPPINGS/3MdB validado"
        }

    if not math.isfinite(ratio_oiii_ha) or ratio_oiii_ha <= 0:
        return {
            "velocity_km_s": None,
            "velocity_err_km_s": None,
            "state": "NO DISPONIBLE",
            "method": "Ratio inválido",
            "note": "Ratio OIII/Hα no válido para inversión"
        }

    # Usar el grid para invertir
    sol = grid.invert(ratio_oiii_ha, ratio_err, n0=n0, grid_model_logerr=grid_model_logerr)

    is_demo = getattr(grid, "name", "heuristic_demo_grid") == "heuristic_demo_grid"
    is_validated = getattr(grid, "validated_model_grid", False)
    if is_demo:
        state = "INFERENCIA DE MODELO / DEMO (no publicable)"
    elif not is_validated:
        state = "INFERENCIA DE MODELO / NO VALIDADO"
    else:
        state = "INFERENCIA DE MODELO"

    # Extraer velocidad del primer modo si existe
    v_kms = None
    v_err = None
    if sol and sol.modes:
        m0 = sol.modes[0]
        v_kms = m0.get("v_kms")
        v_lo = m0.get("v_lo", v_kms)
        v_hi = m0.get("v_hi", v_kms)
        v_err = (v_hi - v_lo) / 2.0 if v_lo is not None and v_hi is not None else None

    return {
        "velocity_km_s": v_kms,
        "velocity_err_km_s": v_err,
        "n0_cm3": n0,
        "n0_err_cm3": None,
        "T_post_K": None,
        "state": state,
        "method": f"Inversión de grid {getattr(grid, 'name', 'unknown')}",
        "grid_reference": getattr(grid, "name", "unknown"),
        "note": ("Grid heurístico de demostración; resultado NO publicable" if is_demo
                 else ("Grid no validado externamente; usar con precaución" if not is_validated
                 else "Inversión mediante grid MAPPINGS/3MdB validado"))
    }


# ====================================================================
# SECTION 36: AGE ESTIMATION
# ====================================================================
def estimate_ast_remnant_age(
    radius_arcsec: float,
    distance_pc: float,
    velocity_km_s: Optional[float] = None,
    velocity_err_km_s: Optional[float] = None,
    n0_cm3: float = 6.0
) -> dict:
    """
    Estima la edad de un remanente de supernova.

    REGLA: La edad es una INFERENCIA DE MODELO dinámico, no una medida directa.
    Requiere radio + distancia + velocidad simultáneamente.

    Modelos:
    - Fase adiabática (Sedov-Taylor): t ~ R / v_shock
    - Fase de radiativa: requiere densidad ambient y cooling curve

    Si falta velocidad: devuelve 'no inferible'.
    """
    if not (radius_arcsec and distance_pc and velocity_km_s):
        return {
            "age_yr": None,
            "age_err_yr": None,
            "state": "NO DISPONIBLE",
            "method": "Sin inputs suficientes",
            "note": "Se requiere radio + distancia + velocidad para inferir edad"
        }

    if velocity_km_s <= 0 or distance_pc <= 0 or radius_arcsec <= 0:
        return {
            "age_yr": None,
            "age_err_yr": None,
            "state": "NO DISPONIBLE",
            "method": "Inputs no físicos",
            "note": "Radio, distancia y velocidad deben ser positivos"
        }

    # Radio físico en pc
    radius_pc = radius_arcsec / 3600.0 * distance_pc * np.pi / 180.0

    # Edad Sedov-Taylor: usa la misma implementación compartida que dynamical_ages(),
    # evitando dos fórmulas independientes en el código.
    # Para fase adiabática, el parámetro de expansión m = 2/5 = 0.4
    # t = m * R / v
    # R[km], v[km/s] -> t[s] = R[km] / v[km/s]  (ambos en km)
    # t[yr] = t[s] / 3.154e7
    radius_km = radius_pc * 3.0857e13  # pc to km
    v_km_s = velocity_km_s  # ya en km/s
    t_s_simple = radius_km / v_km_s  # edad simple R/v en segundos
    age_yr_simple = t_s_simple / 3.154e7  # a años

    # Corrección Sedov: t_sedov = (2/5) * R / v = 0.4 * R / v
    sedov_m = 0.4  # parámetro de expansión adiabática
    age_yr = float(dynamical_ages(radius_pc, v_km_s)["sedov_taylor"])

    # Error de edad (propagación simple)
    if velocity_err_km_s and velocity_err_km_s > 0:
        age_err_yr = age_yr * (velocity_err_km_s / velocity_km_s)
    else:
        age_err_yr = age_yr * 0.3  # 30% si no hay error de velocidad

    return {
        "age_yr": float(age_yr),
        "age_err_yr": float(age_err_yr),
        "age_simple_R_over_v_yr": float(age_yr_simple),
        "radius_pc": float(radius_pc),
        "method": "Sedov-Taylor (fase adiabática, m=0.4)",
        "state": "INFERENCIA DE MODELO",
        "note": "Edad dinámica; depende de la fase evolutiva y la densidad ambient. Resultado aproximado.",
        "n0_cm3": n0_cm3,
        "expansion_parameter": sedov_m,
        "assumptions": [
            "Fase adiabática (Sedov-Taylor, m=0.4)",
            f"Densidad ambient n0={n0_cm3} cm^-3",
            "Velocidad medida representa el shock actual",
            "Simetría esférica aproximada"
        ]
    }



# ====================================================================
# v51: PIXEL-LEVEL SCIENTIFIC IMAGE ENGINE
# ====================================================================
def _load_science_image(path: str, *, plane=None) -> FitsImage:
    """Carga una imagen científica 2-D aunque carezca de WCS/metadata.

    La ausencia de metadata NO invalida la medición pixel a pixel; simplemente
    impide convertir píxeles a unidades angulares/absolutas sin parámetros
    externos. El resultado conserva ese estado epistemológico.
    """
    if not path:
        raise ValueError("Ruta de imagen vacía")
    return load_fits(Path(path), plane=plane)


def _science_background(image: np.ndarray) -> tuple[float, float]:
    a = np.asarray(image, dtype=np.float64)
    finite_a = a[np.isfinite(a)]
    if finite_a.size < 32:
        raise ValueError("Imagen insuficiente: menos de 32 píxeles finitos")
    med = float(np.median(finite_a))
    mad = float(np.median(np.abs(finite_a - med)))
    sigma = 1.4826 * mad
    if not math.isfinite(sigma) or sigma <= 0:
        q16, q84 = np.percentile(finite_a, [16, 84])
        sigma = max((float(q84) - float(q16)) / 2.0, 1e-12)
    return med, sigma


def _robust_scale_to_reference(reference: np.ndarray, target: np.ndarray, valid: np.ndarray) -> float:
    r = np.asarray(reference, dtype=np.float64)[valid]
    t = np.asarray(target, dtype=np.float64)[valid]
    good = np.isfinite(r) & np.isfinite(t) & (np.abs(t) > np.finfo(float).eps)
    if np.count_nonzero(good) < 64:
        return 1.0
    ratios = r[good] / t[good]
    ratios = ratios[np.isfinite(ratios) & (ratios > 0)]
    if ratios.size == 0:
        return 1.0
    return float(np.median(ratios))


def analyze_pixel_science_images(
    ha_path: str,
    oiii_path: str,
    broadband_path: str = "",
    *,
    pixel_scale_arcsec: float = float("nan"),
    ebv: float = 0.0,
    r_v: float = 3.1,
    nii_over_ha: float = 0.0,
    ha_scale: float = 1.0,
    oiii_scale: float = 1.0,
    snr_min: float = 4.0,
    background_percentile_clip: tuple[float, float] = (1.0, 99.0),
    output_dir: str = "science_pixel_products",
    plane_ha=None,
    plane_oiii=None,
    plane_broadband=None,
) -> dict:
    """Analiza Hα/OIII y una posible banda ancha píxel a píxel.

    Está diseñado para imágenes YA APILADAS que pueden no conservar metadata.
    No requiere WCS. Cuando no existe escala angular, las salidas espaciales
    quedan en píxeles. No declara flujo absoluto: las cantidades son
    OBSERVABLES o PROXIES hasta que exista calibración instrumental trazable.
    """
    if not (math.isfinite(float(snr_min)) and float(snr_min) > 0):
        raise ValueError("snr_min debe ser > 0")
    if not (math.isfinite(float(ha_scale)) and float(ha_scale) > 0):
        raise ValueError("ha_scale debe ser > 0")
    if not (math.isfinite(float(oiii_scale)) and float(oiii_scale) > 0):
        raise ValueError("oiii_scale debe ser > 0")
    if not (math.isfinite(float(ebv)) and float(ebv) >= 0):
        raise ValueError("E(B-V) debe ser >= 0")
    if not (math.isfinite(float(r_v)) and 2.0 <= float(r_v) <= 6.0):
        raise ValueError("R_V debe estar entre 2 y 6 para CCM89")

    ha = _load_science_image(ha_path, plane=plane_ha)
    o3 = _load_science_image(oiii_path, plane=plane_oiii)
    broad = _load_science_image(broadband_path, plane=plane_broadband) if broadband_path else None
    a = np.asarray(ha.data, dtype=np.float64)
    b = np.asarray(o3.data, dtype=np.float64)
    if a.ndim != 2 or b.ndim != 2 or a.shape != b.shape:
        raise ValueError(f"Hα/OIII deben ser 2-D y del mismo shape: {a.shape} vs {b.shape}")
    if broad is not None and (np.asarray(broad.data).ndim != 2 or np.asarray(broad.data).shape != a.shape):
        raise ValueError("La banda ancha debe ser 2-D y tener exactamente el mismo shape que Hα/OIII")

    ha_bg, ha_rms = _science_background(a)
    o3_bg, o3_rms = _science_background(b)
    ha_sig = (a - ha_bg) * float(ha_scale)
    o3_sig = (b - o3_bg) * float(oiii_scale)
    ha_noise = max(ha_rms * float(ha_scale), 1e-12)
    o3_noise = max(o3_rms * float(oiii_scale), 1e-12)
    ha_snr = ha_sig / ha_noise
    o3_snr = o3_sig / o3_noise

    finite = np.isfinite(ha_sig) & np.isfinite(o3_sig)
    valid_lines = finite & (ha_snr >= float(snr_min)) & (o3_snr >= float(snr_min)) & (ha_sig > 0) & (o3_sig > 0)
    ratio = np.full(a.shape, np.nan, dtype=np.float32)
    ratio[valid_lines] = (o3_sig[valid_lines] / ha_sig[valid_lines]).astype(np.float32)
    log_ratio = np.full(a.shape, np.nan, dtype=np.float32)
    log_ratio[valid_lines] = np.log10(ratio[valid_lines]).astype(np.float32)

    # Propagación de error del ratio a partir del RMS local robusto.
    ratio_err = np.full(a.shape, np.nan, dtype=np.float32)
    rel2 = (ha_noise / np.maximum(ha_sig, 1e-20)) ** 2 + (o3_noise / np.maximum(o3_sig, 1e-20)) ** 2
    ratio_err[valid_lines] = (ratio[valid_lines] * np.sqrt(rel2[valid_lines])).astype(np.float32)
    log_ratio_err = np.full(a.shape, np.nan, dtype=np.float32)
    log_ratio_err[valid_lines] = (ratio_err[valid_lines] / np.maximum(ratio[valid_lines], 1e-20) / math.log(10.0)).astype(np.float32)

    # Corrección [N II] aproximada si se facilita NII/Hα. Sin curva real de transmisión
    # se asume transmisión relativa unitaria y el resultado queda como INFERENCIA relativa.
    nii_factor = 1.0 + max(float(nii_over_ha), 0.0)
    ratio_nii_corrected = np.full(a.shape, np.nan, dtype=np.float32)
    ratio_nii_corrected[valid_lines] = (ratio[valid_lines] * nii_factor).astype(np.float32)

    # Extinción diferencial CCM89; sigue siendo una corrección relativa.
    extinction_factor = 10.0 ** (0.4 * float(ebv) * float(r_v) * (ccm89_alav(5007.0, r_v) - ccm89_alav(6563.0, r_v)))
    ratio_dered = np.full(a.shape, np.nan, dtype=np.float32)
    ratio_dered[valid_lines] = (ratio_nii_corrected[valid_lines] * extinction_factor).astype(np.float32)

    broadband_metrics = {"available": False, "state": "NO DISPONIBLE"}
    broad_sig = None
    if broad is not None:
        c = np.asarray(broad.data, dtype=np.float64)
        bb_bg, bb_rms = _science_background(c)
        broad_sig = c - bb_bg
        # Sólo una comparación morfológica: escala robusta a Hα+OIII.
        line_sum = np.maximum(ha_sig + o3_sig, 0.0)
        valid_bb = np.isfinite(broad_sig) & np.isfinite(line_sum) & (line_sum > 0) & (ha_snr >= snr_min) & (o3_snr >= snr_min)
        bb_scale = _robust_scale_to_reference(line_sum, broad_sig, valid_bb)
        line_pred = broad_sig * bb_scale
        residual = np.full(a.shape, np.nan, dtype=np.float32)
        residual[valid_bb] = (broad_sig[valid_bb] * bb_scale - line_sum[valid_bb]).astype(np.float32)
        broadband_metrics = {
            "available": True,
            "state": "PROXY MORFOLÓGICO",
            "background": float(bb_bg),
            "rms": float(bb_rms),
            "line_sum_scale_to_broadband": float(bb_scale),
            "note": "No es separación física de continuo sin throughput/calibración espectral; sirve para contraste morfológico y residual broadband vs líneas."
        }
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    arrays = {
        "ha_signal": ha_sig.astype(np.float32),
        "oiii_signal": o3_sig.astype(np.float32),
        "ha_snr": ha_snr.astype(np.float32),
        "oiii_snr": o3_snr.astype(np.float32),
        "ratio_oiii_ha": ratio,
        "ratio_oiii_ha_nii_corrected": ratio_nii_corrected,
        "ratio_oiii_ha_dereddened": ratio_dered,
        "ratio_error": ratio_err,
        "log_ratio": log_ratio,
        "log_ratio_error": log_ratio_err,
        "valid_mask": valid_lines.astype(np.uint8),
    }
    if broad_sig is not None:
        arrays["broadband_signal"] = broad_sig.astype(np.float32)
        # residual vuelve a estar en arrays vía cierre local si existe
        arrays["broadband_line_residual"] = residual
    valid_n = int(np.count_nonzero(valid_lines))
    total_n = int(valid_lines.size)

    # Detección agnóstica de regiones y anomalías píxel a píxel.
    # El baseline espacial se modela antes de llamar "anómalo" a un píxel,
    # reduciendo falsos positivos en gradientes físicos ordinarios.
    region_id = np.zeros(a.shape, dtype=np.int32)
    anomaly_z = np.full(a.shape, np.nan, dtype=np.float32)
    if valid_n >= 128:
        yy, xx = np.indices(a.shape)
        v = valid_lines & np.isfinite(log_ratio)
        xv = xx[v].astype(np.float64); yv = yy[v].astype(np.float64); zv = log_ratio[v].astype(np.float64)
        A = np.column_stack([np.ones_like(xv), xv, yv])
        try:
            beta, *_ = np.linalg.lstsq(A, zv, rcond=None)
            trend = np.full(a.shape, np.nan, dtype=np.float64)
            trend[v] = A @ beta
            resid = log_ratio.astype(np.float64) - trend
            rv = resid[v]
            rmed = float(np.median(rv))
            rsig = float(1.4826 * np.median(np.abs(rv - rmed)))
            if not math.isfinite(rsig) or rsig <= 0:
                rsig = float(np.std(rv))
            if math.isfinite(rsig) and rsig > 0:
                anomaly_z[v] = ((resid[v] - rmed) / rsig).astype(np.float32)
        except (np.linalg.LinAlgError, ValueError, FloatingPointError) as exc:
            LOG.debug("No se pudo ajustar la tendencia espacial de ratio: %s", exc)
    # Regiones conectadas de emisión válida: útiles para pasar de píxeles a objetos físicos.
    region_mask = valid_lines & np.isfinite(log_ratio) & (np.abs(anomaly_z) < 8 if np.any(np.isfinite(anomaly_z)) else True)
    labeled, nreg = ndi.label(region_mask, structure=np.ones((3,3), dtype=np.int8))
    min_region_pixels = 25
    regions = []
    if nreg:
        for rid in range(1, nreg + 1):
            yy, xx = np.where(labeled == rid); npix = int(xx.size)
            if npix < min_region_pixels:
                continue
            vals_ha = ha_sig[yy, xx]; vals_o3 = o3_sig[yy, xx]; vals_r = ratio[yy, xx]; vals_lr = log_ratio[yy, xx]
            rr = anomaly_z[yy, xx]
            regions.append({
                "region_id": int(rid), "n_pixels": npix,
                "centroid_x_px": float(np.mean(xx)), "centroid_y_px": float(np.mean(yy)),
                "ha_sum_relative": float(np.nansum(vals_ha)), "oiii_sum_relative": float(np.nansum(vals_o3)),
                "ratio_median": float(np.nanmedian(vals_r)), "ratio_mad": float(1.4826*np.nanmedian(np.abs(vals_r-np.nanmedian(vals_r)))),
                "log_ratio_median": float(np.nanmedian(vals_lr)),
                "max_abs_anomaly_z": float(np.nanmax(np.abs(rr))) if np.any(np.isfinite(rr)) else None,
                "pixel_scale_arcsec": float(pixel_scale_arcsec) if math.isfinite(float(pixel_scale_arcsec)) and float(pixel_scale_arcsec)>0 else None,
                "state": "OBSERVABLE_REGION"
            })
    arrays["region_id"] = labeled.astype(np.int32)
    arrays["ratio_anomaly_z"] = anomaly_z

    np.savez_compressed(out / "pixel_science_maps.npz", **arrays)
    atomic_json_dump({"n_regions": len(regions), "regions": regions, "min_region_pixels": min_region_pixels}, out / "pixel_science_regions.json")

    # Si Astropy existe, exporta productos FITS con estados epistemológicos claros.
    fits_exported = []
    if HAS_ASTROPY:
        for name, arr, unit_note in [
            ("ha_signal.fits", ha_sig, "relative_counts"),
            ("oiii_signal.fits", o3_sig, "relative_counts"),
            ("oiii_ha_ratio.fits", ratio, "dimensionless"),
            ("oiii_ha_ratio_error.fits", ratio_err, "dimensionless"),
            ("oiii_ha_ratio_nii_corrected.fits", ratio_nii_corrected, "dimensionless"),
            ("oiii_ha_log_ratio.fits", log_ratio, "log10_ratio"),
            ("valid_mask.fits", valid_lines.astype(np.uint8), "boolean_mask"),
            ("region_id.fits", region_id, "region_identifier"),
            ("ratio_anomaly_z.fits", anomaly_z, "standardized_pixel_residual"),
        ]:
            hdu = _fits.PrimaryHDU(np.asarray(arr, dtype=np.float32))
            hdu.header["APSSTATE"] = "OBSERVABLE" if "ratio" not in name else "PROXY_RELATIVE"
            hdu.header["APSUNIT"] = unit_note
            hdu.header["SNRMIN"] = float(snr_min)
            if math.isfinite(float(pixel_scale_arcsec)) and float(pixel_scale_arcsec) > 0:
                hdu.header["PIXSCALE"] = float(pixel_scale_arcsec)
                hdu.header["UNITNOTE"] = "arcsec/pixel supplied by user"
            hdu.writeto(out / name, overwrite=True)
            fits_exported.append(str(out / name))
        if broad_sig is not None:
            hdu = _fits.PrimaryHDU(np.asarray(arrays["broadband_line_residual"], dtype=np.float32))
            hdu.header["APSSTATE"] = "PROXY_MORPHOLOGICAL"
            hdu.header["NOTE"] = "Broadband-vs-line residual; not continuum subtraction"
            hdu.writeto(out / "broadband_line_residual.fits", overwrite=True)
            fits_exported.append(str(out / "broadband_line_residual.fits"))

    summary = {
        "engine": "AstroPhysics Pixel Science Engine v51",
        "state": "OK",
        "input": {"ha": str(ha_path), "oiii": str(oiii_path), "broadband": str(broadband_path or "")},
        "metadata_policy": {
            "wcs_required": False,
            "pixel_scale_source": "user_override" if math.isfinite(float(pixel_scale_arcsec)) and float(pixel_scale_arcsec) > 0 else "none",
            "absolute_photometry": False,
            "scientific_rule": "pixel-level relative measurements remain valid without FITS metadata; angular/absolute interpretation requires external calibration."
        },
        "background": {"ha": float(ha_bg), "ha_rms": float(ha_rms), "oiii": float(o3_bg), "oiii_rms": float(o3_rms)},
        "valid_pixels": valid_n,
        "total_pixels": total_n,
        "valid_fraction": float(valid_n / total_n) if total_n else 0.0,
        "ratio_statistics": {
            "median": float(np.nanmedian(ratio)) if valid_n else None,
            "mad": float(1.4826 * np.nanmedian(np.abs(ratio - np.nanmedian(ratio)))) if valid_n else None,
            "median_error": float(np.nanmedian(ratio_err)) if valid_n else None,
            "median_dereddened": float(np.nanmedian(ratio_dered)) if valid_n else None,
            "extinction_factor": float(extinction_factor),
            "nii_correction_factor": float(nii_factor),
        },
        "broadband": broadband_metrics,
        "regions": {"count": len(regions), "min_pixels": 25, "catalog": str(out / "pixel_science_regions.json")},
        "pixel_anomaly": {
            "available": bool(np.any(np.isfinite(anomaly_z))),
            "max_abs_z": float(np.nanmax(np.abs(anomaly_z))) if np.any(np.isfinite(anomaly_z)) else None,
            "threshold_policy": "descriptive only; FDR/multiple-testing correction must precede a discovery claim"
        },
        "products": {"npz": str(out / "pixel_science_maps.npz"), "fits": fits_exported},
        "state_labels": {
            "ha_signal": "OBSERVABLE_RELATIVE",
            "oiii_signal": "OBSERVABLE_RELATIVE",
            "ratio_oiii_ha": "OBSERVABLE_RELATIVE_RATIO",
            "ratio_oiii_ha_nii_corrected": "INFERRED_RELATIVE_CORRECTION",
            "ratio_oiii_ha_dereddened": "INFERRED_RELATIVE_CORRECTION",
            "broadband_line_residual": "PROXY_MORPHOLOGICAL" if broadband_path else "NO DISPONIBLE"
        }
    }
    atomic_json_dump(summary, out / "pixel_science_summary.json")
    return summary

# ====================================================================
# SECTION 34: MULTIBAND STACKER
# ====================================================================
def stack_multiband(
    image_paths: list,
    output_path: str,
    plane: Optional[int] = None,
    normalize: bool = True
) -> dict:
    """
    Apila múltiples imágenes de bandas estrechas (NII, SII, OIII, Hα) en un cubo 3D.

    Requiere: todas las imágenes con el mismo shape y registration previa.
    No realiza registro automático; las imágenes deben estar alineadas.

    Devuelve metadata del stack.
    """
    if not image_paths:
        return {"error": "Sin imágenes de entrada"}

    images = []
    bands = []
    for p in image_paths:
        try:
            img = load_fits(Path(p), plane=plane)
            images.append(img.data.astype(np.float32))
            # Inferir banda del nombre del archivo
            name = Path(p).stem.upper()
            if "OIII" in name or "O3" in name:
                bands.append("OIII")
            elif "HALPHA" in name or "HA" in name or "H_A" in name:
                bands.append("HA")
            elif "NII" in name or "N2" in name:
                bands.append("NII")
            elif "SII" in name or "S2" in name:
                bands.append("SII")
            else:
                bands.append("UNKNOWN")
        except Exception as exc:
            return {"error": f"No se pudo cargar {p}: {exc}"}

    # Verificar mismo shape
    shapes = set(img.shape for img in images)
    if len(shapes) > 1:
        return {"error": f"Las imágenes tienen shapes diferentes: {shapes}"}

    # Normalizar (restar fondo y escalar a unidad)
    if normalize:
        for i, img in enumerate(images):
            bg = estimate_background(img)
            img_norm = img - np.asarray(bg.bkg, dtype=np.float32)
            rms = float(np.nanmedian(np.asarray(bg.rms, dtype=np.float32)))
            rms = max(rms, 1e-6)
            images[i] = img_norm / rms

    # Stack en cubo 3D
    cube = np.stack(images, axis=0)

    # Escribir cubo FITS si Astropy está disponible
    if HAS_ASTROPY:
        hdu = _fits.PrimaryHDU(cube.astype(np.float32))
        hdu.header["NBANDS"] = len(bands)
        for i, b in enumerate(bands):
            hdu.header[f"BAND{i}"] = b
        hdu.writeto(output_path, overwrite=True)
    else:
        # Fallback: escribir como numpy .npy
        np.save(output_path, cube.astype(np.float32))

    return {
        "output_path": output_path,
        "n_bands": len(bands),
        "bands": bands,
        "shape": list(cube.shape),
        "normalized": normalize,
        "state": "OBSERVABLE"
    }


def compute_color_color_diagram(payload: dict) -> dict:
    """
    Calcula diagramas color-color ([NII]/Hα vs [SII]/Hα) si los datos existen.

    Requiere multibanda: si solo hay OIII y Hα, devuelve 'no disponible'.
    """
    # Verificar si hay datos de NII y SII
    bands = payload.get("summary", {}).get("bands_available", [])
    if not isinstance(bands, list):
        bands = []

    has_nii = "NII" in bands or any("nii" in str(k).lower() for k in payload.keys())
    has_sii = "SII" in bands or any("sii" in str(k).lower() for k in payload.keys())

    if not (has_nii and has_sii):
        return {
            "available": False,
            "reason": "Se requieren datos de [NII] y [SII] para diagrama color-color",
            "state": "NO DISPONIBLE"
        }

    # Si hay datos, calcular ratios
    # (implementación futura cuando se proporcionen datos multibanda reales)
    return {
        "available": True,
        "nii_ha_ratios": [],
        "sii_ha_ratios": [],
        "state": "OBSERVABLE"
    }


# ====================================================================
# SECTION 35: PROPER MOTION
# ====================================================================
def measure_proper_motion(
    epoch1_path: str,
    epoch2_path: str,
    pixel_scale_arcsec: float = 1.0,
    time_baseline_yr: float = 1.0
) -> dict:
    """
    Mide el movimiento propio entre dos épocas de la misma región.

    Requiere:
    - Dos imágenes de la misma región en épocas diferentes
    - Mismo shape y registration previa
    - Pixel scale conocido
    - Time baseline conocido

    Devuelve: desplazamiento mediano, RMS, y movimiento propio en mas/yr.
    """
    try:
        img1 = load_fits(Path(epoch1_path))
        img2 = load_fits(Path(epoch2_path))
    except Exception as exc:
        return {"error": f"No se pudieron cargar imágenes: {exc}", "state": "NO DISPONIBLE"}

    if img1.data.shape != img2.data.shape:
        return {"error": "Las imágenes tienen shapes diferentes", "state": "NO DISPONIBLE"}

    # Detectar estrellas en ambas imágenes. El contrato canónico es Nx3: [x, y, flux].
    bg1 = estimate_background(img1.data)
    bg2 = estimate_background(img2.data)
    stars1 = np.asarray(detect_point_sources(img1.data, bg1, fwhm_px=4.0), dtype=float)
    stars2 = np.asarray(detect_point_sources(img2.data, bg2, fwhm_px=4.0), dtype=float)

    if stars1.ndim != 2 or stars1.shape[1] < 2 or stars2.ndim != 2 or stars2.shape[1] < 2 or len(stars1) == 0 or len(stars2) == 0:
        return {"error": "No se detectaron estrellas suficientes", "state": "NO DISPONIBLE"}

    # Matching uno-a-uno para evitar reutilizar la misma estrella y sesgar el desplazamiento.
    det1 = stars1[:, :2]
    det2 = stars2[:, :2]
    pairs = _match_points_one_to_one(det1, det2, max_dist=5.0)
    if len(pairs) < 3:
        return {"error": f"Solo {len(pairs)} estrellas matched; mínimo 3", "state": "NO DISPONIBLE"}

    shifts = det2[pairs[:, 1]] - det1[pairs[:, 0]]
    shifts_x = shifts[:, 0]
    shifts_y = shifts[:, 1]

    median_dx = float(np.median(shifts_x))
    median_dy = float(np.median(shifts_y))
    rms_dx = float(np.std(shifts_x))
    rms_dy = float(np.std(shifts_y))

    baseline = float(time_baseline_yr)
    if not math.isfinite(baseline) or baseline <= 0:
        return {"error": "time_baseline_yr debe ser finito y > 0", "state": "NO DISPONIBLE"}
    scale = float(pixel_scale_arcsec)
    if not math.isfinite(scale) or scale <= 0:
        return {"error": "pixel_scale_arcsec debe ser finito y > 0", "state": "NO DISPONIBLE"}

    # Convertir a mas/yr
    shift_mas_x = median_dx * scale * 1000.0
    shift_mas_y = median_dy * scale * 1000.0
    pm_total = float(np.hypot(shift_mas_x, shift_mas_y) / baseline)

    return {
        "median_dx_px": median_dx,
        "median_dy_px": median_dy,
        "rms_dx_px": rms_dx,
        "rms_dy_px": rms_dy,
        "pm_x_masyr": shift_mas_x / baseline,
        "pm_y_masyr": shift_mas_y / baseline,
        "pm_total_masyr": pm_total,
        "n_stars_matched": int(len(pairs)),
        "time_baseline_yr": baseline,
        "state": "PROXY OBSERVACIONAL",
        "systematic_model": "traslación rígida; matching uno-a-uno; sin ajuste afín/WCS diferencial",
        "note": "Movimiento propio relativo aproximado; para astrometría científica se requiere solución WCS/transformación robusta y control de estrellas de referencia"
    }


# ====================================================================
# SECTION 41: REDSHIFT / COSMOLOGY
# ====================================================================
def apply_redshift_correction(
    observed_wavelength_nm: float,
    z: float
) -> dict:
    """
    Corrige la longitud de onda observada por redshift.
    λ_rest = λ_obs / (1 + z)

    Para objetos extragalácticos. Los remanentes locales (z≈0) no necesitan corrección.
    """
    if z < 0:
        return {"error": "Redshift negativo no físico", "state": "NO DISPONIBLE"}
    if z == 0:
        return {
            "observed_wavelength_nm": observed_wavelength_nm,
            "rest_wavelength_nm": observed_wavelength_nm,
            "z": 0.0,
            "correction_applied": False,
            "state": "OBSERVABLE",
            "note": "Objeto local (z=0); no se requiere corrección"
        }

    rest_wl = observed_wavelength_nm / (1.0 + z)
    return {
        "observed_wavelength_nm": observed_wavelength_nm,
        "rest_wavelength_nm": rest_wl,
        "z": z,
        "correction_applied": True,
        "state": "RESULTADO CALIBRADO",
        "note": f"Longitud de onda corregida por redshift z={z}"
    }


def luminosity_distance(z: float) -> float:
    """
    Calcula la distancia de luminosidad para z pequeño (aproximación Hubble).
    D_L = c * z / H0

    Solo válida para z << 1. Para z grande, requiere cosmología completa.
    """
    if z <= 0:
        return 0.0
    H0 = 70.0  # km/s/Mpc (constante de Hubble aproximada)
    c_km_s = 299792.458  # velocidad de la luz en km/s
    d_l_mpc = c_km_s * z / H0
    d_l_pc = d_l_mpc * 1e6
    return d_l_pc


# ====================================================================
# SECTION 50: PROVENANCE
# ====================================================================
def build_provenance_chain(payload: dict) -> dict:
    """
    Construye la cadena de provenance completa del resultado.

    Registra: inputs, versiones, parámetros, grid, calibración, y cada paso
    del pipeline con su estado científico.
    """
    payload = normalize_scientific_payload(payload)
    manifest = payload.get("manifest", {})
    summary = payload.get("summary", {})

    provenance = {
        "software_version": __version__,
        "schema_version": SCHEMA_VERSION,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": payload.get("inputs", {}),
        "configuration": manifest.get("configuration", {}),
        "configuration_sha256": manifest.get("configuration_sha256", ""),
        "pipeline_steps": [
            {
                "step": "fits_loading",
                "description": "Carga de FITS con validación de HDU y plano explícito",
                "state": "OBSERVABLE"
            },
            {
                "step": "calibration_frames",
                "description": "Aplicación de bias/dark/flat si se proporcionaron",
                "state": "OBSERVABLE" if manifest.get("calibration_applied") or (manifest.get("background", {}) or {}).get("ccd_calibration_frames") else "NO APLICADO"
            },
            {
                "step": "background_estimation",
                "description": "Estimación de fondo y varianza",
                "state": "OBSERVABLE"
            },
            {
                "step": "source_detection",
                "description": "Detección de fuentes y separación estrella/choque",
                "state": "OBSERVABLE"
            },
            {
                "step": "registration",
                "description": f"Registro {summary.get('registration', {}).get('method', 'unknown')}",
                "state": "OBSERVABLE"
            },
            {
                "step": "filament_detection",
                "description": "Detección de filamentos y extracción de perfiles",
                "state": "OBSERVABLE"
            },
            {
                "step": "ratio_computation",
                "description": "Cálculo de ratio [OIII]/Hα y mapa de enfriamiento",
                "state": "PROXY OBSERVACIONAL"
            },
            {
                "step": "grid_inversion",
                "description": "Inversión de modelo (si se aplicó)",
                "state": "INFERENCIA DE MODELO" if manifest.get("grid_info") else "NO APLICADO"
            },
            {
                "step": "literature_comparison",
                "description": "Comparación con literatura (si hay target)",
                "state": "PROXY OBSERVACIONAL"
            }
            ,{
                "step": "discovery_ai",
                "description": "Clasificación de fenómenos conocidos y detección de outliers mediante ML entrenado con observaciones reales",
                "state": summary.get("discovery_ai",{}).get("state", "NO DISPONIBLE")
            }
        ],
        "grid_provenance": manifest.get("grid_info") or manifest.get("grid") or summary.get("grid_manifest") or {},
        "filter_curves": {
            "oiii_sha256": manifest.get("filter_curve_sha256", {}).get("oiii", ""),
            "ha_sha256": manifest.get("filter_curve_sha256", {}).get("ha", "")
        },
        "calibration_provenance": {
            "calibrated": summary.get("calibration", {}).get("calibrated", False),
            "method": summary.get("calibration", {}).get("calibration_basis", "instrumental"),
            "warning": summary.get("calibration", {}).get("calibration_warning", "")
        },
        "reproducibility": {
            "configuration_sha256": manifest.get("configuration_sha256", ""),
            "filter_curve_sha256": manifest.get("filter_curve_sha256", {}),
            "grid_sha256": (manifest.get("grid_info") or manifest.get("grid") or summary.get("grid_manifest") or {}).get("sha256", ""),
            "seed": manifest.get("configuration", {}).get("seed", None)
        }
    }

    return provenance


# ====================================================================
# SECTION 28: 2D PHYSICAL QUANTITY MAPS
# ====================================================================
def compute_physical_maps(payload: dict) -> dict:
    """
    Calcula mapas 2D de todas las magnitudes físicas disponibles.

    Cada mapa se etiqueta con su estado científico.
    """
    payload = normalize_scientific_payload(payload)
    maps = {}
    grid_info = ((payload.get("manifest", {}) or {}).get("grid_info") or (payload.get("manifest", {}) or {}).get("grid") or (payload.get("summary", {}) or {}).get("grid_manifest") or {})

    # 1. Mapa de ratio [OIII]/Hα (siempre disponible)
    maps["ratio_oiii_ha"] = {
        "description": "Mapa de ratio [OIII]/Hα",
        "state": "OBSERVABLE",
        "unit": "adimensional"
    }

    # 2. Mapa de SNR
    maps["snr"] = {
        "description": "Mapa de señal-ruido",
        "state": "OBSERVABLE",
        "unit": "sigma"
    }

    # 3. Mapa de fondo
    maps["background"] = {
        "description": "Mapa de fondo estimado",
        "state": "OBSERVABLE",
        "unit": "ADU"
    }

    # 4. Mapa de varianza
    maps["variance"] = {
        "description": "Mapa de varianza local",
        "state": "OBSERVABLE",
        "unit": "ADU^2"
    }

    # 5. Mapa de cooling proxy
    maps["cooling_proxy"] = {
        "description": "Proxy de régimen de excitación/enfriamiento",
        "state": "PROXY OBSERVACIONAL",
        "unit": "adimensional"
    }

    # 6. Mapa de velocidad (solo si hay grid validado)
    if grid_info and grid_info.get("model_family", "heuristic_demo_grid") not in ("heuristic_demo_grid", "unknown"):
        maps["velocity"] = {
            "description": "Mapa de velocidad de choque (inversión de grid)",
            "state": "INFERENCIA DE MODELO",
            "unit": "km/s"
        }
    else:
        maps["velocity"] = {
            "description": "No disponible sin grid MAPPINGS/3MdB validado",
            "state": "NO DISPONIBLE",
            "unit": "N/A"
        }

    # 7. Mapa de temperatura (solo si hay grid validado + calibración)
    if grid_info and grid_info.get("model_family", "heuristic_demo_grid") not in ("heuristic_demo_grid", "unknown"):
        maps["temperature"] = {
            "description": "Mapa de temperatura post-shock (inversión de grid)",
            "state": "INFERENCIA DE MODELO",
            "unit": "K"
        }
    else:
        maps["temperature"] = {
            "description": "No disponible sin grid MAPPINGS/3MdB validado",
            "state": "NO DISPONIBLE",
            "unit": "N/A"
        }

    return maps


# ====================================================================
# SECTION 27: RADIAL PROFILES
# ====================================================================
def extract_radial_profile(
    image_data: np.ndarray,
    center_x: float,
    center_y: float,
    max_radius_px: float = None,
    bin_size_px: float = 1.0
) -> dict:
    """
    Extrae un perfil radial desde un punto central.

    Útil para remanentes con simetría aproximadamente circular (Cas A, Tycho).
    Para filamentos lineales, usar extract_profile.
    """
    H, W = image_data.shape
    if max_radius_px is None:
        max_radius_px = min(H, W) / 2.0

    yy, xx = np.mgrid[0:H, 0:W]
    r = np.sqrt((xx - center_x) ** 2 + (yy - center_y) ** 2)

    mask = r <= max_radius_px
    r_flat = r[mask]
    data_flat = image_data[mask]

    # Binear por radio
    n_bins = int(max_radius_px / bin_size_px)
    if n_bins < 1:
        n_bins = 1

    bin_edges = np.linspace(0, max_radius_px, n_bins + 1)
    bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])
    bin_values = np.full(n_bins, np.nan)
    bin_errors = np.full(n_bins, np.nan)
    bin_n = np.zeros(n_bins, dtype=int)

    for i in range(n_bins):
        sel = (r_flat >= bin_edges[i]) & (r_flat < bin_edges[i + 1])
        if np.any(sel):
            bin_values[i] = np.median(data_flat[sel])
            bin_errors[i] = np.std(data_flat[sel]) / max(np.sqrt(np.sum(sel)), 1)
            bin_n[i] = np.sum(sel)

    return {
        "radius_px": bin_centers.tolist(),
        "intensity": bin_values.tolist(),
        "error": bin_errors.tolist(),
        "n_pixels": bin_n.tolist(),
        "center": (float(center_x), float(center_y)),
        "max_radius_px": float(max_radius_px),
        "state": "OBSERVABLE"
    }


# ====================================================================
# SECTION 45: REPRODUCIBLE ENVIRONMENT EXPORT
# ====================================================================
def export_environment(output_path: str = "environment_export.json") -> str:
    """Exporta el estado del entorno para reproducibilidad."""
    import platform
    env = {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "packages": {
            "numpy": np.__version__,
            "scipy": getattr(__import__("scipy"), "__version__", "not installed"),
            "astropy": getattr(__import__("astropy"), "__version__", "not installed") if HAS_ASTROPY else "not installed",
            "photutils": getattr(__import__("photutils"), "__version__", "not installed") if HAS_PHOTUTILS else "not installed",
            "skimage": getattr(__import__("skimage"), "__version__", "not installed") if HAS_SKIMAGE else "not installed",
            "sklearn": getattr(__import__("sklearn"), "__version__", "not installed") if HAS_SKLEARN else "not installed",
            "matplotlib": getattr(__import__("matplotlib"), "__version__", "not installed") if HAS_MPL else "not installed",
        },
        "software_version": __version__,
        "schema_version": SCHEMA_VERSION,
        "available_ram_gb": round(_available_ram_gb(), 1),
        "cpu_count": os.cpu_count()
    }
    Path(output_path).write_text(json.dumps(env, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path


# ====================================================================
# v29 FEATURE: Absolute photometric calibration + atmospheric extinction
# Section 22 (extinction) + Section 24 (photometric calibration)
# ====================================================================

def compute_airmass(zenith_angle_deg: float) -> float:
    """Computa airmass X = sec(z) con corrección de Kasten-Young para z > 70°.

    State: OBSERVABLE (direct measurement from pointing geometry).
    """
    if zenith_angle_deg < 0 or zenith_angle_deg > 90:
        return float("nan")
    z = math.radians(zenith_angle_deg)
    if zenith_angle_deg <= 70:
        return 1.0 / math.cos(z)
    # Kasten-Young correction for high zenith angles
    return 1.0 / (math.cos(z) + 0.50572 * (96.07995 - zenith_angle_deg) ** (-1.6364))


def apply_atmospheric_extinction(flux_adu: float, airmass: float,
                                  k_extinction: float,
                                  k_err: float = 0.0) -> dict:
    """Corrige flujo por extinción atmosférica.

    F_corr = F_obs * 10^(0.4 * k * X)

    Inputs requeridos:
      - flux_adu: flujo observado en ADU/s (PROXY OBSERVACIONAL)
      - airmass: masa de aire (OBSERVABLE)
      - k_extinction: coeficiente de extinción k_λ (CALIBRADO)
      - k_err: error en k_λ (opcional)

    Retorna dict con flujo corregido, error, y estado.
    """
    if not math.isfinite(flux_adu) or not math.isfinite(airmass) or not math.isfinite(k_extinction):
        return {"flux_corrected": None, "state": "NO DISPONIBLE",
                "error": "Inputs no finitos"}
    if airmass < 1.0 or k_extinction < 0:
        return {"flux_corrected": None, "state": "NO DISPONIBLE",
                "error": f"Airmass={airmass} o k_ext={k_extinction} inválidos"}
    extinction_mag = k_extinction * airmass
    correction = 10 ** (0.4 * extinction_mag)
    flux_corrected = flux_adu * correction
    # Error propagation: dF/F = 0.4 * ln(10) * k_err * X
    flux_err = abs(flux_corrected) * 0.4 * math.log(10) * k_err * airmass if k_err > 0 else None
    return {
        "flux_corrected": float(flux_corrected),
        "flux_err": float(flux_err) if flux_err is not None else None,
        "extinction_mag": float(extinction_mag),
        "correction_factor": float(correction),
        "airmass": float(airmass),
        "k_extinction": float(k_extinction),
        "state": "RESULTADO CALIBRADO" if k_err > 0 else "PROXY OBSERVACIONAL",
        "note": "Corrección atmosférica aplicada; requiere k_λ medido localmente"
    }


def absolute_photometric_calibration(flux_adu: float, zeropoint: float,
                                     exposure_s: float, gain: float = 1.0,
                                     airmass: float = None,
                                     k_extinction: float = None,
                                     k_err: float = 0.0,
                                     flux_adu_err: float = None,
                                     zeropoint_err: float = None,
                                     zeropoint_source: str = "") -> dict:
    """Convierte una cuenta instrumental a tasa y magnitud con zeropoint.

    No se declara flujo físico absoluto (erg/s/cm^2) sin una definición de banda/throughput y
    referencia fotométrica apropiada. El resultado numérico principal es e-/s y magnitud.

    Pipeline:
      1. ADU → electrons: e = ADU * gain
      2. electrons → rate: e/s = e / exposure_s
      3. Aplicar extinción atmosférica (si airmass + k disponibles)
      4. Aplicar zeropoint: mag = ZP - 2.5*log10(e/s)
      5. Flujo físico: F = F0 * 10^(-0.4*mag)

    Solo se etiqueta RESULTADO CALIBRADO si TODOS los inputs están presentes
    Y el zeropoint tiene una referencia documentada (zeropoint_source) con su
    incertidumbre (zeropoint_err). Sin zeropoint_err o sin fuente documentada,
    se etiqueta como PROXY OBSERVACIONAL u OBSERVABLE.
    """
    if not all(math.isfinite(x) for x in (flux_adu, zeropoint, exposure_s, gain) if x is not None):
        return {"state": "NO DISPONIBLE", "error": "Inputs no finitos"}
    if exposure_s <= 0 or gain <= 0:
        return {"state": "NO DISPONIBLE", "error": "exposure_s y gain deben ser > 0"}

    # Step 1-2: ADU → electrons/s
    electrons = flux_adu * gain
    rate = electrons / exposure_s

    # Error en rate
    if flux_adu_err is not None and math.isfinite(flux_adu_err):
        rate_err = flux_adu_err * gain / exposure_s
    else:
        rate_err = None

    # Step 3: Atmospheric extinction (optional)
    extinction_applied = False
    if airmass is not None and k_extinction is not None and math.isfinite(airmass) and math.isfinite(k_extinction):
        ext_result = apply_atmospheric_extinction(rate, airmass, k_extinction, k_err)
        if ext_result.get("state") != "NO DISPONIBLE":
            rate = ext_result["flux_corrected"]
            if rate_err is not None and ext_result.get("flux_err") is not None:
                rate_err = math.sqrt(rate_err**2 + ext_result["flux_err"]**2)
            extinction_applied = True

    # Step 4: Magnitude from zeropoint
    if rate > 0:
        magnitude = zeropoint - 2.5 * math.log10(rate)
    else:
        magnitude = None

    # Step 5: No se inventa flujo físico absoluto. El zero-point instrumental sólo fija magnitud
    # en el sistema de calibración utilizado; un flujo físico requiere conocer explícitamente
    # la convención fotométrica y la respuesta espectral integrada del sistema.

    has_zp_error = zeropoint_err is not None and math.isfinite(zeropoint_err) and zeropoint_err > 0
    has_zp_source = bool(zeropoint_source and zeropoint_source.strip())
    has_all_inputs = (extinction_applied and rate_err is not None and has_zp_error and has_zp_source)
    if has_all_inputs:
        state = "RESULTADO CALIBRADO"
    elif extinction_applied or has_zp_error:
        state = "PROXY OBSERVACIONAL"
    else:
        state = "OBSERVABLE"

    return {
        "magnitude": float(magnitude) if magnitude is not None else None,
        "magnitude_err": float(math.sqrt((rate_err / rate * 2.5 / math.log(10))**2 + (zeropoint_err or 0.0)**2)) if (rate_err is not None and rate_err >= 0 and rate > 0) else (float(zeropoint_err) if has_zp_error else None),
        "flux_rate_electrons_per_s": float(rate),
        "flux_rate_err": float(rate_err) if rate_err is not None else None,
        "extinction_applied": extinction_applied,
        "state": state,
        "note": ("Flujo calibrado con zeropoint + extinción atmosférica" if has_all_inputs
                 else "Flujo instrumental sin extinción atmosférica" if not extinction_applied
                 else "Extinción aplicada; falta zeropoint_err o fuente documentada"),
        "inputs": {
            "zeropoint": zeropoint,
            "zeropoint_err": zeropoint_err,
            "zeropoint_source": zeropoint_source,
            "exposure_s": exposure_s,
            "gain": gain,
            "airmass": airmass,
            "k_extinction": k_extinction
        }
    }


# ====================================================================
# v29 FEATURE: PSF / seeing / source quality module
# Section 16 (PSF) + Section 46 (QC)
# ====================================================================

def measure_source_quality(image: np.ndarray, x: float, y: float,
                           cutout_size: int = 25,
                           gain: float = 1.0,
                           saturation_level: float = None) -> dict:
    """Mide la calidad de una fuente detectada en (x, y).

    Mide: FWHM, elipticidad, agudeza (sharpness), flag de saturación,
    SNR local, y flag de aislamiento.

    Usa photutils si está disponible; fallback con momentos 2D.
    """
    h, w = image.shape
    half = cutout_size // 2
    ix, iy = int(round(x)), int(round(y))
    x0 = max(0, ix - half); x1 = min(w, ix + half + 1)
    y0 = max(0, iy - half); y1 = min(h, iy + half + 1)
    if x1 - x0 < 5 or y1 - y0 < 5:
        return {"state": "NO DISPONIBLE", "error": "Cutout demasiado pequeño"}

    stamp = image[y0:y1, x0:x1].astype(float)
    bg = np.median(stamp)
    stamp_bg = stamp - bg
    peak = np.max(stamp_bg)

    # Saturation check
    saturated = False
    if saturation_level is not None:
        saturated = bool(np.max(stamp) >= saturation_level * 0.95)
    else:
        # Auto-detect: if peak > 0.95 * max possible for dtype
        if image.dtype.kind == 'i' and np.max(stamp) >= 0.95 * np.iinfo(image.dtype).max:
            saturated = True

    # Local noise
    noise = np.std(stamp_bg[stamp_bg < 0.3 * peak]) if peak > 0 else 1.0
    snr = float(peak / noise) if noise > 0 else 0.0

    # FWHM and ellipticity via 2D moments (fallback method)
    cy, cx = np.mgrid[0:stamp_bg.shape[0], 0:stamp_bg.shape[1]]
    total = np.sum(stamp_bg[stamp_bg > 0]) if np.any(stamp_bg > 0) else 1.0
    if total <= 0:
        return {"state": "NO DISPONIBLE", "error": "Sin señal positiva"}

    stamp_pos = np.where(stamp_bg > 0, stamp_bg, 0)
    total = max(np.sum(stamp_pos), 1.0)
    mx = np.sum(cx * stamp_pos) / total
    my = np.sum(cy * stamp_pos) / total
    # Second moments
    mxx = np.sum(((cx - mx) ** 2) * stamp_pos) / total
    myy = np.sum(((cy - my) ** 2) * stamp_pos) / total
    mxy = np.sum((cx - mx) * (cy - my) * stamp_pos) / total
    # FWHM = 2 * sqrt(2 * ln(2)) * sigma
    sigma_avg = math.sqrt((mxx + myy) / 2.0)
    fwhm = 2.0 * math.sqrt(2.0 * math.log(2.0)) * sigma_avg if sigma_avg > 0 else None
    # Ellipticity = 1 - b/a where b/a = sqrt((a^2 - c^2) / (a^2 + c^2))
    a_squared = (mxx + myy) / 2.0 + math.sqrt(((mxx - myy) / 2.0) ** 2 + mxy ** 2)
    b_squared = (mxx + myy) / 2.0 - math.sqrt(((mxx - myy) / 2.0) ** 2 + mxy ** 2)
    if a_squared > 0:
        ba_ratio = math.sqrt(max(b_squared, 0) / a_squared)
        ellipticity = 1.0 - ba_ratio
    else:
        ba_ratio = None
        ellipticity = None

    # Sharpness: ratio of peak to mean of 3x3 central region
    cy_stamp, cx_stamp = stamp_bg.shape[0] // 2, stamp_bg.shape[1] // 2
    r = 1
    central_region = stamp_bg[max(0, cy_stamp - r):cy_stamp + r + 1,
                              max(0, cx_stamp - r):cx_stamp + r + 1]
    mean_central = np.mean(central_region) if central_region.size > 0 else 0
    sharpness = float(peak / mean_central) if mean_central > 0 else None

    # Isolation: count connected components above 30% of peak (not pixel count)
    threshold = 0.3 * peak
    labeled, n_components = ndi.label(stamp_bg > threshold)
    isolated = n_components <= 1  # Only the central source

    return {
        "fwhm_px": float(fwhm) if fwhm is not None else None,
        "ellipticity": float(ellipticity) if ellipticity is not None else None,
        "sharpness": sharpness,
        "snr_local": float(snr),
        "saturated": saturated,
        "isolated": isolated,
        "n_peaks_in_stamp": n_components,
        "peak_adu": float(peak),
        "background_adu": float(bg),
        "noise_adu": float(noise),
        "state": "OBSERVABLE",
        "note": "Medida directa desde imagen; FWHM via momentos 2D"
    }


def measure_psf_quality(image: np.ndarray, sources: list,
                        gain: float = 1.0,
                        saturation_level: float = None) -> dict:
    """Mide la calidad PSF promedio de un conjunto de fuentes detectadas.

    Returns:
      - median_fwhm, median_ellipticity, n_saturated, n_isolated
      - seeing estimate (FWHM in pixels)
      - quality flags
    """
    results = []
    for src in sources:
        sx = src.get("x", src.get("x_pix", 0))
        sy = src.get("y", src.get("y_pix", 0))
        if sx <= 0 or sy <= 0:
            continue
        sq = measure_source_quality(image, sx, sy, gain=gain, saturation_level=saturation_level)
        if sq.get("state") != "NO DISPONIBLE":
            results.append(sq)
    if not results:
        return {"state": "NO DISPONIBLE", "error": "Sin fuentes medibles"}
    fwhms = [r["fwhm_px"] for r in results if r.get("fwhm_px") is not None and math.isfinite(r["fwhm_px"])]
    ells = [r["ellipticity"] for r in results if r.get("ellipticity") is not None and math.isfinite(r["ellipticity"])]
    snrs = [r["snr_local"] for r in results if r.get("snr_local") is not None]
    n_saturated = sum(1 for r in results if r.get("saturated", False))
    n_isolated = sum(1 for r in results if r.get("isolated", False))
    return {
        "median_fwhm_px": float(np.median(fwhms)) if fwhms else None,
        "std_fwhm_px": float(np.std(fwhms)) if fwhms else None,
        "median_ellipticity": float(np.median(ells)) if ells else None,
        "median_snr": float(np.median(snrs)) if snrs else None,
        "n_sources": len(results),
        "n_saturated": n_saturated,
        "n_isolated": n_isolated,
        "seeing_px": float(np.median(fwhms)) if fwhms else None,
        "quality_flag": ("GOOD" if fwhms and np.median(fwhms) < 5 and n_saturated == 0
                         else "WARN" if fwhms and np.median(fwhms) < 8
                         else "POOR"),
        "state": "OBSERVABLE",
        "note": "FWHM medido via momentos 2D; seeing = FWHM mediano"
    }


# ====================================================================
# v29 FEATURE: WCS validation + Gaia cross-match
# Section 12 (astrometric registration) + Section 42 (Gaia)
# ====================================================================

def validate_wcs(wcs_header: dict, image_shape: tuple) -> dict:
    """Valida que un WCS FITS sea consistente y utilizable.

    Comprueba: existencia de CRPIX/CRVAL/CD (o CDELT+CROTA),
    consistencia de escala, cobertura, y no-NaN.

    Retorna dict con is_valid, scale_arcsec_per_px, rotation_deg, state.
    """
    required_keys = ("CRPIX1", "CRPIX2", "CRVAL1", "CRVAL2")
    has_required = all(k in wcs_header for k in required_keys)
    has_cd = "CD1_1" in wcs_header and "CD1_2" in wcs_header
    has_cdelt = "CDELT1" in wcs_header and "CDELT2" in wcs_header
    if not has_required or not (has_cd or has_cdelt):
        return {"is_valid": False, "state": "NO DISPONIBLE",
                "error": "Faltan claves WCS requeridas (CRPIX/CRVAL/CD o CDELT)"}
    try:
        if has_cd:
            cd11 = float(wcs_header["CD1_1"]); cd12 = float(wcs_header["CD1_2"])
            cd21 = float(wcs_header["CD2_1"]); cd22 = float(wcs_header["CD2_2"])
            scale1 = math.sqrt(cd11**2 + cd12**2) * 3600  # arcsec/px
            scale2 = math.sqrt(cd21**2 + cd22**2) * 3600
            rotation = math.degrees(math.atan2(cd12, cd11))
        else:
            cdelt1 = abs(float(wcs_header["CDELT1"])) * 3600
            cdelt2 = abs(float(wcs_header["CDELT2"])) * 3600
            scale1 = cdelt1; scale2 = cdelt2
            rotation = float(wcs_header.get("CROTA2", 0.0))
        scale_arcsec = (scale1 + scale2) / 2.0
        # Check scale consistency
        scale_ratio = max(scale1, scale2) / max(min(scale1, scale2), 1e-12)
        consistent = scale_ratio < 1.1  # Within 10%
        # Check coverage
        h, w = image_shape
        ra_center = float(wcs_header["CRVAL1"])
        dec_center = float(wcs_header["CRVAL2"])
        coverage_ra = scale1 * w / 3600  # degrees
        coverage_dec = scale2 * h / 3600
        return {
            "is_valid": consistent,
            "scale_arcsec_per_px": float(scale_arcsec),
            "scale1": float(scale1), "scale2": float(scale2),
            "rotation_deg": float(rotation),
            "scale_consistent": consistent,
            "ra_center_deg": ra_center,
            "dec_center_deg": dec_center,
            "coverage_ra_deg": float(coverage_ra),
            "coverage_dec_deg": float(coverage_dec),
            "state": "OBSERVABLE",
            "note": "WCS validado desde header FITS"
        }
    except Exception as exc:
        return {"is_valid": False, "state": "NO DISPONIBLE", "error": str(exc)}


def crossmatch_gaia_safe(ra_deg: float, dec_deg: float,
                         radius_arcsec: float = 30.0,
                         mag_limit: float = 18.0,
                         max_rows: int = 100) -> dict:
    """Cross-match con Gaia DR3 (si astroquery disponible).

    NUNCA marca resultados como descubrimientos.
    Retorna: lista de fuentes Gaia, residuales astrométricos, QC.
    """
    if not HAS_GAIA:
        return {"state": "NO DISPONIBLE",
                "error": "astroquery no instalado; ejecutar: pip install astroquery",
                "gaia_available": False}
    try:
        from astroquery.gaia import Gaia
        radius_deg = radius_arcsec / 3600.0
        query = (
            f"SELECT source_id, ra, dec, phot_g_mean_mag, pmra, pmdec, parallax "
            f"FROM gaiadr3.gaia_source "
            f"WHERE CONTAINS(POINT('ICRS', ra, dec), "
            f"CIRCLE('ICRS', {ra_deg}, {dec_deg}, {radius_deg})) = 1 "
            f"AND phot_g_mean_mag < {mag_limit} "
            f"ORDER BY phot_g_mean_mag ASC "
            f"LIMIT {max_rows}"
        )
        job = Gaia.launch_job(query)
        tbl = job.get_results()
        n_matched = len(tbl)
        sources = []
        for i in range(n_matched):
            sources.append({
                "source_id": str(tbl["source_id"][i]),
                "ra_deg": float(tbl["ra"][i]),
                "dec_deg": float(tbl["dec"][i]),
                "mag_g": float(tbl["phot_g_mean_mag"][i]) if tbl["phot_g_mean_mag"][i] else None,
                "pmra_mas_yr": float(tbl["pmra"][i]) if tbl["pmra"][i] else None,
                "pmdec_mas_yr": float(tbl["pmdec"][i]) if tbl["pmdec"][i] else None,
                "parallax_mas": float(tbl["parallax"][i]) if tbl["parallax"][i] else None,
            })
        return {
            "gaia_available": True,
            "n_matched": n_matched,
            "sources": sources[:max_rows],
            "state": "OBSERVABLE",
            "note": "Cross-match Gaia DR3; NO constituye descubrimiento astronómico"
        }
    except Exception as exc:
        return {"state": "NO DISPONIBLE", "error": str(exc), "gaia_available": False}


# ====================================================================
# v29 FEATURE: Monte Carlo grid interpolation inference
# Section 39 (inference) - validated grid only
# ====================================================================

# ====================================================================
# v30: CALIBRACION ESPECTROFOTOMETRICA DE COLOR (SPCC-compatible)
# ====================================================================
def _gaussian_response(wave_nm, center_nm, fwhm_nm, peak):
    wave_nm=np.asarray(wave_nm,float)
    sigma=float(fwhm_nm)/2.354820045
    return float(peak)*np.exp(-0.5*((wave_nm-float(center_nm))/sigma)**2)

def _filter_response_callable(filter_name, channel, curve=None, grid_nm=None):
    if curve is not None:
        def fn(w): return np.interp(np.asarray(w,float), curve.wavelength_nm, curve.transmission, left=0.0, right=0.0)
        return fn, "measured_curve"
    if filter_name == "SVBONY SV220 Hα/OIII 7 nm":
        center = 500.7 if channel == "oiii" else 656.3
        fwhm = 7.0
        peak = 0.90 if channel == "oiii" else 0.94
        return lambda w: _gaussian_response(w,center,fwhm,peak), "nominal_SVBONY_7nm_proxy"
    if filter_name == "Optolong L-Quad Enhance":
        # L-QEF is a four-band broadband filter. The official product page gives
        # the qualitative passband design but the plotted spectrum must not be
        # digitized/invented here as a calibration curve. Keep it identifiable,
        # but require a measured T(lambda) for quantitative spectrophotometry.
        return None, "broadband_LQEF_requires_measured_curve"
    return None, "no_response_curve"

def _get_gaia_xp_spectra(source_ids):
    if not HAS_GAIA:
        return {}, "Gaia/astroquery no disponible"
    ids=[str(x) for x in source_ids if str(x).strip()]
    if not ids:
        return {}, "sin source_id Gaia"
    try:
        # Gaia DataLink/astroquery supports XP_SAMPLED for Gaia DR3.
        loaded = Gaia.load_data(ids=ids[:5000], data_release="Gaia DR3",
                                retrieval_type="XP_SAMPLED",
                                data_structure="DATAMODEL_GAIA")
        out={}
        for key, value in (loaded or {}).items():
            try:
                for row in value:
                    sid=str(row["source_id"]) if "source_id" in row.colnames else None
                    if sid: out[sid]=row
            except Exception:
                continue
        return out, "Gaia DR3 XP_SAMPLED"
    except Exception as exc:
        return {}, f"Gaia XP no disponible: {type(exc).__name__}: {exc}"

def broadband_context_diagnostics(im_broadband: FitsImage, im_ha: FitsImage, im_o3: FitsImage,
                                  im_ha_starless: Optional[FitsImage]=None,
                                  im_o3_starless: Optional[FitsImage]=None) -> dict:
    """Caracteriza una toma broadband (L-QEF) como canal contextual del objeto.

    No convierte la imagen L-QEF en Halpha/OIII. Su objetivo es cuantificar cuánto
    de la estructura observada también existe en banda ancha y separar, de forma
    reproducible, señal de continuo/estrellas frente a estructuras dominadas por
    líneas estrechas. Los índices son diagnósticos observacionales, no abundancias.
    """
    try:
        b=np.asarray(im_broadband.data,float)
        h=np.asarray(im_ha.data,float); o=np.asarray(im_o3.data,float)
        if b.shape != h.shape or b.shape != o.shape:
            return {"state":"NO DISPONIBLE","reason":"L-QEF y canales estrechos con formas distintas"}
        def robust_scale(a):
            med=float(np.nanmedian(a)); mad=float(np.nanmedian(np.abs(a-med)))*1.4826
            return med, max(mad, 1e-12)
        mb,sb=robust_scale(b); mh,sh=robust_scale(h); mo,so=robust_scale(o)
        bn=(b-mb)/sb; hn=(h-mh)/sh; on=(o-mo)/so
        valid=np.isfinite(bn)&np.isfinite(hn)&np.isfinite(on)
        if valid.sum()<100:
            return {"state":"NO DISPONIBLE","reason":"Demasiados valores no finitos"}
        def corr(a,c):
            x=np.asarray(a[valid]); y=np.asarray(c[valid])
            if np.std(x)<=0 or np.std(y)<=0: return float('nan')
            return float(np.corrcoef(x,y)[0,1])
        corr_ha=corr(bn,hn); corr_o3=corr(bn,on)
        # A higher narrowband-vs-broadband contrast suggests line-dominated structure,
        # while the broadband channel preserves continuum-rich morphology.
        line_strength=float(np.nanmedian(np.hypot(hn,on)-0.5*bn))
        if im_ha_starless is not None and im_o3_starless is not None:
            hs=np.asarray(im_ha_starless.data,float); os=np.asarray(im_o3_starless.data,float)
            cont_ratio=float(np.nanmedian((b-mb)/np.maximum(np.hypot(hs,os),1e-12)))
        else:
            cont_ratio=float('nan')
        return {
            "state":"OBSERVABLE",
            "filter_family":"Optolong L-Quad Enhance",
            "role":"broadband_context",
            "corr_lqef_ha":corr_ha,
            "corr_lqef_oiii":corr_o3,
            "line_structure_index":line_strength,
            "broadband_vs_starless_line_ratio_proxy":cont_ratio,
            "interpretation":"contexto continuo+lineas; no sustituye a la separación Halpha/OIII",
            "calibration_status":"proxy unless measured system response is supplied",
        }
    except Exception as exc:
        return {"state":"NO DISPONIBLE","reason":f"Diagnóstico L-QEF falló: {type(exc).__name__}: {exc}"}


def spectrophotometric_color_calibration(
        im_ha: FitsImage, im_o3: FitsImage, bkg_ha: Background, bkg_o3: Background,
        stellar_catalog: list, ha_filter: str, oiii_filter: str,
        ha_curve: Optional[FilterTransmission]=None, oiii_curve: Optional[FilterTransmission]=None,
        min_stars: int=8) -> dict:
    """Calibración de color basada en fotometría sintética de espectros Gaia DR3 XP.

    Es conceptualmente compatible con SPCC público: WCS + crossmatch Gaia + espectro XP +
    integración sintética en las respuestas de los filtros. No pretende reproducir el binario
    propietario de PixInsight ni sus decisiones internas de weighting/normalización.
    """
    rows=[r for r in (stellar_catalog or [])
          if r.get("source_id") is not None and
             math.isfinite(finite(r.get("x_px"),np.nan)) and math.isfinite(finite(r.get("y_px"),np.nan)) and
             not bool(r.get("saturated",False))]
    if len(rows)<min_stars:
        return {"state":"NO DISPONIBLE","reason":f"Solo {len(rows)} estrellas Gaia aptas; se requieren >= {min_stars}","n_stars_used":len(rows)}
    source_ids=[r.get("source_id") for r in rows]
    xp, xp_note = _get_gaia_xp_spectra(source_ids)
    if not xp:
        return {"state":"NO DISPONIBLE","reason":xp_note,"n_stars_used":0}
    ro, ro_method = _filter_response_callable(oiii_filter,"oiii",oiii_curve)
    rh, rh_method = _filter_response_callable(ha_filter,"ha",ha_curve)
    if ro is None or rh is None:
        return {"state":"NO DISPONIBLE","reason":"Se requiere curva T(lambda) real para este filtro; el preset L-eNhance no inventa una respuesta espectral.","n_stars_used":0}
    # Uniform wavelength grid around optical lines.
    wave=np.linspace(380.0,760.0,3801)
    resp_o=np.asarray(ro(wave),float); resp_h=np.asarray(rh(wave),float)
    if np.max(resp_o)<=0 or np.max(resp_h)<=0:
        return {"state":"NO DISPONIBLE","reason":"Respuesta de filtro degenerada","n_stars_used":0}
    obs_o=[]; obs_h=[]; pred_o=[]; pred_h=[]; used=[]
    # Reuse a simple aperture+annulus photometry model on normal frames.
    H,W=im_ha.data.shape
    yy,xx=np.mgrid[0:H,0:W]
    for r in rows:
        sid=str(r.get("source_id")); xp_row=xp.get(sid)
        if xp_row is None: continue
        x=float(r["x_px"]); y=float(r["y_px"]); rr=np.hypot(xx-x,yy-y)
        ap=(rr<=max(2.0,1.5*(finite(r.get("fwhm_px"),3.0))))
        an=(rr>=max(5.0,3.0*(finite(r.get("fwhm_px"),3.0))))&(rr<=max(8.0,5.0*(finite(r.get("fwhm_px"),3.0))))
        if ap.sum()<5 or an.sum()<10: continue
        fo=float(np.nansum((im_o3.data-bkg_o3.bkg)[ap])-np.nanmedian((im_o3.data-bkg_o3.bkg)[an])*ap.sum())
        fh=float(np.nansum((im_ha.data-bkg_ha.bkg)[ap])-np.nanmedian((im_ha.data-bkg_ha.bkg)[an])*ap.sum())
        if fo<=0 or fh<=0: continue
        # XP_SAMPLED formats differ across astroquery versions; accept wavelength/flux-like tables.
        try:
            fk=next((c for c in xp_row.colnames if str(c).lower()=="flux"),None)
            if fk is None: continue
            wk=next((c for c in xp_row.colnames if str(c).lower() in {"wavelength","wavelength_nm","lambda","lambda_nm"}),None)
            f=np.asarray(xp_row[fk],float).ravel()
            w=np.asarray(xp_row[wk],float).ravel() if wk is not None else np.arange(336.0,1020.0+2.0,2.0,dtype=float)
            if wk is not None and w.size and np.nanmedian(np.abs(w))<2.0: w=w*1e9
            if f.size != w.size: continue
            m=np.isfinite(w)&np.isfinite(f)&(w>=wave.min())&(w<=wave.max())
            if m.sum()<50: continue
            so=float(trapezoid(np.interp(wave,w[m],f[m],left=0,right=0)*resp_o,wave))
            sh=float(trapezoid(np.interp(wave,w[m],f[m],left=0,right=0)*resp_h,wave))
            if so<=0 or sh<=0: continue
            obs_o.append(fo); obs_h.append(fh); pred_o.append(so); pred_h.append(sh); used.append(r)
        except Exception:
            continue
    if len(used)<min_stars:
        return {"state":"NO DISPONIBLE","reason":f"Solo {len(used)} estrellas con XP y fotometría usable; se requieren >= {min_stars}","n_stars_used":len(used),"xp_source":xp_note}
    log_o=np.log10(np.asarray(pred_o)/np.asarray(obs_o)); log_h=np.log10(np.asarray(pred_h)/np.asarray(obs_h))
    # Robust zero point fit in each channel.
    med_o=float(np.median(log_o)); med_h=float(np.median(log_h))
    mad_o=float(1.4826*np.median(np.abs(log_o-med_o))); mad_h=float(1.4826*np.median(np.abs(log_h-med_h)))
    ratio_factor=10.0**(med_o-med_h)
    # Residual colour scatter in magnitudes.
    color_resid_mag=2.5*(log_o-log_h-(med_o-med_h))
    measured = ("measured_curve" in ro_method) and ("measured_curve" in rh_method)
    state = "RESULTADO CALIBRADO" if measured else "PROXY OBSERVACIONAL"
    return {"state":state,"method":"Gaia DR3 XP synthetic photometry (conceptually_SPCC_like_public_workflow)",
            "n_stars_used":len(used),"channel_scale_oiii":10.0**med_o,"channel_scale_ha":10.0**med_h,
            "spcc_ratio_factor":float(ratio_factor),"spcc_ratio_factor_err":float(ratio_factor*math.log(10)*math.hypot(mad_o,mad_h)) if math.isfinite(mad_o) and math.isfinite(mad_h) else None,"residual_rms_mag":float(np.std(color_resid_mag,ddof=1)) if len(color_resid_mag)>1 else 0.0,
            "residual_mad_mag":float(2.5*math.hypot(mad_o,mad_h)),"response_oiii":ro_method,"response_ha":rh_method,
            "xp_source":xp_note,"used_source_ids":[str(r.get("source_id")) for r in used],
            "note":"La metodología sigue el principio público de SPCC (Gaia DR3 XP + filtros), pero no afirma identidad binaria con PixInsight. Las respuestas nominales del filtro se etiquetan como proxy; una calibración trazable requiere T(lambda) medida del filtro/sistema."}

def grid_posterior_inference(ratio_obs: float, ratio_err: float,
                             grid=None, n0: float = None, n_samples: int = 5000,
                             rng=None, n0_logerr: float = 0.3) -> dict:
    """Posterior discreto sobre los nodos de un grid validado.

    No asume monotonicidad ratio->velocidad: evalúa el likelihood en TODOS los nodos
    y marginaliza mediante muestreo categórico.
    """
    if grid is None:
        return {"state":"NO DISPONIBLE", "error":"Se requiere grid MAPPINGS/3MdB"}
    if not getattr(grid, "validated_model_grid", False) or not getattr(grid, "inference_ready", False):
        return {"state":"NO DISPONIBLE", "error":"Grid cargado pero no validado para inferencia; añada metadatos validated_model_grid/inference_ready=true con referencia física."}
    if ratio_obs is None or not math.isfinite(ratio_obs) or ratio_obs <= 0:
        return {"state":"NO DISPONIBLE", "error":"Ratio observado inválido"}
    if ratio_err is None or not math.isfinite(ratio_err) or ratio_err <= 0:
        ratio_err = max(0.1*ratio_obs, 1e-6)
    rng = rng or np.random.default_rng(0)
    v = np.asarray(grid.v, float); r = np.asarray(grid.r, float)
    n0g = np.asarray(grid.n0, float) if grid.n0 is not None else None
    m = np.isfinite(v) & np.isfinite(r) & (v>0) & (r>0)
    if n0g is not None: m &= np.isfinite(n0g) & (n0g>0)
    v, r = v[m], r[m]
    n0g = n0g[m] if n0g is not None else None
    if len(v) < 3:
        return {"state":"NO DISPONIBLE", "error":"Grid con menos de 3 nodos válidos"}
    sig_obs_dex = max(ratio_err/(ratio_obs*math.log(10)), 0.01)
    sig_model_dex = max(float(getattr(grid, "model_logerr", 0.15)), 0.0)
    sig_total = math.hypot(sig_obs_dex, sig_model_dex)
    resid = (np.log10(r) - math.log10(ratio_obs)) / max(sig_total, 1e-6)
    logw = -0.5*resid*resid
    if n0 is not None and n0g is not None and math.isfinite(float(n0)) and n0 > 0:
        lp = (np.log10(n0g) - math.log10(float(n0))) / max(float(n0_logerr), 1e-6)
        logw += -0.5*lp*lp
    logw -= np.max(logw)
    w = np.exp(logw); sw = float(w.sum())
    if not math.isfinite(sw) or sw <= 0:
        return {"state":"NO DISPONIBLE", "error":"Likelihood degenerada o fuera del dominio del grid"}
    p = w/sw
    idx = rng.choice(np.arange(len(v)), size=int(max(100,n_samples)), replace=True, p=p)
    vs = v[idx]
    ns = n0g[idx] if n0g is not None else np.full(idx.size, np.nan)
    p16,p50,p84 = np.percentile(vs,[16,50,84])
    hist, edges = np.histogram(vs, bins=min(40,max(10,int(np.sqrt(len(vs))))))
    peaks = int(sum(hist[i] >= hist[i-1] and hist[i] >= hist[i+1] and hist[i] >= max(2,0.05*hist.max()) for i in range(1,len(hist)-1)))
    return {"v_median":float(p50),"v_mean":float(np.mean(vs)),"v_std":float(np.std(vs)),
            "v_p16":float(p16),"v_p84":float(p84),"v_ci_68":[float(p16),float(p84)],
            "n0_median":float(np.nanmedian(ns)) if np.isfinite(ns).any() else None,
            "n_samples":int(len(vs)),"degenerate":bool(peaks>1),"n_posterior_peaks":peaks,
            "state":"INFERENCIA DE MODELO","method":"Discrete grid likelihood + categorical posterior sampling",
            "note":"Posterior sobre todos los nodos; no presupone monotonicidad ratio→velocidad.",
            "grid_reference":getattr(grid,"reference",getattr(grid,"name","grid")),
            "grid_validated":True,"sigma_obs_dex":sig_obs_dex,"sigma_model_dex":sig_model_dex,"sigma_total_dex":sig_total}


# ====================================================================
# v29 FEATURE: Connect multiband + color-color to pipeline
# ====================================================================

def analyze_multiband_pipeline(image_paths: list, out_dir: str,
                                pixel_scale: float = 1.0,
                                normalize: bool = True) -> dict:
    """Pipeline multibanda: apila imágenes y genera diagramas color-color.

    Requiere imágenes pre-registradas de misma geometría.
    Ratios son OBSERVABLE (ADU); solo RESULTADO CALIBRADO con zeropoint.
    """
    if len(image_paths) < 2:
        return {"state": "NO DISPONIBLE", "error": "Se requieren al menos 2 imágenes"}
    # Stack images
    stack_result = stack_multiband(image_paths, out_dir, normalize=normalize)
    if stack_result.get("state") == "NO DISPONIBLE":
        return stack_result
    # Generate color-color diagram data
    # For pairs of bands, compute color = mag1 - mag2 = -2.5*log10(f1/f2)
    colors = {}
    for i in range(len(image_paths) - 1):
        for j in range(i + 1, len(image_paths)):
            label = f"band{i}_band{j}"
            # Color from stack data (if available)
            colors[label] = {"state": "OBSERVABLE",
                             "note": "Color instrumental; requiere calibración para mag física"}
    return {
        "stack": stack_result,
        "colors": colors,
        "state": "OBSERVABLE",
        "note": "Pipeline multibanda; ratios en ADU, no calibrados"
    }



def analyze_pair_with_consistency(oiii_path, ha_path, out_dir, params, grid=None, labels_path=None, progress=None, cancel=None):
    """
    Wrapper de analyze_pair que añade verificación de consistencia científica,
    presupuesto de incertidumbre, comparación con literatura, y QC summary.
    Reescribe catalog.json con los campos enriquecidos.
    """
    payload = analyze_pair_core(oiii_path, ha_path, out_dir, params, grid, labels_path, progress, cancel)
    payload["schema_version"] = SCHEMA_VERSION
    payload["science_schema"] = SCIENCE_SCHEMA_VERSION

    # Añadir verificación de consistencia científica
    try:
        consistency = check_scientific_consistency(payload)
        payload["scientific_consistency"] = consistency.to_dict()
    except Exception as exc:
        LOG.warning("check_scientific_consistency falló: %s", exc)
        payload["scientific_consistency"] = {"passed": False, "error": str(exc)}

    # Añadir presupuesto de incertidumbre
    try:
        budget = compute_uncertainty_budget(payload)
        payload["uncertainty_budget"] = [b.to_dict() for b in budget]
    except Exception as exc:
        LOG.warning("compute_uncertainty_budget falló: %s", exc)

    # Comparación de literatura: una única estructura canónica para PDF/HTML/QC.
    try:
        lit_comp = build_literature_comparison(payload.get("summary", {}), (payload.get("summary", {}) or {}).get("target_name", ""),
                                                user_distance_pc=(payload.get("summary", {}) or {}).get("distance_pc"))
        payload["literature_comparison"] = lit_comp
        payload.setdefault("summary", {})["literature_comparison"] = lit_comp
        payload["literature_zscores"] = compare_with_literature_zscore(payload)
    except Exception as exc:
        LOG.warning("Comparación con literatura falló: %s", exc)

    # Añadir detección de anomalías
    try:
        anomalies = detect_anomalies(payload)
        payload["anomalies"] = anomalies
    except Exception as exc:
        LOG.warning("detect_anomalies falló: %s", exc)

    # Añadir QC summary
    try:
        qc = generate_qc_summary(payload)
        payload["qc_summary"] = qc
    except Exception as exc:
        LOG.warning("generate_qc_summary falló: %s", exc)

    # Añadir provenance
    try:
        prov = build_provenance_chain(payload)
        payload["provenance"] = prov
    except Exception as exc:
        LOG.warning("build_provenance_chain falló: %s", exc)

    # Añadir mapas físicos
    try:
        phys_maps = compute_physical_maps(payload)
        payload["physical_maps"] = phys_maps
    except Exception as exc:
        LOG.warning("compute_physical_maps falló: %s", exc)

    # Reescribir catalog.json con los campos enriquecidos
    try:
        out_path = Path(out_dir) if not isinstance(out_dir, Path) else out_dir
        catalog_path = out_path / "catalog.json"
        if catalog_path.is_file():
            atomic_json_dump(payload, catalog_path)
            LOG.info("catalog.json reescrito con campos de consistencia científica y QC")
    except Exception as exc:
        LOG.warning("No se pudo reescribir catalog.json: %s", exc)

    return payload

# API pública única y explícita; no se realiza monkey-patch de símbolos al final del módulo.
def analyze_pair(oiii_path, ha_path, out_dir, params, grid=None, labels_path=None, progress=None, cancel=None):
    return analyze_pair_with_consistency(oiii_path, ha_path, out_dir, params, grid, labels_path, progress, cancel)

# ====================================================================
# SELFTEST
# ====================================================================
def _write_minimal_fits_2d(path: Path, data: np.ndarray, pixel_scale_arcsec: float = 1.0):
    """Escribe un FITS 2D mínimo para pruebas offline cuando falta Astropy."""
    a=np.asarray(data,np.float32); H,W=a.shape
    raw_cards=[]
    def c(k,v): raw_cards.append(f"{k:<8}= {v:<70}"[:80])
    c("SIMPLE","                    T"); c("BITPIX","                  -32"); c("NAXIS","                      2")
    c("NAXIS1",f"{W:>22d}"); c("NAXIS2",f"{H:>22d}")
    c("CDELT1",f"{-pixel_scale_arcsec/3600.0:>22.12g}"); c("CDELT2",f"{pixel_scale_arcsec/3600.0:>22.12g}")
    c("BUNIT","'ADU'"); raw_cards.append("END"+" ".ljust(76))
    hdr=''.join(raw_cards).encode('ascii'); hdr += b' ' * ((2880-len(hdr)%2880)%2880)
    dat=np.asarray(a,dtype='>f4').tobytes(order='C'); dat += b'\0' * ((2880-len(dat)%2880)%2880)
    Path(path).write_bytes(hdr+dat)


def _write_synthetic_pair(out_dir, seed=20260914, shape=(256,256), offset_px=4.25):
    out=Path(out_dir); out.mkdir(parents=True,exist_ok=True); rng=np.random.default_rng(seed)
    H,W=shape; yy,xx=np.mgrid[0:H,0:W]
    bg=100.0+0.03*xx+0.02*yy
    ha=bg.copy(); o3=bg.copy()
    curve=135.0+10*np.sin((xx-50)/35.0)
    ha+=450*np.exp(-0.5*((yy-curve)/2.2)**2)
    o3+=300*np.exp(-0.5*((yy-(curve+offset_px))/2.8)**2)
    stars=[]
    for x,y,a in [(40,45,1000),(80,210,700),(150,65,1200),(205,180,900),(225,55,500),(110,150,600)]:
        ps=a*np.exp(-0.5*((xx-x)**2+(yy-y)**2)/(2.0**2)); ha+=ps; o3+=ps; stars.append((x,y,a))
    noise_ha=rng.normal(0,5,ha.shape); noise_o3=rng.normal(0,5,o3.shape)
    ha+=noise_ha; o3+=noise_o3
    ha_starless=ha.copy(); o3_starless=o3.copy()
    for x,y,a in stars:
        ps=a*np.exp(-0.5*((xx-x)**2+(yy-y)**2)/(2.0**2)); ha_starless-=ps; o3_starless-=ps
    ha_path=out/"synthetic_HA.fits"; o3_path=out/"synthetic_OIII.fits"
    ha_sl_path=out/"synthetic_HA_starless.fits"; o3_sl_path=out/"synthetic_OIII_starless.fits"
    if HAS_ASTROPY:
        _fits.PrimaryHDU(ha.astype(np.float32)).writeto(ha_path,overwrite=True)
        _fits.PrimaryHDU(o3.astype(np.float32)).writeto(o3_path,overwrite=True)
        _fits.PrimaryHDU(ha_starless.astype(np.float32)).writeto(ha_sl_path,overwrite=True)
        _fits.PrimaryHDU(o3_starless.astype(np.float32)).writeto(o3_sl_path,overwrite=True)
    else:
        _write_minimal_fits_2d(ha_path,ha); _write_minimal_fits_2d(o3_path,o3)
        _write_minimal_fits_2d(ha_sl_path,ha_starless); _write_minimal_fits_2d(o3_sl_path,o3_starless)
    return o3_path,ha_path


def validate_pipeline_qc_contract(payload: dict) -> dict:
    """Regresión de contrato: QC debe leer el schema real del pipeline."""
    n = normalize_scientific_payload(payload)
    candidates = n.get("candidates", [])
    has_real_candidate_fields = bool(candidates) and any(r.get("ratio") is not None or r.get("ratio_oiii_ha") is not None for r in candidates)
    qc = generate_qc_summary(n)
    return {
        "state": "OK" if (not has_real_candidate_fields or n.get("schema_diagnostics", {}).get("normalized")) else "FAIL",
        "normalized": bool(n.get("schema_diagnostics", {}).get("normalized")),
        "candidate_count": len(candidates),
        "qc_errors": int(qc.get("n_errors", 0)),
        "qc_warnings": int(qc.get("n_warnings", 0)),
    }

def synthetic_end_to_end(out_dir):
    out=Path(out_dir); out.mkdir(parents=True,exist_ok=True)
    o3,ha=_write_synthetic_pair(out,seed=20260914)
    o3_sl=out/"synthetic_OIII_starless.fits"; ha_sl=out/"synthetic_HA_starless.fits"
    cal=LineCalibration(oiii_exptime_s=120,ha_exptime_s=120,calibrated=False,calibration_basis="instrumental",calibration_warning="synthetic")
    P=AnalysisParams(snr_min=4,max_candidates=100,min_separation_px=10,distance_pc=725,workers=1,use_processes=False,register="stars",target_name="",offline=True,calibration=cal,export_products=True,oiii_starless_path=str(o3_sl),ha_starless_path=str(ha_sl))
    payload=analyze_pair(str(o3),str(ha),str(out/"analysis"),P,None)
    return payload

def _selftest_v43_scientific_hardening():
    """Regresiones de seguridad científica introducidas en v43."""
    # CCM89: valores ópticos válidos y rechazo explícito de Rv fuera de dominio.
    a_o3 = ccm89_alav(5007.0, 3.1)
    a_ha = ccm89_alav(6563.0, 3.1)
    if not (math.isfinite(a_o3) and math.isfinite(a_ha) and a_o3 > a_ha):
        raise AssertionError("CCM89 regresión: A(5007) debe superar A(6563) para Rv=3.1")
    try:
        ccm89_alav(5007.0, 1.5)
        raise AssertionError("CCM89 aceptó Rv fuera de dominio")
    except ValueError:
        pass
    # La vista previa de calibración no puede ocultar una excepción de CCM89.
    return True


def selftest(verbose=True):
    fails=0
    def check(name,cond,detail=""):
        nonlocal fails; ok=bool(cond); fails += (not ok)
        if verbose: print(f"[{'OK ' if ok else 'FAIL'}] {name} {detail}")
    try:
        _selftest_v43_scientific_hardening(); check("v43: direct CCM89 calibration regression", True)
    except Exception as exc:
        check("v43: direct CCM89 calibration regression", False, str(exc))
    try:
        _v45_regression_tests(); check("v45: regression/security/scientific-contract suite", True)
    except Exception as exc:
        check("v45: regression/security/scientific-contract suite", False, str(exc))
    check("json sanitize NaN/inf", json_sanitize({"a":float("nan"),"b":float("inf")})=={"a":None,"b":None})
    # atomic write
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)/"a.json"; atomic_json_dump({"x":1},p); check("atomic JSON",json.loads(p.read_text())=={"x":1})
        # filter curves
        c=Path(td)/"curve.csv"; c.write_text("wavelength_angstrom,Transmission\n4959,50\n5007,90\n6563,1\n",encoding="utf-8")
        curve,note=load_filter_curve(c); check("curva Å→nm + porcentaje", abs(curve.wavelength_nm[0]-495.9)<1e-6 and abs(curve.transmission[0]-0.5)<1e-6 and note=="Å→nm")
        good=demix_two_filters(1.0,0.7,0.8,0.2,0.2,0.9); check("demezcla 2x2 bien condicionada", good["condition_number"]<100)
        try:
            calibrate_from_filters(FILTER_DEFAULT,FILTER_DEFAULT,120,120,r_v=3.1)
            check("calibración r_v", True)
        except Exception as exc:
            check("calibración r_v", False, str(exc))
        ccurve=Path(td)/"curve.dat"; ccurve.write_text("wavelength_nm Transmission\n480 0.1\n500.7 0.8\n656.3 0.9\n670 0.1\n",encoding="utf-8")
        try:
            load_filter_curve(ccurve); check("curva DAT", True)
        except Exception as exc:
            check("curva DAT", False, str(exc))
        bad=False
        try: demix_two_filters(1,1,0.5,0.5,0.5,0.5)
        except ValueError: bad=True
        check("demezcla singular bloqueada",bad)
        gm_test=GridManager()
        try:
            gm_test.validate(ShockGrid([100,100,200],[0.1,0.2,0.3],[1,1,1]))
            check("grilla duplicada bloqueada", False)
        except ValueError:
            check("grilla duplicada bloqueada", True)
        try:
            gm_test.validate(ShockGrid([100,200,300],[0.1,float("nan"),0.3],[1,1,1]))
            check("grilla NaN bloqueada", False)
        except ValueError:
            check("grilla NaN bloqueada", True)
        # Registro: signo independientemente de Astropy, con desplazamiento conocido.
        rng_reg=np.random.default_rng(1234); N=128; yy,xx=np.mgrid[0:N,0:N]
        pos_reg=np.array([[20,20],[35,60],[60,30],[80,90],[100,55],[45,100],[90,25],[110,110]],float)
        dx0,dy0=2.4,-1.7
        def _sf(pp):
            aa=np.full((N,N),100.0,np.float32)
            for x,y in pp: aa += 800*np.exp(-((xx-x)**2+(yy-y)**2)/(2*1.7**2))
            return (aa+rng_reg.normal(0,2,(N,N))).astype(np.float32)
        ha_reg=_sf(pos_reg); o3_reg_test=_sf(pos_reg+[dx0,dy0])
        reg_test=register_on_stars(o3_reg_test,ha_reg,estimate_background(o3_reg_test),estimate_background(ha_reg),fwhm_px=4.0,search_radius_px=8.0)
        check("registro: convención de signo verificada", abs(reg_test.dx+dx0)<0.25 and abs(reg_test.dy+dy0)<0.25, f"dx={reg_test.dx:.3f} dy={reg_test.dy:.3f}")
        check("registro: coincidencia uno-a-uno", reg_test.n_inliers<=reg_test.n_stars<=min(reg_test.n_sources_oiii,reg_test.n_sources_ha) and reg_test.method.startswith("stars-"))
        fake_im = FitsImage("synthetic", ha_reg, {"SATURATE": 1e6}, 1.0)
        fake_bkg = estimate_background(ha_reg)
        star_rows = enrich_star_rows(fake_im, np.asarray([[20,20,1000.0],[35,60,900.0]]), fake_bkg)
        check("enrich_star_rows: ROI/SNR local", len(star_rows)==2 and "roi" in star_rows[0] and "local_rms_adu" in star_rows[0] and "snr_peak" in star_rows[0])
        cfg=AnalysisParams(snr_min=3.0,max_candidates=50,filament_strategy="canny",offline=True)
        img_c=np.zeros((64,64),np.float32); img_c[30:34,8:56]=20.0
        bb_c=estimate_background(img_c); vr_c=np.maximum(bb_c.rms**2,1e-6)
        cres=CannyFilamentStrategy().detect(img_c,vr_c,{"background":bb_c,"star_mask":np.zeros_like(img_c,bool)},cfg)
        check("estrategia Canny conectada", str(cres.strategy).startswith("canny"))
        if HAS_ASTROPY:
            # FITS 2D/3D/cube explicit
            hdu=_fits.PrimaryHDU(np.arange(25,dtype=np.float32).reshape(5,5)); hdu.writeto(Path(td)/"2d.fits")
            im2d = load_fits(Path(td)/"2d.fits")
            check("FITS 2D",im2d.shape==(5,5))
            check("FITS 2D dtype intact", np.issubdtype(im2d.data.dtype, np.number))
            if isinstance(im2d.data, np.memmap):
                check("FITS 2D memmap preservado", True)
            else:
                check("FITS 2D memmap preservado", False, "el FITS float32 no quedó como memmap")
            cube=np.stack([np.zeros((5,5)),np.ones((5,5))])
            _fits.PrimaryHDU(cube.astype(np.float32)).writeto(Path(td)/"3d.fits")
            raised=False
            try: load_fits(Path(td)/"3d.fits")
            except AmbiguousCubeError: raised=True
            check("FITS 3D sin plano falla",raised)
            im=load_fits(Path(td)/"3d.fits",plane=1); check("FITS 3D plano explícito",float(im.data[0,0])==1.0 and im.selected_plane==(1,))
            # synthetic E2E
            syn=synthetic_end_to_end(Path(td)/"e2e"); ss=syn["summary"]; check("E2E catalog JSON",(Path(td)/"e2e"/"analysis"/"catalog.json").is_file())
            check("E2E productos",len(ss.get("product_files",[]))>0)
            check("E2E manifest", "configuration_sha256" in syn.get("manifest",{}) and "filter_curve_sha256" in syn.get("manifest",{}))
            qc_contract = validate_pipeline_qc_contract(syn)
            check("E2E QC contract: schema real", qc_contract.get("normalized") and qc_contract.get("candidate_count",0)==len(syn.get("candidates",[])))
        else:
            try:
                syn=synthetic_end_to_end(Path(td)/"e2e_fallback")
                ss=syn.get("summary",{})
                analysis_dir=Path(td)/"e2e_fallback"/"analysis"
                check("E2E offline sin Astropy", (analysis_dir/"catalog.json").is_file() and int(ss.get("n_analyzed",0))>0)
                check("manifest observatorio", isinstance(syn.get("manifest"),dict) and "configuration_sha256" in syn.get("manifest",{}) and "filter_curve_sha256" in syn.get("manifest",{}))
                qc_contract = validate_pipeline_qc_contract(syn)
                check("E2E QC contract: schema real", qc_contract.get("normalized") and qc_contract.get("candidate_count",0)==len(syn.get("candidates",[])))
                if HAS_MPL:
                    pdf=write_report_pdf(syn,analysis_dir/"report.pdf",ha_image=load_fits(syn["inputs"]["ha"]).data,o3_image=load_fits(syn["inputs"]["oiii"]).data)
                    html=write_html_report(syn,analysis_dir/"report.html",ha_image=load_fits(syn["inputs"]["ha"]).data,o3_image=load_fits(syn["inputs"]["oiii"]).data)
                    check("PDF/HTML E2E", Path(pdf).is_file() and Path(html).is_file())
            except Exception as exc:
                check("E2E offline sin Astropy", False, str(exc))
            if verbose: print("[INFO] Productos FITS/WCS de E2E quedan cubiertos cuando Astropy está instalado")
    with tempfile.TemporaryDirectory() as td2:
        td2=Path(td2); sci=np.full((16,16),110.0,np.float32); bias=np.full((16,16),10.0,np.float32); dark=np.full((16,16),2.0,np.float32); flat=np.full((16,16),2.0,np.float32)
        _write_minimal_fits_2d(td2/"bias.fits",bias); _write_minimal_fits_2d(td2/"dark.fits",dark); _write_minimal_fits_2d(td2/"flat.fits",flat)
        base=FitsImage(str(td2/"science.fits"),sci,{"EXPTIME":10},1.0,exptime=10.0)
        cc,cr=apply_calibration_frames(base,str(td2/"bias.fits"),str(td2/"dark.fits"),str(td2/"flat.fits"))
        check("bias/dark/flat",np.allclose(cc.data,98.0) and abs(cr.get("dark_scale")-1.0)<1e-9)
    # core physics
    comp=Composition(); st=rankine_hugoniot(130,6); Tref=3/16*comp.mu("H+He++")*C.m_p*(130e5)**2/C.k_B; check("RH",abs(st.T_post/Tref-1)<0.05)
    check("literatura NGC6960",find_literature("NGC 6960") is not None)
    # --- v38 regression tests ---
    # Scientific consistency check
    try:
        fake_payload = {"summary": {"calibration": {"calibrated": False}, "registration": {"phase_fallback": True, "may_absorb_scientific_filament_shift": True}, "cooling_proxy": 0.5, "cooling_label": "Proxy de régimen de excitación/enfriamiento"}, "candidates": [{"det_id": 1, "ratio": 2.5, "snr": 5.0, "candidate_type": "shock"}], "manifest": {"grid_info": {"model_family": "heuristic_demo_grid"}}}
        sc = check_scientific_consistency(fake_payload)
        check("scientific_consistency: phase_fallback warning", any(i["category"] == "registration" for i in sc.issues))
        check("scientific_consistency: grid demo warning", any(i["category"] == "grid" for i in sc.issues))
        check("scientific_consistency: ratio OBSERVABLE", sc.result_states.get(list(sc.result_states.keys())[0]) == "OBSERVABLE" if sc.result_states else False)
    except Exception as exc:
        check("scientific_consistency", False, str(exc))
    # Uncertainty budget
    try:
        fake_payload2 = {"summary": {"calibration": {"calibrated": False}, "background_rms": 5.0, "registration": {"residual_rms_arcsec": 0.1}, "distance_pc": 725, "distance_err_pc": 15}, "manifest": {"rdnoise_e": 5.0, "grid_info": {"model_family": "heuristic_demo_grid", "model_logerr": 0.15}}}
        budget = compute_uncertainty_budget(fake_payload2)
        check("uncertainty_budget: componentes", len(budget) >= 3)
        check("uncertainty_budget: read_noise OBSERVABLE", any(b.component == "read_noise" and b.state == "OBSERVABLE" for b in budget))
        check("uncertainty_budget: calibration NO DISPONIBLE", any(b.component == "calibration" and b.state == "NO DISPONIBLE" for b in budget))
    except Exception as exc:
        check("uncertainty_budget", False, str(exc))
    # Literature z-score
    try:
        fake_payload3 = {"summary": {"target_name": "NGC 6960", "radius_arcsec": 1140, "radius_err_arcsec": 50, "distance_pc": 725, "distance_err_pc": 15}, "manifest": {"grid_info": {"model_family": "heuristic_demo_grid"}}}
        comps = compare_with_literature_zscore(fake_payload3)
        check("literature_zscore: comparaciones", len(comps) >= 1)
        check("literature_zscore: tiene z_score", all("z_score" in c for c in comps))
        check("literature_zscore: tiene agreement", all("agreement" in c for c in comps))
    except Exception as exc:
        check("literature_zscore", False, str(exc))
    # Anomaly detection
    try:
        fake_payload4 = {"candidates": [{"det_id": 1, "ratio": 50.0, "candidate_type": "shock", "snr": 10.0}, {"det_id": 2, "ratio": 2.0, "candidate_type": "shock", "snr": 5.0}], "summary": {}, "stars": []}
        anomalies = detect_anomalies(fake_payload4)
        check("anomaly_detection: detecta ratio extremo", len(anomalies) >= 1)
        check("anomaly_detection: NO es discovery", all(not a.get("is_discovery") for a in anomalies))
    except Exception as exc:
        check("anomaly_detection", False, str(exc))
    # Forward model
    try:
        sim = simulate_observation((64, 64), n_filaments=1, n_stars=3, seed=42)
        check("forward_model: shapes", sim["ha_array"].shape == (64, 64) and sim["oiii_array"].shape == (64, 64))
        check("forward_model: true_offset", abs(sim["true_offset_px"] - 4.0) < 1e-6)
    except Exception as exc:
        check("forward_model", False, str(exc))
    # Shock velocity (grid-only)
    try:
        gm = GridManager()
        demo_grid = gm.embedded()
        vel = estimate_shock_velocity(2.0, 0.2, demo_grid, n0=6.0)
        check("shock_velocity: devuelve resultado", vel.get("velocity_km_s") is not None or vel.get("state") == "NO DISPONIBLE")
        check("shock_velocity: DEMO label", "DEMO" in vel.get("state", "") or vel.get("state") == "NO DISPONIBLE")
        # Sin grid
        vel_no = estimate_shock_velocity(2.0, 0.2, None)
        check("shock_velocity: sin grid bloqueado", vel_no.get("state") == "NO DISPONIBLE")
    except Exception as exc:
        check("shock_velocity", False, str(exc))
    # Age estimation
    try:
        age = estimate_ast_remnant_age(1140, 725, velocity_km_s=100, velocity_err_km_s=10)
        check("age: calculado", age.get("age_yr") is not None and age.get("age_yr") > 0)
        check("age: INFERENCIA DE MODELO", age.get("state") == "INFERENCIA DE MODELO")
        # Verificación numérica Sedov: t = 0.4 * R / v
        expected_radius_pc = 1140/3600 * 725 * np.pi/180
        expected_age = 0.4 * expected_radius_pc * 3.0857e13 / 100 / 3.154e7
        check("age: Sedov numérico", abs(age.get("age_yr", 0) - expected_age) / max(expected_age, 1) < 0.05, f"expected={expected_age:.0f} got={age.get('age_yr', 0):.0f}")
        check("age: expansion_parameter", abs(age.get("expansion_parameter", 0) - 0.4) < 1e-6)
        # Sin velocidad
        age_no = estimate_ast_remnant_age(1140, 725, velocity_km_s=None)
        check("age: sin velocidad bloqueado", age_no.get("state") == "NO DISPONIBLE")
    except Exception as exc:
        check("age", False, str(exc))
    # Redshift
    try:
        z = apply_redshift_correction(500.7, 0.01)
        check("redshift: correccion", abs(z["rest_wavelength_nm"] - 500.7/1.01) < 0.01)
        z0 = apply_redshift_correction(500.7, 0.0)
        check("redshift: z=0 sin correccion", not z0["correction_applied"])
    except Exception as exc:
        check("redshift", False, str(exc))
    # Provenance
    try:
        fake_payload5 = {"summary": {"calibration": {"calibrated": False, "calibration_basis": "instrumental"}, "registration": {"method": "stars-cross-correlation"}}, "manifest": {"configuration_sha256": "abc123", "grid_info": {"model_family": "heuristic_demo_grid"}, "filter_curve_sha256": {"oiii": "def", "ha": "ghi"}}, "inputs": {"oiii": "test.fits", "ha": "test2.fits"}}
        prov = build_provenance_chain(fake_payload5)
        check("provenance: pipeline_steps", len(prov.get("pipeline_steps", [])) >= 5)
        check("provenance: configuration_sha256", prov.get("reproducibility", {}).get("configuration_sha256") == "abc123")
    except Exception as exc:
        check("provenance", False, str(exc))
    # QC summary
    try:
        fake_payload6 = {"summary": {"calibration": {"calibrated": False}, "registration": {}, "cooling_proxy": 0.5, "cooling_label": "Proxy de régimen de excitación/enfriamiento"}, "candidates": [{"det_id": 1, "ratio": 2.5, "snr": 5.0, "candidate_type": "shock"}], "manifest": {"grid_info": {"model_family": "heuristic_demo_grid"}}}
        qc = generate_qc_summary(fake_payload6)
        check("qc_summary: tiene consistencia", "scientific_consistency" in qc)
        check("qc_summary: tiene budget", "uncertainty_budget" in qc)
        check("qc_summary: tiene anomalies", "anomalies" in qc)
    except Exception as exc:
        check("qc_summary", False, str(exc))
    # Physical maps
    try:
        fake_payload7 = {"summary": {"calibration": {"calibrated": False}}, "manifest": {"grid_info": {"model_family": "heuristic_demo_grid"}}}
        pmaps = compute_physical_maps(fake_payload7)
        check("physical_maps: ratio OBSERVABLE", pmaps.get("ratio_oiii_ha", {}).get("state") == "OBSERVABLE")
        check("physical_maps: velocity NO DISPONIBLE", pmaps.get("velocity", {}).get("state") == "NO DISPONIBLE")
    except Exception as exc:
        check("physical_maps", False, str(exc))
    # Radial profile
    try:
        test_img = np.zeros((32, 32), dtype=np.float32)
        cx, cy = 16, 16
        yy, xx = np.mgrid[0:32, 0:32]
        test_img = 100 * np.exp(-0.5 * ((xx - cx)**2 + (yy - cy)**2) / 5.0).astype(np.float32)
        rp = extract_radial_profile(test_img, cx, cy, max_radius_px=15, bin_size_px=2.0)
        check("radial_profile: tiene bins", len(rp["radius_px"]) > 0)
        check("radial_profile: OBSERVABLE", rp.get("state") == "OBSERVABLE")
    except Exception as exc:
        check("radial_profile", False, str(exc))
    # MAPPINGS grid loader
    try:
        import tempfile
        with tempfile.TemporaryDirectory() as tdd:
            grid_path = Path(tdd) / "test_mappings.csv"
            grid_path.write_text(
                "# model_family: MAPPINGS-V\n# version: 5.0\n# reference: Allen et al. 2008\n"
                "# cooling_table: Sutherland & Dopita 1993\n# abundance_set: solar\n"
                "velocity_km_s,n0_cm3,T_post_K,OIII_Hb,Ha_Hb\n"
                "100,1,50000,2.0,1.0\n"
                "150,1,70000,3.5,1.0\n"
                "200,1,90000,5.0,1.0\n"
                "100,10,40000,1.5,1.0\n"
                "150,10,60000,2.8,1.0\n"
                "200,10,80000,4.5,1.0\n",
                encoding="utf-8")
            loader = MappingsGridLoader()
            grid = loader.load(str(grid_path))
            check("mappings_loader: model_family", grid.name == "MAPPINGS-V")
            check("mappings_loader: sha256", len(loader.metadata.sha256) == 64)
            check("mappings_loader: n_points", len(grid.v) == 6)
            check("mappings_loader: has_real_mappings", loader.has_real_mappings_grid())
            # Grid inválido (sin columnas requeridas)
            bad_path = Path(tdd) / "bad_grid.csv"
            bad_path.write_text("velocity,n0,T\n100,1,50000\n", encoding="utf-8")
            bad_grid = False
            try:
                loader.load(str(bad_path))
            except ValueError:
                bad_grid = True
            check("mappings_loader: columnas faltantes bloqueadas", bad_grid)
    except Exception as exc:
        check("mappings_loader", False, str(exc))
    # Environment export
    try:
        import tempfile
        with tempfile.TemporaryDirectory() as tde:
            env_path = export_environment(str(Path(tde) / "env.json"))
            env_data = json.loads(Path(env_path).read_text(encoding="utf-8"))
            check("env_export: version", env_data.get("software_version") == __version__)
            check("env_export: packages", "numpy" in env_data.get("packages", {}))
    except Exception as exc:
        check("env_export", False, str(exc))
    # Catalog persistence is already exercised by the single E2E above; avoid rerunning the full pipeline.
    try:
        with tempfile.TemporaryDirectory() as tdp:
            pth=Path(tdp)/"catalog.json"; atomic_json_dump({"scientific_consistency":{},"qc_summary":{},"provenance":{}},pth)
            disk=json.loads(pth.read_text(encoding="utf-8"))
            check("catalog.json persistence", all(k in disk for k in ("scientific_consistency","qc_summary","provenance")))
    except Exception as exc:
        check("catalog.json persistence", False, str(exc))
    # v29 tests
    try:
        am = compute_airmass(45.0)
        check("airmass: sec(45)=1.414", abs(am - 1.4142) < 0.01, f"got={am:.4f}")
        am_zenith = compute_airmass(0.0)
        check("airmass: zenith=1.0", abs(am_zenith - 1.0) < 1e-6)
    except Exception as exc:
        check("airmass", False, str(exc))
    try:
        ext = apply_atmospheric_extinction(1000.0, 1.2, 0.15, 0.02)
        check("extinction: flux_corrected", ext.get("flux_corrected") is not None and ext.get("flux_corrected") > 1000.0)
        check("extinction: RESULTADO CALIBRADO", ext.get("state") == "RESULTADO CALIBRADO")
        ext_no_k = apply_atmospheric_extinction(1000.0, 1.2, 0.15, 0.0)
        check("extinction: PROXY sin k_err", ext_no_k.get("state") == "PROXY OBSERVACIONAL")
    except Exception as exc:
        check("extinction", False, str(exc))
    try:
        cal = absolute_photometric_calibration(5000.0, 25.0, 120.0, gain=2.0, airmass=1.2, k_extinction=0.15, k_err=0.02, flux_adu_err=100.0, zeropoint_err=0.05, zeropoint_source="Landolt SA107")
        check("photometric_cal: magnitude", cal.get("magnitude") is not None)
        check("photometric_cal: RESULTADO CALIBRADO", cal.get("state") == "RESULTADO CALIBRADO")
        cal_no_zp_err = absolute_photometric_calibration(5000.0, 25.0, 120.0, gain=2.0, airmass=1.2, k_extinction=0.15, k_err=0.02, flux_adu_err=100.0)
        check("photometric_cal: PROXY sin zp_err", cal_no_zp_err.get("state") == "PROXY OBSERVACIONAL")
        cal_no_ext = absolute_photometric_calibration(5000.0, 25.0, 120.0, gain=2.0)
        check("photometric_cal: OBSERVABLE sin extinc", cal_no_ext.get("state") == "OBSERVABLE")
    except Exception as exc:
        check("photometric_cal", False, str(exc))
    try:
        # Create synthetic image with a Gaussian source
        _yy, _xx = np.mgrid[0:51, 0:51]
        _gauss = 1000.0 * np.exp(-((_xx-25)**2 + (_yy-25)**2) / (2*3.0**2))
        _img = _gauss + 100.0 + np.random.default_rng(42).normal(0, 5, _gauss.shape)
        sq = measure_source_quality(_img.astype(np.float32), 25.0, 25.0, cutout_size=25)
        check("psf: FWHM measured", sq.get("fwhm_px") is not None and sq.get("fwhm_px") > 0)
        check("psf: OBSERVABLE", sq.get("state") == "OBSERVABLE")
        check("psf: not saturated", sq.get("saturated") is False)
        pq = measure_psf_quality(_img.astype(np.float32), [{"x": 25.0, "y": 25.0}])
        check("psf_quality: median_fwhm", pq.get("median_fwhm_px") is not None)
        check("psf_quality: quality_flag", pq.get("quality_flag") in ("GOOD", "WARN", "POOR"))
    except Exception as exc:
        check("psf", False, str(exc))
    try:
        hdr = {"CRPIX1": 128.0, "CRPIX2": 128.0, "CRVAL1": 312.5, "CRVAL2": 32.0,
               "CD1_1": -5.555e-5, "CD1_2": 0.0, "CD2_1": 0.0, "CD2_2": 5.555e-5}
        wcs_val = validate_wcs(hdr, (256, 256))
        check("wcs: valid", wcs_val.get("is_valid") is True)
        check("wcs: scale", wcs_val.get("scale_arcsec_per_px") is not None and wcs_val.get("scale_arcsec_per_px") > 0)
        check("wcs: OBSERVABLE", wcs_val.get("state") == "OBSERVABLE")
        bad_hdr = {"CRPIX1": 128.0}
        wcs_bad = validate_wcs(bad_hdr, (256, 256))
        check("wcs: invalid header blocked", wcs_bad.get("is_valid") is False)
    except Exception as exc:
        check("wcs", False, str(exc))
    try:
        # Posterior with validated grid
        import tempfile, json as _json
        grid_data = {
            "metadata": {"model_family": "3MdB", "version": "1.0", "reference": "test", "validated_model_grid": True},
            "points": [
                {"velocity_km_s": 100, "n0_cm3": 1, "T_post_K": 1.0e5, "OIII_Ha": 2.0},
                {"velocity_km_s": 150, "n0_cm3": 1, "T_post_K": 2.0e5, "OIII_Ha": 3.5},
                {"velocity_km_s": 200, "n0_cm3": 1, "T_post_K": 3.5e5, "OIII_Ha": 5.0},
                {"velocity_km_s": 250, "n0_cm3": 1, "T_post_K": 5.5e5, "OIII_Ha": 7.0},
                {"velocity_km_s": 300, "n0_cm3": 1, "T_post_K": 8.0e5, "OIII_Ha": 9.0},
            ]
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
            _json.dump(grid_data, tf); grid_path = tf.name
        loader0 = MappingsGridLoader()
        grid_hash = sha256_file(grid_path)
        loader = MappingsGridLoader(trusted_hashes=[grid_hash])
        grid = loader.load(grid_path)
        post = grid_posterior_inference(3.5, 0.3, grid, n_samples=1000)
        check("posterior: v_median", post.get("v_median") is not None and post.get("v_median") > 0)
        check("posterior: CI", post.get("v_ci_68") is not None and len(post.get("v_ci_68", [])) == 2)
        check("posterior: INFERENCIA", post.get("state") == "INFERENCIA DE MODELO")
        check("posterior: grid_validated", post.get("grid_validated") is True)
        # Non-validated grid should be blocked
        gm = GridManager()
        demo_grid = gm.embedded()
        post_demo = grid_posterior_inference(2.0, 0.2, demo_grid, n_samples=100)
        check("posterior: DEMO blocked", post_demo.get("state") == "NO DISPONIBLE")
    except Exception as exc:
        check("posterior", False, str(exc))
    try:
        # HTML report contains QC blocks
        import tempfile
        with tempfile.TemporaryDirectory() as tdp:
            payload = synthetic_end_to_end(Path(tdp) / "html_test")
            html_path = str(Path(tdp) / "report.html")
            write_html_report(payload, html_path)
            html_content = Path(html_path).read_text(encoding="utf-8")
            check("html: has consistency", "Consistencia Científica" in html_content)
            check("html: has QC", "Quality Control" in html_content)
            check("html: has provenance", "Provenance" in html_content)
            check("html: has uncertainty", "Incertidumbre" in html_content)
    except Exception as exc:
        check("html_report v29", False, str(exc))

    # v29: Sistema de scripts externos
    import tempfile as _tmp
    _tmpd = _tmp.mkdtemp(prefix="aps_st_")
    try:
        # Script válido
        _s1 = os.path.join(_tmpd, "valid.py")
        with open(_s1, "w") as _f:
            _f.write("def run(ctx):\n    return {\"result\": 42, \"state\": \"OBSERVABLE\"}\n")
        _r = run_external_script(_s1, payload={"candidates": []}, out_dir=_tmpd)
        check("script: estado OK", _r["state"] == "OK")
        check("script: resultado dict", isinstance(_r["result"], dict) and _r["result"].get("result") == 42)
        check("script: sha256 provenance", len(_r["provenance"].get("script_sha256", "")) == 64)
        check("script: external flag", _r["provenance"]["external"] is True)
        # Script sin run()
        _s2 = os.path.join(_tmpd, "no_run.py")
        with open(_s2, "w") as _f:
            _f.write("x = 1\n")
        _r2 = run_external_script(_s2, out_dir=_tmpd)
        check("script: no run() -> error", _r2["state"] == "ERROR")
        check("script: mensaje error", "run" in (_r2["error"] or ""))
        # Script que lanza excepción
        _s3 = os.path.join(_tmpd, "crash.py")
        with open(_s3, "w") as _f:
            _f.write("def run(ctx):\n    raise RuntimeError(\"test error\")\n")
        _r3 = run_external_script(_s3, out_dir=_tmpd)
        check("script: crash capturado", _r3["state"] == "ERROR")
        check("script: stderr capturado", "test error" in (_r3["error"] or ""))
        # CLI script --template
        _tpl = os.path.join(_tmpd, "template.py")
        create_template_script(_tpl)
        check("template: created", os.path.exists(_tpl))
        check("template: has run()", "def run(ctx):" in Path(_tpl).read_text())
        # API version constante
        check("script: api_version", SCRIPT_API_VERSION == "1.0")
    finally:
        import shutil as _sh; _sh.rmtree(_tmpd, ignore_errors=True)

    try:
        _rows=[{"id":1,"nx":1.0,"ny":1.0,"offset_px":4.0,"offset_arcsec":4.0,"ratio":2.0,"peak_snr_ha":10.0,"peak_snr_oiii":10.0},
               {"id":2,"nx":-1.0,"ny":-1.0,"offset_px":-4.0,"offset_arcsec":-4.0,"ratio":2.1,"peak_snr_ha":10.0,"peak_snr_oiii":10.0}]
        _pa=physical_anomaly_engine(_rows)
        _keys=[a.get("parameter") for rr in _pa["rows"] for a in rr.get("anomalies",[])]
        check("v39: physical anomaly ignores signed geometry", "nx" not in _keys and "ny" not in _keys and "offset_arcsec" not in _keys and "offset_px" not in _keys)
    except Exception as exc:
        check("v39: physical anomaly ignores signed geometry", False, str(exc))
    try:
        # v36: corrected calibrated map should differ from raw ratio when correction != 1
        calx=LineCalibration(oiii_transmission=1.0,ha_transmission=1.0,oiii_exptime_s=1.0,ha_exptime_s=1.0,nii_over_ha=0.2,nii_transmission_rel=1.0,ebv=0.0,calibrated=True)
        yy,xx=np.mgrid[:32,:32]
        h=(10.0+2.0*np.exp(-((xx-16)**2+(yy-16)**2)/40.0)).astype(np.float32)
        o=(20.0+4.0*np.exp(-((xx-16)**2+(yy-16)**2)/40.0)).astype(np.float32)
        bh=estimate_background(h); bo=estimate_background(o)
        qp=quantitative_ratio_products(h,o,bh,bo,[],cal=calx)
        vals=qp["ratio_linear"][np.isfinite(qp["ratio_linear"])]
        check("v39: ratio map incorpora corrección NII", bool(vals.size) and float(np.nanmax(vals)) > 2.0)
    except Exception as exc:
        check("v36: ratio map calibration", False, str(exc))
    try:
        base=[{"id":i,"ratio":1.0+0.03*i,"peak_snr_ha":10,"peak_snr_oiii":10} for i in range(8)]
        base.append({"id":99,"ratio":20.0,"peak_snr_ha":10,"peak_snr_oiii":10})
        pa=physical_anomaly_engine(base)
        check("v39: anomaly engine", pa.get("n_anomalies",0) >= 1)
    except Exception as exc:
        check("v39: anomaly engine", False, str(exc))
    try:
        with tempfile.TemporaryDirectory() as _pdir:
            pf=Path(_pdir)/"project.json"
            ds=DiscoveryStore(pf); proj=ds.create("test-project",target_name="Synthetic")
            rows=[{"id":i,"ratio":1.0+0.02*i,"peak_snr_ha":10.0,"peak_snr_oiii":10.0} for i in range(8)]
            rows.append({"id":99,"ratio":50.0,"peak_snr_ha":10.0,"peak_snr_oiii":10.0})
            pld={"summary":{"target_name":"Synthetic"},"candidates":rows}
            ds.add_analysis(pld,source_path="synthetic.json")
            rr=ds.rank_candidates(); check("v40: discovery project persistent", pf.is_file() and len(rr)>=1 and rr[0]["row_id"]==99 and rr[0]["priority"]>0)
            rv=ds.review("99","PHYSICAL_TENSION",note="test"); check("v40: candidate review", rv["state"]=="PHYSICAL_TENSION")
            rec=build_discovery_record(pld,project_id=proj["project_id"]); check("v40: discovery record", rec["scientific_policy"]["human_verification_required"] and len(rec["candidate_states"])==9)
    except Exception as exc:
        check("v40: discovery platform",False,str(exc))
    try:
        phys=physical_discovery_bundle({"candidates":[{"row_id":"p1","ratio":2.0,"ratio_err":0.1,"offset_arcsec":60.0,"velocity_kms":800.0,"radius_pc":0.30}]}, object_family="SNR", distance_pc=1000.0, distance_err_pc=50.0)
        check("v41: physical inference engine", phys.get("state")=="OK" and phys.get("n_rows")==1)
        pp=phys["rows"][0]["inference"]["parameters"]
        check("v41: model labels", pp.get("postshock_temperature_K",{}).get("model")=="strong_shock_temperature" and pp.get("age_yr",{}).get("model")=="sedov_uniform_medium")
        check("v41: ai independent", phys.get("ai",{}).get("state")=="NO EJECUTADA")
    except Exception as exc:
        check("v41: physical inference",False,str(exc))
    try:
        rng=np.random.default_rng(20260915)
        x=np.linspace(-2,2,40); sigma=np.full_like(x,0.08); y=1.2+0.45*x+rng.normal(0,0.08,x.size)
        cmp=compare_physical_models_from_catalog({"model_data":{"x":x.tolist(),"y":y.tolist(),"sigma":sigma.tolist()}})
        check("v42: model comparison activo", cmp.get("state")=="OK" and cmp.get("n_models")==3)
        check("v42: modelo lineal seleccionado", cmp.get("best_model_bic")=="linear")
        check("v42: AICc/BIC delta", all("delta_bic" in m and "delta_aicc" in m for m in cmp.get("models",[])))
        # Sigma inválida debe bloquear el ajuste en vez de ser ponderación infinita.
        eng=build_default_model_comparison_engine()
        try: eng.fit("constant",[0,1],[1,2],[0,-1])
        except ValueError: invalid=True
        else: invalid=False
        check("v42: sigma invalida bloqueada", invalid)
    except Exception as exc:
        check("v42: model comparison",False,str(exc))
    try:
        # stack_multiband: regression for Background.bkg contract.
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            a=np.ones((32,32),np.float32)*100
            b=np.ones((32,32),np.float32)*200
            p1=Path(td)/"test_Ha.fits"; p2=Path(td)/"test_OIII.fits"; out=Path(td)/"stack.fits"
            if HAS_ASTROPY:
                _fits.PrimaryHDU(a).writeto(p1,overwrite=True); _fits.PrimaryHDU(b).writeto(p2,overwrite=True)
                sr=stack_multiband([str(p1),str(p2)],str(out),normalize=True)
                check("stack_multiband: normalize", sr.get("state")=="OBSERVABLE" and sr.get("n_bands")==2 and out.is_file())
            else:
                check("stack_multiband: normalize", True, "omitido sin Astropy")
    except Exception as exc:
        check("stack_multiband: normalize", False, str(exc))
    try:
        # proper motion: regression for Nx3 detector return contract.
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            yy,xx=np.mgrid[:96,:96]
            def mk(shiftx):
                im=np.ones((96,96),np.float32)*100
                for x,y,a in [(20+shiftx,20,300),(50+shiftx,35,500),(70+shiftx,70,400),(30+shiftx,60,350)]:
                    im += a*np.exp(-0.5*((xx-x)**2+(yy-y)**2)/(2.0**2))
                return im
            p1=Path(td)/"e1.fits"; p2=Path(td)/"e2.fits"
            if HAS_ASTROPY:
                _fits.PrimaryHDU(mk(0)).writeto(p1,overwrite=True); _fits.PrimaryHDU(mk(1.25)).writeto(p2,overwrite=True)
                mr=measure_proper_motion(str(p1),str(p2),pixel_scale_arcsec=1.0,time_baseline_yr=1.0)
                check("proper_motion: Nx3 contract", mr.get("state") != "NO DISPONIBLE" and mr.get("n_stars_matched",0) >= 3)
            else:
                check("proper_motion: Nx3 contract", True, "omitido sin Astropy")
    except Exception as exc:
        check("proper_motion: Nx3 contract", False, str(exc))
    return fails

def audit_report():
    return {
        "version": __version__,
        "schema": SCHEMA_VERSION,
        "v36_policy": {
            "profile_source": "starless_only",
            "stellar_source": "normal_images_only",
            "allowed_filters": FILTER_VISIBLE,
        "discovery_ai": {"enabled": True, "purpose": "neural known-class classification + novelty ranking", "requires_real_training_data": True, "human_validation_required": True, "persistent_session": True, "model_format_version": AI_MODEL_FORMAT_VERSION},
        "camera_system": CAMERA_PROFILE_ASI533MC_PRO,
            "narrowband_pair_filter": FILTER_NARROWBAND_VISIBLE[0],
            "broadband_context_filter": "Optolong L-Quad Enhance",
            "spectrophotometric_color_calibration": "Gaia DR3 XP / SPCC-compatible public workflow",
            "scientific_integrity": "unit-aware, multi-parameter, IA-independent anomaly analysis; no automatic discovery claims",
        },
        "implemented": [
            "v40: persistent DiscoveryProject/DiscoveryStore with candidate lifecycle",
            "v40: auditable discovery-record product with physical anomalies and human verification gates",
            "v40: multiparameter candidate ranking independent of IA",
        "v54: all v36-v47 APIs retained; commercial hardware diagnostics; cached/cancellable independent Excel; physical+visual AI series; spatial-greedy profiles",
            "v42: model-comparison engine with sigma-aware likelihood, AICc/BIC, identifiability diagnostics, optional explicit-prior Laplace evidence, residual-structure discrepancy tests and independent-evidence discovery gate",
            "FITS/HDU validation with explicit cube-plane requirement",
            "WCS/scale metadata and Gaia diagnostic hooks",
            "photutils Background2D when available + robust fallback",
            "physical variance when GAIN/RDNOISE exist + local-RMS fallback",
            "one-to-one stellar registration with Hungarian assignment",
            "subpixel sign convention test and phase fallback warning",
            "strict stellar-vs-shock profile separation",
            "safe ratio/cooling masks and registered-edge exclusion",
            "quantitative FITS ratio/error/SNR/background/RMS/star-mask products when Astropy is installed",
            "filter curve CSV/DAT/JSON loader with Angstrom/percent normalization",
            "2x2 line de-mixing with determinant/condition-number guard and MC uncertainty option",
            "GridManager for embedded demo grid + CSV/ECSV/JSON validation",
            "offline-safe Gaia/SIMBAD gating",
            "reproducible manifest and atomic JSON persistence",
            "GUI profiles selector, filter curves, offline mode, PDF/HTML/CSV/JSON/ECSV exports",
            "reproducible synthetic data and selftest/pytest coverage",
            "v28: check_scientific_consistency() with OBSERVABLE/PROXY/INFERENCIA/CALIBRADO/EXTRAPOLADO states",
            "v28: MappingsGridLoader for external MAPPINGS/3MdB grids with SHA256 provenance",
            "v28: compute_uncertainty_budget() structured error budget",
            "v28: compare_with_literature_zscore() replacing percentage comparison",
            "v28: detect_anomalies() with conservative labels (never 'discovery')",
            "v28: generate_qc_summary() unified quality control",
            "v28: simulate_observation() forward model",
            "v28: estimate_shock_velocity() grid-only (never from naked ratio)",
            "v28: estimate_ast_remnant_age() with radius+distance+velocity guard",
            "v28: stack_multiband() for NII/SII/OIII/Halpha stacking",
            "v28: measure_proper_motion() two-epoch proper motion",
            "v28: apply_redshift_correction() and luminosity_distance()",
            "v28: build_provenance_chain() full pipeline provenance",
            "v28: compute_physical_maps() 2D quantity maps with states",
            "v28: extract_radial_profile() for circular remnants",
            "v28: export_environment() for reproducibility",
            "v28: analyze_pair wrapper with scientific consistency, uncertainty budget, literature z-score, anomalies, QC summary, provenance, physical maps",
            "v29: MappingsGridLoader connected to CLI analyze (no silent fallback to DEMO)",
            "v29: HTML report with QC/consistency/provenance/anomalies/uncertainty/literature blocks",
            "v29: PDF report with dedicated QC/consistency/provenance page",
            "v29: compute_airmass() Kasten-Young airmass",
            "v29: apply_atmospheric_extinction() flux correction with error propagation",
            "v29: absolute_photometric_calibration() ADU to magnitude/flux with state tracking",
            "v29: measure_source_quality() FWHM/ellipticity/sharpness/saturation/isolation",
            "v29: measure_psf_quality() seeing estimate and quality flags",
            "v29: validate_wcs() WCS header validation with scale/rotation/coverage",
            "v29: crossmatch_gaia_safe() Gaia DR3 cross-match (never discovery)",
            "v29: grid_posterior_inference() Monte Carlo posterior over validated MAPPINGS grid",
            "v29: analyze_multiband_pipeline() multiband stacking + color-color connection",
            "v29: CLI commands: calibrate, psf, wcs, gaia-match, posterior, multiband-pipeline"],
        "conditioned": [
            "absolute photometric calibration: requires documented instrumental response and zeropoint",
            "physical shock velocity/temperature/density: requires validated calibrated line data plus MAPPINGS/3MdB grid",
            "atmospheric correction: requires local extinction coefficient and airmass",
            "Gaia/SIMBAD object novelty: internet and catalogue-quality matching are required",
            "3D/4D FITS plane selection: full support requires Astropy in the runtime",
            "MAPPINGS/3MdB grid inversion: requires external grid file; heuristic grid is DEMO only",
            "multiband stacker: requires pre-registered images of same shape",
            "proper motion: requires two epochs with sufficient time baseline",
            "age estimation: requires radius + distance + velocity simultaneously; Sedov approximation only",
            "v29: absolute photometric calibration: requires zeropoint, exposure, gain; CALIBRADO only with extinction",
            "v29: WCS validation: requires FITS header with CRPIX/CRVAL/CD or CDELT",
            "v29: Gaia cross-match: requires astroquery + internet; never marks discoveries",
            "v29: Bayesian posterior: requires validated_model_grid=True; NO DISPONIBLE otherwise",
            "v29: PSF quality: FWHM via 2D moments; not full PSF photometry",
            "v29: multiband pipeline: requires pre-registered images of same shape",
            "v30: strict normal-vs-starless separation for scientific profiles",
            "v31: Optolong L-Quad Enhance as broadband contextual scientific channel",
            "v33: AstroDiscovery AI with persistent session, MLP classifier, novelty detector and grouped validation",
            "v33: GUI error-proofing for filter curve initialization and persistent AI controls",
            "v31: instrument profile locked to ZWO ASI533MC Pro nominal specifications",
            "v31: multi-object scientific scope beyond SNR/profile-only analysis",
            "v30: object-adaptive profile geometry and ranking",
            "v30: Gaia DR3 XP spectrophotometric color calibration (SPCC-compatible public method)",
            "v30: non-monotonic discrete-grid posterior and strict grid validation"],
        "not_claimed": [
            "no direct velocity from spatial OIII-Halpha offset",
            "no direct temperature/density/cooling time from two images",
            "no claim of astronomical discovery from catalogue matches or anomaly detection",
            "no invented filter curves or measured transmissions",
            "no claim that L-QEF alone isolates Halpha/OIII; it is treated as broadband context",
            "no MAPPINGS/3MdB grid included; loader/validator provided but real grid must be supplied externally",
            "no atmospheric extinction correction without local coefficient"],
        "tests": {
            "py_compile": "run: python -m py_compile AstroPhysics_Suite_v45_0_0.py",
            "selftest": "run: python AstroPhysics_Suite_v45_0_0.py selftest",
            "pytest": "run: pytest test_aps_v45.py -v",
            "astropy_dependent_tests": "E2E tests require Astropy; fallback tests run without it"}
    }


# ====================================================================
# Sistema de Scripts Externos (Plugin API v1.0)
# ====================================================================
SCRIPT_API_VERSION = "1.0"

@dataclass
class ScriptContext:
    """Contexto de solo lectura pasado a scripts externos.

    Un script externo debe definir:

        def run(ctx):
            # ctx.payload: dict con catálogo, summary, scientific_consistency, etc.
            # ctx.params: dict con parámetros del análisis
            # ctx.grid: ShockGrid o None
            # ctx.calibration: dict con calibración fotométrica
            # ctx.out_dir: str, directorio de salida
            # ctx.api_version: str
            # ctx.helpers: dict con funciones de la suite
            return {"my_result": 42, "state": "OBSERVABLE"}

    El valor devuelto debe ser JSON-serializable.
    Todo resultado se marca como externo/no validado en la provenance.
    """
    payload: dict
    params: dict
    grid: object
    calibration: dict
    out_dir: str
    api_version: str = SCRIPT_API_VERSION
    helpers: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.helpers:
            self.helpers = {
                "json_sanitize": json_sanitize,
                "estimate_ast_remnant_age": estimate_ast_remnant_age,
                "apply_redshift_correction": apply_redshift_correction,
                "estimate_shock_velocity": estimate_shock_velocity,
                "build_provenance_chain": build_provenance_chain,
                "generate_qc_summary": generate_qc_summary,
                "evaluate_scientific_consistency": check_scientific_consistency,
                "literature_zscore": compare_with_literature_zscore,
                "load_scientific_grid": load_scientific_grid,
            }


def run_external_script(script_path, payload=None, params=None, grid=None,
                        calibration=None, out_dir=".", timeout_s=120):
    """Ejecuta un script Python externo con acceso al contexto de la suite.

    El script debe definir ``run(ctx) -> dict``.
    Se ejecuta en un namespace aislado; NO es un sandbox seguro: solo ejecutar
    scripts de confianza.

    Returns
    -------
    dict with keys:
        - result: dict devuelto por el script (o vacío)
        - provenance: dict con ruta, sha256, api_version, timestamp, args
        - stdout: str
        - stderr: str
        - error: str o None
        - state: "OK" | "ERROR"
    """
    import hashlib as _hl
    import io as _io
    import importlib.util as _ilu

    script_path = str(script_path)
    if not Path(script_path).is_file():
        return {"state": "ERROR", "error": f"Script no encontrado: {script_path}",
                "result": {}, "provenance": {}, "stdout": "", "stderr": ""}

    sha256 = _hl.sha256(Path(script_path).read_bytes()).hexdigest()
    ctx = ScriptContext(
        payload=payload or {},
        params=params or {},
        grid=grid,
        calibration=calibration or {},
        out_dir=str(out_dir),
    )

    # Capturar stdout/stderr
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = _io.StringIO()
    sys.stderr = _io.StringIO()
    error_msg = None
    result = {}
    try:
        # Cargar el script como módulo
        spec = _ilu.spec_from_file_location("aps_external_script", script_path)
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if not hasattr(mod, "run"):
            error_msg = "El script no define la función run(ctx)."
        elif not callable(getattr(mod, "run")):
            error_msg = "El atributo 'run' del script no es callable."
        else:
            _old_handler = None
            _timer_set = False
            try:
                if timeout_s is not None and float(timeout_s) > 0 and hasattr(_signal, "setitimer") and threading.current_thread() is threading.main_thread():
                    class _ScriptTimeout(RuntimeError): pass
                    _old_handler = _signal.signal(_signal.SIGALRM, lambda *_: (_ for _ in ()).throw(_ScriptTimeout(f"timeout > {float(timeout_s):.1f}s")))
                    _signal.setitimer(_signal.ITIMER_REAL, float(timeout_s)); _timer_set = True
                elif timeout_s is not None and float(timeout_s) > 0:
                    LOG.warning("timeout_s=%s no puede imponerse en este hilo/plataforma; ejecución en proceso actual", timeout_s)
                result = mod.run(ctx)
            except Exception:
                raise
            finally:
                if _timer_set:
                    _signal.setitimer(_signal.ITIMER_REAL, 0.0)
                    _signal.signal(_signal.SIGALRM, _old_handler)
            if not isinstance(result, dict):
                error_msg = f"run() debe devolver dict, devolvió {type(result).__name__}"
                result = {}
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
    finally:
        stdout_val = sys.stdout.getvalue()
        stderr_val = sys.stderr.getvalue()
        sys.stdout, sys.stderr = old_stdout, old_stderr

    # Intentar JSON-serializar el resultado
    try:
        json.dumps(json_sanitize(result), ensure_ascii=False)
    except Exception as exc:
        error_msg = f"Resultado no JSON-serializable: {exc}"
        result = {"_raw_type": str(type(result))}

    prov = {
        "script_path": script_path,
        "script_sha256": sha256,
        "api_version": SCRIPT_API_VERSION,
        "executed_utc": datetime.now(timezone.utc).isoformat(),
        "out_dir": str(out_dir),
        "external": True,
        "validated": False,
    }

    state = "ERROR" if error_msg else "OK"
    if error_msg:
        LOG.error("Script externo falló: %s", error_msg)

    return {
        "result": result,
        "provenance": prov,
        "stdout": stdout_val,
        "stderr": stderr_val,
        "error": error_msg,
        "state": state,
    }


def create_template_script(path):
    """Escribe un script plantilla en la ruta dada."""
    template = '''#!/usr/bin/env python3
"""Plantilla de script externo para AstroPhysics Suite v29.

Defina la función run(ctx) -> dict. El resultado debe ser JSON-serializable.
"""


def run(ctx):
    """Ejecutar análisis personalizado.

    Parámetros disponibles en ctx:
        ctx.payload      -> dict con catálogo, summary, scientific_consistency
        ctx.params       -> dict con parámetros del análisis
        ctx.grid         -> ShockGrid o None
        ctx.calibration  -> dict con calibración fotométrica
        ctx.out_dir      -> str, directorio de salida
        ctx.api_version  -> str ("1.0")
        ctx.helpers      -> dict con funciones de la suite
    """
    # Ejemplo: extraer número de filamentos del catálogo
    n_fil = len(ctx.payload.get("candidates", []))

    return {
        "n_filaments": n_fil,
        "state": "OBSERVABLE",
        "note": "Conteo directo del catálogo de la suite",
    }
'''
    Path(path).write_text(template, encoding="utf-8")
    return str(path)


# ====================================================================
# CLI
# ====================================================================
def build_parser():
    p=argparse.ArgumentParser(prog=f"AstroPhysics_Suite_{__version__}")
    p.add_argument("-v","--verbose",action="store_true"); sub=p.add_subparsers(dest="cmd",required=True)
    a=sub.add_parser("analyze",help="Analiza un par [O III]/Hα")
    a.add_argument("--oiii"); a.add_argument("--ha"); a.add_argument("--oiii-starless",required=True); a.add_argument("--ha-starless",required=True); a.add_argument("--out",required=True); a.add_argument("--dir")
    a.add_argument("--oiii-plane",default="",help="Plano explícito: 0 para 3D, o i,j para 4D")
    a.add_argument("--ha-plane",default="",help="Plano explícito: 0 para 3D, o i,j para 4D")
    a.add_argument("--grid"); a.add_argument("--grid-registry",default="",help="Registro JSON de SHA256 de grids auditados"); a.add_argument("--no-builtin-grid",action="store_true"); a.add_argument("--labels"); a.add_argument("--light",default="")
    a.add_argument("--pixel-scale",type=float,default=float("nan")); a.add_argument("--target-name",default="")
    a.add_argument("--starless",action="store_true",help=argparse.SUPPRESS); a.add_argument("--register",choices=["auto","stars","phase","none"],default="stars",help=argparse.SUPPRESS)
    a.add_argument("--distance-pc",type=float,default=725.0); a.add_argument("--distance-err-pc",type=float,default=15.0); a.add_argument("--n0",type=float,default=6.0)
    a.add_argument("--snr-min",type=float,default=4.0); a.add_argument("--max-candidates",type=int,default=2000); a.add_argument("--min-separation-px",type=float,default=8.0)
    a.add_argument("--workers",type=int,default=max(1,(os.cpu_count() or 2)-2)); a.add_argument("--threads",action="store_true"); a.add_argument("--no-accumulate",action="store_true")
    a.add_argument("--seed",type=int,default=20260914); a.add_argument("--ebv",type=float,default=0.0); a.add_argument("--nii-over-ha",type=float,default=0.0)
    a.add_argument("--oiii-filter",default=FILTER_DEFAULT,choices=FILTER_NARROWBAND_VISIBLE); a.add_argument("--ha-filter",default=FILTER_DEFAULT,choices=FILTER_NARROWBAND_VISIBLE,help=argparse.SUPPRESS)
    a.add_argument("--broadband",default="",help="FITS normal registrado con Optolong L-Quad Enhance (opcional)")
    a.add_argument("--grid-model-logerr",type=float,default=0.15); a.add_argument("--filament-strategy",choices=["hessian","canny"],default="hessian"); a.add_argument("--pdf",action="store_true"); a.add_argument("--html",action="store_true"); a.add_argument("--png-dpi",type=int,default=300)
    a.add_argument("--export-products",action="store_true"); a.add_argument("--export-ecsv",action="store_true"); a.add_argument("--offline",action="store_true"); a.add_argument("--oiii-curve",default=""); a.add_argument("--ha-curve",default=""); a.add_argument("--photometric-calibrated",action="store_true"); a.add_argument("--oiii-zp-factor",type=float,default=1.0); a.add_argument("--ha-zp-factor",type=float,default=1.0); a.add_argument("--zeropoint-source",default="",help="Fuente/estándar del zeropoint; obligatorio para validar"); a.add_argument("--zeropoint-error-mag",type=float,default=float("nan"),help="Incertidumbre del zeropoint en mag; obligatoria para validar"); a.add_argument("--calibration-id",default="",help="ID trazable de la calibración"); a.add_argument("--r-v",type=float,default=3.1); a.add_argument("--bias-oiii",default=""); a.add_argument("--bias-ha",default=""); a.add_argument("--dark-oiii",default=""); a.add_argument("--dark-ha",default=""); a.add_argument("--flat-oiii",default=""); a.add_argument("--flat-ha",default="")
    ph=sub.add_parser("physics"); ph.add_argument("--v",type=float,required=True); ph.add_argument("--v-err",type=float,default=10); ph.add_argument("--n0",type=float,default=6); ph.add_argument("--T0",type=float,default=1e4); ph.add_argument("--beta",type=float,default=1); ph.add_argument("--cooling-csv")
    pdx=sub.add_parser("physics-diagnostics",help="Diagnóstico multiobjeto de observables de un catálogo JSON")
    pdx.add_argument("catalog"); pdx.add_argument("--out",default="physics_diagnostics.json"); pdx.add_argument("--distance-pc",type=float,default=float("nan")); pdx.add_argument("--distance-err-pc",type=float,default=float("nan")); pdx.add_argument("--ebv",type=float,default=0.0); pdx.add_argument("--pixel-scale",type=float,default=float("nan"))
    pan=sub.add_parser("physical-anomalies",help="Busca anomalías multiparámetro sin depender de IA"); pan.add_argument("catalog",help="catalog.json o lista JSON de observaciones"); pan.add_argument("--out",default="physical_anomalies.json")
    inv=sub.add_parser("invert"); inv.add_argument("--grid-registry",default=""); inv.add_argument("--grid"); inv.add_argument("--ratio",type=float,required=True); inv.add_argument("--ratio-err",type=float,default=.1); inv.add_argument("--n0",type=float); inv.add_argument("--grid-model-logerr",type=float,default=.15)
    rp=sub.add_parser("report"); rp.add_argument("catalog"); rp.add_argument("--out",default="report.pdf"); rp.add_argument("--html",action="store_true")
    sub.add_parser("selftest"); syn=sub.add_parser("synthetic"); syn.add_argument("--out",default="synthetic_run")
    dv=sub.add_parser("discover-v46",help="Motor físico/estadístico multimotor v46"); dv.add_argument("catalog"); dv.add_argument("--out",default="discovery_v46.json"); dv.add_argument("--object-family",default="unknown"); dv.add_argument("--reference",default="")
    sv=sub.add_parser("spatial-anomalies",help="Anomalías espaciales con detrending + FDR"); sv.add_argument("catalog"); sv.add_argument("--out",default="spatial_anomalies.json"); sv.add_argument("--z-threshold",type=float,default=4.0); sv.add_argument("--fdr-alpha",type=float,default=0.01)
    tv=sub.add_parser("temporal-anomalies",help="Variabilidad multiepoch con errores explícitos"); tv.add_argument("catalog"); tv.add_argument("--out",default="temporal_analysis.json"); tv.add_argument("--min-epochs",type=int,default=3); tv.add_argument("--sigma-threshold",type=float,default=4.0)
    rd=sub.add_parser("real-dataset",help="Crea dataset de parches a partir de observaciones reales FITS/XISF"); rd.add_argument("--out",required=True); rd.add_argument("--images",nargs="+",required=True); rd.add_argument("--object",action="append",default=[]); rd.add_argument("--patch-size",type=int,default=128); rd.add_argument("--patches-per-image",type=int,default=48); rd.add_argument("--seed",type=int,default=47)
    ra=sub.add_parser("real-ai-train",help="Entrena AstroVision con dataset real del usuario"); ra.add_argument("--dataset",required=True); ra.add_argument("--model",required=True); ra.add_argument("--epochs",type=int,default=8); ra.add_argument("--batch-size",type=int,default=16); ra.add_argument("--seed",type=int,default=47); ra.add_argument("--max-patches",type=int,default=1024)
    g=sub.add_parser("gui"); g.add_argument("--oiii"); g.add_argument("--ha")
    sub.add_parser("audit")
    sub.add_parser("deps"); sub.add_parser("literature"); sub.add_parser("filters")
    gc_=sub.add_parser("gaia"); gc_.add_argument("--ra",type=float,required=True); gc_.add_argument("--dec",type=float,required=True); gc_.add_argument("--radius",type=float,default=.5); gc_.add_argument("--mag-limit",type=float,default=18); gc_.add_argument("--max-rows",type=int,default=500); gc_.add_argument("--distance",action="store_true")
    # v28 CLI commands
    mb=sub.add_parser("multiband"); mb.add_argument("--images",nargs="+",required=True); mb.add_argument("--out",required=True); mb.add_argument("--plane",default=""); mb.add_argument("--no-normalize",action="store_true")
    pm=sub.add_parser("propermotion"); pm.add_argument("--epoch1",required=True); pm.add_argument("--epoch2",required=True); pm.add_argument("--pixel-scale",type=float,default=1.0); pm.add_argument("--baseline-yr",type=float,default=1.0)
    fv=sub.add_parser("velocity"); fv.add_argument("--ratio",type=float,required=True); fv.add_argument("--ratio-err",type=float,default=0.1); fv.add_argument("--grid-registry",default=""); fv.add_argument("--grid",default=""); fv.add_argument("--n0",type=float,default=6.0)
    ag=sub.add_parser("age"); ag.add_argument("--radius-arcsec",type=float,required=True); ag.add_argument("--distance-pc",type=float,required=True); ag.add_argument("--velocity",type=float,default=None); ag.add_argument("--velocity-err",type=float,default=None); ag.add_argument("--n0",type=float,default=6.0)
    rz=sub.add_parser("redshift"); rz.add_argument("--wavelength",type=float,required=True); rz.add_argument("--z",type=float,required=True)
    qg=sub.add_parser("qc"); qg.add_argument("catalog",help="catalog.json"); qg.add_argument("--out",default="qc_summary.json")
    pr=sub.add_parser("provenance"); pr.add_argument("catalog",help="catalog.json"); pr.add_argument("--out",default="provenance.json")
    fw=sub.add_parser("forward"); fw.add_argument("--shape",type=int,nargs=2,default=[256,256]); fw.add_argument("--n-filaments",type=int,default=1); fw.add_argument("--n-stars",type=int,default=10); fw.add_argument("--offset",type=float,default=4.0); fw.add_argument("--seed",type=int,default=42); fw.add_argument("--out",default="forward_model.json")
    mg=sub.add_parser("mappings"); mg.add_argument("--grid-registry",default=""); mg.add_argument("--grid",required=True); mg.add_argument("--validate",action="store_true")
    gt=sub.add_parser("grid-trust",help="Registra el SHA256 de un grid externo que el usuario ha auditado"); gt.add_argument("--grid",required=True); gt.add_argument("--registry",required=True); gt.add_argument("--reference",default="")
    # v29 CLI commands
    pc=sub.add_parser("calibrate"); pc.add_argument("--flux-adu",type=float,required=True); pc.add_argument("--zeropoint",type=float,required=True); pc.add_argument("--exposure",type=float,required=True); pc.add_argument("--gain",type=float,default=1.0); pc.add_argument("--airmass",type=float,default=None); pc.add_argument("--k-ext",type=float,default=None); pc.add_argument("--k-err",type=float,default=0.0); pc.add_argument("--flux-err",type=float,default=None)
    ps=sub.add_parser("psf"); ps.add_argument("--image",required=True); ps.add_argument("--x",type=float,required=True); ps.add_argument("--y",type=float,required=True); ps.add_argument("--cutout",type=int,default=25); ps.add_argument("--gain",type=float,default=1.0); ps.add_argument("--saturation",type=float,default=None)
    wc=sub.add_parser("wcs"); wc.add_argument("--header",required=True,help="FITS file with WCS header"); wc.add_argument("--shape",type=int,nargs=2,default=[256,256])
    gm=sub.add_parser("gaia-match"); gm.add_argument("--ra",type=float,required=True); gm.add_argument("--dec",type=float,required=True); gm.add_argument("--radius",type=float,default=30.0); gm.add_argument("--mag-limit",type=float,default=18.0)
    bi=sub.add_parser("posterior"); bi.add_argument("--ratio",type=float,required=True); bi.add_argument("--ratio-err",type=float,default=0.1); bi.add_argument("--grid-registry",default=""); bi.add_argument("--grid",required=True); bi.add_argument("--n0",type=float,default=6.0); bi.add_argument("--n-samples",type=int,default=5000)
    mb=sub.add_parser("multiband-pipeline"); mb.add_argument("--images",nargs="+",required=True); mb.add_argument("--out",required=True); mb.add_argument("--pixel-scale",type=float,default=1.0); mb.add_argument("--no-normalize",action="store_true")
    # v29: External scripting system
    sc=sub.add_parser("script",help="Ejecuta un script Python externo sobre un análisis")
    sc.add_argument("--file",required=True,help="Ruta al script .py externo")
    sc.add_argument("--catalog",default="",help="catalog.json de un análisis previo (opcional)")
    sc.add_argument("--out",default="",help="Directorio de salida (opcional)")
    sc.add_argument("--template",action="store_true",help="Generar script plantilla en --file y salir")
    ai=sub.add_parser("ai-train",help="Entrena la IA de descubrimiento con datos reales etiquetados/no etiquetados")
    ai.add_argument("--training",required=True,help="CSV o JSON de observaciones reales")
    ai.add_argument("--model",required=True,help="Fichero .pkl del modelo local")
    ai.add_argument("--min-rows",type=int,default=80)
    ai.add_argument("--contamination",type=float,default=0.02)
    rv=sub.add_parser("ai-real-corpus",help="Crea y descarga un corpus FITS real público para preentrenamiento visual")
    rv.add_argument("--manifest",default="real_vision_manifest.json"); rv.add_argument("--out",default="real_vision_corpus"); rv.add_argument("--max-objects",type=int,default=32); rv.add_argument("--overwrite",action="store_true")
    arvt=sub.add_parser("ai-real-train",help="Descarga corpus real público y entrena AstroVision")
    arvt.add_argument("--out",default="real_vision_corpus"); arvt.add_argument("--model",default="astrovision_v35_real.pt"); arvt.add_argument("--manifest",default="real_vision_manifest.json"); arvt.add_argument("--max-objects",type=int,default=32); arvt.add_argument("--epochs",type=int,default=18); arvt.add_argument("--batch-size",type=int,default=8); arvt.add_argument("--max-images",type=int,default=512)
    av=sub.add_parser("ai-vision-train",help="Entrena la CNN visual con FITS astronómicos reales")
    av.add_argument("--training",required=True,help="Directorio con FITS reales")
    av.add_argument("--model",required=True,help="Modelo .pt")
    av.add_argument("--epochs",type=int,default=12)
    av.add_argument("--batch-size",type=int,default=8)
    av.add_argument("--max-images",type=int,default=256)
    ais=sub.add_parser("ai-session",help="Mantiene una sesión IA persistente en consola y analiza catalog.json repetidamente")
    ais.add_argument("--model",default="astrodiscovery_v33.pkl")
    ais.add_argument("--training",default="")
    ais.add_argument("--catalog",default="")
    ais.add_argument("--min-rows",type=int,default=80)
    ais.add_argument("--contamination",type=float,default=0.02)
    prj=sub.add_parser("project",help="Gestiona un proyecto científico persistente")
    prj.add_argument("action",choices=["create","show","rank","review"])
    prj.add_argument("--file",required=True,help="Fichero project.json")
    prj.add_argument("--name",default="")
    prj.add_argument("--description",default="")
    prj.add_argument("--target-name",default="")
    prj.add_argument("--row-id",default="")
    prj.add_argument("--state",choices=DISCOVERY_STATES,default="SCREENING")
    prj.add_argument("--note",default="")
    dr=sub.add_parser("discovery-record",help="Genera registro de descubrimiento auditable desde catalog.json")
    dr.add_argument("catalog")
    dr.add_argument("--out",default="discovery_record.json")
    dr.add_argument("--project-id",default="")
    pi=sub.add_parser("infer-physics",help="Infiere parámetros físicos permitidos de un catálogo sin depender de IA")
    pi.add_argument("catalog")
    pi.add_argument("--out",default="physical_inference.json")
    pi.add_argument("--object-family",default="unknown")
    pi.add_argument("--distance-pc",type=float,default=float("nan"))
    pi.add_argument("--distance-err-pc",type=float,default=float("nan"))
    da=sub.add_parser("discover",help="Ejecuta física + anomalías multiparámetro + IA opcional")
    da.add_argument("catalog")
    da.add_argument("--out",default="discovery_bundle.json")
    da.add_argument("--object-family",default="unknown")
    da.add_argument("--distance-pc",type=float,default=float("nan"))
    da.add_argument("--distance-err-pc",type=float,default=float("nan"))
    da.add_argument("--reference",default="",help="JSON con referencias físicas explícitas")
    da.add_argument("--ai-model",default="")
    mc=sub.add_parser("model-compare",help="Compara hipótesis mediante ajuste ponderado y AICc/BIC")
    mc.add_argument("catalog",help="JSON con model_data.x/y/sigma")
    mc.add_argument("--out",default="model_comparison.json")
    mc.add_argument("--models",nargs="+",default=None,choices=["constant","linear","quadratic"])
    pix=sub.add_parser("pixel-science",help="Analiza imágenes apiladas Hα/OIII y banda ancha píxel a píxel, incluso sin metadata")
    pix.add_argument("--ha",required=True)
    pix.add_argument("--oiii",required=True)
    pix.add_argument("--broadband",default="")
    pix.add_argument("--out",default="science_pixel_products")
    pix.add_argument("--pixel-scale",type=float,default=float("nan"),help="arcsec/pixel opcional; no se inventa si falta")
    pix.add_argument("--ebv",type=float,default=0.0)
    pix.add_argument("--r-v",type=float,default=3.1)
    pix.add_argument("--nii-over-ha",type=float,default=0.0)
    pix.add_argument("--ha-scale",type=float,default=1.0)
    pix.add_argument("--oiii-scale",type=float,default=1.0)
    pix.add_argument("--snr-min",type=float,default=4.0)
    pix.add_argument("--ha-plane",default="")
    pix.add_argument("--oiii-plane",default="")
    pix.add_argument("--broadband-plane",default="")
    return p

def parse_plane_arg(text):
    text = str(text or "").strip()
    if not text:
        return None
    try:
        parts = tuple(int(x.strip()) for x in text.split(",") if x.strip() != "")
    except ValueError as exc:
        raise ValueError(f"Plano inválido '{text}': use N o i,j") from exc
    return parts[0] if len(parts) == 1 else parts



# ====================================================================
# v52.0.0 — SIMPLIFIED GUI / ROBUST SIMBAD / FULL-FRAME MAPS /
#          ADAPTIVE PROFILE SELECTION / ASIAIR OBSERVATORY EXCEL
# ====================================================================

V52_VERSION = "54.0.0"


def _dao_column(tab, wanted):
    """Find a Photutils table column case-insensitively and with safe aliases."""
    if tab is None or not hasattr(tab, "colnames"):
        return None
    names = list(tab.colnames)
    wl = {str(n).lower(): n for n in names}
    if wanted.lower() in wl:
        return wl[wanted.lower()]
    aliases = {
        "xcentroid": ("xcentroid", "x_peak", "xpos", "x"),
        "ycentroid": ("ycentroid", "y_peak", "ypos", "y"),
        "flux": ("flux", "source_flux"),
    }
    for a in aliases.get(wanted, (wanted,)):
        if a.lower() in wl:
            return wl[a.lower()]
    return None


def detect_point_sources(data, bkg, fwhm_px=3.0, threshold_sigma=5.0,
                         max_sources=3000, **_ignored_kwargs):
    """Robust point-source detection compatible with current and legacy Photutils."""
    if HAS_PHOTUTILS and DAOStarFinder is not None:
        try:
            img = np.asarray(data, np.float32) - np.asarray(bkg.bkg, np.float32)
            img = np.where(np.isfinite(img), img, 0.0)
            rms_med = float(np.nanmedian(np.asarray(bkg.rms, np.float32)))
            threshold = float(threshold_sigma) * max(rms_med, 1e-9)
            try:
                # Photutils current API.
                daofind = DAOStarFinder(
                    fwhm=float(fwhm_px), threshold=threshold,
                    sharpness_range=(DAO_SHARPLO, DAO_SHARPHI),
                    roundness_range=(DAO_ROUNDLO, DAO_ROUNDHI),
                    exclude_border=True,
                )
            except TypeError:
                # Legacy Photutils API retained for older environments.
                daofind = DAOStarFinder(
                    fwhm=float(fwhm_px), threshold=threshold,
                    sharplo=DAO_SHARPLO, sharphi=DAO_SHARPHI,
                    roundlo=DAO_ROUNDLO, roundhi=DAO_ROUNDHI,
                    exclude_border=True,
                )
            sources = daofind(img)
            if sources is None or len(sources) == 0:
                return np.zeros((0, 3), dtype=np.float64)
            xc, yc = _dao_column(sources, "xcentroid"), _dao_column(sources, "ycentroid")
            if xc is None or yc is None:
                raise RuntimeError(f"Photutils sin centroid columns; columnas={getattr(sources, 'colnames', None)}")
            xs = np.asarray(sources[xc], float)
            ys = np.asarray(sources[yc], float)
            fc = _dao_column(sources, "flux")
            flux = np.asarray(sources[fc], float) if fc else np.ones_like(xs)
            good = np.isfinite(xs) & np.isfinite(ys) & np.isfinite(flux)
            xs, ys, flux = xs[good], ys[good], flux[good]
            order = np.argsort(flux)[::-1][:int(max_sources)]
            xs, ys, flux = xs[order], ys[order], flux[order]
            LOG.info("DAOStarFinder: %d fuentes (σ=%.1f, fwhm=%.1f px)", len(xs), threshold_sigma, fwhm_px)
            return np.column_stack([xs, ys, flux]).astype(np.float64)
        except Exception as exc:
            LOG.warning("DAOStarFinder no utilizable (%s); usando detector robusto legacy", exc)
    return _detect_point_sources_legacy(
        data, bkg, fwhm_px=fwhm_px, threshold_sigma=threshold_sigma,
        max_sources=max_sources, **_ignored_kwargs)


def _normalise_object_query(name: str) -> list[str]:
    """Generate conservative SIMBAD aliases without inventing coordinates."""
    raw = str(name or "").strip()
    if not raw:
        return []
    compact = re.sub(r"[\s_]+", "", raw)
    queries = [raw, compact]
    aliases = {
        "ngc6960": ["NGC 6960", "NGC6960", "Veil Nebula", "Western Veil Nebula"],
        "m31": ["M 31", "M31", "Andromeda Galaxy", "NGC 224"],
        "m42": ["M 42", "M42", "Orion Nebula", "NGC 1976"],
        "m27": ["M 27", "M27", "Dumbbell Nebula", "NGC 6853"],
    }
    queries.extend(aliases.get(compact.lower(), []))
    seen=[]
    for q in queries:
        if q and q.lower() not in {x.lower() for x in seen}:
            seen.append(q)
    return seen


def resolve_object_center(target_name: str, ra_hint=None, dec_hint=None):
    """Resolve target using SIMBAD aliases first, then explicit RA/Dec fallback."""
    if HAS_SIMBAD and HAS_ASTROPY and str(target_name or "").strip():
        try:
            for q in _normalise_object_query(target_name):
                s = Simbad()
                s.ROW_LIMIT = 5
                try:
                    s.add_votable_fields("otype", "sptype")
                except Exception:
                    pass
                result = s.query_object(q)
                if result is not None and len(result) > 0:
                    names = list(result.colnames)
                    ra_col = next((c for c in ("ra", "RA") if c in names), None)
                    dec_col = next((c for c in ("dec", "DEC") if c in names), None)
                    if ra_col and dec_col:
                        try:
                            from astropy.coordinates import Angle
                            import astropy.units as u
                            ra = Angle(str(result[ra_col][0]), unit=u.hourangle).degree if isinstance(result[ra_col][0], str) else float(result[ra_col][0])
                            dec = Angle(str(result[dec_col][0]), unit=u.deg).degree if isinstance(result[dec_col][0], str) else float(result[dec_col][0])
                        except Exception:
                            ra=float(result[ra_col][0]); dec=float(result[dec_col][0])
                        return ra, dec, f"SIMBAD: {q}"
        except Exception as exc:
            LOG.debug("SIMBAD alias resolution failed: %s", exc)
    if ra_hint is not None and dec_hint is not None and math.isfinite(finite(ra_hint)) and math.isfinite(finite(dec_hint)):
        return float(ra_hint), float(dec_hint), "RA/Dec manual"
    return None, None, "no resuelto"


def infer_target_from_paths(*paths) -> str:
    """Infer a target label from filenames/folder names using known aliases."""
    hay = " ".join(str(p or "") for p in paths).lower()
    for key, aliases in {
        "NGC6960": ("ngc6960", "ngc_6960", "veil", "western veil"),
        "M31": ("m31", "andromeda"),
        "M42": ("m42", "orion"),
        "M27": ("m27", "dumbbell"),
    }.items():
        if any(a in hay for a in aliases):
            return key
    m = re.search(r"\b(?:NGC|IC|M)\s*[-_]?\s*\d{1,5}\b", hay, re.I)
    return re.sub(r"\s+", "", m.group(0)).upper() if m else ""


def robust_query_simbad_field(ra_deg, dec_deg, radius_deg=0.6, max_rows=1000):
    """Field query with generous radius and reliable column discovery."""
    if not HAS_SIMBAD or not HAS_ASTROPY:
        return []
    try:
        from astropy.coordinates import SkyCoord
        import astropy.units as u
        sb = Simbad(); sb.ROW_LIMIT = int(max_rows)
        try: sb.add_votable_fields("otype", "sptype")
        except Exception: pass
        coord = SkyCoord(float(ra_deg), float(dec_deg), unit="deg", frame="icrs")
        tab = sb.query_region(coord, radius=float(radius_deg)*u.deg)
        if tab is None or len(tab)==0:
            return []
        names=list(tab.colnames)
        def get(rec, *cols):
            for c in cols:
                if c in names:
                    try:
                        v=rec[c]
                        return "" if v is None else str(v)
                    except Exception: pass
            return ""
        out=[]
        for rec in tab:
            try: ra=float(rec[next(c for c in ("ra","RA") if c in names)])
            except Exception: ra=float("nan")
            try: dec=float(rec[next(c for c in ("dec","DEC") if c in names)])
            except Exception: dec=float("nan")
            out.append({"main_id":get(rec,"main_id","MAIN_ID"),"ra_deg":ra,"dec_deg":dec,
                        "otype":get(rec,"otype","OTYPE","otype_txt"),
                        "sp_type":get(rec,"sp_type","SP_TYPE","sp_type_txt")})
        LOG.info("SIMBAD campo: %d objetos", len(out)); return out
    except Exception as exc:
        LOG.warning("SIMBAD consulta de campo falló: %s", exc); return []


# ---------- improved profile selection ----------
def _profile_selection_quality(c, cfg):
    def f(k, d=float("nan")):
        return finite(c.get(k), d)
    snh=max(f("peak_snr_ha",0),0.0); sno=max(f("peak_snr_oiii",0),0.0)
    ratio=max(f("ratio",0),0.0); rerr=f("ratio_err",float("nan"))
    qratio=1.0 if ratio>0 and math.isfinite(rerr) and rerr/ratio<=0.35 else (0.5 if ratio>0 else 0.0)
    chi=[]
    for k in ("chi2_red_ha","chi2_red_oiii"):
        v=f(k,float("nan"));
        if math.isfinite(v): chi.append(min(abs(v-1.0),3.0))
    qfit=1.0/(1.0+(sum(chi)/max(1,len(chi))))
    comp=min(max(min(f("profile_valid_ha",0),f("profile_valid_o3",0))/max(1.0,float(2*cfg.get("half_length_px",26)/0.5+1)),0.0),1.0)
    trunc=0.0 if c.get("profile_truncated") else 1.0
    sd=f("source_distance_px",float("inf")); minsep=max(1.0,float(cfg.get("min_separation_px",10)))
    qstar=1.0 if not math.isfinite(sd) else min(1.0,max(0.0,(sd-minsep)/(2.0*minsep)))
    anis=f("anisotropy",0.25); qshape=max(0.0,1.0-min(abs(anis-0.25)/0.65,1.0))
    ridge=min(max(f("ridge_response",0.0),0.0),1e6)
    # Log-score avoids SNR domination and rewards multi-evidence quality.
    snterm=math.log1p(min(snh,100))*0.9 + math.log1p(min(sno,100))*0.9
    off=f("offset_px",float("nan")); oe=max(f("offset_err_px",float("nan")),1e-6)
    qoff=min(abs(off)/oe,6.0)/6.0 if math.isfinite(off) and math.isfinite(oe) else 0.0
    return float(snterm + 2.4*comp + 1.8*qfit + 1.8*qratio + 1.3*qoff + 1.1*qshape + 1.0*qstar + 0.8*trunc + 0.6*math.log1p(ridge))


def select_optimal_profile_candidates(cands, target_name, max_profiles=24):
    cfg=get_object_profile_config(target_name); candidates=[]; rejected=[]
    for c in cands or []:
        if c.get("candidate_type","shock")=="star":
            c["status"]="rejected_star"; c["reason"]="fuente puntual identificada en imágenes normales"; rejected.append(c); continue
        if not c.get("keep",True):
            c["status"]="rejected_profile_selection"; c["reason"]="QC previo: no apto"; rejected.append(c); continue
        snh=finite(c.get("peak_snr_ha"),finite(c.get("snr_pix"),0)); sno=finite(c.get("peak_snr_oiii"),finite(c.get("snr_pix"),0))
        if (not math.isfinite(snh) and not math.isfinite(sno)) or (snh<=0 and sno<=0):
            c["status"]="rejected_profile_selection"; c["reason"]="sin señal de perfil medible"; rejected.append(c); continue
        c["profile_selection_score"]=_profile_selection_quality(c,cfg); candidates.append(c)
    candidates.sort(key=lambda r:(-finite(r.get("profile_selection_score"),-np.inf),int(r.get("id",0))))
    n=max(1,int(max_profiles)); minsep=max(3.0,float(cfg.get("min_separation_px",10)))
    if not candidates: return [],rejected,cfg
    xs=np.array([finite(c.get("x"),np.nan) for c in candidates]); ys=np.array([finite(c.get("y"),np.nan) for c in candidates]); valid=np.isfinite(xs)&np.isfinite(ys)
    if valid.any():
        xmin,xmax=float(np.nanmin(xs[valid])),float(np.nanmax(xs[valid])); ymin,ymax=float(np.nanmin(ys[valid])),float(np.nanmax(ys[valid]))
    else: xmin=ymin=0.0; xmax=ymax=1.0
    diag=max(math.hypot(xmax-xmin,ymax-ymin),minsep); selected=[]; remaining=list(candidates)
    while remaining and len(selected)<n:
        best=None; best_total=-np.inf
        for c in remaining:
            q=finite(c.get("profile_selection_score"),0.0); x=finite(c.get("x"),np.nan); y=finite(c.get("y"),np.nan)
            if selected and math.isfinite(x) and math.isfinite(y):
                d=min(math.hypot(x-finite(s.get("x"),x),y-finite(s.get("y"),y)) for s in selected); div=min(d/diag,1.0); crowd=0.45 if d<minsep else 0.0
            else: div=1.0 if not selected else 0.0; crowd=0.0
            total=q*(0.78+0.22*div)+1.8*div-crowd*q
            if total>best_total: best_total=total; best=c
        if best is None: break
        selected.append(best); remaining.remove(best)
    chosen={id(c) for c in selected}
    for c in candidates:
        if id(c) not in chosen: c["status"]="rejected_profile_selection"; c["reason"]=f"fuera del conjunto óptimo/diverso de {n} perfiles"; rejected.append(c)
    for rank,c in enumerate(selected,1):
        c["status"]="ok"; c["profile_rank"]=rank; c["profile_selection"]="quality+diversity+multiband+spatial-greedy"; c["profile_geometry"]=cfg["geometry"]; c["profile_object"]=cfg["canonical"]
    return selected,rejected,cfg


# ---------- embedded observatory survey ----------
def _survey_safe_float(v):
    try:
        if v is None or v == "": return None
        x=float(v); return x if math.isfinite(x) else None
    except Exception:
        return None


def _survey_safe_int(v):
    try: return int(v)
    except Exception: return None


def _survey_infer_role(name, filter_name=""):
    hay=f"{name} {filter_name}".lower()
    if re.search(r"(?:^|[_\-.])(ha|halpha|h-alpha)(?:[_\-.]|$)",hay): return "Ha"
    if re.search(r"(?:^|[_\-.])(oiii|o3|oxygen)(?:[_\-.]|$)",hay): return "OIII"
    if re.search(r"(?:^|[_\-.])(rgb|color|colour)(?:[_\-.]|$)",hay): return "RGB"
    if re.search(r"(?:l-?qef|quad.?enhance|lquad)",hay): return "L-QEF"
    return "UNKNOWN"


def _survey_infer_object(name, parent_parts=()):
    hay=" ".join([str(name),*(str(x) for x in parent_parts)]).lower()
    if re.search(r"(?:ngc[\s_-]?6960|veil|western[\s_-]?veil)",hay): return "NGC6960"
    if re.search(r"(?:^|[^a-z0-9])m31(?:[^a-z0-9]|$)|andromeda",hay): return "M31"
    return infer_target_from_paths(name,*parent_parts) or "UNKNOWN"


def _survey_discover(root, max_depth=32):
    root=Path(root).expanduser().resolve(); out=[]
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".fit",".fits",".fts",".xisf"}:
            try:
                if len(p.relative_to(root).parts)<=int(max_depth): out.append(p)
            except Exception: pass
    return sorted(out)



_SURVEY_CACHE_VERSION = 2

def _survey_cache_path(root: Path) -> Path:
    base=os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    return Path(base)/"AstroPhysicsSuite"/"cache"/"observatory_scan_cache.json"

def _survey_load_cache(root: Path) -> dict:
    try:
        p=_survey_cache_path(root); data=json.loads(p.read_text(encoding="utf-8"))
        if data.get("version")!=_SURVEY_CACHE_VERSION or data.get("root")!=str(root.resolve()): return {}
        return data.get("files",{}) if isinstance(data.get("files"),dict) else {}
    except Exception: return {}

def _survey_save_cache(root: Path, cache: dict) -> None:
    try:
        p=_survey_cache_path(root); p.parent.mkdir(parents=True,exist_ok=True); tmp=p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version":_SURVEY_CACHE_VERSION,"root":str(root.resolve()),"files":cache},ensure_ascii=False),encoding="utf-8"); os.replace(tmp,p)
    except Exception: pass

def _survey_cached_read(path: Path, cache: dict, reader):
    try: st=path.stat(); sig=f"{st.st_size}:{st.st_mtime_ns}"
    except OSError: return reader(path)
    key=str(path.resolve()); hit=cache.get(key)
    if isinstance(hit,dict) and hit.get("sig")==sig and isinstance(hit.get("record"),dict): return dict(hit["record"])
    rec=reader(path); cache[key]={"sig":sig,"record":rec}; return rec

def _survey_read_fits(path):
    rec={"path":str(path),"filename":path.name,"extension":path.suffix.lower(),"file_format":"FITS","size_bytes":path.stat().st_size,
         "modified_utc":datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat(),"sha256":sha256_file(path),"object_name":"","role":"","date_obs":"",
         "exposure_s":None,"camera":"","telescope":"","filter_name":"","gain":None,"offset":None,"sensor_temp_c":None,"binning":"",
         "width_px":None,"height_px":None,"naxis":None,"nplanes":None,"bitpix":None,"pixel_scale_arcsec_px":None,"focal_length_mm":None,"aperture_mm":None,
         "focal_ratio":None,"ra_deg":None,"dec_deg":None,"airmass":None,"rotation_deg":None,"bunit":"","zeropoint":None,"readnoise_e":None,
         "wcs_present":False,"header_completeness":None,"warnings":""}
    if not HAS_ASTROPY: return rec
    try:
        with fits.open(path,memmap=True) as hdul:
            hdu=hdul[0]; h=hdu.header; data=hdu.data
            get=lambda *ks: next((h[k] for k in ks if k in h), None)
            rec.update({"object_name":str(get("OBJECT") or ""),"date_obs":str(get("DATE-OBS","DATE_OBS","DATEOBS") or ""),"filter_name":str(get("FILTER","FILTER1") or ""),"exposure_s":_survey_safe_float(get("EXPTIME","EXPOSURE")),
                        "camera":str(get("INSTRUME","CAMERA") or ""),"telescope":str(get("TELESCOP") or ""),"gain":_survey_safe_float(get("GAIN")),"offset":_survey_safe_float(get("OFFSET")),
                        "sensor_temp_c":_survey_safe_float(get("CCD-TEMP","TEMP","SET-TEMP")),"binning":str(get("BINNING") or ""),"bunit":str(get("BUNIT") or ""),
                        "zeropoint":_survey_safe_float(get("PHOTZP","ZEROPT")),"readnoise_e":_survey_safe_float(get("RDNOISE")),"airmass":_survey_safe_float(get("AIRMASS")),
                        "naxis":_survey_safe_int(h.get("NAXIS")),"bitpix":_survey_safe_int(h.get("BITPIX")),"ra_deg":_survey_safe_float(get("CRVAL1","RA")),"dec_deg":_survey_safe_float(get("CRVAL2","DEC")),
                        "focal_length_mm":_survey_safe_float(get("FOCALLEN","FOCALLEN")),"aperture_mm":_survey_safe_float(get("APTDIA","APERTURE"))})
            if data is not None:
                sh=tuple(getattr(data,"shape",()))
                if len(sh)>=2: rec["height_px"],rec["width_px"]=int(sh[-2]),int(sh[-1])
                rec["nplanes"]=int(np.prod(sh[:-2])) if len(sh)>2 and np is not None else None
            try:
                w=_WCS(h,naxis=2)
                rec["wcs_present"]=bool(w.has_celestial)
                if w.has_celestial: rec["pixel_scale_arcsec_px"]=float(np.mean(np.abs(_pps(w))) * 3600.0)
            except Exception: pass
            completeness=sum(1 for k in ("OBJECT","DATE-OBS","EXPTIME","FILTER","INSTRUME","TELESCOP","GAIN","CCD-TEMP","CRVAL1","CRVAL2") if k in h)/10
            rec["header_completeness"]=float(completeness)
    except Exception as exc:
        rec["warnings"]=f"{type(exc).__name__}: {exc}"
    rec["role"]=_survey_infer_role(path.name, rec.get("filter_name",""))
    rec["session_key"]=f"{rec.get('object_name') or infer_target_from_paths(path)}|{str(rec.get('date_obs') or rec.get('modified_utc',''))[:10]}"
    return rec


def _survey_read_xisf(path):
    # Best-effort XML metadata reader; preserves missing values as blank.
    text=path.read_text(encoding="utf-8",errors="replace") if path.stat().st_size < 100_000_000 else ""
    rec={"path":str(path),"filename":path.name,"extension":".xisf","file_format":"XISF","size_bytes":path.stat().st_size,
         "modified_utc":datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat(),"sha256":sha256_file(path),"object_name":"","role":"","date_obs":"",
         "exposure_s":None,"camera":"","telescope":"","filter_name":"","gain":None,"offset":None,"sensor_temp_c":None,"binning":"",
         "width_px":None,"height_px":None,"naxis":None,"nplanes":None,"bitpix":None,"pixel_scale_arcsec_px":None,"ra_deg":None,"dec_deg":None,"warnings":""}
    for key,pat in (("object_name",r'Object(?:Name)?\s*[=:]\s*["\']([^"\']+)'),("camera",r'(?:Camera|Instrument).*?[=:]\s*["\']([^"\']+)'),("filter_name",r'Filter(?:Name)?\s*[=:]\s*["\']([^"\']+)'),("date_obs",r'(?:DATE-OBS|DateObs).*?[=:]\s*["\']([^"\']+)'),("gain",r'Gain\s*[=:]\s*["\']?([0-9.+-]+)'),("offset",r'Offset\s*[=:]\s*["\']?([0-9.+-]+)'),("exposure_s",r'(?:Exposure|EXPTIME).*?[=:]\s*["\']?([0-9.+-]+)')):
        try:
            m=re.search(pat,text,re.I)
            if m:
                rec[key]=_survey_safe_float(m.group(1)) if key in {"gain","offset","exposure_s"} else m.group(1)
        except Exception: pass
    rec["role"]=_survey_infer_role(path.name,rec.get("filter_name",""))
    rec["session_key"]=f"{rec.get('object_name') or infer_target_from_paths(path)}|{str(rec.get('date_obs') or rec.get('modified_utc',''))[:10]}"
    return rec


def export_training_workbook(rows, output, source_note="AstroPhysics Suite"):
    """Exporta candidatos/observables a XLSX listo para revisión humana y entrenamiento."""
    if not HAS_OPENPYXL: raise RuntimeError("openpyxl no está instalado")
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    data=[]
    fields=list(AI_IMAGE_FEATURES)+["x","y","id","label","group","object_name","source_image","notes"]
    for r in rows or []:
        data.append([r.get(k,"") for k in fields])
    if not data:
        raise ValueError("No hay candidatos para exportar al libro de entrenamiento")
    wb=Workbook(); ws=wb.active; ws.title="TRAINING"
    ws.append(fields)
    for c in ws[1]:
        c.font=Font(bold=True,color="FFFFFF"); c.fill=PatternFill("solid",fgColor="1F4E78"); c.alignment=Alignment(vertical="center")
    for row in data: ws.append(row)
    ws.freeze_panes="A2"; ws.auto_filter.ref=ws.dimensions
    # Sheet with instructions, deliberately human-editable.
    info=wb.create_sheet("README")
    info.append(["Campo","Uso"])
    info.append(["label","Etiqueta humana real; no inventar. Use 0=desconocido/no válido, 1=conocido/interesante; otras clases si el modelo las soporta."])
    info.append(["group","Grupo/observación/objeto usado para evitar fugas entre entrenamiento y validación."])
    info.append(["notes","Justificación o referencia humana para cada etiqueta."])
    info.append(["source","Libro generado por AstroPhysics Suite; la IA visual necesita además imágenes reales."])
    for c in info[1]: c.font=Font(bold=True,color="FFFFFF"); c.fill=PatternFill("solid",fgColor="1F4E78")
    for sh in (ws,info):
        for col in sh.columns:
            letter=col[0].column_letter
            sh.column_dimensions[letter].width=min(42,max(12,max(len(str(x.value or "")) for x in list(col)[:300])+2))
    wb.save(output)
    return str(Path(output).resolve())


def train_ai_from_excel(training_xlsx, model_path, min_rows=80, contamination=0.02, seed=20260915):
    rows=_load_ai_training_rows(training_xlsx, sheet_preference=("TRAINING","CANDIDATES","LIGHTS"))
    # Metadata-only ASIAIR sheets are useful context but cannot train the candidate classifier.
    feature_present=sum(1 for k in AI_IMAGE_FEATURES if any(k in r for r in rows))
    if feature_present < 3:
        return {"state":"NO DISPONIBLE","reason":"El Excel contiene metadatos de observación pero no suficientes features de candidatos. Genere primero 'Exportar entrenamiento Excel' tras un análisis y etiquete TRAINING.","n_rows":len(rows),"feature_fields_found":feature_present}
    return train_discovery_ai(training_xlsx,model_path,seed=seed,min_rows=min_rows,contamination=contamination)


def analyze_series_with_ai(folders, base_params, model_path="", training_path="", vision_model_path="", output="series_results.json", seed=20260915):
    """Analiza múltiples épocas y aplica IA física + novedad visual persistente si existe."""
    results=[]; errors=[]; visual=None
    if vision_model_path and Path(vision_model_path).is_file():
        try: visual=AstroVisionAI.load(vision_model_path)
        except Exception as exc: LOG.warning("AstroVision serie: no se pudo cargar modelo visual: %s",exc)
    for idx,folder in enumerate([Path(x) for x in folders]):
        try: o3,h,os,hs,broad=auto_pair_directory(str(folder), return_starless=True)
        except TypeError:
            fs=list(_survey_discover(folder,32))
            def pick(tokens):
                cand=[x for x in fs if any(t in x.name.lower() for t in tokens)]; return str(cand[0]) if cand else ""
            o3=pick(("oiii","o3")); h=pick(("ha","halpha","h-alpha")); os=pick(("starless_oiii","oiii_starless","starless-o3")); hs=pick(("starless_ha","ha_starless","starless-ha")); broad=pick(("l-qef","lquad","rgb","color"))
        if not (o3 and h and os and hs): errors.append({"folder":str(folder),"error":"Falta OIII/Hα normal o una de las dos starless"}); continue
        P=dataclasses.replace(base_params,oiii_starless_path=os,ha_starless_path=hs,broadband_path=broad or "",target_name=base_params.target_name or infer_target_from_paths(folder))
        outdir=Path(output).parent/(folder.name+f"_run_{idx+1:03d}"); outdir.mkdir(parents=True,exist_ok=True)
        payload=analyze_pair_core(o3,h,str(outdir),P,grid=None,progress=None,cancel=None)
        ai=discovery_ai_from_rows(payload.get("candidates",[]),model_path=model_path,training_path=training_path,seed=seed,min_rows=80)
        visual_novelty=0
        if visual is not None:
            try:
                H=load_fits(hs).data; O=load_fits(os).data; B=load_fits(broad).data if broad else None
                scored=visual.score_candidate_patches(H,O,B,payload.get("candidates",[]),half_size=64)
                by_id={id(c):s for c,s in scored}
                for c in payload.get("candidates",[]):
                    sc=by_id.get(id(c))
                    if sc: c.update(sc); visual_novelty+=int(sc.get("visual_novelty_state")=="OUTLIER_VISUAL")
            except Exception as exc: LOG.warning("AstroVision serie %s: %s",folder,exc)
        payload["series_ai"]={k:v for k,v in ai.items() if k!="candidates"}; payload["series_visual_ai"]={"state":"ACTIVA" if visual is not None else "NO DISPONIBLE","n_visual_outliers":visual_novelty}; payload["series_index"]=idx
        atomic_json_dump(payload,outdir/"catalog.json")
        results.append({"folder":str(folder),"series_index":idx,"catalog":str(outdir/"catalog.json"),"n_candidates":len(payload.get("candidates",[])),"n_outliers":ai.get("n_outliers",0),"n_visual_outliers":visual_novelty,"ai_state":ai.get("state"),"visual_state":payload["series_visual_ai"]["state"]})
    report={"state":"OK","n_epochs":len(results),"results":results,"errors":errors,"output":str(Path(output).resolve()),"ai_physical":bool(model_path or training_path),"ai_visual":bool(visual is not None)}; atomic_json_dump(report,output); return report


def generate_observatory_excel(root, output, max_depth=32, include_labels=True, progress=None, cancel=None):
    """Excel independiente de las imágenes, optimizado para miles de archivos mediante caché."""
    root=Path(root).expanduser().resolve(); output=Path(output).expanduser().resolve(); files=_survey_discover(root,max_depth); cache=_survey_load_cache(root); rows=[]; total=max(1,len(files))
    if progress: progress(0.01,f"Encontrados {len(files)} archivos astronómicos")
    for i,pth in enumerate(files,1):
        if cancel is not None and cancel.is_set(): raise RuntimeError("Generación de Excel cancelada")
        try:
            reader=_survey_read_xisf if pth.suffix.lower()==".xisf" else _survey_read_fits; rows.append(_survey_cached_read(pth,cache,reader))
        except Exception as exc: LOG.warning("Observatory scan %s: %s",pth,exc)
        if progress and (i==1 or i%10==0 or i==total): progress(0.02+0.66*i/total,f"Leyendo metadatos {i}/{total}")
    _survey_save_cache(root,cache); sessions={}
    for r in rows: sessions.setdefault(r.get("session_key","UNKNOWN"),[]).append(r)
    sess=[]; ready=[]
    for k,rr in sorted(sessions.items()):
        ex=[r["exposure_s"] for r in rr if r.get("exposure_s") is not None]; roles={}
        for r in rr: roles[r.get("role","")]=roles.get(r.get("role",""),0)+1
        sess.append({"session_key":k,"object_name":rr[0].get("object_name") or infer_target_from_paths(rr[0].get("path")),"date":str(rr[0].get("date_obs") or "")[:10],"n_files":len(rr),"total_exposure_s":sum(ex) if ex else None,"mean_exposure_s":statistics.fmean(ex) if ex else None,"n_ha":roles.get("Ha",0),"n_oiii":roles.get("OIII",0),"n_rgb":roles.get("RGB",0),"n_lqef":roles.get("L-QEF",0),"roles":json.dumps(roles,ensure_ascii=False)})
        ready.append({"session_key":k,"object_name":rr[0].get("object_name") or infer_target_from_paths(rr[0].get("path")),"n_files":len(rr),"has_time":any(bool(r.get("date_obs")) for r in rr),"analysis_ready":len(rr)>=2,"reason":"inventario de metadata; validación astrométrica/fotométrica sigue siendo necesaria"})
    labels=[{"label_id":"","x_px":"","y_px":"","class":"","group":"","source":"human","notes":"Asignar solo con evidencia real"}] if include_labels else []
    readme=[{"item":"purpose","value":"Inventario de observaciones reales ASIAIR/FITS/XISF para AstroPhysics Suite"},{"item":"policy","value":"No se inventan metadatos; campos ausentes quedan vacíos. DISCOVERY_READY no declara SN/NEO."},{"item":"training","value":"Para entrenar IA física use Exportar entrenamiento IA desde un catálogo analizado; el Excel de observatorio aporta contexto/metadatos."}]
    sheets={"LIGHTS":rows,"SESSIONS":sess,"DISCOVERY_READY":ready,"LABELS":labels,"TRAINING":[],"README":readme}
    try:
        from openpyxl import Workbook; from openpyxl.styles import Font,PatternFill,Alignment
        wb=Workbook(); wb.remove(wb.active)
        for idx,(name,data) in enumerate(sheets.items()):
            if cancel is not None and cancel.is_set(): raise RuntimeError("Generación de Excel cancelada")
            ws=wb.create_sheet(name[:31]); cols=list(data[0].keys()) if data else []
            if cols:
                ws.append(cols)
                for cell in ws[1]: cell.font=Font(bold=True,color="FFFFFF"); cell.fill=PatternFill("solid",fgColor="1F4E78"); cell.alignment=Alignment(vertical="center")
                for row in data: ws.append([row.get(c) for c in cols])
                ws.freeze_panes="A2"; ws.auto_filter.ref=ws.dimensions
                sample=list(ws.iter_rows(min_row=1,max_row=min(ws.max_row,300)))
                for j,colcells in enumerate(zip(*sample),start=1): ws.column_dimensions[ws.cell(1,j).column_letter].width=min(45,max(12,max(len(str(c.value or "")) for c in colcells)+2))
            if progress: progress(0.72+0.22*(idx+1)/len(sheets),f"Hoja {name}")
        output.parent.mkdir(parents=True,exist_ok=True); wb.save(output)
        if progress: progress(1.0,"Excel terminado")
    except Exception as exc: raise RuntimeError(f"No se pudo crear Excel: {exc}") from exc
    return {"output":str(output),"n_files":len(rows),"n_sessions":len(sess),"sheets":list(sheets),"cache":"enabled"}


def check_hardware():
    """Diagnóstico de equipo inspirado en el paquete comercial v49."""
    def ps(script):
        try:
            cp=subprocess.run(["powershell","-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass","-Command",script],capture_output=True,text=True,timeout=8); return cp.stdout.strip() if cp.returncode==0 else ""
        except Exception: return ""
    try: ram=float(ps("[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB,2)"))
    except Exception: ram=None
    try: cpu=json.loads(ps("Get-CimInstance Win32_Processor | Select-Object -First 1 Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed | ConvertTo-Json -Compress"))
    except Exception: cpu={}
    try: g=json.loads(ps("Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,AdapterRAM | ConvertTo-Json -Compress")); gpus=g if isinstance(g,list) else ([g] if isinstance(g,dict) else [])
    except Exception: gpus=[]
    try: a=json.loads(ps("Get-PnpDevice -PresentOnly | Where-Object { $_.FriendlyName -match 'ZWO|ASI533|ASI Camera' -or $_.InstanceId -match 'VID_03C3' } | Select-Object Status,Class,FriendlyName,InstanceId | ConvertTo-Json -Compress")); asi=a if isinstance(a,list) else ([a] if isinstance(a,dict) else [])
    except Exception: asi=[]
    try: free_gb=shutil.disk_usage(Path.home().anchor or os.getcwd()[:3]).free/(1024**3)
    except Exception: free_gb=None
    torch_info={"available":False,"cuda":False,"version":None}
    if HAS_TORCH:
        try: torch_info={"available":True,"cuda":bool(torch.cuda.is_available()),"version":getattr(torch,"__version__",None),"devices":int(torch.cuda.device_count()) if torch.cuda.is_available() else 0}
        except Exception: pass
    rec=[]
    if ram is not None and ram<16: rec.append("16 GB+ de RAM recomendado para FITS grandes/IA.")
    if free_gb is not None and free_gb<20: rec.append("Menos de 20 GB libres; conviene liberar espacio.")
    if not asi: rec.append("No se detecta ZWO ASI por PnP; ASIAIR puede usarse como almacenamiento de red.")
    if torch_info["available"] and not torch_info["cuda"]: rec.append("AstroVision funcionará por CPU.")
    return {"ok":True,"ram_gb":ram,"cpu":cpu,"gpus":gpus,"gpu_names":"; ".join(str(x.get("Name","")) for x in gpus if isinstance(x,dict)),"zwo_asi_devices":asi,"zwo_asi_detected":bool(asi),"free_disk_gb":free_gb,"torch":torch_info,"recommendations":rec}


def update_check_https(manifest_url, current_version=__version__, timeout=15):
    if not str(manifest_url).lower().startswith("https://"): raise ValueError("El manifiesto debe usar HTTPS")
    req=urllib.request.Request(str(manifest_url),headers={"User-Agent":f"AstroPhysicsSuite/{current_version}"})
    with urllib.request.urlopen(req,timeout=int(timeout)) as r: data=json.loads(r.read().decode("utf-8"))
    for key in ("version","installer_url","sha256"):
        if key not in data: raise ValueError(f"Manifest incompleto: falta {key}")
    if not str(data["installer_url"]).lower().startswith("https://"): raise ValueError("installer_url debe usar HTTPS")
    if not re.fullmatch(r"[0-9a-fA-F]{64}",str(data["sha256"])): raise ValueError("SHA256 inválido")
    def vt(v):
        m=re.match(r"^v?(\d+)\.(\d+)\.(\d+)",str(v)); return tuple(map(int,m.groups())) if m else (0,0,0)
    return {"current":current_version,"remote":str(data["version"]),"update_available":vt(data["version"])>vt(current_version),"installer_url":str(data["installer_url"]),"sha256":str(data["sha256"])}


def download_verified_update(url, expected_sha256, target, timeout=120, max_bytes=4*1024**3):
    """Descarga una actualización HTTPS y verifica SHA256 antes de sustituir el archivo."""
    if not str(url).lower().startswith("https://"): raise ValueError("La actualización debe usar HTTPS")
    target=Path(target).expanduser().resolve(); target.parent.mkdir(parents=True,exist_ok=True); tmp=target.with_suffix(target.suffix+".part")
    total=0; h=hashlib.sha256()
    try:
        req=urllib.request.Request(str(url),headers={"User-Agent":f"AstroPhysicsSuite/{__version__}"})
        with urllib.request.urlopen(req,timeout=int(timeout)) as r, tmp.open("wb") as f:
            while True:
                b=r.read(1024*1024)
                if not b: break
                total+=len(b)
                if total>int(max_bytes): raise ValueError("Actualización demasiado grande")
                f.write(b); h.update(b)
        got=h.hexdigest().lower()
        if got!=str(expected_sha256).lower(): raise ValueError(f"SHA256 no coincide: {got} != {expected_sha256}")
        os.replace(tmp,target); return str(target)
    finally:
        try: tmp.unlink()
        except OSError: pass

def launch_verified_installer(installer_path):
    """Lanza un instalador ya verificado; no ejecuta binarios sin comprobación previa."""
    p=Path(installer_path).expanduser().resolve()
    if not p.is_file(): raise FileNotFoundError(str(p))
    return subprocess.Popen([str(p)],close_fds=True)


def _style_simple(root):
    try:
        style=ttk.Style(root)
        if "vista" in style.theme_names(): style.theme_use("vista")
        elif "clam" in style.theme_names(): style.theme_use("clam")
    except Exception: pass




# ====================================================================
# v57: DISCOVERY WORKSPACE — DESCUBRIMIENTO DIRECTO DESDE IMÁGENES
# ====================================================================
DISCOVERY_SCAN_ENGINE_VERSION = "1.0"


def _robust_z_vector(values):
    a=np.asarray(values,float)
    out=np.zeros_like(a,dtype=float)
    finite=np.isfinite(a)
    if finite.sum()<5:
        return out
    med=float(np.nanmedian(a[finite])); mad=float(1.4826*np.nanmedian(np.abs(a[finite]-med)))
    scale=max(mad,1e-9)
    out[finite]=(a[finite]-med)/scale
    out[~finite]=0.0
    return out


def _label_discovery_morphology(area, elongation, compactness, peak_snr):
    """Clasificación descriptiva para separar fuentes científicas de artefactos.
    No declara ningún objeto nuevo; solo documenta señales morfológicas observables.
    """
    if not all(math.isfinite(float(x)) for x in (area,elongation,compactness,peak_snr)):
        return "QUALITY_LIMITED", "medición incompleta"
    if elongation >= 8.0:
        return "ARTIFACT_REJECTED", "traza lineal/elongación extrema"
    if area <= 2.0:
        return "ARTIFACT_REJECTED", "fuente demasiado compacta para caracterización robusta"
    if peak_snr < 4.0:
        return "QUALITY_LIMITED", "S/N insuficiente"
    if elongation <= 2.5 and compactness >= 0.18:
        return "SCIENCE_CANDIDATE", "morfología compatible con fuente astronómica"
    return "REVIEW", "morfología no concluyente"


def detect_discovery_sources(image, snr_min=5.0, max_candidates=2000, min_area=3, mask_border=4):
    """Escaneo de descubrimiento de imagen completa.

    Devuelve fuentes de punto/extendidas con S/N, morfología y estado de exclusión
    de artefactos. La detección es deliberadamente agnóstica del tipo de objeto.
    """
    arr=np.asarray(image,dtype=np.float32)
    if arr.ndim!=2: raise AmbiguousCubeError("Discovery Scan requiere una imagen 2D")
    bg=estimate_background(arr,box=max(32,min(256,min(arr.shape)//4)))
    b=np.asarray(bg.bkg,dtype=np.float32); r=np.asarray(bg.rms,dtype=np.float32)
    sn=(arr-b)/np.maximum(r,1e-6)
    good=np.isfinite(sn)
    thr=np.where(good,sn,-np.inf) >= float(snr_min)
    if mask_border>0:
        thr[:mask_border,:]=False; thr[-mask_border:,:]=False; thr[:,:mask_border]=False; thr[:,-mask_border:]=False
    # Connected high-S/N structures. A local maximum is required for each component.
    lab,n=ndi.label(thr,structure=np.ones((3,3),dtype=int))
    objs=ndi.find_objects(lab)
    rows=[]
    for lab_id,sl in enumerate(objs,1):
        if sl is None: continue
        yy,xx=np.nonzero(lab[sl]==lab_id)
        if yy.size < int(min_area): continue
        y0,y1=sl[0].start,sl[0].stop; x0,x1=sl[1].start,sl[1].stop
        ys=yy+y0; xs=xx+x0
        w=np.clip(sn[ys,xs],0,None)
        sw=float(np.sum(w))
        if sw<=0: continue
        cx=float(np.sum(xs*w)/sw); cy=float(np.sum(ys*w)/sw)
        dx=xs-cx; dy=ys-cy
        cxx=float(np.sum(w*dx*dx)/sw); cyy=float(np.sum(w*dy*dy)/sw); cxy=float(np.sum(w*dx*dy)/sw)
        cov=np.array([[cxx,cxy],[cxy,cyy]],float)
        try:
            ev=np.linalg.eigvalsh(cov); major=max(float(ev[-1]),1e-6); minor=max(float(ev[0]),1e-6)
            elong=math.sqrt(major/minor)
        except Exception:
            elong=float("inf")
        peak=float(np.nanmax(sn[ys,xs])); area=int(yy.size)
        flux=float(np.nansum(arr[ys,xs]-b[ys,xs]))
        bbox=(int(x0),int(y0),int(x1-1),int(y1-1))
        compact=float(area/max((x1-x0)*(y1-y0),1))
        state,reason=_label_discovery_morphology(area,elong,compact,peak)
        rows.append({"det_id":int(lab_id),"x":cx,"y":cy,"area_px":area,"peak_snr":peak,
                     "flux_adu":flux,"elongation":elong,"bbox":bbox,"compactness":compact,
                     "discovery_state":state,"artifact_reason":reason})
    rows.sort(key=lambda z: float(z.get("peak_snr",0)),reverse=True)
    rows=rows[:int(max_candidates)]
    # Independent feature outliers: this is an anomaly flag, not a discovery claim.
    for feature in ("area_px","elongation","compactness","peak_snr"):
        z=_robust_z_vector([r.get(feature,float("nan")) for r in rows])
        for rr,zz in zip(rows,z): rr[f"z_{feature}"]=float(zz)
    for rr in rows:
        anomaly_features=[]
        for feature in ("area_px","elongation","compactness","peak_snr"):
            if abs(float(rr.get(f"z_{feature}",0))) >= 4.0: anomaly_features.append(feature)
        rr["anomaly_features"]=anomaly_features
        rr["anomaly_state"]="MORPHOLOGY_OUTLIER" if len(anomaly_features)>=2 and rr["discovery_state"] not in ("ARTIFACT_REJECTED",) else "NONE"
    return {"state":"OK","n_detected":len(rows),"background":{"median":float(np.nanmedian(b)) if np.isfinite(b).any() else None,
            "rms_median":float(np.nanmedian(r)) if np.isfinite(r).any() else None},
            "sources":rows,"sn_map":sn}


def _crossmatch_discovery_sources(im, rows, match_arcsec=3.0):
    """Añade evidencia de catálogo; ausencia de match no se interpreta como novedad.
    """
    if not rows or getattr(im,"wcs",None) is None or not HAS_GAIA or not HAS_ASTROPY:
        return rows,{"state":"NOT_AVAILABLE","reason":"sin WCS/Gaia"}
    try:
        x=np.asarray([r["x"] for r in rows],float); y=np.asarray([r["y"] for r in rows],float)
        ra,dec=im.pixel_to_world(x,y)
        gtbl=[]
        for rr,ra0,dec0 in zip(rows,np.asarray(ra,float),np.asarray(dec,float)):
            tab=query_gaia_sources(float(ra0),float(dec0),radius_deg=match_arcsec/3600*3,mag_limit=20,max_rows=25)
            best=None; best_d=1e9
            if tab is not None:
                gra=np.asarray(tab["ra"],float); gdec=np.asarray(tab["dec"],float)
                d=np.hypot((gra-float(ra0))*np.cos(np.deg2rad(float(dec0))),gdec-float(dec0))*3600.0
                if len(d) and np.isfinite(d).any():
                    j=int(np.nanargmin(np.where(np.isfinite(d),d,np.inf))); best_d=float(d[j])
                    if best_d<=float(match_arcsec):
                        best={"source_id":int(tab["source_id"][j]),"ra_deg":float(gra[j]),"dec_deg":float(gdec[j]),
                              "g_mag":float(tab["phot_g_mean_mag"][j]) if "phot_g_mean_mag" in tab.colnames and tab["phot_g_mean_mag"][j] is not None else None}
            rr["gaia_match"]=best; rr["gaia_separation_arcsec"]=best_d if best is not None else None
            if best is not None:
                rr["catalog_state"]="KNOWN_GAIA"
                if rr.get("anomaly_state")=="MORPHOLOGY_OUTLIER": rr["discovery_state"]="KNOWN_VARIANT"
            else:
                rr["catalog_state"]="UNMATCHED_GAIA"
                if rr.get("discovery_state")=="SCIENCE_CANDIDATE": rr["discovery_state"]="UNMATCHED"
        return rows,{"state":"OK","catalog":"Gaia DR3","radius_arcsec":float(match_arcsec)}
    except Exception as exc:
        return rows,{"state":"ERROR","reason":f"{type(exc).__name__}: {exc}"}


def discovery_scan_observation(paths, output_dir, *, snr_min=5.0, max_candidates=2000, pixel_scale_arcsec=float("nan"), target_name=""):
    """Pipeline comercial de descubrimiento: imágenes → fuentes → evidencia → candidatos.

    Acepta una o varias imágenes 2D (por ejemplo Hα, [O III], RGB/L-Quad). No exige
    starless ni una pareja concreta. La salida conserva evidencia y estados descriptivos.
    """
    paths=[str(Path(p).expanduser().resolve()) for p in paths if p and Path(p).is_file()]
    if not paths: raise FileNotFoundError("No se seleccionó ninguna imagen")
    out=Path(output_dir).expanduser().resolve(); out.mkdir(parents=True,exist_ok=True)
    layers=[]; per_image=[]
    for p in paths:
        im=load_fits(p)
        scan=detect_discovery_sources(im.data,snr_min=snr_min,max_candidates=max_candidates)
        scan_sources,_=_crossmatch_discovery_sources(im,scan["sources"])
        layer={"path":p,"shape":list(im.data.shape),"pixel_scale_arcsec":im.pixel_scale_arcsec,
               "wcs":bool(im.wcs is not None),"scan":{"n_detected":len(scan_sources)},"sources":scan_sources}
        layers.append(layer)
        per_image.append(scan)
    # Merge detections across images in detector coordinates when shapes are compatible.
    base=layers[0]["sources"]
    if len(layers)>1:
        for rr in base: rr["bands"]= [Path(layers[0]["path"]).name]
        for layer in layers[1:]:
            if tuple(layer["shape"])!=tuple(layers[0]["shape"]): continue
            others=layer["sources"]
            used=set()
            for rr in base:
                d=[]
                for j,qq in enumerate(others):
                    if j in used: continue
                    d.append((math.hypot(rr["x"]-qq["x"],rr["y"]-qq["y"]),j))
                if not d: continue
                dd,j=min(d)
                if dd<=2.5:
                    qq=others[j]; used.add(j); rr["bands"].append(Path(layer["path"]).name)
                    rr.setdefault("band_measurements",[]).append({"file":Path(layer["path"]).name,"peak_snr":qq.get("peak_snr"),"flux_adu":qq.get("flux_adu")})
                    if math.isfinite(float(rr.get("flux_adu",np.nan))) and math.isfinite(float(qq.get("flux_adu",np.nan))) and abs(float(rr.get("flux_adu",0)))>0:
                        rr.setdefault("relative_fluxes",{})[Path(layer["path"]).stem]=float(qq.get("flux_adu",0))/max(abs(float(rr.get("flux_adu",1))),1e-12)
            for qq in others:
                if qq.get("det_id") not in used and qq.get("discovery_state") not in ("ARTIFACT_REJECTED",):
                    extra=dict(qq); extra["bands"]=[Path(layer["path"]).name]; extra["crossband_state"]="SINGLE_LAYER"; base.append(extra)
    for i,rr in enumerate(base,1): rr["candidate_id"]=f"DISC-{i:05d}"; rr["evidence_state"]="REVIEW_REQUIRED" if rr.get("discovery_state") not in ("ARTIFACT_REJECTED",) else "REJECTED_ARTIFACT"
    summary={"engine_version":DISCOVERY_SCAN_ENGINE_VERSION,"target_name":target_name or infer_target_from_paths(Path(paths[0]).parent,*[Path(x).name for x in paths]),
             "n_images":len(paths),"n_detected":sum(len(x["sources"]) for x in layers),
             "n_candidates":sum(r.get("evidence_state")=="REVIEW_REQUIRED" for r in base),
             "n_unmatched":sum(r.get("discovery_state")=="UNMATCHED" for r in base),
             "n_morphology_outliers":sum(r.get("anomaly_state")=="MORPHOLOGY_OUTLIER" for r in base),
             "n_artifact_rejected":sum(r.get("evidence_state")=="REJECTED_ARTIFACT" for r in base),
             "pixel_scale_arcsec":next((x.get("pixel_scale_arcsec") for x in layers if x.get("pixel_scale_arcsec") is not None),pixel_scale_arcsec),
             "human_verification_required":True,
             "scientific_policy":"Los estados indican evidencia observacional; la Suite no declara descubrimientos automáticamente."}
    payload={"schema_version":SCHEMA_VERSION,"discovery_engine":DISCOVERY_SCAN_ENGINE_VERSION,"summary":summary,
             "inputs":{"images":paths},"layers":layers,"candidates":base,
             "evidence_policy":{"human_verification_required":True,"catalog_absence_is_not_discovery":True,
                                "artifact_rejection_before_candidate":True,"no_automatic_discovery_claim":True}}
    out_json=out/"discovery_catalog.json"; atomic_json_dump(payload,out_json)
    return payload


def write_discovery_report_pdf(payload, path, image=None, max_candidates=30):
    """Informe comercial de revisión: evidencia, candidatos y exclusiones de artefactos."""
    if not HAS_MPL: return None
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    s=payload.get("summary",{}) or {}; rows=payload.get("candidates",[]) or []
    with PdfPages(path) as pdf:
        fig=Figure(figsize=(11.69,8.27)); ax=fig.add_subplot(111); ax.axis("off")
        ax.text(0.02,0.96,"AstroPhysics Suite — Discovery Report",fontsize=18,weight="bold",va="top")
        ax.text(0.02,0.915,f"Objeto: {s.get('target_name') or 'No identificado'}",fontsize=11,va="top")
        lines=[
            f"Imágenes: {s.get('n_images',0)}",
            f"Fuentes detectadas: {s.get('n_detected',0)}",
            f"Candidatos a revisión humana: {s.get('n_candidates',0)}",
            f"No asociados a Gaia: {s.get('n_unmatched',0)}",
            f"Outliers morfológicos: {s.get('n_morphology_outliers',0)}",
            f"Artefactos rechazados: {s.get('n_artifact_rejected',0)}",
            "",
            "POLÍTICA: un candidato no equivale a un descubrimiento.",
            "La ausencia de catálogo no se interpreta como novedad por sí sola.",
            "La revisión humana y la trazabilidad de las evidencias son obligatorias.",
        ]
        ax.text(0.03,0.84,"\n".join(lines),family="monospace",fontsize=10,va="top")
        ax.text(0.03,0.23,"Fuentes de entrada:\n"+"\n".join(payload.get("inputs",{}).get("images",[])[:8]),family="monospace",fontsize=7.5,va="top")
        pdf.savefig(fig); fig.clear()
        fig=Figure(figsize=(11.69,8.27)); ax=fig.add_subplot(111)
        if image is not None:
            arr=np.asarray(image,float); finite_mask=np.isfinite(arr)
            if finite_mask.any():
                lo,hi=np.nanpercentile(arr[finite_mask],[1,99.7]); ax.imshow(arr,origin="lower",cmap="gray",vmin=lo,vmax=hi,aspect="equal")
        for rr in rows[:int(max_candidates)]:
            if rr.get("evidence_state")=="REJECTED_ARTIFACT": continue
            ax.plot(rr.get("x"),rr.get("y"),marker="o",ms=7,mfc="none",mec="red",lw=1)
            ax.text(rr.get("x"),rr.get("y"),str(rr.get("candidate_id","")),fontsize=6,color="white")
        ax.set_title("Discovery field — candidatos a revisión")
        ax.set_xlabel("x (px)"); ax.set_ylabel("y (px)")
        pdf.savefig(fig); fig.clear()
        fig=Figure(figsize=(11.69,8.27)); ax=fig.add_subplot(111); ax.axis("off")
        ax.set_title("Candidate evidence table",loc="left",fontsize=13,weight="bold")
        tab_rows=[]
        for r in rows[:int(max_candidates)]:
            tab_rows.append([r.get("candidate_id",""),r.get("discovery_state",""),r.get("anomaly_state",""),
                             ",".join(Path(x).stem for x in r.get("bands",[])[:3]),
                             f"{finite(r.get('peak_snr'),0):.1f}",f"{finite(r.get('elongation'),0):.2f}",
                             r.get("catalog_state","—")])
        if tab_rows:
            table=ax.table(cellText=tab_rows,colLabels=["ID","Estado","Anomalía","Bandas","S/N","Elong.","Catálogo"],loc="upper left",cellLoc="left")
            table.auto_set_font_size(False); table.set_fontsize(7.5); table.scale(1,1.35)
        else:
            ax.text(0.02,0.90,"No hay candidatos a revisión en este escaneo.",fontsize=11)
        pdf.savefig(fig)
    return str(path)

def launch_gui(oiii=None, ha=None, _test_hook=None):
    """AstroPhysics Suite v57 Discovery Workspace.

    Design goals:
      * no ambiguous auto-pairing: manual selection always wins;
      * complete scientific map views over the full frame;
      * profile browser with scrollbars and interactive detail plot;
      * candidate browser with scrollbars and detail panel;
      * PDF/HTML/JSON/CSV export from the GUI;
      * independent ASIAIR metadata Excel export, async + cancellable;
      * real-data AI training from a generated workbook;
      * multi-epoch analysis with physical + visual AI;
      * advanced controls hidden but available.
    """
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    from tkinter.scrolledtext import ScrolledText
    import threading, queue

    try:
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.figure import Figure
    except Exception:
        FigureCanvasTkAgg = None
        Figure = None

    root = tk.Tk()
    _style_simple(root)
    root.title(f"AstroPhysics Suite {__version__} — descubrimiento astrofísico")
    root.geometry("1460x920")
    root.minsize(1180, 760)

    q = queue.Queue()
    cancel = threading.Event()
    state = {"payload": None, "images": None, "profile_keys": [], "profile_mode": "nebula", "profile_index": -1}

    v = {
        "folder": tk.StringVar(value=""),
        "oiii": tk.StringVar(value=oiii or ""),
        "ha": tk.StringVar(value=ha or ""),
        "o3star": tk.StringVar(value=""),
        "hastar": tk.StringVar(value=""),
        "broad": tk.StringVar(value=""),
        "out": tk.StringVar(value=str(Path.cwd() / "run")),
        "target": tk.StringVar(value=""),
        "grid": tk.StringVar(value=""),
        "excel_out": tk.StringVar(value=""),
        "pixel": tk.StringVar(value=""),
        "distance": tk.StringVar(value="725"),
        "n0": tk.StringVar(value="6"),
        "snr": tk.StringVar(value="4"),
        "maxc": tk.StringVar(value="2000"),
        "profiles": tk.StringVar(value="24"),
        "workers": tk.StringVar(value="1"),
        "ai_model": tk.StringVar(value=""),
        "ai_vision_model": tk.StringVar(value=""),
        "offline": tk.BooleanVar(value=False),
    }

    def log(msg):
        log_txt.configure(state="normal")
        log_txt.insert("end", str(msg) + "\n")
        log_txt.see("end")
        log_txt.configure(state="disabled")

    def set_status(msg, frac=None):
        status_var.set(str(msg))
        if frac is not None:
            progress["value"] = max(0, min(1, float(frac)))

    def valid_file(path):
        try: return bool(path and Path(path).is_file())
        except Exception: return False

    def update_file_summary():
        fields = [
            ("Hα normal", v["ha"].get()),
            ("[O III] normal", v["oiii"].get()),
            ("Hα starless", v["hastar"].get()),
            ("[O III] starless", v["o3star"].get()),
            ("Banda ancha", v["broad"].get()),
        ]
        lines = []
        for label, p in fields:
            ok = valid_file(p)
            lines.append(f"{'✓' if ok else '—'} {label}: {Path(p).name if ok else 'no seleccionado'}")
        files_lbl.configure(text="\n".join(lines))

    def pick_file(var_key, title):
        p = filedialog.askopenfilename(
            title=f"Seleccionar {title}",
            filetypes=[("Imágenes astronómicas", "*.fits *.fit *.fts *.fz *.xisf"), ("Todos los archivos", "*.*")])
        if p:
            v[var_key].set(p)
            if not v["folder"].get():
                v["folder"].set(str(Path(p).parent))
            log(f"{title}: {p}")
            update_file_summary()

    def pick_dir():
        p = filedialog.askdirectory(title="Selecciona la carpeta de observación / ASIAIR")
        if p:
            v["folder"].set(p)
            discover(auto_fill=True)

    def discover(auto_fill=True):
        folder = Path(v["folder"].get().strip())
        if not folder.is_dir():
            return
        try:
            files = list(_survey_discover(folder, 64))
        except Exception as exc:
            log(f"Exploración: {exc}")
            return
        # Auto-pair may return only normal channels; never use it for starless.
        try:
            o3, h = auto_pair_directory(str(folder))
        except Exception:
            o3, h = "", ""

        def best_starless(kind):
            toks = ("starless", "ha") if kind == "ha" else ("starless", "oiii")
            cand = []
            for p in files:
                low = p.name.lower().replace("-", "_").replace(" ", "_")
                if "starless" in low and all(t in low for t in toks):
                    cand.append(p)
                elif kind == "ha" and ("ha_starless" in low or "starless_ha" in low):
                    cand.append(p)
                elif kind == "o3" and ("oiii_starless" in low or "starless_oiii" in low):
                    cand.append(p)
            return str(sorted(set(cand))[0]) if cand else ""

        hs, os = best_starless("ha"), best_starless("o3")
        if hs and not valid_file(v["hastar"].get()): v["hastar"].set(hs)
        if os and not valid_file(v["o3star"].get()): v["o3star"].set(os)
        if auto_fill:
            if o3 and not valid_file(v["oiii"].get()): v["oiii"].set(o3)
            if h and not valid_file(v["ha"].get()): v["ha"].set(h)
        if not v["target"].get():
            try: v["target"].set(infer_target_from_paths(folder, *[p.name for p in files]))
            except Exception: pass
        update_file_summary()
        log(f"Exploración: {len(files)} archivos · selección manual preservada")
        set_status("Datos cargados")

    def resolve_target():
        name = v["target"].get().strip()
        if not name:
            messagebox.showwarning("SIMBAD", "Escribe un nombre (por ejemplo NGC6960 o M31).")
            return
        set_status("Consultando SIMBAD…", 0.1)
        def worker():
            try:
                ra, dec, msg = resolve_object_center(name)
                if ra is None:
                    q.put(("simbad_error", f"SIMBAD no resolvió {name}: {msg}"))
                else:
                    q.put(("simbad_done", (ra, dec, msg)))
            except Exception as exc:
                q.put(("simbad_error", f"SIMBAD: {type(exc).__name__}: {exc}"))
        threading.Thread(target=worker, daemon=True).start()

    def start_excel():
        folder = Path(v["folder"].get().strip())
        if not folder.is_dir():
            messagebox.showerror("Excel", "Selecciona primero una carpeta de observación.")
            return
        out = filedialog.asksaveasfilename(title="Guardar inventario de observación", initialfile="OBSERVACIONES.xlsx", defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
        if not out: return
        v["excel_out"].set(out)
        cancel.clear(); excel_btn.configure(state="disabled")
        set_status("Generando Excel…", 0.01); log("Generación de Excel iniciada en segundo plano.")
        def worker():
            try:
                def prog(fr, msg): q.put(("excel_progress", fr, msg))
                info = generate_observatory_excel(folder, out, progress=prog, cancel=cancel)
                q.put(("excel_done", info))
            except Exception as exc:
                q.put(("excel_error", f"{type(exc).__name__}: {exc}"))
        threading.Thread(target=worker, daemon=True).start()

    def export_current(kind):
        payload = state.get("payload")
        if not payload:
            messagebox.showwarning("Exportación", "Primero ejecuta o abre un análisis.")
            return
        out_dir = Path(v["out"].get().strip() or Path.cwd())
        out_dir.mkdir(parents=True, exist_ok=True)
        h = o = None
        try:
            h, o = state.get("images") or (None, None)
        except Exception: pass
        if kind == "pdf":
            p = filedialog.asksaveasfilename(title="Exportar informe PDF", initialfile="AstroPhysics_Report.pdf", defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])
            if not p: return
            def worker():
                try: q.put(("export_done", "PDF", write_report_pdf(payload, p, ha_image=h, o3_image=o, max_profiles=24)))
                except Exception as exc: q.put(("export_error", f"PDF: {type(exc).__name__}: {exc}"))
            threading.Thread(target=worker, daemon=True).start()
        elif kind == "html":
            p = filedialog.asksaveasfilename(title="Exportar informe HTML", initialfile="AstroPhysics_Report.html", defaultextension=".html", filetypes=[("HTML", "*.html")])
            if not p: return
            def worker():
                try: q.put(("export_done", "HTML", write_html_report(payload, p, ha_image=h, o3_image=o)))
                except Exception as exc: q.put(("export_error", f"HTML: {type(exc).__name__}: {exc}"))
            threading.Thread(target=worker, daemon=True).start()
        elif kind == "json":
            p = filedialog.asksaveasfilename(title="Exportar catálogo JSON", initialfile="catalog_export.json", defaultextension=".json", filetypes=[("JSON", "*.json")])
            if not p: return
            atomic_json_dump(payload, p); log(f"JSON exportado: {p}"); set_status("JSON exportado", 1)
        elif kind == "csv":
            p = filedialog.asksaveasfilename(title="Exportar candidatos CSV", initialfile="candidates.csv", defaultextension=".csv", filetypes=[("CSV", "*.csv")])
            if not p: return
            write_catalog_csv(payload.get("candidates", []), p); log(f"CSV exportado: {p}"); set_status("CSV exportado", 1)

    def open_catalog():
        p = filedialog.askopenfilename(title="Abrir catálogo generado", filetypes=[("Catálogo JSON", "*.json"), ("Todos", "*.*")])
        if not p: return
        try:
            payload = json.loads(Path(p).read_text(encoding="utf-8"))
            state["payload"] = payload
            hpath = (payload.get("inputs", {}) or {}).get("ha", "")
            opath = (payload.get("inputs", {}) or {}).get("oiii", "")
            state["images"] = (load_fits(hpath).data, load_fits(opath).data) if valid_file(hpath) and valid_file(opath) else (None, None)
            if payload.get("summary", {}).get("target_name") and not v["target"].get(): v["target"].set(payload["summary"]["target_name"])
            fill_results(payload); log(f"Catálogo abierto: {p}")
        except Exception as exc:
            messagebox.showerror("Catálogo", str(exc))

    def show_profile(index=None):
        keys = state.get("profile_keys", [])
        if not keys: return
        if index is None: index = state.get("profile_index", 0)
        index = max(0, min(len(keys)-1, int(index)))
        state["profile_index"] = index
        key = keys[index]
        prof_tree.selection_set(key)
        prof_tree.focus(key)
        payload = state.get("payload") or {}
        if state.get("profile_mode") == "stellar":
            sp = (payload.get("stellar_profiles") or {}).get(str(key))
            if FigureCanvasTkAgg and sp is not None:
                _plot_stellar_profile(profile_fig, sp, *(state.get("images") or (None,None)))
                profile_canvas.draw_idle()
        else:
            if FigureCanvasTkAgg:
                _plot_profiles(profile_fig, payload, key, *(state.get("images") or (None,None)))
                profile_canvas.draw_idle()
        profile_info.set(f"Perfil {index+1}/{len(keys)} · clave {key}")

    def on_profile_select(_event=None):
        sel = prof_tree.selection()
        if sel:
            state["profile_index"] = prof_tree.index(sel[0])
            show_profile(state["profile_index"])

    def rebuild_profiles(mode=None):
        if mode: state["profile_mode"] = mode
        prof_tree.delete(*prof_tree.get_children())
        payload = state.get("payload") or {}
        rows = payload.get("candidates", []) or []
        if state["profile_mode"] == "stellar":
            keys = list((payload.get("stellar_profiles") or {}).keys())
            keys = [str(k) for k in keys]
        else:
            sel = [r for r in rows if r.get("profile_rank")]
            sel.sort(key=lambda r:int(r.get("profile_rank", 10**9)))
            keys = [profile_key(r) for r in sel]
        state["profile_keys"] = keys
        for i, key in enumerate(keys):
            row = next((r for r in rows if profile_key(r) == str(key)), {})
            if state["profile_mode"] == "stellar":
                prof_tree.insert("", "end", iid=str(key), values=(i+1, key, "estrella", "", "", "", ""))
            else:
                prof_tree.insert("", "end", iid=str(key), values=(i+1, key, f"{finite(row.get('x'),0):.0f}", f"{finite(row.get('y'),0):.0f}", f"{finite(row.get('peak_snr_ha'),0):.1f}", f"{finite(row.get('peak_snr_oiii'),0):.1f}", f"{finite(row.get('ratio'),0):.3g}"))
        profile_info.set(f"{len(keys)} perfiles disponibles")
        if keys: show_profile(0)

    def fill_candidate_detail(row):
        detail_txt.configure(state="normal"); detail_txt.delete("1.0", "end")
        if not row:
            detail_txt.insert("end", "Selecciona un candidato para ver todos sus datos.")
        else:
            for k in sorted(row.keys()):
                detail_txt.insert("end", f"{k}: {row[k]}\n")
        detail_txt.configure(state="disabled")

    def on_candidate_select(_event=None):
        sel = cand_tree.selection()
        if not sel: return
        item = cand_tree.item(sel[0], "values")
        try: idx = int(item[0])
        except Exception: return
        rows = state.get("payload", {}).get("candidates", []) or []
        for r in rows:
            if str(r.get("id")) == str(idx):
                fill_candidate_detail(r); break

    def fill_results(payload):
        state["payload"] = payload
        fill = payload.get("inputs", {}) or {}
        hp = fill.get("ha") or v["ha"].get(); op = fill.get("oiii") or v["oiii"].get()
        try:
            state["images"] = (load_fits(hp).data, load_fits(op).data) if valid_file(hp) and valid_file(op) else (None, None)
        except Exception:
            state["images"] = (None, None)
        for tree in (cand_tree,): tree.delete(*tree.get_children())
        rows = payload.get("candidates", []) or []
        for r in sorted(rows, key=lambda x:(0 if str(x.get('status','')).startswith('ok') else 1, int(x.get('id',0) or 0))):
            cand_tree.insert("", "end", values=(r.get("id"), r.get("status"), r.get("candidate_type",""), f"{finite(r.get('x'),0):.0f}", f"{finite(r.get('y'),0):.0f}", f"{finite(r.get('peak_snr_ha'),0):.1f}", f"{finite(r.get('peak_snr_oiii'),0):.1f}", f"{finite(r.get('ratio'),0):.3g}", f"{finite(r.get('ratio_err'),0):.2g}", r.get("reason", "")))
        s = payload.get("summary", {}) or {}
        cards_vars["candidates"].set(str(s.get("n_candidates", len(rows))))
        cards_vars["profiles"].set(str(s.get("n_profiles_total", 0)))
        cards_vars["stars"].set(str(s.get("n_stars_detected", 0)))
        cards_vars["ratio"].set("—" if s.get("ratio_median") is None else f"{s.get('ratio_median'):.3g}")
        cards_vars["target"].set(str(s.get("target_name") or v["target"].get() or "No identificado"))
        summary_txt.configure(state="normal"); summary_txt.delete("1.0", "end")
        summary_txt.insert("end", f"OBJETO: {cards_vars['target'].get()}\n\n")
        summary_txt.insert("end", f"Candidatos: {s.get('n_candidates',0)}\nAnalizados: {s.get('n_analyzed',0)}\nPerfiles nebulosa: {s.get('n_profiles_total',0)}\nEstrellas detectadas: {s.get('n_stars_detected',0)}\n")
        summary_txt.insert("end", f"Ratio [O III]/Hα mediano: {s.get('ratio_median')}\nEscala angular: {s.get('pixel_scale_arcsec')}\n")
        summary_txt.insert("end", f"Grid: {s.get('grid_name')}\nCalibración: {(s.get('calibration') or {}).get('calibrated')}\n")
        summary_txt.insert("end", "\nLos mapas de ratio, proxy de enfriamiento y S/N se representan sobre la IMAGEN COMPLETA. Los perfiles son mediciones locales independientes.\n")
        summary_txt.configure(state="disabled")
        rebuild_profiles("nebula")
        draw_map()
        notebook.select(map_tab)

    def draw_map():
        if not FigureCanvasTkAgg or not state.get("images"):
            return
        h, o = state["images"]
        mode = map_choice.get()
        map_fig.clear()
        rows = state.get("payload", {}).get("candidates", []) or []
        if mode == "ratio":
            _plot_map(map_fig, h, o, 1, rows, mode="ratio", show_candidates=True, star_sources=state.get("payload", {}).get("stars"))
        elif mode == "cooling":
            _plot_map(map_fig, h, o, 1, rows, mode="cooling", show_candidates=True, star_sources=state.get("payload", {}).get("stars"))
        elif mode == "composite":
            _plot_map(map_fig, h, o, 1, rows, mode="rgb", show_candidates=True, star_sources=state.get("payload", {}).get("stars"))
        else:
            img = np.asarray(h if mode == "snr_ha" else o, np.float32)
            bg = estimate_background(img, box=64)
            arr = (img - np.asarray(bg.bkg, np.float32)) / np.maximum(np.asarray(bg.rms, np.float32), 1e-6)
            arr = np.where(np.isfinite(arr), arr, np.nan)
            lo, hi = np.nanpercentile(arr, [1, 99.5]) if np.isfinite(arr).any() else (-1, 1)
            ax = map_fig.add_subplot(111)
            im = ax.imshow(arr, origin="lower", cmap="magma", vmin=lo, vmax=hi, aspect="equal")
            map_fig.colorbar(im, ax=ax, label="S/N local")
            ax.set_title("Hα — S/N · imagen completa" if mode == "snr_ha" else "[O III] — S/N · imagen completa")
            ax.set_xlabel("x (px)"); ax.set_ylabel("y (px)")
        map_canvas.draw_idle()

    def run_discovery():
        paths=[v["ha"].get().strip(),v["oiii"].get().strip(),v["broad"].get().strip()]
        paths=[p for p in paths if valid_file(p)]
        if not paths:
            messagebox.showerror("Descubrimiento","Selecciona al menos una imagen normal (Hα, [O III] o banda ancha/RGB/L-Quad).")
            return
        cancel.clear(); discovery_btn.configure(state="disabled"); set_status("Escaneo de descubrimiento…",0.02)
        def worker():
            try:
                out=Path(v["out"].get().strip() or Path(v["folder"].get() or Path.cwd())/"run")
                payload=discovery_scan_observation(paths,out,snr_min=float(v["discovery_snr"].get() or 5),max_candidates=int(v["discovery_max"].get() or 2000),pixel_scale_arcsec=float(v["pixel"].get()) if v["pixel"].get().strip() else float("nan"),target_name=v["target"].get().strip())
                q.put(("discovery_done",payload))
            except Exception as exc: q.put(("discovery_error",f"{type(exc).__name__}: {exc}"))
        threading.Thread(target=worker,daemon=True).start()

    def run_analysis():
        required = {"Hα normal":v["ha"].get(), "[O III] normal":v["oiii"].get(), "Hα starless":v["hastar"].get(), "[O III] starless":v["o3star"].get()}
        missing = [k for k,p in required.items() if not valid_file(p)]
        if missing:
            messagebox.showerror("Análisis", "Faltan archivos:\n\n" + "\n".join(missing))
            return
        cancel.clear(); run_btn.configure(state="disabled"); set_status("Analizando…", 0.02)
        def worker():
            try:
                grid_path = v["grid"].get().strip()
                grid, _ = load_scientific_grid(grid_path or None, allow_demo=True, context="GUI v57.3")
                P = AnalysisParams(
                    oiii_filter=FILTER_DEFAULT, ha_filter=FILTER_DEFAULT,
                    light_path="",
                    oiii_starless_path=v["o3star"].get().strip(), ha_starless_path=v["hastar"].get().strip(),
                    broadband_path=v["broad"].get().strip(), distance_pc=float(v["distance"].get() or 725),
                    distance_err_pc=15, n0=float(v["n0"].get() or 6), snr_min=float(v["snr"].get() or 4),
                    max_candidates=int(v["maxc"].get() or 2000), max_shock_profiles=int(v["profiles"].get() or 24),
                    workers=max(1,int(v["workers"].get() or 1)), use_processes=True, register="stars", starless=True,
                    pixel_scale_override=float(v["pixel"].get()) if v["pixel"].get().strip() else float("nan"),
                    target_name=v["target"].get().strip(), offline=bool(v["offline"].get()), accumulate=True)
                out = Path(v["out"].get().strip() or Path(v["folder"].get()) / "run")
                out.mkdir(parents=True, exist_ok=True)
                def prog(fr,msg): q.put(("progress",fr,msg))
                payload = analyze_pair(v["oiii"].get(), v["ha"].get(), str(out), P, grid=grid, progress=prog, cancel=cancel)
                q.put(("done", payload))
            except Exception as exc:
                q.put(("error", f"{type(exc).__name__}: {exc}"))
        threading.Thread(target=worker, daemon=True).start()

    def export_discovery_pdf():
        payload=state.get("discovery_payload")
        if not payload:
            messagebox.showwarning("Descubrimiento","Primero ejecuta un escaneo de descubrimiento."); return
        p=filedialog.asksaveasfilename(title="Exportar informe de descubrimiento",initialfile="Discovery_Report.pdf",defaultextension=".pdf",filetypes=[("PDF","*.pdf")])
        if not p: return
        try:
            image=None
            imgs=payload.get("inputs",{}).get("images",[]) or []
            if imgs and valid_file(imgs[0]): image=load_fits(imgs[0]).data
            q.put(("export_done","Discovery PDF",write_discovery_report_pdf(payload,p,image=image,max_candidates=30)))
        except Exception as exc: q.put(("export_error",f"Discovery PDF: {type(exc).__name__}: {exc}"))

    def export_training():
        payload = state.get("payload")
        if not payload:
            messagebox.showwarning("IA", "Primero ejecuta o abre un análisis.")
            return
        p = filedialog.asksaveasfilename(title="Exportar dataset de entrenamiento", initialfile="AI_TRAINING.xlsx", defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
        if not p: return
        try:
            path = export_training_workbook(payload.get("candidates", []) or [], p)
            set_status("Dataset IA exportado", 1); log(f"Dataset IA: {path}")
            messagebox.showinfo("IA", f"Dataset exportado:\n{path}\n\nEtiqueta solo con evidencia real.")
        except Exception as exc: messagebox.showerror("IA", str(exc))

    def train_excel():
        xlsx = filedialog.askopenfilename(title="Seleccionar Excel de entrenamiento", filetypes=[("Excel", "*.xlsx")])
        if not xlsx: return
        model = filedialog.asksaveasfilename(title="Guardar modelo IA", initialfile="astrodiscovery_v56.modelzip", defaultextension=".modelzip", filetypes=[("Modelo IA", "*.modelzip")])
        if not model: return
        cancel.clear(); train_btn.configure(state="disabled"); set_status("Entrenando IA…", 0.03); log("Entrenamiento IA iniciado en segundo plano.")
        def worker():
            try: q.put(("ai_done", train_ai_from_excel(xlsx, model, min_rows=80, contamination=0.02)))
            except Exception as exc: q.put(("ai_error", f"{type(exc).__name__}: {exc}"))
        threading.Thread(target=worker, daemon=True).start()

    def start_series():
        parent = filedialog.askdirectory(title="Seleccionar carpeta que contiene las épocas/observaciones")
        if not parent: return
        subs = [p for p in sorted(Path(parent).iterdir()) if p.is_dir()]
        if not subs:
            messagebox.showwarning("Serie", "No hay subcarpetas de observación.")
            return
        cancel.clear(); series_btn.configure(state="disabled"); set_status(f"Serie 0/{len(subs)}", 0.02); log(f"Análisis de serie: {len(subs)} épocas")
        def worker():
            try:
                P = AnalysisParams(oiii_filter=FILTER_DEFAULT, ha_filter=FILTER_DEFAULT, target_name=v["target"].get().strip(), light_path="", distance_pc=float(v["distance"].get() or 725), distance_err_pc=15, n0=float(v["n0"].get() or 6), snr_min=float(v["snr"].get() or 4), max_candidates=int(v["maxc"].get() or 2000), max_shock_profiles=int(v["profiles"].get() or 24), workers=max(1,int(v["workers"].get() or 1)), use_processes=True, register="stars", offline=bool(v["offline"].get()), accumulate=False)
                rep = analyze_series_with_ai([str(x) for x in subs], P, model_path=v["ai_model"].get().strip(), vision_model_path=v["ai_vision_model"].get().strip(), output=str(Path(v["out"].get() or parent)/"series_results.json"))
                q.put(("series_done", rep))
            except Exception as exc: q.put(("series_error", f"{type(exc).__name__}: {exc}"))
        threading.Thread(target=worker, daemon=True).start()

    # -------- UI --------
    header = ttk.Frame(root, padding=16); header.pack(fill="x")
    ttk.Label(header, text="AstroPhysics Suite", font=("TkDefaultFont", 22, "bold")).pack(side="left")
    ttk.Label(header, text="ANÁLISIS · MEDICIÓN · ANOMALÍAS · DESCUBRIMIENTO", font=("TkDefaultFont", 9, "bold")).pack(side="left", padx=18, pady=(8,0))

    top = ttk.LabelFrame(root, text="1 · DATOS DE LA OBSERVACIÓN", padding=10); top.pack(fill="x", padx=12, pady=(0,8))
    ttk.Button(top, text="Elegir carpeta…", command=pick_dir).grid(row=0,column=0,padx=3,pady=3)
    ttk.Button(top, text="Hα normal", command=lambda:pick_file("ha","Hα normal · CON ESTRELLAS")).grid(row=0,column=1,padx=3)
    ttk.Button(top, text="[O III] normal", command=lambda:pick_file("oiii","[O III] normal · CON ESTRELLAS")).grid(row=0,column=2,padx=3)
    ttk.Button(top, text="Hα starless", command=lambda:pick_file("hastar","Hα starless")).grid(row=0,column=3,padx=3)
    ttk.Button(top, text="[O III] starless", command=lambda:pick_file("o3star","[O III] starless")).grid(row=0,column=4,padx=3)
    ttk.Button(top, text="Banda ancha", command=lambda:pick_file("broad","Banda ancha / RGB / L-Quad")).grid(row=0,column=5,padx=3)
    ttk.Button(top, text="Detectar automáticamente", command=lambda:discover(True)).grid(row=0,column=6,padx=3)
    files_lbl = ttk.Label(top, text="Selecciona archivos o una carpeta.", justify="left")
    files_lbl.grid(row=1,column=0,columnspan=7,sticky="w",pady=(6,0))
    top.columnconfigure(6,weight=1)

    cfg = ttk.Frame(root, padding=(12,2)); cfg.pack(fill="x")
    ttk.Label(cfg,text="Objeto").pack(side="left")
    ttk.Entry(cfg,textvariable=v["target"],width=22).pack(side="left",padx=4)
    ttk.Button(cfg,text="Resolver SIMBAD",command=resolve_target).pack(side="left",padx=3)
    ttk.Button(cfg,text="Abrir catálogo…",command=open_catalog).pack(side="left",padx=3)
    ttk.Label(cfg,text="Salida").pack(side="left",padx=(18,4))
    ttk.Entry(cfg,textvariable=v["out"],width=45).pack(side="left",fill="x",expand=True)
    ttk.Button(cfg,text="…",width=3,command=lambda:v["out"].set(filedialog.askdirectory(title="Carpeta de resultados") or v["out"].get())).pack(side="left")

    adv_open=tk.BooleanVar(value=False)
    adv=ttk.LabelFrame(root,text="Opciones avanzadas",padding=8)
    def toggle_adv():
        if adv_open.get(): adv.pack(fill="x",padx=12,pady=5,before=actionbar)
        else: adv.pack_forget()
    ttk.Checkbutton(root,text="Mostrar opciones avanzadas",variable=adv_open,command=toggle_adv).pack(anchor="w",padx=12,pady=(0,3))
    ttk.Label(adv,text="Grid MAPPINGS/3MdB").grid(row=0,column=0,sticky="w"); ttk.Entry(adv,textvariable=v["grid"],width=42).grid(row=0,column=1,sticky="ew",padx=4); ttk.Button(adv,text="…",command=lambda:v["grid"].set(filedialog.askopenfilename(title="Seleccionar grilla",filetypes=[("Grillas","*.csv *.ecsv *.json *.txt"),("Todos","*.*")]) or v["grid"].get())).grid(row=0,column=2)
    ttk.Label(adv,text="IA física").grid(row=0,column=3,sticky="w",padx=(20,0)); ttk.Entry(adv,textvariable=v["ai_model"],width=34).grid(row=0,column=4,sticky="ew",padx=4)
    ttk.Label(adv,text="IA visual").grid(row=0,column=5,sticky="w",padx=(10,0)); ttk.Entry(adv,textvariable=v["ai_vision_model"],width=30).grid(row=0,column=6,sticky="ew",padx=4)
    labels=[("distance","Distancia pc"),("n0","n0 cm⁻³"),("pixel","Escala ″/px"),("snr","SNR mín."),("maxc","Máx. candidatos"),("profiles","Perfiles"),("workers","Workers")]
    for i,(key,label) in enumerate(labels):
        rr=1+i//4; cc=(i%4)*2
        ttk.Label(adv,text=label).grid(row=rr,column=cc,sticky="w",padx=2,pady=2); ttk.Entry(adv,textvariable=v[key],width=11).grid(row=rr,column=cc+1,sticky="w",padx=(0,10),pady=2)
    ttk.Checkbutton(adv,text="Modo offline",variable=v["offline"]).grid(row=3,column=0,columnspan=2,sticky="w")
    for c in range(7): adv.columnconfigure(c,weight=1 if c in (1,4,6) else 0)

    actionbar=ttk.Frame(root,padding=(12,4)); actionbar.pack(fill="x")
    discovery_btn=ttk.Button(actionbar,text="◎  ESCANEAR DESCUBRIMIENTO",command=run_discovery); discovery_btn.pack(side="left",padx=3)
    run_btn=ttk.Button(actionbar,text="▶  ANALIZAR",command=run_analysis); run_btn.pack(side="left",padx=3)
    ttk.Button(actionbar,text="⏹ Cancelar",command=lambda:cancel.set()).pack(side="left",padx=3)
    series_btn=ttk.Button(actionbar,text="Analizar serie…",command=start_series); series_btn.pack(side="left",padx=(10,3))
    excel_btn=ttk.Button(actionbar,text="Generar Excel…",command=start_excel); excel_btn.pack(side="left",padx=3)
    train_btn=ttk.Button(actionbar,text="Entrenar IA con Excel…",command=train_excel); train_btn.pack(side="left",padx=3)
    ttk.Button(actionbar,text="Exportar entrenamiento…",command=export_training).pack(side="left",padx=3)
    ttk.Separator(actionbar,orient="vertical").pack(side="left",fill="y",padx=10)
    for label,kind in (("PDF","pdf"),("HTML","html"),("JSON","json"),("CSV","csv")):
        ttk.Button(actionbar,text=f"Exportar {label}",command=lambda k=kind:export_current(k)).pack(side="left",padx=2)

    status_var=tk.StringVar(value="Listo")
    progress=ttk.Progressbar(actionbar,maximum=1,length=250)
    progress.pack(side="right",padx=6)
    ttk.Label(actionbar,textvariable=status_var).pack(side="right",padx=5)

    # Dashboard cards
    cards=ttk.Frame(root,padding=(12,5)); cards.pack(fill="x")
    cards_vars={k:tk.StringVar(value="—") for k in ("target","candidates","profiles","stars","ratio")}
    card_specs=[("target","OBJETO"),("candidates","CANDIDATOS"),("profiles","PERFILES"),("stars","ESTRELLAS"),("ratio","RATIO MEDIANO")]
    for i,(k,lab) in enumerate(card_specs):
        lf=ttk.LabelFrame(cards,text=lab,padding=(10,5)); lf.grid(row=0,column=i,padx=4,sticky="ew"); cards.columnconfigure(i,weight=1)
        ttk.Label(lf,textvariable=cards_vars[k],font=("TkDefaultFont",13,"bold")).pack(anchor="w")

    notebook=ttk.Notebook(root); notebook.pack(fill="both",expand=True,padx=12,pady=(2,12))

    # DISCOVERY WORKSPACE
    disc_tab=ttk.Frame(notebook,padding=10); notebook.add(disc_tab,text="DESCUBRIMIENTO")
    dtop=ttk.Frame(disc_tab); dtop.pack(fill="x")
    ttk.Label(dtop,text="ESCANEO CIENTÍFICO DE LA IMAGEN COMPLETA",font=("TkDefaultFont",14,"bold")).pack(side="left")
    ttk.Label(dtop,text="detecta · identifica · caracteriza · contrasta · evidencia",font=("TkDefaultFont",9,"bold")).pack(side="left",padx=18)
    dbar=ttk.Frame(disc_tab); dbar.pack(fill="x",pady=6)
    ttk.Label(dbar,text="S/N mín.").pack(side="left"); ttk.Entry(dbar,textvariable=v["discovery_snr"],width=8).pack(side="left",padx=4)
    ttk.Label(dbar,text="Máx. candidatos").pack(side="left",padx=(12,0)); ttk.Entry(dbar,textvariable=v["discovery_max"],width=10).pack(side="left",padx=4)
    ttk.Button(dbar,text="Volver a escanear",command=run_discovery).pack(side="left",padx=8)
    ttk.Button(dbar,text="Exportar informe PDF",command=export_discovery_pdf).pack(side="left",padx=3)
    ttk.Label(disc_tab,text="La ausencia de catálogo, por sí sola, no se interpreta como descubrimiento. Se rechazan trazas lineales y detecciones de mala calidad antes de presentar un candidato.",wraplength=1100).pack(anchor="w",pady=(0,8))
    dp=ttk.Panedwindow(disc_tab,orient="vertical"); dp.pack(fill="both",expand=True)
    dc_top=ttk.Frame(dp); dc_bot=ttk.Frame(dp); dp.add(dc_top,weight=4); dp.add(dc_bot,weight=2)
    dcols=("cid","state","anomaly","bands","x","y","snr","elong","catalog","reason")
    discovery_tree=ttk.Treeview(dc_top,columns=dcols,show="headings")
    for c,t in zip(dcols,("ID","Estado","Anomalía","Bandas","X","Y","S/N","Elongación","Catálogo","Evidencia")): discovery_tree.heading(c,text=t)
    for c,w in zip(dcols,(95,145,135,240,65,65,70,95,125,360)): discovery_tree.column(c,width=w,anchor="center")
    dy=ttk.Scrollbar(dc_top,orient="vertical",command=discovery_tree.yview); dx=ttk.Scrollbar(dc_top,orient="horizontal",command=discovery_tree.xview); discovery_tree.configure(yscrollcommand=dy.set,xscrollcommand=dx.set)
    discovery_tree.grid(row=0,column=0,sticky="nsew"); dy.grid(row=0,column=1,sticky="ns"); dx.grid(row=1,column=0,sticky="ew"); dc_top.rowconfigure(0,weight=1); dc_top.columnconfigure(0,weight=1)
    discovery_detail=ScrolledText(dc_bot,wrap="word",font=("TkFixedFont",9)); discovery_detail.pack(fill="both",expand=True); discovery_detail.configure(state="disabled")

    def fill_discovery(payload):
        state["discovery_payload"]=payload; discovery_tree.delete(*discovery_tree.get_children())
        for r in payload.get("candidates",[]) or []:
            discovery_tree.insert("","end",values=(r.get("candidate_id"),r.get("discovery_state"),r.get("anomaly_state"),", ".join(r.get("bands",[])),f"{finite(r.get('x'),0):.1f}",f"{finite(r.get('y'),0):.1f}",f"{finite(r.get('peak_snr'),0):.1f}",f"{finite(r.get('elongation'),0):.2f}",r.get("catalog_state","—"),r.get("artifact_reason","") ))
        set_status(f"Descubrimiento: {payload.get('summary',{}).get('n_candidates',0)} candidatos a revisar",1); notebook.select(disc_tab)

    def on_discovery_select(_event=None):
        sel=discovery_tree.selection()
        if not sel: return
        vals=discovery_tree.item(sel[0],"values"); cid=str(vals[0]); row=next((r for r in (state.get("discovery_payload") or {}).get("candidates",[]) if str(r.get("candidate_id"))==cid),None)
        discovery_detail.configure(state="normal"); discovery_detail.delete("1.0","end")
        if row is not None:
            discovery_detail.insert("end",json.dumps(json_sanitize(row),indent=2,ensure_ascii=False))
        discovery_detail.configure(state="disabled")
    discovery_tree.bind("<<TreeviewSelect>>",on_discovery_select)

    # MAPS
    map_tab=ttk.Frame(notebook,padding=8); notebook.add(map_tab,text="MAPAS · IMAGEN COMPLETA")
    mbar=ttk.Frame(map_tab); mbar.pack(fill="x")
    map_choice=tk.StringVar(value="ratio")
    ttk.Label(mbar,text="Capa científica").pack(side="left")
    ttk.Combobox(mbar,textvariable=map_choice,state="readonly",width=26,values=["ratio","cooling","composite","snr_ha","snr_oiii"]).pack(side="left",padx=6)
    ttk.Button(mbar,text="Actualizar mapa",command=draw_map).pack(side="left")
    map_fig=Figure(figsize=(11,7),dpi=96) if Figure is not None else None
    map_canvas=FigureCanvasTkAgg(map_fig,master=map_tab) if FigureCanvasTkAgg and map_fig else None
    if map_canvas: map_canvas.get_tk_widget().pack(fill="both",expand=True)
    else: ttk.Label(map_tab,text="Matplotlib no disponible").pack(expand=True)

    # PROFILES
    prof_tab=ttk.Frame(notebook,padding=8); notebook.add(prof_tab,text="PERFILES · EXPLORADOR")
    prof_top=ttk.Frame(prof_tab); prof_top.pack(fill="x")
    ttk.Label(prof_top,text="Tipo").pack(side="left")
    ttk.Button(prof_top,text="Perfiles nebulosa",command=lambda:rebuild_profiles("nebula")).pack(side="left",padx=3)
    ttk.Button(prof_top,text="Perfiles estelares",command=lambda:rebuild_profiles("stellar")).pack(side="left",padx=3)
    ttk.Button(prof_top,text="◀ anterior",command=lambda:show_profile(state.get("profile_index",0)-1)).pack(side="left",padx=(14,2))
    ttk.Button(prof_top,text="siguiente ▶",command=lambda:show_profile(state.get("profile_index",0)+1)).pack(side="left",padx=2)
    profile_info=tk.StringVar(value="Sin perfiles")
    ttk.Label(prof_top,textvariable=profile_info).pack(side="right")
    pan=ttk.Panedwindow(prof_tab,orient="horizontal"); pan.pack(fill="both",expand=True,pady=6)
    left=ttk.Frame(pan); right=ttk.Frame(pan); pan.add(left,weight=1); pan.add(right,weight=3)
    pcols=("rank","key","x","y","snrha","snro3","ratio")
    prof_tree=ttk.Treeview(left,columns=pcols,show="headings")
    for c,t in zip(pcols,("#","clave","X","Y","SNR Hα","SNR OIII","ratio")): prof_tree.heading(c,text=t)
    for c,w in zip(pcols,(45,125,55,55,75,78,75)): prof_tree.column(c,width=w,anchor="center")
    py=ttk.Scrollbar(left,orient="vertical",command=prof_tree.yview); px=ttk.Scrollbar(left,orient="horizontal",command=prof_tree.xview); prof_tree.configure(yscrollcommand=py.set,xscrollcommand=px.set)
    prof_tree.grid(row=0,column=0,sticky="nsew"); py.grid(row=0,column=1,sticky="ns"); px.grid(row=1,column=0,sticky="ew"); left.rowconfigure(0,weight=1); left.columnconfigure(0,weight=1)
    prof_tree.bind("<<TreeviewSelect>>",on_profile_select)
    profile_fig=Figure(figsize=(9,6),dpi=96) if Figure else None
    profile_canvas=FigureCanvasTkAgg(profile_fig,master=right) if FigureCanvasTkAgg and profile_fig else None
    if profile_canvas: profile_canvas.get_tk_widget().pack(fill="both",expand=True)

    # CANDIDATES
    cand_tab=ttk.Frame(notebook,padding=8); notebook.add(cand_tab,text="CANDIDATOS · CATÁLOGO")
    cp=ttk.Panedwindow(cand_tab,orient="vertical"); cp.pack(fill="both",expand=True)
    ct=ttk.Frame(cp); cd=ttk.Frame(cp); cp.add(ct,weight=4); cp.add(cd,weight=2)
    ccols=("id","status","type","x","y","snrha","snro3","ratio","ratioerr","reason")
    cand_tree=ttk.Treeview(ct,columns=ccols,show="headings")
    for c,t in zip(ccols,("ID","Estado","Tipo","X","Y","SNR Hα","SNR OIII","Ratio","Err","Motivo")): cand_tree.heading(c,text=t)
    for c,w in zip(ccols,(55,120,100,65,65,78,80,75,70,360)): cand_tree.column(c,width=w,anchor="center")
    cy=ttk.Scrollbar(ct,orient="vertical",command=cand_tree.yview); cx=ttk.Scrollbar(ct,orient="horizontal",command=cand_tree.xview); cand_tree.configure(yscrollcommand=cy.set,xscrollcommand=cx.set)
    cand_tree.grid(row=0,column=0,sticky="nsew"); cy.grid(row=0,column=1,sticky="ns"); cx.grid(row=1,column=0,sticky="ew"); ct.rowconfigure(0,weight=1); ct.columnconfigure(0,weight=1)
    cand_tree.bind("<<TreeviewSelect>>",on_candidate_select)
    ttk.Label(cd,text="DETALLE DEL CANDIDATO",font=("TkDefaultFont",10,"bold")).pack(anchor="w")
    detail_txt=ScrolledText(cd,wrap="word",font=("TkFixedFont",9)); detail_txt.pack(fill="both",expand=True)
    detail_txt.configure(state="disabled")

    # SUMMARY
    sum_tab=ttk.Frame(notebook,padding=8); notebook.add(sum_tab,text="RESUMEN")
    summary_txt=ScrolledText(sum_tab,wrap="word",font=("TkFixedFont",10)); summary_txt.pack(fill="both",expand=True); summary_txt.configure(state="disabled")

    # SERIES / AI
    ai_tab=ttk.Frame(notebook,padding=10); notebook.add(ai_tab,text="SERIES · IA")
    ttk.Label(ai_tab,text="Serie temporal",font=("TkDefaultFont",12,"bold")).pack(anchor="w")
    ttk.Label(ai_tab,text="Selecciona una carpeta con subcarpetas por época. La Suite mantiene un catálogo por época y, si hay modelos persistentes, aplica IA física y visual.",wraplength=1050).pack(anchor="w",pady=5)
    ttk.Button(ai_tab,text="Analizar serie…",command=start_series).pack(anchor="w",pady=3)
    ttk.Separator(ai_tab,orient="horizontal").pack(fill="x",pady=10)
    ttk.Label(ai_tab,text="Entrenamiento",font=("TkDefaultFont",12,"bold")).pack(anchor="w")
    ttk.Label(ai_tab,text="1) Analiza datos reales · 2) Exporta AI_TRAINING.xlsx · 3) etiqueta con evidencia real · 4) Entrena IA con Excel · 5) conserva el modelo en una ruta persistente.",wraplength=1050).pack(anchor="w",pady=5)
    ttk.Button(ai_tab,text="Exportar entrenamiento desde análisis",command=export_training).pack(anchor="w",pady=2)
    ttk.Button(ai_tab,text="Entrenar IA con Excel…",command=train_excel).pack(anchor="w",pady=2)

    # LOG
    log_tab=ttk.Frame(notebook,padding=8); notebook.add(log_tab,text="LOG")
    log_txt=ScrolledText(log_tab,wrap="word",font=("TkFixedFont",9)); log_txt.pack(fill="both",expand=True); log_txt.configure(state="disabled")

    def poll():
        try:
            while True:
                item=q.get_nowait(); kind=item[0]
                if kind in ("progress","excel_progress"):
                    set_status(item[2], item[1]); log(item[2])
                elif kind == "excel_done":
                    info=item[1]; set_status("Excel terminado",1); log(f"Excel generado: {info['output']} · {info['n_files']} archivos · {info['n_sessions']} sesiones")
                    excel_btn.configure(state="normal"); messagebox.showinfo("Excel",f"Excel generado:\n{info['output']}\n\nArchivos: {info['n_files']}\nSesiones: {info['n_sessions']}")
                elif kind == "excel_error":
                    excel_btn.configure(state="normal"); set_status("Error Excel",0); log(item[1]); messagebox.showerror("Excel",item[1])
                elif kind == "simbad_done":
                    ra,dec,msg=item[1]; set_status("SIMBAD resuelto",1); log(msg); messagebox.showinfo("SIMBAD",f"{msg}\n\nRA = {ra:.6f}°\nDec = {dec:.6f}°")
                elif kind == "simbad_error":
                    set_status("SIMBAD sin resolver",0); log(item[1]); messagebox.showwarning("SIMBAD",item[1])
                elif kind == "ai_done":
                    rep=item[1]; train_btn.configure(state="normal"); set_status("IA entrenada",1); log(json.dumps(rep,ensure_ascii=False,indent=2));
                    if rep.get("state","").startswith("ENTRENADA"): v["ai_model"].set(rep.get("model_path",v["ai_model"].get()))
                    messagebox.showinfo("IA",f"Estado: {rep.get('state')}\nFilas: {rep.get('n_rows',rep.get('n_train','?'))}")
                elif kind == "ai_error":
                    train_btn.configure(state="normal"); set_status("Error IA",0); log(item[1]); messagebox.showerror("IA",item[1])
                elif kind == "series_done":
                    series_btn.configure(state="normal"); set_status("Serie terminada",1); log(json.dumps(item[1],ensure_ascii=False,indent=2)); messagebox.showinfo("Serie",f"Épocas procesadas: {item[1].get('n_epochs',0)}\nErrores: {len(item[1].get('errors',[]))}")
                elif kind == "series_error":
                    series_btn.configure(state="normal"); set_status("Error serie",0); log(item[1]); messagebox.showerror("Serie",item[1])
                elif kind == "export_done":
                    set_status(f"{item[1]} exportado",1); log(f"{item[1]}: {item[2]}"); messagebox.showinfo("Exportación",f"{item[1]} generado:\n{item[2] or 'ok'}")
                elif kind == "export_error":
                    set_status("Error exportación",0); log(item[1]); messagebox.showerror("Exportación",item[1])
                elif kind == "discovery_done":
                    discovery_btn.configure(state="normal"); fill_discovery(item[1]); log(json.dumps(item[1].get("summary",{}),ensure_ascii=False,indent=2))
                elif kind == "discovery_error":
                    discovery_btn.configure(state="normal"); set_status("Error descubrimiento",0); log(item[1]); messagebox.showerror("Descubrimiento",item[1])
                elif kind == "done":
                    run_btn.configure(state="normal"); fill_results(item[1]); set_status("Análisis terminado",1); log("Análisis completado correctamente.")
                elif kind == "error":
                    run_btn.configure(state="normal"); set_status("Error",0); log(item[1]); messagebox.showerror("Análisis",item[1])
        except queue.Empty:
            pass
        root.after(120,poll)

    update_file_summary()
    if v["folder"].get(): discover()
    elif oiii or ha:
        try: v["folder"].set(str(Path(oiii or ha).parent)); discover()
        except Exception: pass
    root.after(120,poll)
    root.mainloop()

def main(argv=None):
    if argv is None and len(sys.argv)==1: argv=["gui"]
    args=build_parser().parse_args(argv); logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    if args.cmd=="pixel-science":
        try:
            rep=analyze_pixel_science_images(args.ha,args.oiii,args.broadband,pixel_scale_arcsec=args.pixel_scale,ebv=args.ebv,r_v=args.r_v,nii_over_ha=args.nii_over_ha,ha_scale=args.ha_scale,oiii_scale=args.oiii_scale,snr_min=args.snr_min,output_dir=args.out,plane_ha=parse_plane_arg(args.ha_plane),plane_oiii=parse_plane_arg(args.oiii_plane),plane_broadband=parse_plane_arg(args.broadband_plane))
            print(json.dumps(json_sanitize(rep),indent=2,ensure_ascii=False)); return 0
        except (OSError,ValueError,TypeError,KeyError,RuntimeError) as exc:
            LOG.error("pixel-science: %s",exc); return 2
    if args.cmd=="model-compare":
        try:
            payload=json.loads(Path(args.catalog).read_text(encoding="utf-8"))
            rep=compare_physical_models_from_catalog(payload,model_ids=args.models)
            atomic_json_dump(rep,args.out)
            print(json.dumps(json_sanitize(rep),indent=2,ensure_ascii=False))
            return 0 if rep.get("state")=="OK" else 2
        except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:
            LOG.error("model-compare: %s",exc); return 2
    if args.cmd=="selftest": return selftest()
    if args.cmd=="infer-physics":
        try:
            payload=json.load(open(args.catalog,encoding="utf-8"))
            pnorm=normalize_scientific_payload(payload)
            rows=pnorm.get("candidates",[]) or pnorm.get("results",[])
            bundle=physical_discovery_bundle({"candidates":rows},object_family=args.object_family,distance_pc=args.distance_pc,distance_err_pc=args.distance_err_pc)
            atomic_json_dump(bundle,args.out)
            print(json.dumps(json_sanitize(bundle),indent=2,ensure_ascii=False)); return 0
        except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:
            print(f"Error de inferencia física: {exc}",file=sys.stderr); return 2
    if args.cmd=="discover":
        try:
            payload=json.load(open(args.catalog,encoding="utf-8"))
            ref=json.load(open(args.reference,encoding="utf-8")) if args.reference else {}
            ai_result=None
            if args.ai_model and Path(args.ai_model).is_file():
                try:
                    ai_result=discovery_ai_from_rows((normalize_scientific_payload(payload).get("candidates") or []),model_path=args.ai_model)
                except (OSError,ValueError,TypeError,KeyError) as exc:
                    LOG.warning("IA opcional no disponible: %s",exc)
                    ai_result={"state":"NO DISPONIBLE","error":f"{type(exc).__name__}: {exc}"}
            bundle=physical_discovery_bundle(payload,object_family=args.object_family,reference=ref,distance_pc=args.distance_pc,distance_err_pc=args.distance_err_pc,ai_result=ai_result)
            atomic_json_dump(bundle,args.out)
            print(json.dumps(json_sanitize(bundle),indent=2,ensure_ascii=False)); return 0
        except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:
            print(f"Error de descubrimiento: {exc}",file=sys.stderr); return 2
    if args.cmd=="project":
        store=DiscoveryStore(args.file)
        try:
            if args.action=="create":
                d=store.create(args.name,description=args.description,target_name=args.target_name); print(json.dumps(json_sanitize(d),indent=2,ensure_ascii=False)); return 0
            if args.action=="show":
                print(json.dumps(json_sanitize(store.load()),indent=2,ensure_ascii=False)); return 0
            if args.action=="rank":
                print(json.dumps(json_sanitize(store.rank_candidates()),indent=2,ensure_ascii=False)); return 0
            if args.action=="review":
                print(json.dumps(json_sanitize(store.review(args.row_id,args.state,note=args.note)),indent=2,ensure_ascii=False)); return 0
        except (OSError,ValueError,KeyError,TypeError) as exc:
            LOG.error("Proyecto: %s", exc); return 2
    if args.cmd=="discovery-record":
        try:
            with open(args.catalog,encoding="utf-8") as fh: payload=json.load(fh)
            rec=build_discovery_record(payload,project_id=args.project_id)
            atomic_json_dump(rec,args.out); print(json.dumps(json_sanitize(rec),indent=2,ensure_ascii=False)); return 0
        except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as exc:
            LOG.error("discovery-record: %s", exc); return 2
    if args.cmd=="discover-v46":
        try:
            payload=json.loads(Path(args.catalog).read_text(encoding="utf-8"))
            ref=json.loads(Path(args.reference).read_text(encoding="utf-8")) if args.reference else {}
            rep=discovery_v46(payload,object_family=args.object_family,reference=ref)
            atomic_json_dump(rep,args.out); print(json.dumps(json_sanitize(rep),indent=2,ensure_ascii=False)); return 0
        except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:
            LOG.error("discover-v46: %s",exc); return 2
    if args.cmd=="spatial-anomalies":
        try:
            payload=json.loads(Path(args.catalog).read_text(encoding="utf-8")); rows=payload.get("candidates",payload if isinstance(payload,list) else [])
            rep=SpatialTrendAnomalyEngine(z_threshold=args.z_threshold,fdr_alpha=args.fdr_alpha).analyze(rows)
            atomic_json_dump(rep,args.out); print(json.dumps(json_sanitize(rep),indent=2,ensure_ascii=False)); return 0
        except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:
            LOG.error("spatial-anomalies: %s",exc); return 2
    if args.cmd=="temporal-anomalies":
        try:
            payload=json.loads(Path(args.catalog).read_text(encoding="utf-8")); epochs=payload.get("epochs",payload if isinstance(payload,list) else [])
            rep=TemporalChangeEngine().analyze(epochs,min_epochs=args.min_epochs,sigma_threshold=args.sigma_threshold)
            atomic_json_dump(rep,args.out); print(json.dumps(json_sanitize(rep),indent=2,ensure_ascii=False)); return 0
        except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:
            LOG.error("temporal-anomalies: %s",exc); return 2
    if args.cmd=="synthetic":
        try:
            payload=synthetic_end_to_end(args.out); print(json.dumps(json_sanitize(payload["summary"]),indent=2,ensure_ascii=False)); return 0
        except Exception:
            LOG.exception("Synthetic E2E falló"); return 1
    if args.cmd=="audit": print(json.dumps(json_sanitize(audit_report()),indent=2,ensure_ascii=False)); return 0
    if args.cmd=="ai-train":
        try:
            rep=train_discovery_ai(args.training,args.model,seed=20260915,min_rows=args.min_rows,contamination=args.contamination)
            print(json.dumps(json_sanitize(rep),indent=2,ensure_ascii=False)); return 0 if rep.get("state")=="ENTRENADA CON DATOS REALES" else 2
        except Exception as exc:
            LOG.exception("AI training failed"); return 1
    if args.cmd=="ai-real-corpus":
        try:
            manifest=build_real_vision_manifest(args.manifest,max_objects=args.max_objects)
            rep=download_real_vision_corpus(args.manifest,args.out,overwrite=args.overwrite)
            rep["manifest"]=args.manifest; print(json.dumps(json_sanitize(rep),indent=2,ensure_ascii=False)); return 0 if rep.get("n_downloaded",0)>0 else 2
        except Exception:
            LOG.exception("No se pudo preparar el corpus real")
            return 1
    if args.cmd=="ai-real-train":
        try:
            build_real_vision_manifest(args.manifest,max_objects=args.max_objects)
            rep=download_real_vision_corpus(args.manifest,args.out)
            if rep.get("n_downloaded",0)<8:
                print(json.dumps(json_sanitize(rep),indent=2,ensure_ascii=False)); return 2
            trep=train_real_visual_seed(args.out,args.model,epochs=args.epochs,batch_size=args.batch_size,max_images=args.max_images,seed=20260915)
            trep["download"]={"n_downloaded":rep.get("n_downloaded"),"n_failed":rep.get("n_failed"),"manifest":args.manifest}
            print(json.dumps(json_sanitize(trep),indent=2,ensure_ascii=False)); return 0 if trep.get("state","").startswith("ENTRENADA") else 2
        except Exception:
            LOG.exception("Real visual training failed"); return 1
    if args.cmd=="ai-vision-train":
        try:
            rep=train_vision_ai(args.training,args.model,seed=20260915,epochs=args.epochs,batch_size=args.batch_size,max_images=args.max_images)
            print(json.dumps(json_sanitize(rep),indent=2,ensure_ascii=False)); return 0 if rep.get("state","").startswith("ENTRENADA") else 2
        except Exception:
            LOG.exception("AI visual training failed"); return 1
    if args.cmd=="ai-session":
        try:
            session=DiscoverySession(model_path=args.model,training_path=args.training,seed=20260915,min_rows=args.min_rows,contamination=args.contamination)
            if session.state!="ACTIVA":
                print(json.dumps({"state":session.state,"error":session.last_error},ensure_ascii=False)); return 2
            print(json.dumps({"state":"ACTIVA","model":args.model,"message":"Sesión persistente. Ctrl+C para salir."},ensure_ascii=False))
            if args.catalog:
                while True:
                    cp=Path(args.catalog)
                    payload=json.loads(cp.read_text(encoding="utf-8"))
                    rows=payload.get("candidates",[]) if isinstance(payload,dict) else payload
                    scores=session.analyze(rows)
                    for r,sc in zip(rows,scores): r.update(sc)
                    payload["discovery_ai_session"]={"state":"ACTIVA","model":args.model,"n_candidates":len(rows),"n_outliers":sum(s.get("novelty_state")=="OUTLIER" for s in scores),"human_validation_required":True}
                    cp.write_text(json.dumps(json_sanitize(payload),indent=2,ensure_ascii=False),encoding="utf-8")
                    print(json.dumps(payload["discovery_ai_session"],ensure_ascii=False),flush=True)
                    time.sleep(2.0)
            while True: time.sleep(1.0)
        except KeyboardInterrupt: return 0
        except Exception:
            LOG.exception("AI session failed"); return 1
    if args.cmd=="deps": print(json.dumps({"version":__version__,"astropy":HAS_ASTROPY,"skimage":HAS_SKIMAGE,"sklearn":HAS_SKLEARN,"pandas":HAS_PANDAS,"matplotlib":HAS_MPL,"photutils":HAS_PHOTUTILS, "photutils_background":HAS_PHOTUTILS_BACKGROUND, "photutils_dao":HAS_PHOTUTILS_DAO,"simbad":HAS_SIMBAD,"gaia":HAS_GAIA,"torch":HAS_TORCH,"numpy":np.__version__,"ram_gb":round(_available_ram_gb(),1),"workers_safe":_safe_worker_count(8)},indent=2)); return 0
    if args.cmd=="filters": print(json.dumps(json_sanitize({"visible":FILTER_VISIBLE,"narrowband_pair":FILTER_NARROWBAND_VISIBLE,"broadband_context":FILTER_BROADBAND_CONTEXT_VISIBLE,"presets":FILTER_PRESETS}),indent=2,ensure_ascii=False)); return 0
    if args.cmd=="literature": print(json.dumps(json_sanitize({k:{"canonical":v["canonical"],"aliases":v["aliases"][:5]} for k,v in LITERATURE_DB.items()}),indent=2,ensure_ascii=False)); return 0
    if args.cmd=="real-dataset":
        labels={}
        for item in args.object:
            if "=" not in item: LOG.error("--object requiere nombre_archivo=OBJETO"); return 2
            k,v=item.split("=",1); labels[k]=v
        try:
            rep=build_real_observation_dataset(args.images,args.out,object_labels=labels,patch_size=args.patch_size,patches_per_image=args.patches_per_image,seed=args.seed)
            print(json.dumps(json_sanitize(rep),indent=2,ensure_ascii=False)); return 0 if rep['state']=='OK' else 2
        except (OSError,ValueError,TypeError,AmbiguousCubeError) as exc:
            LOG.error('real-dataset: %s',exc); return 2
    if args.cmd=="real-ai-train":
        try:
            rep=train_real_vision_domain(args.dataset,args.model,epochs=args.epochs,batch_size=args.batch_size,seed=args.seed,max_patches=args.max_patches)
            print(json.dumps(json_sanitize(rep),indent=2,ensure_ascii=False)); return 0 if rep['state'].startswith('ENTRENADA') else 2
        except (OSError,ValueError,TypeError,RuntimeError) as exc:
            LOG.error('real-ai-train: %s',exc); return 2
    if args.cmd=="gui": launch_gui(args.oiii,args.ha); return 0
    if args.cmd=="physical-anomalies":
        try:
            payload=json.loads(Path(args.catalog).read_text(encoding="utf-8")); rows=payload.get("candidates",payload if isinstance(payload,list) else [])
            rep=physical_anomaly_engine(rows,target_name=(payload.get("summary",{}) or {}).get("target_name","") if isinstance(payload,dict) else "")
            Path(args.out).write_text(json.dumps(json_sanitize(rep),indent=2,ensure_ascii=False),encoding="utf-8")
            print(json.dumps(json_sanitize(rep),indent=2,ensure_ascii=False)); return 0
        except Exception:
            LOG.exception("physical-anomalies failed"); return 1
    if args.cmd=="physics-diagnostics":
        try:
            payload=json.loads(Path(args.catalog).read_text(encoding="utf-8"))
            rows=payload.get("candidates",payload if isinstance(payload,list) else [])
            eng=MultiObjectPhysicsEngine(args.distance_pc,args.distance_err_pc,args.ebv,args.pixel_scale)
            rep=eng.summarize(rows)
            Path(args.out).write_text(json.dumps(json_sanitize(rep),indent=2,ensure_ascii=False),encoding="utf-8")
            print(json.dumps(json_sanitize(rep),indent=2,ensure_ascii=False)); return 0
        except Exception:
            LOG.exception("physics-diagnostics failed"); return 1
    if args.cmd=="physics":
        cool=CoolingCurve.from_csv(args.cooling_csv) if args.cooling_csv else CoolingCurve(); st=rankine_hugoniot(args.v,args.n0,T0=args.T0,beta_te_ti=args.beta,cooling=cool); print(json.dumps(json_sanitize({"state":dataclasses.asdict(st),"mc":shock_monte_carlo(args.v,args.v_err,args.n0,cooling=cool)}),indent=2)); return 0
    if args.cmd=="invert":
        # v29: Use load_scientific_grid; abort on invalid grid
        try:
            grid, _ = load_scientific_grid(args.grid or None, allow_demo=not args.grid, context="CLI invert", trust_registry_path=args.grid_registry)
        except Exception as exc:
            print(f"No se pudo cargar grid MAPPINGS/3MdB: {exc}", file=sys.stderr)
            return 2
        sol = grid.invert(args.ratio, args.ratio_err, n0=args.n0, grid_model_logerr=args.grid_model_logerr)
        print(json.dumps(json_sanitize(dataclasses.asdict(sol)), indent=2, ensure_ascii=False)); return 0
    if args.cmd=="report":
        payload=json.load(open(args.catalog,encoding="utf-8")); prof=Path(args.catalog).with_name("profiles.json"); payload["profiles"]=json.load(open(prof,encoding="utf-8")).get("profiles",{}) if prof.exists() else {}; payload.setdefault("stellar_profiles",{})
        img_ha=img_o3=None; hp=(payload.get("inputs") or {}).get("ha_starless") or (payload.get("inputs") or {}).get("ha"); op=(payload.get("inputs") or {}).get("oiii_starless") or (payload.get("inputs") or {}).get("oiii")
        selected=(payload.get("manifest") or {}).get("selected_cube_plane") or {}
        if hp and Path(hp).is_file():
            try: img_ha=load_fits(hp,plane=selected.get("ha")).data
            except Exception as exc: LOG.warning("Sin imagen Hα: %s",exc)
        if op and Path(op).is_file():
            try: img_o3=load_fits(op,plane=selected.get("oiii")).data
            except Exception as exc: LOG.warning("Sin imagen OIII: %s",exc)
        if args.html: print(write_html_report(payload,args.out,ha_image=img_ha,o3_image=img_o3) or "sin HTML")
        else: print(write_report_pdf(payload,args.out,ha_image=img_ha,o3_image=img_o3) or "sin PDF")
        return 0
    if args.cmd=="gaia":
        if not HAS_GAIA: print("Gaia no disponible: pip install astroquery"); return 1
        tbl=query_gaia_sources(args.ra,args.dec,args.radius,args.mag_limit,args.max_rows)
        if tbl is None: print("Sin resultados"); return 1
        print(f"Gaia DR3: {len(tbl)} fuentes"); print(tbl[:min(10,len(tbl))]); return 0
    # v28 CLI commands
    if args.cmd=="multiband":
        plane = parse_plane_arg(args.plane)
        result = stack_multiband(args.images, args.out, plane=plane, normalize=not args.no_normalize)
        print(json.dumps(json_sanitize(result), indent=2, ensure_ascii=False)); return 0
    if args.cmd=="propermotion":
        result = measure_proper_motion(args.epoch1, args.epoch2, pixel_scale_arcsec=args.pixel_scale, time_baseline_yr=args.baseline_yr)
        print(json.dumps(json_sanitize(result), indent=2, ensure_ascii=False)); return 0
    if args.cmd=="velocity":
        # v29: Use load_scientific_grid; abort on invalid grid (no silent fallback)
        try:
            grid, _ = load_scientific_grid(args.grid or None, allow_demo=not args.grid, context="CLI velocity", trust_registry_path=getattr(args,"grid_registry",""))
        except Exception as exc:
            print(f"No se pudo cargar grid MAPPINGS/3MdB: {exc}", file=sys.stderr)
            return 2
        result = estimate_shock_velocity(args.ratio, args.ratio_err, grid, n0=args.n0)
        print(json.dumps(json_sanitize(result), indent=2, ensure_ascii=False)); return 0
    if args.cmd=="age":
        result = estimate_ast_remnant_age(args.radius_arcsec, args.distance_pc, velocity_km_s=args.velocity, velocity_err_km_s=args.velocity_err, n0_cm3=args.n0)
        print(json.dumps(json_sanitize(result), indent=2, ensure_ascii=False)); return 0
    if args.cmd=="redshift":
        result = apply_redshift_correction(args.wavelength, args.z)
        print(json.dumps(json_sanitize(result), indent=2, ensure_ascii=False)); return 0
    if args.cmd=="qc":
        payload = json.load(open(args.catalog, encoding="utf-8"))
        qc = generate_qc_summary(payload)
        Path(args.out).write_text(json.dumps(json_sanitize(qc), indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"QC summary written to {args.out}"); return 0
    if args.cmd=="provenance":
        payload = json.load(open(args.catalog, encoding="utf-8"))
        prov = build_provenance_chain(payload)
        Path(args.out).write_text(json.dumps(json_sanitize(prov), indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Provenance written to {args.out}"); return 0
    if args.cmd=="forward":
        sim = simulate_observation(tuple(args.shape), n_filaments=args.n_filaments, n_stars=args.n_stars, offset_px=args.offset, seed=args.seed)
        # Save arrays as .npy, metadata as JSON
        np.save(args.out.replace('.json', '_ha.npy'), sim["ha_array"])
        np.save(args.out.replace('.json', '_oiii.npy'), sim["oiii_array"])
        meta = {k: v for k, v in sim.items() if k not in ("ha_array", "oiii_array")}
        Path(args.out).write_text(json.dumps(json_sanitize(meta), indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Forward model written to {args.out}"); return 0
    if args.cmd=="grid-trust":
        try:
            rep=register_trusted_grid(args.grid,args.registry,reference=args.reference)
            print(json.dumps(json_sanitize(rep),indent=2,ensure_ascii=False)); return 0
        except (OSError,ValueError,TypeError,KeyError) as exc:
            LOG.error("grid-trust: %s",exc); return 2
    if args.cmd=="mappings":
        loader = MappingsGridLoader(trust_registry_path=(getattr(args,"grid_registry","") or None))
        grid = loader.load(args.grid)
        meta = loader.metadata
        if args.validate:
            print(json.dumps(json_sanitize(meta.to_dict()), indent=2, ensure_ascii=False))
        else:
            print(f"Grid loaded: {grid.name}, {len(grid.v)} points, SHA256={meta.sha256[:16]}...")
        return 0
    # v29 CLI commands
    if args.cmd=="calibrate":
        result = absolute_photometric_calibration(args.flux_adu, args.zeropoint, args.exposure, args.gain, args.airmass, args.k_ext, args.k_err, args.flux_err)
        print(json.dumps(json_sanitize(result), indent=2, ensure_ascii=False)); return 0
    if args.cmd=="psf":
        img = load_fits(args.image).data
        result = measure_source_quality(img, args.x, args.y, cutout_size=args.cutout, gain=args.gain, saturation_level=args.saturation)
        print(json.dumps(json_sanitize(result), indent=2, ensure_ascii=False)); return 0
    if args.cmd=="wcs":
        if not HAS_ASTROPY:
            print("Error: astropy no disponible; instale con pip install astropy", file=sys.stderr)
            return 2
        from astropy.io import fits as _fits
        with _fits.open(args.header) as hdul:
            hdr = dict(hdul[0].header)
        result = validate_wcs(hdr, tuple(args.shape))
        print(json.dumps(json_sanitize(result), indent=2, ensure_ascii=False)); return 0
    if args.cmd=="gaia-match":
        result = crossmatch_gaia_safe(args.ra, args.dec, radius_arcsec=args.radius, mag_limit=args.mag_limit)
        print(json.dumps(json_sanitize(result), indent=2, ensure_ascii=False)); return 0
    if args.cmd=="posterior":
        loader = MappingsGridLoader()
        grid = loader.load(args.grid)
        result = grid_posterior_inference(args.ratio, args.ratio_err, grid, n0=args.n0, n_samples=args.n_samples)
        print(json.dumps(json_sanitize(result), indent=2, ensure_ascii=False)); return 0
    if args.cmd=="multiband-pipeline":
        result = analyze_multiband_pipeline(args.images, args.out, pixel_scale=args.pixel_scale, normalize=not args.no_normalize)
        print(json.dumps(json_sanitize(result), indent=2, ensure_ascii=False)); return 0
    if args.cmd=="script":
        if args.template:
            create_template_script(args.file)
            print(f"Plantilla escrita en {args.file}"); return 0
        payload = None
        if args.catalog:
            try:
                payload = json.load(open(args.catalog, encoding="utf-8"))
            except Exception as exc:
                LOG.error("No se pudo cargar catalog.json: %s", exc); return 2
        result = run_external_script(
            args.file, payload=payload, out_dir=args.out or ".")
        print(json.dumps(json_sanitize(result), indent=2, ensure_ascii=False)); return 0 if result["state"] == "OK" else 1
    if args.cmd=="analyze":
        if args.dir:
            o3,h=auto_pair_directory(args.dir); args.oiii=args.oiii or o3; args.ha=args.ha or h
        if not(args.oiii and args.ha and args.oiii_starless and args.ha_starless): LOG.error("Se requieren normales OIII/Hα y starless OIII/Hα"); return 2
        if not(Path(args.oiii_starless).is_file() and Path(args.ha_starless).is_file()): LOG.error("Las imágenes starless no existen"); return 2
        o3_curve=ha_curve=None
        if args.oiii_curve:
            o3_curve,_=load_filter_curve(args.oiii_curve)
        if args.ha_curve:
            ha_curve,_=load_filter_curve(args.ha_curve)
        try:
            o3_plane=parse_plane_arg(args.oiii_plane); ha_plane=parse_plane_arg(args.ha_plane)
        except ValueError as exc:
            LOG.error(str(exc)); return 2
        try:
            args.ha_filter = args.oiii_filter
            cal,_,_=calibrate_from_filters(args.oiii_filter,args.ha_filter,read_fits_exptime(args.oiii),read_fits_exptime(args.ha),args.nii_over_ha,args.ebv,0.0,o3_curve,ha_curve, photometric_calibrated=args.photometric_calibrated, oiii_zp_factor=args.oiii_zp_factor, ha_zp_factor=args.ha_zp_factor, r_v=args.r_v, zeropoint_source=args.zeropoint_source, zeropoint_error_mag=args.zeropoint_error_mag, calibration_id=args.calibration_id)
        except (ValueError, OSError) as exc:
            LOG.error("Calibración inválida: %s", exc); return 2
        P=AnalysisParams(snr_min=args.snr_min,max_candidates=args.max_candidates,min_separation_px=args.min_separation_px,distance_pc=args.distance_pc,distance_err_pc=args.distance_err_pc,n0=args.n0,seed=args.seed,workers=args.workers,use_processes=not args.threads,register="stars",starless=True,light_path="",pixel_scale_override=args.pixel_scale,target_name=args.target_name,broadband_path=args.broadband,camera_model="ZWO ASI533MC Pro",camera_profile_version="ZWO official nominal profile",calibration=cal,accumulate=not args.no_accumulate,filament_strategy=args.filament_strategy,oiii_filter=args.oiii_filter,ha_filter=args.ha_filter,oiii_starless_path=args.oiii_starless,ha_starless_path=args.ha_starless,oiii_stars_path="",ha_stars_path="",oiii_plane=o3_plane,ha_plane=ha_plane,offline=args.offline,filter_curve_oiii=args.oiii_curve,filter_curve_ha=args.ha_curve,
            export_products=bool(args.export_products), export_html=args.html, output_png_dpi=args.png_dpi,
            grid_model_logerr=float(args.grid_model_logerr),
            bias_oiii_path=args.bias_oiii, bias_ha_path=args.bias_ha, dark_oiii_path=args.dark_oiii, dark_ha_path=args.dark_ha,
            flat_oiii_path=args.flat_oiii, flat_ha_path=args.flat_ha, grid_path=args.grid or "")
        # v29: Use load_scientific_grid for external grids; no silent fallback to DEMO
        grid = None
        if args.grid:
            try:
                grid, _ = load_scientific_grid(args.grid, allow_demo=False, context="CLI analyze", trust_registry_path=args.grid_registry)
            except Exception:
                return 2
        elif not args.no_builtin_grid:
            grid, _ = load_scientific_grid(None, allow_demo=True, context="CLI analyze", trust_registry_path=args.grid_registry)
        try: payload=analyze_pair(args.oiii,args.ha,args.out,P,grid,args.labels)
        except AmbiguousCubeError as exc: LOG.error(str(exc)); return 3
        if args.export_ecsv: write_catalog_ecsv(payload["candidates"],Path(args.out)/"catalog.ecsv")
        if args.pdf: write_report_pdf(payload,Path(args.out)/"report.pdf",ha_image=load_fits(args.ha,plane=ha_plane).data,o3_image=load_fits(args.oiii,plane=o3_plane).data)
        if args.html: write_html_report(payload,Path(args.out)/"report.html",ha_image=load_fits(args.ha,plane=ha_plane).data,o3_image=load_fits(args.oiii,plane=o3_plane).data)
        print(json.dumps(json_sanitize(payload["summary"]),indent=2,ensure_ascii=False)); return 0
    return 1


# ====================================================================
# v47: REAL OBSERVATION DATASET + DOMAIN PRETRAINING
# ====================================================================
REAL_DATASET_VERSION = "1.0"

def _xisf_read_uncompressed(path):
    import re
    raw = Path(path).read_bytes(); text = raw[:300000].decode("utf-8", errors="ignore")
    m = re.search(r'<Image[^>]+geometry="(\d+):(\d+):(\d+)"[^>]+sampleFormat="([^"]+)"[^>]+bounds="[^"]+"[^>]+colorSpace="([^"]+)"[^>]+location="attachment:(\d+):(\d+)"', text)
    if not m: raise ValueError(f"XISF sin bloque Image/attachment utilizable: {path}")
    w,h,c=map(int,m.group(1,2,3)); fmt=m.group(4); off,size=int(m.group(6)),int(m.group(7))
    dt={"Float32":"<f4","Float64":"<f8","UInt16":"<u2","UInt32":"<u4","Int16":"<i2","Int32":"<i4"}.get(fmt)
    if dt is None: raise ValueError(f"XISF sampleFormat no soportado: {fmt}")
    expected=w*h*c*np.dtype(dt).itemsize
    if size!=expected or off+size>len(raw): raise ValueError("XISF comprimido/estructurado o bloque fuera de rango")
    arr=np.frombuffer(raw,dtype=np.dtype(dt),count=w*h*c,offset=off).reshape((c,h,w))
    return arr,{"width":w,"height":h,"channels":c,"sampleFormat":fmt,"colorSpace":m.group(5),"offset":off,"size":size}

def _real_observation_array(path):
    if Path(path).suffix.lower()=='.xisf':
        return _xisf_read_uncompressed(path)
    im=load_fits(path); a=np.asarray(im.data)
    if a.ndim!=2: raise AmbiguousCubeError(f"Dataset real requiere FITS 2D: {path}")
    return a[None,...],{"width":int(a.shape[1]),"height":int(a.shape[0]),"channels":1,"format":"FITS"}

def _real_patch_tensor(arr_chw,y0,x0,size=128):
    c,h,w=arr_chw.shape; y1=min(h,y0+size); x1=min(w,x0+size)
    patch=np.zeros((3,size,size),np.float32); src=np.asarray(arr_chw[:,y0:y1,x0:x1])
    chans=[_robust_image_scale(src[i]) for i in range(min(3,src.shape[0]))]
    while len(chans)<3: chans.append(chans[-1].copy() if chans else np.zeros((y1-y0,x1-x0),np.float32))
    for i in range(3): patch[i,:y1-y0,:x1-x0]=chans[i]
    return patch

def build_real_observation_dataset(paths,out_dir,object_labels=None,patch_size=128,patches_per_image=48,seed=47):
    rng=np.random.default_rng(int(seed)); out=Path(out_dir); out.mkdir(parents=True,exist_ok=True); labels=object_labels or {}
    manifest={"dataset_version":REAL_DATASET_VERSION,"source":"user_uploaded_real_observations","seed":int(seed),"patch_size":int(patch_size),"items":[]}
    for path in [str(x) for x in paths]:
        a,meta=_real_observation_array(path); h,w=a.shape[-2:]
        grid=[(y,x) for y in range(0,h-patch_size+1,patch_size) for x in range(0,w-patch_size+1,patch_size)]
        if not grid: continue
        n=min(int(patches_per_image),len(grid)); coords=[grid[i] for i in rng.choice(len(grid),size=n,replace=False)]
        sid=hashlib.sha256(Path(path).read_bytes()).hexdigest(); obj=labels.get(Path(path).name,labels.get(str(path),'unknown'))
        for j,(y,x) in enumerate(coords):
            fp=out/f"patch_{len(manifest['items']):06d}.npy"; np.save(fp,_real_patch_tensor(a,int(y),int(x),int(patch_size)),allow_pickle=False)
            manifest['items'].append({"file":fp.name,"source":str(path),"source_sha256":sid,"object":obj,"y":int(y),"x":int(x),"size":int(patch_size),"source_meta":meta})
    atomic_json_dump(manifest,out/'manifest.json'); return {"state":"OK" if manifest['items'] else "NO DISPONIBLE","dataset":str(out),"n_patches":len(manifest['items']),"n_sources":len({i['source'] for i in manifest['items']}),"manifest":str(out/'manifest.json')}

def train_real_vision_domain(dataset_dir,model_path,epochs=8,batch_size=16,seed=47,max_patches=1024):
    if not HAS_TORCH: raise RuntimeError('PyTorch no instalado')
    d=Path(dataset_dir); manifest=json.loads((d/'manifest.json').read_text(encoding='utf-8')); items=manifest.get('items',[])[:int(max_patches)]
    if len(items)<32: return {"state":"NO DISPONIBLE","reason":f"se requieren al menos 32 parches reales; hay {len(items)}"}
    X=np.stack([np.asarray(np.load(d/it['file'],allow_pickle=False),np.float32) for it in items]).astype(np.float32)
    model=AstroVisionAI(seed=seed,latent_dim=VISION_LATENT_DIM,device='cpu'); ds=TensorDataset(torch.from_numpy(X),torch.from_numpy(X)); dl=DataLoader(ds,batch_size=max(1,min(int(batch_size),len(ds))),shuffle=True)
    opt=torch.optim.AdamW(model.net.parameters(),lr=1e-3,weight_decay=1e-4); losses=[]; model.net.train()
    for _ in range(max(1,int(epochs))):
        total=0.0
        for xb,_ in dl:
            pred,_=model.net(xb); loss=F.smooth_l1_loss(pred,xb); opt.zero_grad(set_to_none=True); loss.backward(); opt.step(); total+=float(loss.detach())*len(xb)
        losses.append(total/len(ds))
    Z=model.embed_arrays(X); model._fit_outlier(Z); model.training_meta.update({"training_source":"real user observations","dataset_manifest_sha256":hashlib.sha256((d/'manifest.json').read_bytes()).hexdigest(),"n_real_patches":len(X),"domain_pretraining":True,"objects":sorted({it.get('object','unknown') for it in items}),"scientific_scope":"visual-domain representation; NOT a universal astrophysical classifier"})
    saved=model.save(model_path); return {"state":"ENTRENADA CON DATOS REALES DEL USUARIO","model":saved,"n_patches":len(X),"loss_history":losses,"objects":sorted({it.get('object','unknown') for it in items}),"scope":model.training_meta['scientific_scope']}


# ====================================================================
# v40: PRODUCT DISCOVERY PLATFORM
# ====================================================================
# La suite deja de ser un conjunto de análisis sueltos y añade una capa
# persistente de investigación: proyectos, candidatos, estados de revisión,
# evidencia, scores y registro de modelos. No convierte anomalías en
# descubrimientos automáticamente; obliga a conservar la cadena de evidencia.


# ====================================================================
# v41: MOTOR DE INFERENCIA FISICA Y DESCUBRIMIENTO MULTIPARAMETRO
# ====================================================================
PHYSICAL_ENGINE_VERSION = "1.0"

@dataclass
class ParameterEstimate:
    name: str
    value: Optional[float]
    error: Optional[float]
    unit: str
    status: str
    source: str
    model: Optional[str] = None
    assumptions: list = field(default_factory=list)
    quality: str = "UNKNOWN"

    def asdict(self):
        return json_sanitize(dataclasses.asdict(self))


@dataclass
class ModelFit:
    model_id: str
    family: str
    log_likelihood: Optional[float]
    reduced_chi2: Optional[float]
    n_observables: int
    n_parameters: int
    status: str
    reason: str = ""
    parameters: dict = field(default_factory=dict)

    def asdict(self):
        return json_sanitize(dataclasses.asdict(self))


class PhysicalModelRegistry:
    """Registro explícito de familias y modelos físicos.

    La regla de diseño es estricta: un modelo sólo puede producir una inferencia
    si sus entradas están presentes, tienen unidades/estado compatibles y el
    propio modelo está marcado como validado. No se convierten heurísticas en
    "mediciones".
    """
    def __init__(self):
        self.models = {
            "sedov_uniform_medium": {"family":"SNR", "validated":True,
                "requires":["radius_pc","velocity_kms"],
                "outputs":["age_yr"], "assumptions":["spherical","adiabatic","uniform_medium"]},
            "strong_shock_temperature": {"family":"shock", "validated":True,
                "requires":["velocity_kms"], "outputs":["postshock_temperature_K"],
                "assumptions":["gamma_5_3","fully_ionized","mu_fixed"]},
            "physical_scale_distance": {"family":"geometry", "validated":True,
                "requires":["angular_size_arcsec","distance_pc"], "outputs":["size_pc"],
                "assumptions":["small_angle"]},
        }

    def describe(self):
        return json_sanitize(self.models)


def _get_float(d, *keys):
    for k in keys:
        if k in d:
            v=finite(d.get(k), float('nan'))
            if math.isfinite(v):
                return v
    return float('nan')


def _estimate_error(d, *keys):
    for k in keys:
        if k in d:
            v=abs(finite(d.get(k), float('nan')))
            if math.isfinite(v):
                return v
    return float('nan')


def infer_physical_parameters(row, *, object_family="unknown", distance_pc=None,
                              distance_err_pc=None, registry=None):
    """Extrae parámetros físicamente permitidos de una observación.

    Devuelve explícitamente OBSERVADO/CALIBRADO/INFERIDO/NO DISPONIBLE y evita
    inferencias cuando faltan observables esenciales. El objetivo es que esta
    capa sea la fuente canónica para los parámetros que luego usa el motor de
    anomalías y no haya varias fórmulas dispersas por el programa.
    """
    r=dict(row or {})
    reg=registry or PhysicalModelRegistry()
    estimates=[]
    family=str(object_family or "unknown").lower()
    dpc=_get_float({"distance_pc":distance_pc},"distance_pc")
    depc=_get_float({"distance_err_pc":distance_err_pc},"distance_err_pc")
    if not math.isfinite(dpc): dpc=_get_float(r,"distance_pc")
    if not math.isfinite(depc): depc=_get_float(r,"distance_err_pc")

    # Observables measured/derived without a model.
    ratio=_get_float(r,"ratio","oiii_ha_ratio")
    ratio_err=_estimate_error(r,"ratio_err","oiii_ha_ratio_err")
    if math.isfinite(ratio) and ratio>0:
        lr=math.log10(ratio)
        lre=(ratio_err/(ratio*math.log(10))) if math.isfinite(ratio_err) else float('nan')
        estimates.append(ParameterEstimate("log10_oiii_over_ha",lr,lre,"dex","OBSERVADO","pipeline_ratio"))

    off=_get_float(r,"offset_arcsec")
    offe=_estimate_error(r,"offset_err_arcsec")
    if math.isfinite(off):
        estimates.append(ParameterEstimate("offset_arcsec",off,offe,"arcsec","OBSERVADO","geometry"))

    # Physical scale from small-angle approximation.
    if math.isfinite(off) and math.isfinite(dpc) and dpc>0:
        size_pc=off/206265.0*dpc
        err=float('nan')
        if math.isfinite(offe) and off>0 and math.isfinite(depc) and depc>0:
            err=abs(size_pc)*math.sqrt((offe/off)**2+(depc/dpc)**2)
        estimates.append(ParameterEstimate("offset_pc",size_pc,err,"pc","INFERIDO","geometry", "physical_scale_distance",["small_angle"]))

    v=_get_float(r,"velocity_kms","v_kms")
    ve=_estimate_error(r,"velocity_err_kms","v_err_kms")
    if math.isfinite(v) and v>0:
        # Fully ionized monoatomic strong-shock temperature, explicitly model-dependent.
        kB=1.380649e-23; mp=1.67262192369e-27; mu=0.61; gamma=5.0/3.0
        # T = 2(gamma-1)/(gamma+1)^2 * mu mp v^2 / kB; for gamma=5/3 => 3/16
        coeff=(2*(gamma-1)/(gamma+1)**2)*mu*mp/kB
        t=coeff*(v*1e3)**2
        te=abs(t*2*ve/max(v,1e-12)) if math.isfinite(ve) else float('nan')
        estimates.append(ParameterEstimate("postshock_temperature_K",t,te,"K","INFERIDO","rankine_hugoniot", "strong_shock_temperature",["gamma=5/3","mu=0.61"]))
        # Dynamic age only if physical radius exists.
        rad=_get_float(r,"radius_pc")
        rade=_estimate_error(r,"radius_err_pc")
        if math.isfinite(rad) and rad>0:
            # Sedov-style age coefficient 2/5; this is only a dynamical age proxy under the stated model.
            age_yr=(2.0/5.0)*rad*3.0856775814913673e13/(v*1e3)/(365.25*86400.0)
            ae=float('nan')
            if math.isfinite(rade) and math.isfinite(ve):
                ae=abs(age_yr)*math.sqrt((rade/rad)**2+(ve/v)**2)
            estimates.append(ParameterEstimate("age_yr",age_yr,ae,"yr","INFERIDO","Sedov-Taylor expansion", "sedov_uniform_medium",["spherical","adiabatic","uniform_medium"]))

    # Optional calibrated fluxes.
    for name, valkeys, errkeys, unit in [
        ("flux_ha", ("flux_ha_calibrated","flux_ha"), ("flux_ha_err","flux_ha_calibrated_err"), "flux"),
        ("flux_oiii", ("flux_oiii_calibrated","flux_oiii"), ("flux_oiii_err","flux_oiii_calibrated_err"), "flux"),
    ]:
        val=_get_float(r,*valkeys); err=_estimate_error(r,*errkeys)
        if math.isfinite(val):
            status="CALIBRADO" if any(k in r for k in valkeys if "calibrated" in k) else "OBSERVADO"
            estimates.append(ParameterEstimate(name,val,err,unit,status,"pipeline"))

    return {
        "engine_version": PHYSICAL_ENGINE_VERSION,
        "object_family": family,
        "parameters": {e.name:e.asdict() for e in estimates},
        "available": [e.name for e in estimates],
        "notes": ["Los parámetros INFERIDO dependen explícitamente del modelo indicado."]
    }


def build_reference_anomaly(row, estimates, reference=None):
    """Compara cada parámetro con un intervalo/referencia externa, sin IA."""
    ref=reference or {}
    anomalies=[]
    for name,p in (estimates or {}).items():
        if not isinstance(p,dict):
            continue
        val=finite(p.get("value"),float('nan')); err=abs(finite(p.get("error"),float('nan')))
        cfg=ref.get(name)
        if not isinstance(cfg,dict) or not math.isfinite(val):
            continue
        lo=finite(cfg.get("min"),float('nan')); hi=finite(cfg.get("max"),float('nan'))
        center=finite(cfg.get("value"),float('nan')); sigma=abs(finite(cfg.get("sigma"),float('nan')))
        unit=cfg.get("unit",p.get("unit",""))
        rec={"parameter":name,"observed":val,"unit":unit,"reference":cfg.get("source","external_reference")}
        if math.isfinite(lo) and val<lo:
            rec["direction"]="LOW"; rec["delta"] = float(val-lo)
        elif math.isfinite(hi) and val>hi:
            rec["direction"]="HIGH"; rec["delta"] = float(val-hi)
        else:
            rec["direction"]="WITHIN"
        if math.isfinite(center) and math.isfinite(sigma) and sigma>0:
            rec["z_score"] = float((val-center)/math.sqrt(sigma*sigma + (err*err if math.isfinite(err) else 0.0)))
        anomalies.append(rec)
    return anomalies


def physical_discovery_bundle(payload, *, object_family="unknown", reference=None, distance_pc=None, distance_err_pc=None, ai_result=None):
    """Producto de descubrimiento con score descompuesto y reproducible."""
    p=normalize_scientific_payload(payload if isinstance(payload,dict) else {"candidates":payload}); rows=p.get("candidates",[]) or p.get("results",[]); results=[]
    for i,row in enumerate(rows):
        inf=infer_physical_parameters(row,object_family=object_family,distance_pc=distance_pc,distance_err_pc=distance_err_pc); model_cmp=None
        if isinstance(row.get("model_data"),dict):
            try: model_cmp=compare_physical_models_from_catalog({"model_data":row["model_data"]})
            except (ValueError,TypeError,KeyError): LOG.debug("model_data inválido",exc_info=True)
        refs=build_reference_anomaly(row,inf.get("parameters",{}),reference=reference)
        ref_score=float(min(1,max([0.0]+[abs(finite(x.get("z_score"),0))/5 for x in refs]))); model_score=0.0
        if model_cmp:
            best=(model_cmp.get("models") or [{}])[0]; rms=finite(best.get("residual_rms_standardized"),0); frac3=finite(best.get("fraction_abs_residual_gt3sigma"),0); model_score=float(min(1,0.5*min(rms/2,1)+0.5*min(frac3/0.25,1)))
            if (model_cmp.get("model_discrepancy") or {}).get("flag"): model_score=max(model_score,0.75)
        physical_score=ref_score; visual=float(np.clip(finite(row.get("visual_novelty_score"),0),0,1)); comps={"physical":physical_score,"model":model_score,"literature":ref_score,"visual":visual}
        priority=float(np.clip(0.45*comps["physical"]+0.30*comps["model"]+0.15*comps["literature"]+0.10*comps["visual"],0,1)); tension=bool(physical_score>=0.6 or model_score>=0.75 or ref_score>=0.6)
        results.append({"row_id":row.get("row_id",row.get("id",i)),"inference":inf,"reference_anomalies":refs,"model_comparison":model_cmp,"physical_tension":tension,"priority":priority,"priority_components":comps,"state":"PHYSICAL_TENSION" if tension else "SCREENING"})
    return {"engine_version":PHYSICAL_ENGINE_VERSION,"state":"OK" if results else "NO DISPONIBLE","object_family":object_family,"n_rows":len(results),"rows":results,"ai":ai_result or {"state":"NO EJECUTADA","note":"La física no depende de IA"},"policy":{"priority_weights":{"physical":0.45,"model":0.30,"literature":0.15,"visual":0.10},"human_verification_required":True}}

PRODUCT_SCHEMA_VERSION = 1
DISCOVERY_STATES = (
    "NEW", "SCREENING", "ARTIFACT_SUSPECTED", "KNOWN_OBJECT",
    "PHYSICAL_TENSION", "CANDIDATE", "FOLLOWUP_REQUIRED", "VERIFIED",
    "REJECTED"
)

@dataclass
class DiscoveryProject:
    project_id: str
    name: str
    created_utc: str
    software_version: str = __version__
    schema_version: int = PRODUCT_SCHEMA_VERSION
    owner: str = "local"
    description: str = ""
    target_name: str = ""
    instrument: str = "ZWO ASI533MC Pro"
    filters: list = field(default_factory=lambda: list(FILTER_VISIBLE))
    status: str = "ACTIVE"
    candidates: list = field(default_factory=list)
    evidence: list = field(default_factory=list)

class DiscoveryStore:
    """Repositorio local, auditable y portable para investigación.

    Se guarda en JSON atómico para que el proyecto pueda versionarse, archivarse
    o sincronizarse después con una aplicación comercial sin cambiar el contrato.
    """
    def __init__(self, path):
        self.path=Path(path)

    def create(self, name, *, description="", target_name="", owner="local", project_id=None):
        if not str(name).strip():
            raise ValueError("El proyecto necesita nombre")
        pid=project_id or (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + hashlib.sha256(os.urandom(8)).hexdigest()[:8])
        p=DiscoveryProject(project_id=pid,name=str(name).strip(),created_utc=datetime.now(timezone.utc).isoformat(),
                           description=str(description),target_name=str(target_name),owner=str(owner))
        self._write(asdict(p))
        return asdict(p)

    def load(self):
        if not self.path.is_file():
            raise FileNotFoundError(f"Proyecto no encontrado: {self.path}")
        d=json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(d,dict) or d.get('schema_version') != PRODUCT_SCHEMA_VERSION:
            raise ValueError("Esquema de proyecto incompatible")
        if d.get('status') not in (None,'ACTIVE','ARCHIVED'):
            raise ValueError("Estado de proyecto inválido")
        return d

    def add_analysis(self, payload, *, source_path=""):
        p=self.load()
        norm=normalize_scientific_payload(payload)
        summary=norm.get('summary') or {}
        qc=norm.get('qc_summary') or generate_qc_summary(norm)
        anomalies=norm.get('physical_anomalies') or physical_anomaly_engine(norm.get('candidates',[]), target_name=summary.get('target_name',p.get('target_name','')))
        entry={
            'analysis_id': datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'),
            'created_utc': datetime.now(timezone.utc).isoformat(),
            'source_path': str(source_path),
            'input_sha256': (norm.get('manifest',{}).get('input_sha256') or norm.get('manifest',{}).get('inputs_sha256') or {}),
            'summary': summary,
            'qc': qc,
            'physical_anomalies': anomalies,
            'provenance': norm.get('provenance',{}),
        }
        p.setdefault('evidence',[]).append(entry)
        p['updated_utc']=entry['created_utc']
        self._write(p)
        return entry

    def rank_candidates(self):
        p=self.load(); ranked=[]
        for ev in p.get('evidence',[]):
            for row in (ev.get('physical_anomalies',{}) or {}).get('rows',[]):
                score=finite(row.get('anomaly_score'),0.0)
                kinds=[a.get('kind') for a in row.get('anomalies',[]) if isinstance(a,dict)]
                has_measurement='measurement_issue' in kinds
                has_physical='field_anomaly' in kinds or 'literature_tension' in kinds
                has_candidate='novel_candidate' in kinds
                # No permite que un problema de medida gane por "rareza".
                priority=0.0 if has_measurement and not has_physical else min(1.0, score/3.0)
                if has_physical: priority += 0.20
                if has_candidate: priority += 0.30
                priority=min(priority,1.0)
                ranked.append({
                    'analysis_id': ev.get('analysis_id'), 'row_id': row.get('row_id'),
                    'priority': float(priority), 'anomaly_score': score,
                    'kinds': kinds, 'state': 'CANDIDATE' if priority>=0.70 else ('PHYSICAL_TENSION' if priority>=0.40 else 'SCREENING')
                })
        ranked.sort(key=lambda x:(x['priority'],x['anomaly_score']), reverse=True)
        p['candidate_ranking']=ranked; self._write(p); return ranked

    def review(self, row_id, state, *, note="", reviewer="local"):
        if state not in DISCOVERY_STATES: raise ValueError(f"Estado no permitido: {state}")
        p=self.load(); item={'reviewed_utc':datetime.now(timezone.utc).isoformat(),'row_id':row_id,'state':state,'reviewer':reviewer,'note':str(note)}
        p.setdefault('candidates',[]).append(item); self._write(p); return item

    def _write(self, data):
        atomic_json_dump(data,self.path)


def build_discovery_record(payload, *, ai_result=None, project_id=""):
    """Construye un registro científico comercializable, no un simple informe."""
    p=normalize_scientific_payload(payload)
    summary=p.get('summary') or {}
    anomalies=p.get('physical_anomalies') or physical_anomaly_engine(p.get('candidates',[]),target_name=summary.get('target_name',''))
    qc=p.get('qc_summary') or generate_qc_summary(p)
    states=[]
    for row in anomalies.get('rows',[]):
        kinds={a.get('kind') for a in row.get('anomalies',[]) if isinstance(a,dict)}
        if 'measurement_issue' in kinds and not ({'field_anomaly','literature_tension'} & kinds):
            state='ARTIFACT_SUSPECTED'
        elif 'novel_candidate' in kinds:
            state='CANDIDATE'
        elif {'field_anomaly','literature_tension'} & kinds:
            state='PHYSICAL_TENSION'
        else:
            state='SCREENING'
        states.append({'row_id':row.get('row_id'),'state':state,'anomaly_score':row.get('anomaly_score',0.0),'evidence':row.get('anomalies',[])})
    return {
        'product_schema_version': PRODUCT_SCHEMA_VERSION,
        'software_version': __version__,
        'project_id': project_id,
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'object': {'name':summary.get('target_name',''),'classification':summary.get('object_type','')},
        'quality': qc,
        'physical_anomalies': anomalies,
        'ai': ai_result or {'state':'NO EJECUTADA','note':'La inferencia IA no es requisito para analizar anomalías físicas'},
        'candidate_states': states,
        'scientific_policy': {
            'human_verification_required': True,
            'measurement_issues_excluded_from_discovery_claims': True,
            'no_discovery_claim_without_independent_evidence': True,
            'provenance_required': True,
        }
    }



# ====================================================================
# v42: MOTOR DE COMPETICIÓN DE MODELOS FÍSICOS
# ====================================================================
# Esta capa compara hipótesis explícitas contra observables e incertidumbres
# independientes. No llama a una discrepancia "descubrimiento" por sí sola.
# AICc/BIC se usan para selección relativa; la evidencia bayesiana sólo se
# reporta cuando se dispone de priors y la aproximación de Laplace es válida.
MODEL_ENGINE_VERSION = "2.0"

@dataclass
class ModelParameter:
    name: str
    value: float
    lower: float
    upper: float
    unit: str = ""

@dataclass
class PhysicalHypothesis:
    model_id: str
    family: str
    parameter_names: list
    forward: Any
    bounds: list
    validated: bool = True
    assumptions: list = field(default_factory=list)
    required_observables: list = field(default_factory=list)
    prior_bounds: Optional[list] = None
    notes: str = ""

class ModelComparisonEngine:
    """Comparación de hipótesis con likelihood gaussiana explícita.

    Entrada canónica:
      x: ndarray de coordenadas/condiciones
      y: ndarray de observables
      sigma: ndarray de incertidumbres 1-sigma

    Reglas científicas:
      * no se ajustan NaN/Inf;
      * sigma <= 0 invalida la observación;
      * todos los modelos deben declarar supuestos y bounds;
      * un modelo no validado no puede ganar la clasificación científica;
      * AICc/BIC son criterios relativos, no probabilidades de modelo;
      * la evidencia Laplace se marca como aproximación, nunca como exacta.
    """
    def __init__(self, seed=20260915):
        self.seed=int(seed)
        self._models={}

    def register(self, hypothesis: PhysicalHypothesis):
        if not hypothesis.model_id or not callable(hypothesis.forward):
            raise ValueError("Hipótesis inválida")
        if len(hypothesis.parameter_names)!=len(hypothesis.bounds):
            raise ValueError("parameter_names y bounds deben tener la misma longitud")
        checked=[]
        for b in hypothesis.bounds:
            if len(b)!=2 or not all(math.isfinite(float(z)) for z in b) or not float(b[0])<float(b[1]):
                raise ValueError("Bounds inválidos")
            checked.append((float(b[0]),float(b[1])))
        hypothesis.bounds=checked
        self._models[hypothesis.model_id]=hypothesis
        return hypothesis.model_id

    def available(self):
        return json_sanitize({k:{
            "family":m.family,"validated":bool(m.validated),
            "parameters":m.parameter_names,"bounds":m.bounds,
            "required_observables":m.required_observables,
            "has_explicit_priors":m.prior_bounds is not None,
            "assumptions":m.assumptions,"notes":m.notes}
            for k,m in self._models.items()})

    @staticmethod
    def _prepare(x,y,sigma):
        x=np.asarray(x,dtype=float); y=np.asarray(y,dtype=float); sigma=np.asarray(sigma,dtype=float)
        if x.shape[0]!=y.shape[0] or y.shape[0]!=sigma.shape[0]:
            raise ValueError("x, y y sigma deben tener igual longitud")
        mask=np.isfinite(x) & np.isfinite(y) & np.isfinite(sigma) & (sigma>0)
        if int(mask.sum())<2:
            raise ValueError("Se necesitan al menos 2 observaciones válidas")
        return x[mask],y[mask],sigma[mask],mask

    @staticmethod
    def _loglike(residuals, sigma):
        sigma=np.asarray(sigma,dtype=float)
        return float(-0.5*np.sum(residuals**2 + np.log(2*np.pi*sigma*sigma)))

    @staticmethod
    def _criteria(loglike,k,n):
        aic=2*k-2*loglike
        if n-k-1>0:
            aicc=aic + (2*k*(k+1))/(n-k-1)
        else:
            aicc=float('inf')
        bic=k*math.log(max(n,1))-2*loglike
        return float(aic),float(aicc),float(bic)

    def fit(self, model_id, x, y, sigma, *, initial=None):
        if model_id not in self._models:
            raise KeyError(f"Modelo no registrado: {model_id}")
        m=self._models[model_id]
        if not m.validated:
            return {"model_id":model_id,"state":"NO DISPONIBLE","reason":"modelo no validado científicamente"}
        x,y,sigma,mask=self._prepare(x,y,sigma)
        bounds=np.asarray(m.bounds,dtype=float).T
        k=len(m.parameter_names); n=len(y)
        if n<=k+1:
            return {"model_id":model_id,"state":"NO DISPONIBLE","reason":"n observaciones insuficiente para el número de parámetros"}
        if initial is None:
            initial=np.mean(bounds,axis=0)
        initial=np.asarray(initial,dtype=float)
        if initial.size!=k or np.any(initial<=bounds[0]) or np.any(initial>=bounds[1]):
            initial=np.clip(initial,bounds[0]+1e-8*(bounds[1]-bounds[0]),bounds[1]-1e-8*(bounds[1]-bounds[0]))
        def resid(theta):
            pred=np.asarray(m.forward(x,theta),dtype=float)
            if pred.shape!=y.shape or not np.all(np.isfinite(pred)):
                return np.full_like(y,1e12,dtype=float)
            return (y-pred)/sigma
        sol=optimize.least_squares(resid,initial,bounds=(bounds[0],bounds[1]),method="trf",x_scale="jac")
        r=resid(sol.x)
        chi2=float(np.sum(r*r)); dof=int(n-k)
        loglike=self._loglike(r,sigma)
        aic,aicc,bic=self._criteria(loglike,k,n)
        cov=None; condition=float('inf'); cov_state="NO DISPONIBLE"
        fisher_cov=None
        try:
            j=np.asarray(sol.jac,dtype=float)
            s=np.linalg.svd(j,compute_uv=False)
            if len(s) and s[-1]>0:
                condition=float(s[0]/s[-1])
            jt=j.T@j
            if np.linalg.matrix_rank(jt)==k and dof>0:
                fisher_cov=np.linalg.pinv(jt)
                # Covarianza MLE local: sigma es conocida y ya entra en los pesos.
                cov=fisher_cov
                cov_state="GAUSSIANA_LOCAL"
        except (ValueError,np.linalg.LinAlgError,TypeError,OverflowError):
            LOG.debug("No se pudo estimar covarianza para %s",model_id,exc_info=True)
        errors=[math.sqrt(max(float(cov[i,i]),0.0)) if cov is not None else float('nan') for i in range(k)]
        lag1=float(np.corrcoef(r[:-1],r[1:])[0,1]) if len(r)>2 and np.std(r[:-1])>0 and np.std(r[1:])>0 else float('nan')
        frac3=float(np.mean(np.abs(r)>3.0)) if len(r) else float('nan')
        pvals={name:{"value":float(val),"error":float(err),"unit":"","at_bound":bool(abs(val-lo)<1e-7 or abs(val-hi)<1e-7)} for name,val,err,(lo,hi) in zip(m.parameter_names,sol.x,errors,m.bounds)}
        # Evidencia bayesiana sólo se calcula si el modelo declara priors finitos
        # independientes de los bounds de optimización. Evitamos convertir bounds
        # numéricos arbitrarios en una probabilidad de modelo.
        logz=None; evidence_state="NO DISPONIBLE"
        prior_bounds=m.prior_bounds
        if prior_bounds is not None and cov is not None and math.isfinite(condition) and condition<1e8 and not any(bool(p.get("at_bound")) for p in pvals.values()):
            try:
                prior_volume=1.0
                for lo,hi in prior_bounds:
                    if not (math.isfinite(float(lo)) and math.isfinite(float(hi)) and float(hi)>float(lo)):
                        raise ValueError("prior_bounds inválidos")
                    prior_volume*=float(hi-lo)
                logdet=np.linalg.slogdet(np.linalg.pinv(cov))[1]
                logprior=-math.log(prior_volume)
                logz=float(loglike + 0.5*k*math.log(2*math.pi) - 0.5*logdet + logprior)
                evidence_state="LAPLACE_APROXIMADA"
            except (ValueError,np.linalg.LinAlgError,TypeError,OverflowError):
                LOG.debug("Evidencia Laplace no disponible para %s",model_id,exc_info=True)
        return {
            "model_id":model_id,"family":m.family,"state":"AJUSTADO","validated":True,
            "n_observations":n,"n_parameters":k,"degrees_of_freedom":dof,
            "chi2":chi2,"reduced_chi2":float(chi2/dof),"log_likelihood":loglike,
            "residual_rms_standardized":float(np.sqrt(np.mean(r*r))),
            "residual_mean_standardized":float(np.mean(r)),"max_abs_residual_standardized":float(np.max(np.abs(r))),
            "fraction_abs_residual_gt3sigma":frac3,"residual_lag1_autocorrelation":lag1,
            "aic":aic,"aicc":aicc,"bic":bic,"log_evidence":logz,
            "evidence_state":evidence_state,"parameters":pvals,
            "condition_number":condition,"covariance_state":cov_state,
            "optimizer":{"success":bool(sol.success),"status":int(sol.status),"message":str(sol.message)},
            "assumptions":m.assumptions,"notes":m.notes,
            "mask_n_valid":int(mask.sum()),"mask_n_total":int(mask.size)
        }

    def compare(self, x,y,sigma,model_ids=None):
        mids=list(model_ids) if model_ids is not None else list(self._models)
        fits=[]
        failures=[]
        for mid in mids:
            try:
                fit=self.fit(mid,x,y,sigma)
                if fit.get("state")=="AJUSTADO": fits.append(fit)
                else: failures.append(fit)
            except (KeyError,ValueError,TypeError,OverflowError) as exc:
                failures.append({"model_id":mid,"state":"NO DISPONIBLE","reason":f"{type(exc).__name__}: {exc}"})
        if not fits:
            return {"engine_version":MODEL_ENGINE_VERSION,"state":"NO DISPONIBLE","fits":[],"failures":failures}
        best_bic=min(fits,key=lambda z:z["bic"]) ; best_aicc=min(fits,key=lambda z:z["aicc"])
        minbic=float(best_bic["bic"]); minaicc=float(best_aicc["aicc"])
        for f in fits:
            f["delta_bic"]=float(f["bic"]-minbic)
            f["delta_aicc"]=float(f["aicc"]-minaicc)
            f["bic_weight"]=float(math.exp(-0.5*min(700.0,f["delta_bic"])))
        norm=sum(f["bic_weight"] for f in fits) or 1.0
        for f in fits: f["bic_weight"]/=norm
        ranked=sorted(fits,key=lambda z:z["bic"])
        # Interpretación prudente: ΔBIC es soporte relativo, no una probabilidad absoluta.
        for f in ranked:
            db=f["delta_bic"]
            f["selection_support"]=("FUERTE" if db<2 else ("MODERADO" if db<6 else ("BAJO" if db<10 else "MUY_BAJO")))
        best=ranked[0]
        structured_residual = (math.isfinite(finite(best.get("residual_lag1_autocorrelation"),float('nan'))) and abs(float(best.get("residual_lag1_autocorrelation")))>=0.25)
        poor_fit = math.isfinite(finite(best.get("reduced_chi2"),float('nan'))) and float(best.get("reduced_chi2"))>2.0
        model_discrepancy = bool(poor_fit or (structured_residual and finite(best.get("residual_rms_standardized"),0.0)>1.25))
        return {"engine_version":MODEL_ENGINE_VERSION,"state":"OK","n_models":len(fits),
                "model_discrepancy":{"flag":model_discrepancy,"reason":("best model has poor residual agreement or structured residuals" if model_discrepancy else "no strong global discrepancy detected"),"requires_independent_evidence":True},
                "best_model_bic":ranked[0]["model_id"],"best_model_aicc":best_aicc["model_id"],
                "models":ranked,"failures":failures,
                "interpretation":{"bic_weight":"peso relativo aproximado entre los modelos comparados; no es probabilidad posterior sin priors/evidencia completa",
                                  "aicc":"preferible para muestras pequeñas/medianas frente a AIC simple",
                                  "discovery_rule":"una discrepancia de modelo requiere evidencia independiente; el mejor BIC no constituye descubrimiento"}}


def build_default_model_comparison_engine():
    eng=ModelComparisonEngine()
    # Modelos fenomenológicos de control: sirven para averiguar si existe
    # estructura espacial más compleja, sin atribuirla todavía a una física concreta.
    eng.register(PhysicalHypothesis("constant", "phenomenological", ["c"], lambda x,t: np.full_like(np.asarray(x,float),t[0],dtype=float), [(-1e9,1e9)], assumptions=["campo constante"], notes="Modelo nulo; no implica una naturaleza física."))
    eng.register(PhysicalHypothesis("linear", "phenomenological", ["c","m"], lambda x,t: t[0]+t[1]*np.asarray(x,float), [(-1e9,1e9),(-1e6,1e6)], assumptions=["gradiente lineal"], notes="Modelo de gradiente; sirve para separar estructura espacial de ruido."))
    eng.register(PhysicalHypothesis("quadratic", "phenomenological", ["c","m","q"], lambda x,t: t[0]+t[1]*np.asarray(x,float)+t[2]*np.asarray(x,float)**2, [(-1e9,1e9),(-1e6,1e6),(-1e6,1e6)], assumptions=["gradiente cuadrático"], notes="Control de curvatura; no constituye un modelo astrofísico por sí mismo."))
    return eng


def compare_physical_models_from_catalog(payload, *, model_ids=None):
    """Entrada JSON científica independiente del pipeline de imágenes.

    Formato mínimo:
      {"model_data":{"x":[...],"y":[...],"sigma":[...]}}
    """
    if not isinstance(payload,dict): raise ValueError("El catálogo debe ser un objeto JSON")
    md=payload.get("model_data") or {}
    x=md.get("x"); y=md.get("y"); sigma=md.get("sigma")
    if x is None or y is None or sigma is None: raise ValueError("Falta model_data.x/y/sigma")
    eng=build_default_model_comparison_engine()
    return eng.compare(x,y,sigma,model_ids=model_ids)

def _v45_regression_tests():
    """Regresiones v45: validación de calibración, seguridad IA, grid trust y anomalías."""
    import ast
    tree=ast.parse(Path(__file__).read_text(encoding="utf-8"))
    assigns=[n for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="analyze_pair" for t in n.targets)]
    assert not any(isinstance(n.value,ast.Name) and n.value.id=="analyze_pair_with_consistency" for n in assigns)
    q=quality_gated_median([{"x":1,"snr_pix":5},{"x":2,"snr_pix":1}],"x",4); assert q["min_snr_applied"]==4.0 and "sufficient_data" in q
    cal,_,ok=calibrate_from_filters(FILTER_DEFAULT,FILTER_DEFAULT,120,120,photometric_calibrated=True)
    assert not ok and not cal.calibrated
    # Curvas artificiales con hash válido + zeropoint documentado deben poder validar.
    curve=FilterTransmission(name="v45-test",wavelength_nm=np.array([490.,495.9,500.7,650.,654.8,656.3,658.4,660.,670.]),transmission=np.array([0.5,0.7,0.9,0.2,0.5,0.9,0.6,0.5,0.2]),source_type="usuario_supplied",source_file="v45-test",sha256=hashlib.sha256(b"v45-test").hexdigest(),approximate=False)
    cal2,_,ok2=calibrate_from_filters(FILTER_DEFAULT,FILTER_DEFAULT,120,120,oiii_curve=curve,ha_curve=curve,photometric_calibrated=True,zeropoint_source="STD-A",zeropoint_error_mag=0.03,calibration_id="CAL-001")
    assert ok2 and cal2.calibrated
    sc=check_scientific_consistency({"candidates":[{"id":1,"ratio":2.0,"v_kms":300.0,"candidate_type":"shock"}],"summary":{"calibration":{"calibrated":False},"registration":{}},"manifest":{"grid":{"validation_status":"untrusted_external_grid","sha256":"x"}}})
    assert any(i.get("category")=="velocity" for i in sc.issues)
    rows=[]
    for i in range(12): rows.append({"id":i,"x":float(i),"y":0.0,"ratio":1.0+0.1*i,"peak_snr_ha":10.0,"peak_snr_oiii":10.0})
    aa=physical_anomaly_engine(rows,z_threshold=5); assert aa["state"]=="ACTIVA" and aa["baseline"]["ratio"]["method"] in {"robust_field","spatial_plane"}
    b=physical_discovery_bundle({"candidates":[{"id":1,"physical_anomaly_score":0.8,"model_tension":1.0,"literature_tension":2.0,"visual_novelty_score":0.7}]})
    assert b["rows"] and "priority_components" in b["rows"][0]
    # Persistencia: no debe haber import de pickle; torch debe cargar sólo pesos.
    for node in ast.walk(tree):
        if isinstance(node,ast.Import):
            assert all(a.name.split(".")[0] != "pickle" for a in node.names)
        elif isinstance(node,ast.ImportFrom):
            assert node.module != "pickle"
    if HAS_TORCH:
        safe_loads=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and node.func.value.id=="torch" and node.func.attr=="load":
                safe_loads.append(any(isinstance(k,ast.keyword) and k.arg=="weights_only" and isinstance(k.value,ast.Constant) and k.value.value is True for k in node.keywords))
        assert safe_loads and all(safe_loads)
    return True

def _v44_regression_tests():
    return _v45_regression_tests()



# ====================================================================
# v46: HIGH-END DISCOVERY / PHYSICAL CONSISTENCY ENGINES
# ====================================================================
DISCOVERY_ENGINE_VERSION = "2.0"


def _safe_array(values, dtype=float):
    a=np.asarray(values, dtype=dtype).ravel()
    return a


def _weighted_linear_fit(x, y, sigma):
    """Weighted straight-line fit with explicit covariance and diagnostics."""
    x=_safe_array(x); y=_safe_array(y); sigma=np.maximum(np.abs(_safe_array(sigma)), 1e-15)
    m=np.isfinite(x)&np.isfinite(y)&np.isfinite(sigma)&(sigma>0)
    x=x[m]; y=y[m]; sigma=sigma[m]
    if x.size<2:
        raise ValueError("Se requieren al menos dos observaciones válidas")
    X=np.column_stack([np.ones(x.size), x])
    w=1.0/(sigma*sigma)
    A=X.T@(X*w[:,None])
    b=X.T@(w*y)
    cov=np.linalg.pinv(A)
    beta=cov@b
    resid=(y-X@beta)/sigma
    chi2=float(np.sum(resid*resid))
    dof=max(1,x.size-2)
    return {"intercept":float(beta[0]),"slope":float(beta[1]),
            "intercept_err":float(math.sqrt(max(cov[0,0],0))),
            "slope_err":float(math.sqrt(max(cov[1,1],0))),
            "chi2":chi2,"reduced_chi2":float(chi2/dof),
            "n":int(x.size),"covariance":cov.tolist(),"residuals_standardized":resid.tolist()}


def _normal_two_sided_p(z):
    z=abs(float(z))
    return float(math.erfc(z/math.sqrt(2.0)))


def _benjamini_hochberg(pvals, alpha=0.01):
    """Benjamini-Hochberg FDR correction; returns q-values and reject flags."""
    p=np.asarray(pvals,dtype=float)
    n=p.size
    q=np.full(n,np.nan,dtype=float); reject=np.zeros(n,dtype=bool)
    finite=np.isfinite(p)
    idx=np.where(finite)[0]
    if idx.size==0: return q.tolist(), reject.tolist()
    order=idx[np.argsort(p[idx])]
    ranked=p[order]
    raw=ranked*n/np.arange(1,ranked.size+1,dtype=float)
    adj=np.minimum.accumulate(raw[::-1])[::-1]
    q[order]=np.clip(adj,0,1)
    ok=np.where(q[order]<=float(alpha))[0]
    if ok.size:
        k=ok.max(); reject[order[:k+1]]=True
    return q.tolist(), reject.tolist()


class PhysicalConstraintEngine:
    """Busca incompatibilidades entre parámetros relacionados por física básica.

    Nunca convierte una incompatibilidad en descubrimiento. Devuelve restricciones,
    z/tensión y los supuestos que permiten interpretar el resultado.
    """
    def __init__(self, min_sigma=4.0):
        self.min_sigma=float(min_sigma)

    def evaluate(self, row, estimates):
        r=dict(row or {}); p=dict(estimates or {}); issues=[]
        def par(name):
            d=p.get(name,{})
            v=finite(d.get("value"),float('nan')); e=abs(finite(d.get("error"),float('nan')))
            return v,e
        # Kinematic age consistency: age = 0.4 R/v in the uniform Sedov self-similar case.
        R,Re=par("radius_pc"); v,ve=par("velocity_kms"); age,agee=par("age_yr")
        if all(math.isfinite(q) for q in (R,v,age)) and R>0 and v>0:
            pred=0.4*R*3.0856775814913673e13/(v*1e3)/(365.25*86400.0)
            pred_err=abs(pred)*math.sqrt((Re/R)**2+(ve/v)**2) if math.isfinite(Re) and Re>0 and math.isfinite(ve) and ve>0 else float('nan')
            den=math.sqrt(max(0.0,pred_err**2)+(agee**2 if math.isfinite(agee) and agee>0 else 0.0))
            z=(age-pred)/den if den>0 else float('nan')
            issues.append({"constraint":"Sedov age-radius-velocity","observed_age_yr":age,"predicted_age_yr":pred,
                           "z_score":float(z) if math.isfinite(z) else None,
                           "flag":bool(math.isfinite(z) and abs(z)>=self.min_sigma),
                           "assumptions":["spherical","adiabatic","uniform_medium","self_similar_eta=0.4"]})
        # Strong shock consistency: T ~= (3/16) mu mp v^2 / kB for gamma=5/3.
        T,Te=par("postshock_temperature_K")
        if math.isfinite(v) and math.isfinite(T) and v>0 and T>0:
            kB=1.380649e-23; mp=1.67262192369e-27; mu=0.61
            pred=(3.0/16.0)*mu*mp*(v*1e3)**2/kB
            pe=abs(pred*2*ve/v) if math.isfinite(ve) and ve>0 else float('nan')
            den=math.sqrt(max(0.0,pe**2)+(Te**2 if math.isfinite(Te) and Te>0 else 0.0))
            z=(T-pred)/den if den>0 else float('nan')
            issues.append({"constraint":"Strong-shock T-v","observed_temperature_K":T,"predicted_temperature_K":pred,
                           "z_score":float(z) if math.isfinite(z) else None,
                           "flag":bool(math.isfinite(z) and abs(z)>=self.min_sigma),
                           "assumptions":["gamma=5/3","mu=0.61","fully_ionized","strong_shock"]})
        # Ratio sanity; negative or non-finite flux-derived ratios are measurement issues.
        ratio=_get_float(r,"ratio","oiii_ha_ratio")
        if math.isfinite(ratio) and ratio<=0:
            issues.append({"constraint":"positive emission-line ratio","flag":True,"classification":"measurement_issue"})
        return {"engine_version":"1.0","issues":issues,
                "n_physical_tensions":sum(bool(i.get("flag")) and i.get("classification")!="measurement_issue" for i in issues),
                "n_measurement_issues":sum(i.get("classification")=="measurement_issue" for i in issues),
                "threshold_sigma":self.min_sigma}


class SpatialTrendAnomalyEngine:
    """Detecta residuales espaciales tras quitar una tendencia de primer orden.

    La mediana del propio campo NO se usa como único baseline cuando existe
    información espacial suficiente. Los q-values son FDR-corregidos.
    """
    def __init__(self, z_threshold=4.0, fdr_alpha=0.01, min_points=8):
        self.z_threshold=float(z_threshold); self.fdr_alpha=float(fdr_alpha); self.min_points=int(min_points)

    def analyze(self, rows, parameter_keys=None):
        rows=[dict(r) for r in (rows or [])]
        if not rows: return {"engine_version":"1.0","state":"NO DATA","results":[],"parameters":{}}
        keys=list(parameter_keys or [])
        if not keys:
            blocked={"id","x","y","row_id","profile_key","candidate_type","status"}
            candidates=set()
            for r in rows:
                for k,v in r.items():
                    if k in blocked or k.endswith("_err") or isinstance(v,bool): continue
                    try:
                        if math.isfinite(float(v)): candidates.add(k)
                    except (TypeError,ValueError):
                        continue
            keys=sorted(candidates)
        out=[]
        for key in keys:
            pts=[]
            for r in rows:
                try:
                    x=float(r.get("x",r.get("x_px",float('nan')))); y=float(r.get("y",r.get("y_px",float('nan')))); v=float(r.get(key,float('nan')))
                    e=abs(float(r.get(f"{key}_err",float('nan'))))
                except (TypeError,ValueError): continue
                if all(math.isfinite(q) for q in (x,y,v)):
                    pts.append((x,y,v,e))
            if len(pts)<self.min_points: continue
            a=np.asarray(pts,float); x=a[:,0]; y=a[:,1]; v=a[:,2];
            e=a[:,3]; finite_err=np.isfinite(e)&(e>0)
            scale0=robust_stats(v)[1]
            if not math.isfinite(scale0) or scale0<=0: scale0=max(float(np.std(v)),1e-12)
            # Plane fit if possible; otherwise robust center only.
            X=np.column_stack([np.ones(len(v)),x-x.mean(),y-y.mean()])
            w=np.ones(len(v)); w[finite_err]=1.0/np.maximum(e[finite_err],1e-12)**2
            try:
                cov=np.linalg.pinv(X.T@(X*w[:,None])); beta=cov@(X.T@(w*v)); pred=X@beta
                resid=v-pred; baseline="spatial_plane"
            except (np.linalg.LinAlgError,ValueError):
                pred=np.full_like(v,float(np.median(v))); resid=v-pred; baseline="robust_median"
            loc=robust_stats(resid)[1]
            if not math.isfinite(loc) or loc<=0: loc=max(float(np.std(resid)),1e-12)
            z=resid/loc
            p=np.asarray([_normal_two_sided_p(q) for q in z],float)
            q,reject=_benjamini_hochberg(p,self.fdr_alpha)
            # Keep point-to-row mapping exact.
            valid_rows=[]
            for r in rows:
                try:
                    x0=float(r.get("x",r.get("x_px",float('nan')))); y0=float(r.get("y",r.get("y_px",float('nan')))); v0=float(r.get(key,float('nan')))
                except (TypeError,ValueError): continue
                if all(math.isfinite(q0) for q0 in (x0,y0,v0)): valid_rows.append(r)
            for idx,r in enumerate(valid_rows):
                out.append({"parameter":key,"row_id":r.get("row_id",r.get("id",idx)),"value":float(v[idx]),
                            "baseline":float(pred[idx]),"residual":float(resid[idx]),"z_score":float(z[idx]),
                            "p_value":float(p[idx]),"q_value":float(q[idx]),"fdr_reject":bool(reject[idx]),
                            "baseline_method":baseline,"candidate":bool(reject[idx] and abs(z[idx])>=self.z_threshold)})
        return {"engine_version":"1.0","state":"ACTIVE" if out else "NO DATA","results":out,
                "parameters":keys,"threshold_sigma":self.z_threshold,"fdr_alpha":self.fdr_alpha}


class TemporalChangeEngine:
    """Busca variabilidad/deriva en medidas multiepoch con errores explícitos."""
    def analyze(self, epochs, min_epochs=3, sigma_threshold=4.0):
        if not isinstance(epochs,list): raise ValueError("epochs debe ser una lista")
        pts=[]
        for e in epochs:
            if not isinstance(e,dict): continue
            try:
                t=float(e.get("time",e.get("epoch",float('nan')))); y=float(e.get("value",float('nan')))
            except (TypeError,ValueError): continue
            try: sy=abs(float(e.get("error",e.get("sigma",float('nan')))))
            except (TypeError,ValueError): sy=float('nan')
            if math.isfinite(t) and math.isfinite(y) and math.isfinite(sy) and sy>0: pts.append((t,y,sy))
        if len(pts)<min_epochs:
            return {"engine_version":"1.0","state":"NO DATA","reason":f"se requieren >= {min_epochs} épocas","n_epochs":len(pts)}
        a=np.asarray(pts,float); t=a[:,0]; y=a[:,1]; sy=a[:,2]
        w=1.0/(sy*sy); c=float(np.sum(w*y)/np.sum(w)); chi_const=float(np.sum(((y-c)/sy)**2)); dof=max(1,len(y)-1)
        fit=_weighted_linear_fit(t-t.mean(),y,sy)
        slope_z=fit["slope"]/fit["slope_err"] if fit["slope_err"]>0 else float('nan')
        return {"engine_version":"1.0","state":"ACTIVE","n_epochs":int(len(y)),
                "weighted_mean":c,"constant_chi2":chi_const,"constant_reduced_chi2":chi_const/dof,
                "linear_fit":fit,"slope_sigma":float(slope_z) if math.isfinite(slope_z) else None,
                "variable_candidate":bool((math.isfinite(slope_z) and abs(slope_z)>=sigma_threshold) or chi_const/dof>2.5),
                "threshold_sigma":float(sigma_threshold),
                "notes":["La variabilidad requiere repetición temporal y errores por época.","No se interpreta como variabilidad física sin descartar cambios instrumentales."]}


class DiscoveryEvidenceEngine:
    """Fusiona evidencias sin convertir scores heurísticos en probabilidades."""
    def __init__(self, sigma_threshold=4.0, fdr_alpha=0.01):
        self.sigma_threshold=float(sigma_threshold); self.fdr_alpha=float(fdr_alpha)
        self.constraints=PhysicalConstraintEngine(min_sigma=sigma_threshold)

    def evaluate_rows(self, rows, *, object_family="unknown", reference=None, ai_results=None):
        rows=[dict(r) for r in (rows or [])]
        raw=[]
        for idx,r in enumerate(rows):
            inf=infer_physical_parameters(r,object_family=object_family)
            constraints=self.constraints.evaluate(r,inf.get("parameters",{}))
            refs=build_reference_anomaly(r,inf.get("parameters",{}),reference=reference)
            phys=[c for c in constraints.get("issues",[]) if c.get("flag") and c.get("classification")!="measurement_issue"]
            ref_sig=[x for x in refs if abs(finite(x.get("z_score"),0))>=self.sigma_threshold]
            model=r.get("model_comparison") if isinstance(r.get("model_comparison"),dict) else None
            model_flag=bool(model and (model.get("model_discrepancy") or {}).get("flag"))
            ai=ai_results[idx] if isinstance(ai_results,list) and idx<len(ai_results) else None
            visual_flag=bool(isinstance(ai,dict) and ai.get("novelty_state") in {"OUTLIER","NOVEL"})
            tension_z=max([0.0]+[abs(finite(c.get("z_score"),0)) for c in phys]+[abs(finite(x.get("z_score"),0)) for x in ref_sig])
            components={"physical_constraint_sigma":float(min(tension_z/10.0,1.0)),"reference_sigma":float(min(max([0.0]+[abs(finite(x.get("z_score"),0))/10 for x in ref_sig]),1.0)),"model_discrepancy":1.0 if model_flag else 0.0,"visual_novelty":1.0 if visual_flag else 0.0}
            independent_count=sum([bool(phys),bool(ref_sig),model_flag,visual_flag])
            raw.append({"row_id":r.get("row_id",r.get("id",idx)),"inference":inf,"constraints":constraints,"reference_anomalies":refs,
                        "evidence_components":components,"independent_evidence_count":independent_count,
                        "measurement_issue":bool(constraints.get("n_measurement_issues",0)),"tension_sigma":tension_z})
        # A conservative priority index, explicitly not a probability.
        for rec in raw:
            rec["priority_index"]=float(0.35*rec["evidence_components"]["physical_constraint_sigma"]+
                                         0.25*rec["evidence_components"]["reference_sigma"]+
                                         0.20*rec["evidence_components"]["model_discrepancy"]+
                                         0.20*rec["evidence_components"]["visual_novelty"])
            rec["scientific_candidate_gate"]=bool(rec["independent_evidence_count"]>=2 and not rec["measurement_issue"] and rec["tension_sigma"]>=self.sigma_threshold)
        return {"engine_version":"1.0","state":"ACTIVE","rows":sorted(raw,key=lambda x:x["priority_index"],reverse=True),
                "policy":{"priority_index_is_not_probability":True,"human_verification_required":True,
                           "measurement_issues_excluded_from_discovery_claims":True,"minimum_independent_evidence":2}}


def discovery_v46(payload, *, object_family="unknown", reference=None, ai_results=None,
                   spatial_rows=None, temporal=None):
    """Producto principal v46: físico + restricciones + espacial + temporal + IA opcional."""
    p=normalize_scientific_payload(payload if isinstance(payload,dict) else {"candidates":payload})
    rows=p.get("candidates",[]) or p.get("results",[])
    engine=DiscoveryEvidenceEngine()
    base=engine.evaluate_rows(rows,object_family=object_family,reference=reference,ai_results=ai_results)
    if spatial_rows is not None:
        base["spatial_anomalies"]=SpatialTrendAnomalyEngine().analyze(spatial_rows)
    if temporal is not None:
        base["temporal_analysis"]=TemporalChangeEngine().analyze(temporal)
    base["product"]= "AstroPhysical Discovery Engine v46"
    base["interpretation"]="La suite busca discrepancias físicas, estadísticas y morfológicas; ningún índice constituye por sí mismo un descubrimiento."
    return base


def _v46_regression_tests():
    # Constraint engine: internally consistent Sedov relation should not be flagged.
    r={"radius_pc":1.0,"velocity_kms":100.0,"ratio":2.0}
    inf=infer_physical_parameters({"velocity_kms":100.0,"radius_pc":1.0,"distance_pc":1000},object_family="SNR")
    age=inf["parameters"]["age_yr"]["value"]
    r["age_yr"]=age; r["postshock_temperature_K"]=inf["parameters"]["postshock_temperature_K"]["value"]
    c=PhysicalConstraintEngine(min_sigma=4).evaluate(r,inf["parameters"])
    assert c["n_physical_tensions"]==0
    # Spatial gradient is removed before anomaly detection.
    rows=[]
    for i in range(12): rows.append({"id":i,"x":float(i),"y":0.0,"ratio":1+0.2*i})
    s=SpatialTrendAnomalyEngine(z_threshold=4).analyze(rows,parameter_keys=["ratio"])
    assert not any(x["candidate"] for x in s["results"])
    # Temporal linear trend and constant data both behave sensibly.
    epochs=[{"time":0,"value":1.0,"error":0.05},{"time":1,"value":1.2,"error":0.05},{"time":2,"value":1.4,"error":0.05}]
    t=TemporalChangeEngine().analyze(epochs); assert t["state"]=="ACTIVE" and t["variable_candidate"]
    d=discovery_v46({"candidates":[r]}); assert d["rows"] and "evidence_components" in d["rows"][0]
    return True

if __name__ == "__main__":
    sys.exit(main())
