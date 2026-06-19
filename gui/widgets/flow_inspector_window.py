"""
Standalone inspector window — pops a single captured flow out into its own
top-level window so it can be dragged to a second monitor or placed side-by-side
with another flow for comparison.

It simply embeds a fresh ``RequestEditorPanel`` (the same widget used in the main
window's Inspector dock) and loads the flow into it, so editing/replay/response
viewing all come for free. The shared ``CollectionStore`` and cookie jar are
passed through so saved request-sets and captured cookies stay in sync with the
main window.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QMainWindow

from proxy.collections import CollectionStore
from proxy.cookies import CapturedCookieJar
from proxy.models import FlowModel
from gui.i18n import i18n, tr
from gui.themes import DARK
from gui.widgets.request_editor import RequestEditorPanel


class FlowInspectorWindow(QMainWindow):
    """An independent window inspecting one captured flow."""

    closed = pyqtSignal(object)  # emits self so the owner can drop its ref

    def __init__(
        self,
        flow: FlowModel,
        store: CollectionStore,
        cookie_jar: CapturedCookieJar,
        parent=None,
    ) -> None:
        # No `parent` keeps it a true independent top-level window (movable to
        # another display), but we still hand `parent` to QMainWindow=None so it
        # is not clipped to the main window.
        super().__init__(None)
        self._flow = flow
        self.resize(900, 720)
        self.setStyleSheet(DARK)

        self._panel = RequestEditorPanel(
            store=store,
            cookie_jar=cookie_jar,
            parent=self,
        )
        self.setCentralWidget(self._panel)
        self._panel.load_inspect_flow(flow)

        i18n.language_changed.connect(self._retranslate)
        self._retranslate()

    def _retranslate(self) -> None:
        title = tr(
            "inspector.window.title",
            method=self._flow.method,
            url=self._flow.url,
        )
        self.setWindowTitle(title)

    def closeEvent(self, event) -> None:
        # Drop the i18n subscription so a later language flip doesn't retranslate
        # a deleted widget (the embedded panel disconnects its own on destroy).
        try:
            i18n.language_changed.disconnect(self._retranslate)
        except TypeError:
            pass
        self.closed.emit(self)
        super().closeEvent(event)
