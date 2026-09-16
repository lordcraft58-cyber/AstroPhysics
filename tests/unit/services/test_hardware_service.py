from __future__ import annotations

import time

from services.hardware_service import HardwareCheckJob


def test_hardware_check_job_completes_and_degrades_gracefully_off_windows():
    """En Linux (este entorno de desarrollo) PowerShell no existe;
    check_hardware() ya está diseñado para degradarse con elegancia en
    vez de fallar (Fase 1, seccion 9) -- este test confirma que sigue
    siendo así también a través del wrapper asíncrono."""
    job = HardwareCheckJob()
    job.start()

    deadline = time.monotonic() + 10.0
    events = []
    while time.monotonic() < deadline:
        events.extend(job.poll())
        if events:
            break
        time.sleep(0.02)

    assert events, "el chequeo de hardware no terminó a tiempo"
    assert events[-1].kind == "done"
    assert "ok" in events[-1].report
