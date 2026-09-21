"""Prueba de humo del tutorial guiado de primer arranque (Fase 22,
objetivo 5): aparece la primera vez, no vuelve a aparecer solo tras
completarse, se puede reabrir manualmente en cualquier momento, y cada
uno de los 12 pasos resuelve un control REAL de la ventana principal
(nunca un control inventado) o explícitamente ninguno (bienvenida/cierre).

Requiere PySide6 y un display X -- se salta si no están disponibles.
"""
from __future__ import annotations

import pytest

PySide6 = pytest.importorskip("PySide6", reason="PySide6 no instalado en este entorno")

from PySide6.QtWidgets import QApplication  # noqa: E402


def _display_available() -> bool:
    try:
        app = QApplication.instance() or QApplication([])
    except Exception:
        return False
    return app is not None


pytestmark = pytest.mark.skipif(not _display_available(), reason="sin display X disponible (ni real ni Xvfb) o Qt no puede inicializar")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _new_main_window(qapp, tmp_path, name="prefs.json"):
    from qt_app.main_window import MainWindow
    from services.app_preferences import AppPreferencesStore

    window = MainWindow(preferences=AppPreferencesStore(tmp_path / name))
    window.show()
    qapp.processEvents()
    return window


def test_tutorial_steps_resolve_only_real_widgets_or_explicitly_none(qapp, tmp_path):
    """Prueba obligatoria O (parcial): cada uno de los 12 pasos, contra
    una ventana principal real, o bien resalta un rectángulo real y no
    vacío, o bien declara explícitamente que no hay control (pasos de
    bienvenida/cierre) -- nunca un rectángulo nulo por accidente en un
    paso que sí promete un control."""
    from qt_app.tutorial.tutorial_steps import build_tutorial_steps

    window = _new_main_window(qapp, tmp_path)
    try:
        steps = build_tutorial_steps()
        assert len(steps) == 12
        no_target_titles = {"1/12 -- Bienvenida a AstroPhysics Suite", "12/12 -- Para empezar a trabajar"}
        for step in steps:
            rect = step.target(window)
            if step.title in no_target_titles:
                assert rect is None
            else:
                assert rect is not None, f"paso «{step.title}» debería resaltar un control real"
                assert rect.width() > 0 and rect.height() > 0
    finally:
        window.close()


def test_tutorial_shows_on_first_launch(qapp, tmp_path):
    """Prueba obligatoria L."""
    from qt_app.tutorial.tutorial_overlay import TutorialOverlay

    window = _new_main_window(qapp, tmp_path)
    try:
        assert window.preferences.get("tutorial_show_on_startup") is None  # nunca fijada -- primer arranque real
        window.maybe_show_tutorial_on_startup()
        qapp.processEvents()
        overlays = window.findChildren(TutorialOverlay)
        assert len(overlays) == 1
        assert overlays[0].isVisible()
        assert overlays[0].current_step_index() == 0
    finally:
        window.close()


def test_tutorial_does_not_reappear_once_completed(qapp, tmp_path):
    """Prueba obligatoria M: tras completarlo (todos los "Siguiente" hasta
    "Finalizar"), un arranque posterior (misma preferencia persistida) no
    debe volver a mostrarlo solo."""
    from qt_app.tutorial.tutorial_overlay import TutorialOverlay

    window = _new_main_window(qapp, tmp_path, name="prefs_m.json")
    try:
        window.maybe_show_tutorial_on_startup()
        qapp.processEvents()
        overlay = window.findChildren(TutorialOverlay)[0]
        for _ in range(20):  # más que suficiente para recorrer los 12 pasos
            if not overlay.isVisible():
                break
            overlay._go_next()
            qapp.processEvents()
        assert not overlay.isVisible()
        assert window.preferences.get("tutorial_show_on_startup") == "false"
        assert window.tutorial_on_startup_action.isChecked() is False

        # "arranque posterior": mismo store de preferencias, ventana nueva.
        window.close()
        second_window = _new_main_window(qapp, tmp_path, name="prefs_m.json")
        try:
            second_window.maybe_show_tutorial_on_startup()
            qapp.processEvents()
            assert second_window.findChildren(TutorialOverlay) == []
        finally:
            second_window.close()
    finally:
        pass


def test_tutorial_can_be_reopened_manually_after_completion(qapp, tmp_path):
    """Prueba obligatoria N: aunque ya no aparezca solo al iniciar, "Ayuda
    -> Tutorial guiado" siempre puede reabrirlo, desde el paso 1."""
    from qt_app.tutorial.tutorial_overlay import TutorialOverlay

    window = _new_main_window(qapp, tmp_path)
    try:
        window.preferences.set("tutorial_show_on_startup", "false")  # simula que ya se completó antes
        window.maybe_show_tutorial_on_startup()
        qapp.processEvents()
        assert window.findChildren(TutorialOverlay) == []  # confirmado: no aparece solo

        window._open_tutorial()
        qapp.processEvents()
        overlays = window.findChildren(TutorialOverlay)
        assert len(overlays) == 1
        assert overlays[0].current_step_index() == 0
    finally:
        window.close()


def test_tutorial_skip_marks_it_as_seen_and_can_navigate_back_and_forward(qapp, tmp_path):
    from qt_app.tutorial.tutorial_overlay import TutorialOverlay

    window = _new_main_window(qapp, tmp_path)
    try:
        window._open_tutorial()
        qapp.processEvents()
        overlay = window.findChildren(TutorialOverlay)[0]

        overlay._go_next()
        overlay._go_next()
        assert overlay.current_step_index() == 2
        overlay._go_back()
        assert overlay.current_step_index() == 1

        overlay._skip_button.click()
        qapp.processEvents()
        assert not overlay.isVisible()
        assert window.preferences.get("tutorial_show_on_startup") == "false"
    finally:
        window.close()


def test_toggling_show_on_startup_action_updates_preference(qapp, tmp_path):
    window = _new_main_window(qapp, tmp_path)
    try:
        assert window.tutorial_on_startup_action.isChecked() is True
        window.tutorial_on_startup_action.setChecked(False)
        assert window.preferences.get("tutorial_show_on_startup") == "false"
        window.tutorial_on_startup_action.setChecked(True)
        assert window.preferences.get("tutorial_show_on_startup") == "true"
    finally:
        window.close()
