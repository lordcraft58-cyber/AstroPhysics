"""Fase 4: `FilamentDetectionStrategy` deja de ser solo documentación --
se vuelve un contrato verificable en tiempo de ejecución
(`@runtime_checkable`). Este test falla si alguna de las dos estrategias
reales deja de cumplir la firma `detect(self, image, variance, masks,
config)`, o si el Protocol pierde `@runtime_checkable` en una edición
futura.

Contexto: docs/audit/03-MAPEO-DEPENDENCIAS-Y-CONTRATOS.md, seccion 1.3.
"""
from __future__ import annotations


def test_hessian_and_canny_strategies_satisfy_the_protocol(aps):
    assert isinstance(aps.HessianFilamentStrategy(), aps.FilamentDetectionStrategy)
    assert isinstance(aps.CannyFilamentStrategy(), aps.FilamentDetectionStrategy)


def test_an_unrelated_object_does_not_satisfy_the_protocol(aps):
    class NotAStrategy:
        pass

    assert not isinstance(NotAStrategy(), aps.FilamentDetectionStrategy)
