"""Los 12 pasos reales del tutorial guiado (Fase 22, objetivo 5) --
cada `target` apunta a un control real de `MainWindow` (dock, menú o
área central), nunca a un control inventado. Sigue el esquema pedido:
Bienvenida, Explorador de procesos, Abrir FITS, Visualización,
Reducción, Astrometría, Fotometría, Espectroscopía, Descubrimiento,
Candidatos, Exportación, Final.
"""
from __future__ import annotations

from PySide6.QtCore import QRect

from qt_app.tutorial.tutorial_overlay import TutorialStep


def _widget_target(attr_name: str):
    def resolve(main_window) -> QRect | None:
        widget = getattr(main_window, attr_name, None)
        if widget is None or not widget.isVisible():
            return None
        top_left = widget.mapTo(main_window, widget.rect().topLeft())
        return QRect(top_left, widget.size())

    return resolve


def _dock_target(attr_name: str):
    """Como `_widget_target`, pero para un `QDockWidget` que puede estar
    tabificado con otro -- lo eleva primero para que el hueco resaltado
    corresponda de verdad a la pestaña visible, no a una oculta detrás."""

    def resolve(main_window) -> QRect | None:
        dock = getattr(main_window, attr_name, None)
        if dock is None:
            return None
        dock.raise_()
        if not dock.isVisible():
            return None
        top_left = dock.mapTo(main_window, dock.rect().topLeft())
        return QRect(top_left, dock.size())

    return resolve


def _menu_target(attr_name: str):
    def resolve(main_window) -> QRect | None:
        menu = getattr(main_window, attr_name, None)
        if menu is None:
            return None
        menu_bar = main_window.menuBar()
        rect = menu_bar.actionGeometry(menu.menuAction())
        if rect.isNull():
            return None
        top_left = menu_bar.mapTo(main_window, rect.topLeft())
        return QRect(top_left, rect.size())

    return resolve


def _no_target(_main_window) -> QRect | None:
    return None


def build_tutorial_steps() -> list[TutorialStep]:
    return [
        TutorialStep(
            title="1/12 -- Bienvenida a AstroPhysics Suite",
            what_it_does=(
                "Un taller de análisis astrofísico: abre imágenes FITS reales, las calibra, las resuelve "
                "astrométricamente, mide fuentes por fotometría o espectroscopía, y ejecuta Discovery -- "
                "detección + identificación contra Gaia -- para encontrar candidatos que revisar tú mismo."
            ),
            when_to_use="Léelo una vez al empezar; puedes reabrirlo cuando quieras desde Ayuda -> Tutorial guiado.",
            what_it_needs="Nada todavía -- solo sigue los pasos.",
            what_it_produces=(
                "Nada se declara \"descubrimiento\" automáticamente: todo candidato pasa por tu revisión "
                "manual antes de considerarse nada."
            ),
            target=_no_target,
        ),
        TutorialStep(
            title="2/12 -- Explorador de procesos",
            what_it_does="Panel lateral con todos los algoritmos disponibles, agrupados por categoría (Reducción, Fotometría, Espectroscopía...).",
            when_to_use="Para ejecutar un proceso sobre una imagen abierta: doble clic, o arrastra el proceso sobre la ventana de la imagen.",
            what_it_needs="Una imagen abierta en el área central para la mayoría de procesos.",
            what_it_produces="Abre el panel de Propiedades con los parámetros del proceso, listo para \"Aplicar\".",
            target=_dock_target("explorer_dock"),
        ),
        TutorialStep(
            title="3/12 -- Abrir un FITS",
            what_it_does="Carga un archivo FITS real (2D, o 3D/4D pidiendo qué plano usar) en una nueva ventana de imagen.",
            when_to_use="Es normalmente el primer paso de cualquier análisis.",
            what_it_needs="Un archivo .fits/.fit/.fts accesible en disco.",
            what_it_produces="Una ventana de imagen con STF automático, lista para el resto de los pasos.",
            target=_menu_target("file_menu"),
        ),
        TutorialStep(
            title="4/12 -- Visualización",
            what_it_does=(
                "La imagen se muestra con estiramiento automático (STF); la rueda del ratón hace zoom "
                "dinámico. El panel PROPIEDADES (derecha) muestra los parámetros del proceso activo, y la "
                "CONSOLA (abajo) registra en tiempo real cada operación y su resultado."
            ),
            when_to_use="Siempre que tengas una imagen abierta -- es la vista de trabajo principal.",
            what_it_needs="Una imagen abierta.",
            what_it_produces="Nada por sí sola -- es donde se ven los resultados de todo lo demás.",
            target=_widget_target("mdi"),
        ),
        TutorialStep(
            title="5/12 -- Reducción",
            what_it_does="Combina fotogramas de calibración (Bias/Dark/Flat) en maestros, y los aplica a las imágenes científicas.",
            when_to_use="Antes de medir nada sobre imágenes crudas -- reduce la señal instrumental no astrofísica.",
            what_it_needs="Al menos 3 fotogramas de entrada por maestro, y una carpeta real donde guardarlo.",
            what_it_produces="Un FITS maestro real en disco (nunca solo en memoria) + la imagen científica calibrada.",
            target=_menu_target("reduction_menu"),
        ),
        TutorialStep(
            title="6/12 -- Astrometría",
            what_it_does=(
                "\"Resolver placa automáticamente...\" detecta estrellas reales, las empareja contra Gaia y "
                "ajusta un WCS real -- sin marcar pares de estrellas a mano. \"Ajustar WCS manualmente...\" "
                "queda como alternativa si la automática no tiene suficiente información."
            ),
            when_to_use="Cuando una imagen no trae WCS válido y necesitas coordenadas celestes reales (para Discovery, fotometría calibrada, etc.).",
            what_it_needs="Una posición y escala aproximadas -- del header FITS si las trae, o introducidas a mano.",
            what_it_produces="Un WCS validado (con RMS y nº de estrellas emparejadas) aplicado a la ventana, y opcionalmente una copia del FITS con el WCS escrito en la cabecera.",
            target=_menu_target("astrometry_menu"),
        ),
        TutorialStep(
            title="7/12 -- Fotometría",
            what_it_does="Mide el flujo de fuentes puntuales por apertura o PSF (categoría \"Fotometría\" del Explorador de procesos), con detección automática o selección a clic.",
            when_to_use="Para medir el brillo de estrellas/candidatos, o calibrar un punto cero fotométrico contra Gaia.",
            what_it_needs="Una imagen abierta; WCS si vas a calibrar contra un catálogo.",
            what_it_produces="Tablas de medidas (flujo, magnitud, FWHM...) exportables a CSV.",
            target=_dock_target("explorer_dock"),
        ),
        TutorialStep(
            title="8/12 -- Espectroscopía",
            what_it_does="Traza el espectro, calibra la longitud de onda detectando líneas reales, y extrae el continuo.",
            when_to_use="Con imágenes de espectros (no de campo estelar).",
            what_it_needs="Una imagen de espectro abierta; líneas de referencia conocidas para la calibración de longitud de onda.",
            what_it_produces="Una solución de longitud de onda (con su RMS) y tablas de líneas identificadas.",
            target=_menu_target("spectroscopy_menu"),
        ),
        TutorialStep(
            title="9/12 -- Discovery",
            what_it_does=(
                "El flujo completo: nueva observación -> selección de imágenes FITS -> WCS automático (si "
                "falta) -> detección de fuentes -> identificación contra Gaia -> candidatos."
            ),
            when_to_use="Cuando quieras analizar un campo completo buscando fuentes no catalogadas o anómalas, no solo medir una estrella conocida.",
            what_it_needs="Uno o varios FITS del mismo objetivo; conexión a Gaia es opcional (sin ella, los candidatos quedan como revisión pendiente, nunca se inventa una identificación).",
            what_it_produces="Candidatos clasificados (conocido, no emparejado, revisión...) para tu revisión -- nunca un \"descubrimiento\" declarado automáticamente.",
            target=_menu_target("discovery_menu"),
        ),
        TutorialStep(
            title="10/12 -- Candidatos",
            what_it_does="Lista todos los candidatos de la sesión, con filtros por estado; el detalle de cada uno muestra su evidencia (imagen, catálogo, calidad).",
            when_to_use="Después de un análisis Discovery, para revisar uno por uno.",
            what_it_needs="Al menos un análisis Discovery completado.",
            what_it_produces="Tu decisión registrada por candidato: Conservar, Descartar o Marcar para seguimiento.",
            target=_dock_target("candidates_dock"),
        ),
        TutorialStep(
            title="11/12 -- Exportación",
            what_it_does="Exporta la última tabla producida (fotometría, WCS, longitud de onda...) a un CSV real.",
            when_to_use="Para llevar los resultados numéricos fuera de la aplicación (hoja de cálculo, otro software).",
            what_it_needs="Haber ejecutado al menos un proceso que produzca una tabla.",
            what_it_produces="Un archivo .csv real en la ruta que elijas.",
            target=_menu_target("tools_menu"),
        ),
        TutorialStep(
            title="12/12 -- Para empezar a trabajar",
            what_it_does="Resumen de la receta habitual, de principio a fin.",
            when_to_use=(
                "ABRIR FITS -> REVISAR METADATA -> RESOLVER WCS -> REDUCIR -> FOTOMETRÍA -> ANALIZAR -> "
                "DISCOVERY -> REVISAR CANDIDATOS."
            ),
            what_it_needs="",
            what_it_produces="Puedes reabrir este tutorial cuando quieras desde Ayuda -> Tutorial guiado.",
            target=_no_target,
        ),
    ]
