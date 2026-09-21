"""Motor de informes científicos: convierte el resultado real de otro
motor (`Candidate`, con toda su cadena de evidencia) en un
`ScientificResult` -- secciones estructuradas con campos, tablas y
series listas para graficar, exportar o mostrar en la GUI. Nunca una
capa decorativa: cada sección se construye únicamente a partir de datos
ya medidos por motores reales, con NOT_AVAILABLE explícito donde no hay
medida (nunca un valor inventado para "rellenar" el informe).
"""
