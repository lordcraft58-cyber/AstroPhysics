"""Vista de conjunto de fotogramas para el taller Qt -- construir
fotogramas maestros de calibración (bias/dark/flat) a partir de varias
imágenes a la vez, y aplicar esa calibración a una imagen científica.
No encaja en el marco genérico de "un proceso transforma la imagen
activa" (`qt_app.processes`): necesita varios archivos de entrada y una
pequeña biblioteca de maestros con estado propio, así que se resuelve
con diálogos dedicados en vez de forzarlo al marco genérico -- ver "Qué
queda" en docs/audit/12-FASE9.6-QT-PIXINSIGHT-GUI.md.
"""
