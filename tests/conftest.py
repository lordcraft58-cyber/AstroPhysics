"""Puente de importación temporal hacia el módulo heredado.

Este conftest existe únicamente mientras el código científico vive en
``legacy/AstroPhysicsSuite_v57_3_COMMERCIAL.py`` (Fase 3-5 del plan de
reingeniería, ver docs/audit/). Cuando la Fase 6 extraiga los motores a
paquetes propios (detection/, physics/, evidence/, ...), estos tests deben
importar esos paquetes directamente y este puente debe desaparecer.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LEGACY_PATH = REPO_ROOT / "legacy" / "AstroPhysicsSuite_v57_3_COMMERCIAL.py"
LEGACY_MODULE_NAME = "aps_legacy"


def _import_legacy():
    spec = importlib.util.spec_from_file_location(LEGACY_MODULE_NAME, LEGACY_PATH)
    module = importlib.util.module_from_spec(spec)
    # dataclasses resuelve anotaciones vía sys.modules[cls.__module__]; el módulo
    # debe estar registrado ANTES de ejecutar su cuerpo, o falla en el primer @dataclass.
    sys.modules[LEGACY_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def aps():
    """El módulo AstroPhysics Suite heredado, importado una sola vez por sesión."""
    return _import_legacy()
