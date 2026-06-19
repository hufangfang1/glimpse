"""
Layout presets + persistence for the dock-based main window.

Each logical region (traffic table, inspector/editor, intercept queue) lives in its own
``QDockWidget`` so the user can float it out to a second monitor, tab-stack it,
close it, or resize it freely. ``LayoutManager`` adds three named presets and
round-trips the whole dock arrangement through ``~/.glimpse/settings.json`` (the
same file i18n uses for the language setting), so the last layout is restored on
the next launch.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import TYPE_CHECKING, Dict

from PyQt6.QtCore import Qt

if TYPE_CHECKING:  # avoid a hard import cycle with main_window
    from gui.main_window import MainWindow

SETTINGS_DIR = Path.home() / ".glimpse"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"

# Preset identifiers (also used as i18n key suffixes: menu.view.layout.<name>).
PRESETS = ("monitor", "inspect", "compose")


class LayoutManager:
    """Applies named layout presets and persists the live dock arrangement.

    The window owns the docks; this helper only arranges and remembers them, so
    main_window stays focused on wiring.
    """

    def __init__(self, window: "MainWindow") -> None:
        self._w = window

    # ------------------------------------------------------------------ #
    # Presets
    # ------------------------------------------------------------------ #

    def apply(self, preset: str) -> None:
        """Arrange the docks for one of the named presets.

        monitor — traffic only, maximised (inspector/intercept out of the way).
        inspect — traffic (left) + inspector (right), the default workbench.
        compose — hide traffic and dedicate the workbench to a blank request draft.
        The intercept dock is event-driven: hidden in presets, auto-shown when
        a breakpoint hits, then auto-hidden when no held flows remain.
        """
        w = self._w
        traffic = w._dock_traffic
        inspector = w._dock_inspector
        intercept = w._dock_intercept

        # Always start from a known docked state so toggling presets is stable
        # even after the user has floated or closed something.
        for dock in (traffic, inspector, intercept):
            dock.setFloating(False)
            dock.show()
        intercept.hide()

        if preset == "monitor":
            inspector.hide()
            w.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, traffic)
        elif preset == "compose":
            traffic.hide()
            w.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, inspector)
            w.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, intercept)
            w._editor_panel.new_draft()
        else:  # "inspect" (default)
            w.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, traffic)
            w.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, inspector)
            w.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, intercept)
            # Keep the traffic dock as a narrow index: enough for # / Host / Path,
            # while the inspector owns the working space.
            w.resizeDocks([traffic, inspector], [400, 880], Qt.Orientation.Horizontal)

    # ------------------------------------------------------------------ #
    # Persistence  (saveState/saveGeometry → base64 in settings.json)
    # ------------------------------------------------------------------ #

    def save_current(self) -> None:
        data = self._read()
        data["layout"] = {
            "state": base64.b64encode(bytes(self._w.saveState())).decode("ascii"),
            "geometry": base64.b64encode(bytes(self._w.saveGeometry())).decode("ascii"),
        }
        self._write(data)

    def restore(self) -> bool:
        """Restore the last saved arrangement. Returns False if none saved."""
        layout = self._read().get("layout")
        if not isinstance(layout, dict):
            return False
        try:
            geometry = base64.b64decode(layout["geometry"])
            state = base64.b64decode(layout["state"])
        except (KeyError, ValueError):
            return False
        ok_geo = self._w.restoreGeometry(geometry)
        ok_state = self._w.restoreState(state)
        return bool(ok_geo or ok_state)

    # ------------------------------------------------------------------ #
    # settings.json read/merge/write (mirrors gui.i18n persistence)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _read() -> Dict[str, object]:
        try:
            loaded = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return loaded if isinstance(loaded, dict) else {}

    @staticmethod
    def _write(data: Dict[str, object]) -> None:
        try:
            SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass
