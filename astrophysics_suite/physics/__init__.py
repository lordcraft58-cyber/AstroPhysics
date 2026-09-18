"""Physical Engine, primer corte (Fase 6, continuación).

Envuelve `legacy...infer_physical_parameters()`, que ya distingue
OBSERVADO/CALIBRADO/INFERIDO por parámetro y nunca convierte un ratio en
velocidad sin declarar el modelo -- exactamente la disciplina que pide el
encargo original. Opera sobre un `row: dict` (el mismo contrato que la
función heredada), no sobre `CharacterizationResult`: los observables que
necesita (`ratio`, `offset_arcsec`, `velocity_kms`, `radius_pc`) son
específicos del pipeline de choque OIII/Hα (`analyze_pair_core`), que
todavía no se ha extraído -- conectar esto a `CharacterizationResult` de
forma genérica antes de extraer ese pipeline produciría un adaptador
artificial que casi siempre estaría vacío. Ver
docs/audit/08-FASE6-MOTORES-RESTANTES.md, seccion 4.
"""
