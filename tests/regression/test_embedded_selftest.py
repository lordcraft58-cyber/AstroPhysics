"""Conecta la suite de regresión embebida (`selftest()`, con sus
`_v43_scientific_hardening`, `_v45_regression_tests` y `_v46_regression_tests`
internos -- ver docs/audit/01-AUDITORIA-TECNICA-FASE1.md, seccion 11) a
pytest/CI.

Antes de la Fase 3, la única forma de ejecutar esta suite era invocar
manualmente `python AstroPhysicsSuite_...py selftest` -- nada en un pipeline
de CI la ejecutaba nunca. Este test la ejecuta como parte de la suite
normal, para que una regresión futura la detecte automáticamente en vez de
depender de que alguien recuerde correrla a mano.

Se acepta una única falla conocida y preexistente (verificada en la Fase 3
contra el archivo SIN modificar: docs/audit/03-...): `load_fits` no
preserva el resultado como `np.memmap` en este entorno/versión de astropy.
No es una regresión introducida por la reingeniería; es candidata a
investigarse en la Fase 6 (rendimiento de lectura FITS) cuando se audite
`load_fits` en profundidad. Cualquier falla ADICIONAL a esa sí debe romper
este test.
"""
from __future__ import annotations

KNOWN_PREEXISTING_FAILURES = {
    "FITS 2D memmap preservado",
}


def test_embedded_selftest_suite(aps, capsys):
    # selftest() imprime "[OK ]"/"[FAIL] <name> <detail>" por cada check en
    # vez de devolver la lista estructurada; se captura vía stdout porque
    # cambiar su contrato de retorno es trabajo de la Fase 5 (portarla a
    # pytest de verdad), no de esta regresión puente.
    aps.selftest(verbose=True)
    captured = capsys.readouterr().out

    failures = []
    for line in captured.splitlines():
        if line.startswith("[FAIL]"):
            name = line[len("[FAIL]"):].strip()
            failures.append(name)

    unexpected = [f for f in failures if not any(f.startswith(known) for known in KNOWN_PREEXISTING_FAILURES)]
    assert not unexpected, (
        f"selftest() embebido reporta fallas nuevas no documentadas: {unexpected}\n"
        f"(fallas conocidas/aceptadas: {KNOWN_PREEXISTING_FAILURES})\n"
        f"Salida completa:\n{captured}"
    )
