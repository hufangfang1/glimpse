"""
Scope configuration dialog — edit allow / block host patterns.
"""
from __future__ import annotations

from typing import List, Tuple

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.i18n import tr


class _PatternEditor(QWidget):
    """Title + multiline pattern editor."""

    def __init__(self, title: str, color: str, placeholder: str, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        header = QLabel(title)
        header.setStyleSheet(
            f"color: {color}; font-weight: 600; font-size: 12px;"
            "text-transform: uppercase; letter-spacing: 1px;"
        )
        layout.addWidget(header)

        self._edit = QPlainTextEdit()
        self._edit.setPlaceholderText(placeholder)
        font = QFont("SF Mono, Menlo, monospace", 12)
        self._edit.setFont(font)
        self._edit.setTabChangesFocus(True)
        layout.addWidget(self._edit, 1)

    def set_patterns(self, patterns: List[str]) -> None:
        self._edit.setPlainText("\n".join(patterns))

    def patterns(self) -> List[str]:
        return self._edit.toPlainText().splitlines()


class ScopeDialog(QDialog):
    """Modal dialog for editing capture scope."""

    def __init__(
        self,
        allow: List[str],
        block: List[str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("scope.title"))
        self.setModal(True)
        self.resize(640, 460)

        self._allow_editor = _PatternEditor(
            tr("scope.allow.title"),
            "#a6e3a1",
            tr("scope.allow.placeholder"),
        )
        self._block_editor = _PatternEditor(
            tr("scope.block.title"),
            "#f38ba8",
            tr("scope.block.placeholder"),
        )

        self._allow_editor.set_patterns(allow)
        self._block_editor.set_patterns(block)

        hint = QLabel(tr("scope.hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #a6adc8; font-size: 11px; padding: 6px 0;")

        editors = QHBoxLayout()
        editors.setSpacing(12)
        editors.addWidget(self._allow_editor, 1)
        editors.addWidget(self._block_editor, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Reset
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("common.save"))
        buttons.button(QDialogButtonBox.StandardButton.Apply).setText(tr("common.apply"))
        buttons.button(QDialogButtonBox.StandardButton.Reset).setText(tr("common.clear_all"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("common.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._on_apply)
        buttons.button(QDialogButtonBox.StandardButton.Reset).clicked.connect(self._on_clear)

        self._buttons = buttons
        self._apply_callback = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(8)
        root.addLayout(editors, 1)
        root.addWidget(hint)
        root.addWidget(buttons)

    # ------------------------------------------------------------------ #
    # Public
    # ------------------------------------------------------------------ #

    def set_apply_callback(self, callback) -> None:
        """Callback invoked with (allow, block) when user clicks Apply or Save."""
        self._apply_callback = callback

    def values(self) -> Tuple[List[str], List[str]]:
        return self._allow_editor.patterns(), self._block_editor.patterns()

    # ------------------------------------------------------------------ #
    # Slots
    # ------------------------------------------------------------------ #

    def _on_apply(self) -> None:
        if self._apply_callback is not None:
            allow, block = self.values()
            self._apply_callback(allow, block)

    def _on_clear(self) -> None:
        self._allow_editor.set_patterns([])
        self._block_editor.set_patterns([])

    def accept(self) -> None:
        # Save = Apply + close
        self._on_apply()
        super().accept()
