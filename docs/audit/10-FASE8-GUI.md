# AstroPhysics Suite — Fase 8: GUI comercial en Tkinter (completada, superada por la Fase 9)

> **Estado:** el código de esta fase está terminado, probado y se conserva en el
> repositorio (`gui/`, `services/`) como referencia histórica. Por decisión explícita
> del propietario del proyecto (ver `docs/audit/11-FASE9-IRAF-PIXINSIGHT-PLAN.md`), el
> producto final **no** usa esta GUI en Tkinter: se sustituye por un taller de
> procesamiento estilo PixInsight construido sobre PySide6/Qt, que además integra el
> flujo de revisión de candidatos que esta fase construyó primero. Este documento
> describe lo que se construyó y por qué, para que ese trabajo no se pierda como
> antecedente de diseño (paleta, vocabulario visual, contratos de servicios).

## 1. Encargo que originó esta fase

Tras la Fase 7 (Discovery Engine integrado, `Observation -> list[Candidate]`
ejecutable de principio a fin), el propietario del proyecto pidió explícitamente
diferir todo el empaquetado comercial/marketing al final, y en su lugar: (a) que el
programa "funcione perfecto, sea relativamente bonito", usando como referencia visual
una landing page ya diseñada; (b) proponer mejoras adicionales; (c) reestructurar y
dejar intuitiva la organización del programa. La instrucción final fue "crea la gui
propuesta".

## 2. Arquitectura construida

Capas, con dirección de dependencia forzada (la misma disciplina que el resto del
proyecto): `astrophysics_suite/` (ciencia, cero tkinter) <- `services/` (orquestación
de trabajos en segundo plano, sin tkinter) <- `gui/` (presentación; único paquete con
permiso de importar tkinter).

- **`services/session_state.py`**: `SessionState`, la única fuente de verdad de "qué
  hay en el proyecto ahora mismo" (observaciones, imágenes cargadas, candidatos),
  con notificación por callback para que la GUI se refresque sin acoplarse a qué
  cambió exactamente.
- **`services/discovery_service.py`**: `DiscoveryJob` ejecuta
  `astrophysics_suite.discovery.pipeline.run_generic_discovery` en un hilo de fondo
  -- el hilo de fondo solo escribe a una `queue.Queue`; el hilo principal la consume
  vía `root.after()`. Mismo patrón que ya usaba correctamente
  `legacy...launch_gui()`, generalizado aquí para cualquier llamador.
- **`services/hardware_service.py`**: primera vez que `check_hardware()` (Fase 1,
  correcto pero sin cablear a ningún punto de entrada) se expone de forma asíncrona.
- **`gui/theme.py`**: paleta y tipografías traducidas (no copiadas) de la landing
  page de referencia -- ámbar/cian/coral/índigo sobre fondo neutro -- con la lógica
  semántica de color centralizada (`STATE_COLOR_KEY`, `REVIEW_COLOR_KEY`,
  `QUALITY_COLOR_KEY`) para que un cambio de vocabulario no obligue a tocar cada
  vista.
- **`gui/widgets/`**: `Badge` (píldora de estado dibujada a mano en `Canvas`, ttk no
  soporta esquinas redondeadas), `Card` (borde de 1px exacto vía
  `highlightbackground`), `ScrollableFrame` (patrón estándar `Canvas`+`Frame`+
  `Scrollbar`).
- **`gui/views/`**: `ProjectView` (resumen del proyecto y acceso a nueva
  observación), `NewObservationView` (asistente de carga), `AnalysisView` (progreso
  con registro colapsable), `CandidatesView` (lista filtrable, el centro del
  producto), `CandidateDetailView` (cadena de evidencia completa + acciones de
  revisión humana), `SettingsView` (parámetros avanzados del Discovery Engine),
  `DiagnosticsView` (equipo y compatibilidad, primer punto de entrada de GUI para
  `check_hardware`).

## 3. Decisión de diseño central que sí se traslada a la Fase 9

El centro del producto es el candidato científico y su evidencia, no la imagen: la
pantalla de candidatos ordena por S/N y muestra badges de estado semántico; la vista
de detalle expone identificación, caracterización, inferencia física, vector de
anomalía, evidencia temporal/de movimiento, catálogos, calidad/artefactos, historial
de revisión y procedencia -- todo antes de cualquier acción, y las únicas acciones
posibles son Conservar/Descartar/Marcar (`Candidate.mark_reviewed`, nunca una
declaración automática de descubrimiento). Este principio se conserva íntegro en el
nuevo taller PixInsight/Qt (Fase 9): la revisión de candidatos pasa a ser un proceso
más dentro del mismo shell, no una aplicación aparte.

## 4. Verificación realizada

Construido y ejecutado de extremo a extremo bajo Xvfb (`DISPLAY=:99`, venv con
tkinter real, no solo importado): las 5 vistas iniciales renderizan sin excepción, el
flujo completo con datos sintéticos (3 candidatos con evidencia física/de anomalía
completa) renderiza correctamente incluyendo badges de estado, y el flujo de revisión
humana (`Conservar` con nota) actualiza `SessionState` y conserva el historial
completo en `Candidate.review_notes`. 11 tests nuevos en `tests/gui_smoke/`
(navegación entre las 7 vistas, `SettingsView.current_params()` con entrada inválida,
apertura de detalle, flujo de revisión completo, invariante de que `mark_reviewed`
nunca vuelve a `PENDING`). Suite completa sin regresiones: 119 passed, 2 skipped (red),
1 xfailed en el venv con tkinter+Xvfb; 106 passed, 3 skipped, 1 xfailed en el venv sin
tkinter.

## 5. Por qué se sustituye

El propietario del proyecto pidió, en un encargo posterior, integrar la suite
completa de reducción y análisis clásica de IRAF (CCD, fotometría de apertura y PSF,
espectroscopía 1D/2D, astrometría/WCS, utilidades de imagen) bajo una interfaz
inspirada en PixInsight (espacio de trabajo MDI, iconos de proceso, STF, consola
integrada). Ese paradigma de interacción -- ventanas de imagen flotantes/acoplables,
arrastrar-y-soltar iconos de proceso sobre vistas, paneles dockeable -- no es
alcanzable con Tkinter sin reconstruir, en la práctica, un framework de ventanas
propio. Mantener dos toolkits de GUI (Tkinter y Qt) permanentemente en el mismo
producto comercial habría sido inconsistente e innecesariamente costoso de mantener;
se optó por unificar en PySide6/Qt y migrar el flujo de candidatos al nuevo shell.
