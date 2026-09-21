# 95 — Auditoría sistemática, motor 7/16: Photometry

Séptimo motor de la fase de cierre sistemático. Al igual que Detección
(informe 92), esta auditoría **no encontró ningún hallazgo que
corregir** -- el motor de Fotometría ya cumplía el checklist de 20
puntos, incluida su limitación más importante (PSF), que ya estaba
correctamente investigada, documentada y con su alcance real acotado
desde antes de esta fase.

## Mapa del motor (fase previa, sin tocar código)

**Motor científico**: `astrophysics_suite/photometry/{aperture,psf,
calibration,pyraf_backend}.py`. **GUI**: tres procesos reales en el
árbol de procesos genérico (`qt_app/processes/registry.py`):
`photometry.aperture` (apertura + curva de crecimiento opcional),
`photometry.zeropoint` (punto cero real contra Gaia), `photometry.psf`
(ajuste simultáneo/desmezclado, con o sin refinamiento de posición tipo
`allstar`, PSF Gaussiana/Moffat/empírica, diagnóstico de ajuste). Los
tres con selección a clic o detección automática, y editor de radio de
apertura arrastrable sobre la imagen.
**Tests**: `tests/unit/photometry/{test_aperture,test_psf,
test_photometric_calibration,test_photometry_pyraf_backend}.py` (47
passed, 4 skipped -- los 4 son pyraf real, no instalable en este
entorno). GUI: `test_qt_app_aperture_edit_smoke.py`,
`test_qt_app_zeropoint_smoke.py`, y los tests de PSF/apertura/detección
automática dentro de `test_qt_app_smoke.py`.

## Verificación (sin hallazgos que cerrar)

1. **`aperture.py`/`calibration.py`**: nativos desde su construcción,
   sin dependencia de legacy en ningún punto. Cobertura de apertura
   subpíxel exacta con submuestreo solo en el borde, cielo local robusto
   (MAD-clip por anillo, mismo criterio que el resto del proyecto),
   curva de crecimiento con radio óptimo real (máxima S/N medida, no
   extrapolada), punto cero por mediana robusta contra outliers reales
   (variables, cruces erróneos). Verificado con datos reales de M31 más
   abajo.
2. **`photometry.psf` sigue correctamente limitado al uso manual,
   como ya se decidió y documentó (informe 41, `docs/audit/
   41-INVESTIGACION-MOTOR-FOTOMETRIA-PSF-PENDIENTE.md`)**: se verificó
   con `grep` que `psf_flux`/`psf_fit_reduced_chi2` NO existen en
   `models/candidate.py` ni en `discovery/pipeline.py` -- el revert
   documentado en el informe 41 sigue intacto, ningún cambio posterior
   de la suite volvió a conectar el flujo PSF al pipeline automático de
   Candidatos. El motor científico (`fit_group_psf_photometry` y su
   variante con refinamiento de posición, PSF Gaussiana/Moffat/empírica,
   diagnóstico chi²) sigue real, maduro y accesible como herramienta
   manual desde la GUI (clic + medir), con sus propios tests -- la
   limitación real y ya encontrada (sesgo del ajuste sobre fondo con
   estructura difusa real, verificado contra M31) sigue aplicando solo
   al uso AUTOMÁTICO no intentado, no a la herramienta manual en sí, que
   nunca pretendió ser una medida de confianza equivalente sin
   supervisión humana.
3. **`pyraf_backend.py`**: mismo patrón honesto ya verificado en
   Reducción/Astrometría/Detección -- backend opcional, correctamente
   documentado como no verificable en este entorno, nunca conectado a
   la GUI (`PhotometryDialog` y el resto de la interfaz usan
   exclusivamente `aperture.py`/`psf.py`).
4. **Los tres procesos manuales no producen imágenes que guardar**
   (`output_data=None` salvo el diagnóstico opcional de PSF, que sí abre
   una ventana nueva con la imagen de residuo) -- son medidas numéricas,
   con tabla exportable a CSV por el mecanismo genérico ya existente
   ("Herramientas -> Exportar última tabla a CSV..."), no el patrón de
   "resultado real sin opción de guardar" que sí se encontró y cerró en
   Reducción (informe 90) y Astrometría (informe 91).

## Validación con datos reales

Fotometría de apertura + curva de crecimiento real ejecutada sobre una
fuente real detectada en el LIGHT sin calibrar de M31 (misma fuente que
valida Detección/Caracterización en informes previos): radio óptimo por
máxima S/N medida = 4.0 px (S/N=450.9), flujo asintótico ajustado =
419 607 ADU, con S/N decreciendo monótonamente para radios mayores
según lo físicamente esperado (más cielo, menos señal marginal) --
comportamiento correcto sobre datos de campo real, no solo sintéticos.

## Checklist de cierre (20 puntos)

| Punto | Estado |
|---|---|
| Implementación científica real | Sí -- apertura subpíxel, curva de crecimiento, punto cero, PSF (Gaussiana/Moffat/empírica + desmezclado), todo nativo |
| Entrada definida | Sí -- posición de píxel (clic o detección automática), radios/anillos, o posiciones + modelo de PSF |
| Salida definida | Sí -- `ApertureMeasurement`/`GrowthCurveFit`/`ZeropointFit`/`PSFFitResult`/`PSFFitDiagnostics` |
| Tipos coherentes | Sí -- dataclasses tipadas en todo el flujo |
| Unidades correctas | Sí -- ADU, mag, px, arcsec según el campo |
| Incertidumbres cuando correspondan | Sí -- ruido de apertura + incertidumbre del cielo propagados; punto cero con incertidumbre por error estándar de la mediana robusta |
| Manejo explícito de datos faltantes | Sí -- flujo neto <= 0 no produce magnitud inventada (`None`); estrella sin cruce Gaia válido se descarta con motivo explícito |
| NOT_AVAILABLE cuando proceda | Sí -- mismo criterio que la fila anterior; PSF sigue LIMITADO/manual por decisión ya documentada (informe 41), no NOT_AVAILABLE silencioso |
| Provenance | N/A directo en el motor (mediciones interactivas sin `Provenance` propio); el flujo de apertura que SÍ llega a `Candidate` vía `characterize_point_source` ya lleva provenance real (informe 94) |
| Errores correctamente gestionados | Sí -- mensajes explícitos y accionables en cada validación (sin puntos marcados, sin WCS, sin cruce Gaia, ajuste con menos de 4 radios) |
| Funciona independientemente | Sí -- sin GUI, ver `tests/unit/photometry/` |
| Conectado al motor anterior (Characterization) | Sí -- `aperture_photometry` es la misma función que ya usa `characterize_point_source` (informe 94) |
| Conectado al siguiente (Identification/Catalogs) | Sí -- `photometry.zeropoint` ya resuelve contra Gaia real; el punto cero ajustado alimenta la dimensión fotométrica de Anomalía |
| GUI funcional | Sí -- tres procesos reales, clic o detección automática, editor de apertura arrastrable, los tres probados de extremo a extremo |
| Guardado de resultados correcto | Sí (tabla exportable a CSV; el diagnóstico de residuo de PSF abre una ventana real) -- ver punto 4 arriba |
| Rutas de salida controladas por el usuario | Sí (mismo mecanismo genérico de exportación de tabla) |
| Tests unitarios | Sí -- 47 passed, 4 skipped (pyraf real) |
| Tests de integración | Sí -- `aperture_photometry` consumida end-to-end por Discovery vía Characterization |
| Test de regresión | N/A directo (sin lector/motor legacy que comparar en este bloque -- aperture/calibration siempre fueron nativos) |
| Validación con datos reales/controlados | Sí -- fuente real de M31, ver arriba |
| Documentación actualizada | Sí -- este informe reconfirma y referencia el informe 41 (PSF) sin necesidad de reescribirlo |
| Ningún placeholder presentado como funcionalidad | Sí -- PSF nunca se presenta como candidato-grade automático, límite correctamente comunicado desde el informe 41 |

## Validación de la suite completa

Sin cambios de código en este informe -- se reejecutaron los tests
directos del motor para confirmar el estado antes de cerrar (47 passed,
4 skipped); la suite completa ya está validada íntegra desde el informe
94 (1704 passed, 24 skipped), sin tocar nada desde entonces.

## CHECKPOINT

```
MOTOR: Photometry
ESTADO: CERRADO
IMPLEMENTACIÓN: astrophysics_suite/photometry/{aperture,psf,calibration}.py
ENTRADA: posición de píxel (clic o auto-detección) + radios/anillos, o posiciones + modelo de PSF
SALIDA: ApertureMeasurement / GrowthCurveFit / ZeropointFit / PSFFitResult+Diagnostics
GUI: sí (3 procesos reales: aperture, zeropoint, psf -- los 3 probados de extremo a extremo)
PROVENANCE: N/A directo en el motor interactivo; real donde SÍ llega a Candidate (vía Characterization, informe 94)
TESTS: 47 unitarios (4 skipped, pyraf real) directos del motor
TESTS PASADOS: 47
TESTS FALLIDOS: 0
VALIDACIÓN REAL: sí (fuente real de M31: curva de crecimiento con radio óptimo físicamente coherente, S/N=450.9)
PROBLEMAS RESTANTES: ninguno bloqueante. PSF sigue LIMITADO a uso manual supervisado (decisión ya tomada y documentada en el informe 41 -- necesitaría un modelo de cielo local no constante Y una decisión de política científica del usuario para poder automatizarse; explícitamente fuera de alcance de "cerrar lo que existe").
CONTRATO HACIA EL SIGUIENTE MOTOR (Identification/Catalogs): ZeropointFit real (para calibrar magnitudes) + ApertureMeasurement.magnitude -- exactamente lo que catalogs/gaia.py e identify_detection ya consumen hoy vía discovery/pipeline.py.
```

## Cambio de motor

Photometry re-verificado bajo el checklist de 20 puntos: sin hallazgos
que corregir, con la limitación real del motor PSF reconfirmada como
correctamente documentada y acotada (no silenciada, no reintentada sin
mandato). Validado de nuevo con datos reales de M31. Siguiente en el
orden fijo del usuario: **Identification/Catalogs**.
