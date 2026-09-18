"""Gráficas científicas reales -- cada función toma datos ya medidos
(nunca los recalcula ni los simula) y devuelve una figura Matplotlib real.
Backend `Agg` fijo (`matplotlib.use("Agg")`, ver `charts.py`): estas
funciones se ejecutan tanto desde la GUI como desde exportación en
lote/pruebas, y nunca deben requerir una pantalla.
"""
