"""
Breakpoint rules dialog — choose which flows to pause for interactive editing.

Modeled on :class:`gui.widgets.scope_dialog.ScopeDialog`: a multiline list of
fnmatch URL patterns plus toggles for whether to break on the request side, the
response side, and a master enable switch.
"""
from __future__ import annotations

from typing import List, Tuple

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from gui.i18n import tr


class BreakpointDialog(QDialog):
    """Modal dialog for editing breakpoint rules."""

    def __init__(
        self,
        *,
        enabled: bool,
        patterns: List[str],
        on_request: bool,
        on_response: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("breakpoints.dialog.title"))
        self.setModal(True)
        self.resize(560, 460)

        header = QLabel(tr("breakpoints.dialog.url"))
        header.setStyleSheet(
            "color: #f9e2af; font-weight: 600; font-size: 12px;"
            "text-transform: uppercase; letter-spacing: 1px;"
        )

        self._edit = QPlainTextEdit()
        self._edit.setPlaceholderText("*.example.com/api/*\n*/login")
        self._edit.setFont(QFont("SF Mono, Menlo, monospace", 12))
        self._edit.setTabChangesFocus(True)
        self._edit.setPlainText("\n".join(patterns))

        self._chk_enabled = QCheckBox(tr("breakpoints.dialog.enabled"))
        self._chk_enabled.setChecked(enabled)
        self._chk_request = QCheckBox(tr("breakpoints.dialog.on_request"))
        self._chk_request.setChecked(on_request)
        self._chk_response = QCheckBox(tr("breakpoints.dialog.on_response"))
        self._chk_response.setChecked(on_response)

        hint = QLabel(tr("breakpoints.dialog.hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #a6adc8; font-size: 11px; padding: 6px 0;")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("common.save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("common.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(8)
        root.addWidget(header)
        root.addWidget(self._edit, 1)
        root.addWidget(self._chk_enabled)
        root.addWidget(self._chk_request)
        root.addWidget(self._chk_response)
        root.addWidget(hint)
        root.addWidget(buttons)

    def values(self) -> Tuple[bool, List[str], bool, bool]:
        return (
            self._chk_enabled.isChecked(),
            self._edit.toPlainText().splitlines(),
            self._chk_request.isChecked(),
            self._chk_response.isChecked(),
        )
