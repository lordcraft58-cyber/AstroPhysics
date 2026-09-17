"""Diagnóstico genérico de ajustes reales (residuales/outliers) -- no un
motor propio: opera sobre residuales que YA calculó otro motor (WCS,
punto cero fotométrico, calibración de longitud de onda...), nunca
recalcula el ajuste en sí. Generaliza el criterio de rechazo robusto
(mediana + MAD, sigma-clip iterativo) que ya usan internamente varios
motores por separado (`photometry.calibration.fit_zeropoint`,
`photometry.aperture`, `spectroscopy.continuum`/`trace`,
`astrometry.plate_solve._robust_fit_wcs`) -- aquí solo para DIAGNÓSTICO
(marcar qué puntos son atípicos en un informe), no para sustituir el
rechazo que cada motor ya aplica dentro de su propio ajuste.
"""
