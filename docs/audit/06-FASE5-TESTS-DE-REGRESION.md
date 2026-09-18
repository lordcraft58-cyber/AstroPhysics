# AstroPhysics Suite — Fase 5: Tests de Regresión

Continuación de `05-FASE4-CONTRATOS-DE-DATOS.md`. Esta fase cierra los pendientes explícitos que las Fases 3 y 4 dejaron anotados para "Fase 5", añade las guardas estructurales que el encargo original pidió literalmente, y conecta por primera vez la suite completa a CI.

**Hallazgo más importante de esta fase: al escribir la primera prueba de humo real de la GUI, se descubrió que `launch_gui()` no arrancaba en absoluto.** No es un defecto teórico encontrado leyendo código -- es un defecto que solo se hizo visible al ejecutar la GUI de verdad por primera vez en todo este proceso de auditoría. Se corrige en esta misma fase (§1).

## 1. `launch_gui()` no construía la ventana — encontrado y corregido

Al escribir `tests/regression/test_gui_smoke.py` y ejecutarlo contra un display real (Xvfb), `launch_gui()` lanzaba:

```
KeyError: 'discovery_snr'
```

al construir la barra de controles del panel "Discovery Workspace". Investigado: el diccionario `v` de variables Tkinter (L11076 aprox.) nunca definía las claves `discovery_snr` ni `discovery_max`, pese a que **dos** puntos distintos del código las leían (`v["discovery_snr"].get()` y `v["discovery_max"].get()`, en el worker de escaneo y en la construcción del panel respectivamente). No es lo mismo que `v["snr"]`/`v["maxc"]` -- esas dos sí existen y son los controles del panel de análisis de par OIII/Hα, un control legítimamente distinto del panel Discovery Workspace; confundirlos habría sido un error nuevo, no una corrección.

**Corrección:** se añadieron las dos claves faltantes al diccionario `v`, con los mismos valores por defecto que ya usaba el código como *fallback* (`v["discovery_snr"].get() or 5` → `"5"`; `v["discovery_max"].get() or 2000` → `"2000"`).

**Severidad:** esto es, en la práctica, más grave que el hallazgo P0 de la Fase 1 (el archivo no parseaba en Python <3.12): aquel afectaba solo a builds con un intérprete antiguo; este impedía que la GUI arrancara **en cualquier versión de Python**, incluida la de desarrollo. Ningún test anterior a esta fase construía la ventana completa -- `selftest()` (Fase 1-3) nunca invoca `launch_gui`, y no existía ninguna otra ruta de verificación. Es la prueba más directa, en todo este proceso, de por qué el encargo pedía explícitamente pruebas de humo de GUI: una lectura de código, por cuidadosa que sea, no sustituye ejecutar el código.

## 2. Prueba de humo de GUI (`tests/regression/test_gui_smoke.py`)

`launch_gui()` no tenía forma de probarse sin bloquear en `root.mainloop()`: el parámetro `_test_hook` sigue en la firma pero ya no se usa en ningún punto del cuerpo de la función (residuo de cuando existía en la GUI legacy, eliminada en la Fase 3). En vez de reintroducir ese parámetro, el test parchea `tkinter.Tk.mainloop` a una función que registra la llamada y cierra la ventana inmediatamente (`monkeypatch.setattr`) -- una técnica estándar de smoke-testing de GUI que no requiere tocar el código de producción.

El test requiere `tkinter` instalado y un display X (real o Xvfb) disponible; si no lo hay, se salta explícitamente con una razón clara (`pytest.importorskip` + comprobación de `tk.Tk()`) en vez de fallar por una causa ajena al código. Verificado en este entorno instalando `python3-tk` + `Xvfb` y ejecutando contra un intérprete Python 3.12 con tkinter real: **pasa**.

Se añadió también `test_launch_gui_is_the_only_public_gui_entry_point`, que enumera todas las funciones `launch_gui*` de nivel de módulo y exige que sea exactamente una -- la guarda permanente contra que vuelva a aparecer un segundo lanzador de GUI (el patrón de la Fase 1, `launch_gui` vs. `launch_gui_legacy`).

## 3. Guardas estructurales pedidas explícitamente por el encargo

### 3.1 Una sola implementación por función crítica

`tests/architecture/test_single_implementation.py`: dieciséis nombres de API pública crítica (`main`, `launch_gui`, `selftest`, `analyze_pair`, `analyze_pair_core`, `detect_point_sources`, `detect_discovery_sources`, `resolve_object_center`, `estimate_background`, `measure_proper_motion`, `stack_multiband`, `select_optimal_profile_candidates`, etc.) deben tener exactamente una definición de nivel de módulo. A diferencia de `test_dead_code.py` (Fase 3, que guarda contra la reaparición de nombres ya eliminados), este test guarda de forma general: protege incluso contra una duplicación *nueva*, hecha de buena fe por alguien que no sepa que el nombre ya existe.

### 3.2 La GUI debe usar el pipeline científico completo

Esto es una cita casi literal del encargo original. Hoy es **falso**: la Fase 2 cuantificó 78 entidades vivas alcanzables desde `main()` y ninguna desde `launch_gui()`, incluyendo el motor físico, el de anomalías y el de evidencia completos.

`tests/architecture/test_gui_uses_full_pipeline.py` fija esto como un `xfail(strict=True)`: el test comprueba, mediante el mismo análisis de grafo de referencias de la Fase 2 (ahora productivizado en pytest en vez de vivir en un script de auditoría desechable), que `launch_gui()` alcanza `infer_physical_parameters`, `PhysicalConstraintEngine`, `SpatialTrendAnomalyEngine`, `TemporalChangeEngine` y `DiscoveryEvidenceEngine`. Falla hoy -- como se espera. El día que la Fase 7/8 conecte la GUI al pipeline unificado, este test empezará a "pasar inesperadamente" (XPASS) y, por ser `strict=True`, **eso romperá la CI** hasta que alguien quite el marcador `xfail` de forma consciente. A partir de ese momento deja de ser una foto del pendiente y pasa a ser una guarda permanente contra que la GUI vuelva a quedarse corta. No se seguirá pateando el problema en silencio: cada corrida de la suite lo recuerda.

### 3.3 Sin Tkinter fuera de la capa de presentación

`tests/architecture/test_no_gui_in_science_layer.py`: ningún archivo de `astrophysics_suite/` (la capa de ciencia objetivo construida en la Fase 4) puede importar `tkinter`. `gui/` todavía no existe (Fase 8); esta guarda cubre lo que sí existe hoy, para que la regla nunca se viole desde el primer módulo en vez de descubrirse tarde con docenas de archivos que limpiar.

### 3.4 Compatibilidad de versión de Python

Ya cubierto en la Fase 3 (`test_python_compatibility.py`); no se repite aquí.

## 4. CI: la suite se ejecuta sola por primera vez

Se añadió `.github/workflows/tests.yml`: matriz Python 3.11/3.12, instala `python3-tk` + `xvfb` vía `apt-get`, y corre `xvfb-run pytest tests/ -v` en cada push/PR. Es la respuesta directa al hallazgo repetido en las Fases 1 y 2 ("cero integración CI... todo el testing ocurre manualmente").

**Nota de honestidad:** no se ha podido verificar este workflow contra una ejecución real de GitHub Actions -- el acceso de escritura a GitHub sigue bloqueado (ver conversación) y no hay forma de disparar un run real desde aquí. Sí se verificó localmente, en este entorno, que la combinación `apt-get install python3-tk` + intérprete con tkinter + Xvfb permite ejecutar el smoke test de GUI de principio a fin (§2). Si el runner de GitHub Actions resultara no exponer `tkinter` al intérprete de `actions/setup-python` pese a la instalación de `python3-tk` (no debería, pero no se ha podido confirmar en vivo), el test de humo se saltaría con su razón explícita en vez de romper la CI -- el resto de la suite (65 de 66 tests) no depende de tkinter y no se vería afectado.

## 5. Estado final de la suite

66 tests: 65 pasan, 1 `xfail` (documentado, esperado, §3.2). Verificado en dos entornos reales distintos:

- Python 3.11.15 + numpy/scipy/astropy/photutils/matplotlib/openpyxl/pytest (sin tkinter): 63 passed, 1 skipped (smoke de GUI, sin tkinter), 1 xfailed.
- Python 3.12.3 + las mismas dependencias + tkinter + Xvfb: 65 passed, 1 xfailed.

```
tests/
├── conftest.py
├── architecture/
│   ├── test_dead_code.py                    # Fase 3
│   ├── test_gui_uses_full_pipeline.py        # Fase 5 -- xfail estricto, pendiente de Fase 7/8
│   ├── test_no_gui_in_science_layer.py       # Fase 5
│   └── test_single_implementation.py         # Fase 5
├── regression/
│   ├── test_analyze_series_consistency.py    # Fase 3
│   ├── test_embedded_selftest.py             # Fase 3
│   ├── test_filament_strategy_protocol.py    # Fase 4
│   ├── test_gui_smoke.py                     # Fase 5 -- encontró y verificó la corrección de §1
│   ├── test_historical_contracts.py          # Fase 3
│   └── test_python_compatibility.py          # Fase 3
└── unit/models/                              # Fase 4 (12 archivos)
```

## 6. Qué queda deliberadamente fuera de esta fase

- **Integración de extremo a extremo con los modelos nuevos** (`Observation → ... → Candidate` pasando por motores reales, no por el adaptador de una sola fila de la Fase 4): no tiene sentido construirla ya -- los motores todavía son funciones sueltas dentro del monolito, no paquetes con el contrato que `astrophysics_suite/models/` define. Es, explícitamente, el trabajo de la Fase 6.
- **Interacción real con widgets de la GUI** (clics, entradas de texto): el smoke test de esta fase confirma que la ventana se construye; probar que cada botón hace lo correcto es un nivel de prueba más caro que solo vale la pena una vez exista la GUI objetivo (Fase 8), no la heredada.
- **Validación científica adicional más allá de lo ya cubierto** por `selftest()` (conectado a CI desde la Fase 3) y los invariantes de `Quantity`/`PhysicalInference` (Fase 4): no se ha identificado ningún hueco nuevo que justifique más tests en esta fase concreta.
