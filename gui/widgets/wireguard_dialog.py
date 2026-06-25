"""WireGuard client setup dialog."""
from __future__ import annotations

from io import BytesIO

import qrcode
from qrcode.constants import ERROR_CORRECT_L
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from gui.i18n import tr


class WireGuardDialog(QDialog):
    """Show a scannable WireGuard client config and its text equivalent."""

    def __init__(self, config: str, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle(tr("dialog.wireguard.title"))
        self.setModal(True)
        self.resize(560, 720)

        hint = QLabel(tr("dialog.wireguard.hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #a6adc8; font-size: 12px;")

        qr_label = QLabel()
        qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_label.setPixmap(self._qr_pixmap(config))

        config_edit = QPlainTextEdit()
        config_edit.setReadOnly(True)
        config_edit.setFont(QFont("SF Mono, Menlo, monospace", 11))
        config_edit.setPlainText(config)
        config_edit.setMaximumHeight(220)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(
            tr("common.close")
        )
        copy_button = QPushButton(tr("dialog.wireguard.copy"))
        buttons.addButton(copy_button, QDialogButtonBox.ButtonRole.ActionRole)
        copy_button.clicked.connect(self._copy_config)
        buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(12)
        root.addWidget(hint)
        root.addWidget(qr_label, 1)
        root.addWidget(config_edit)
        root.addWidget(buttons)

    @staticmethod
    def _qr_pixmap(config: str) -> QPixmap:
        qr = qrcode.QRCode(
            version=None,
            error_correction=ERROR_CORRECT_L,
            box_size=7,
            border=3,
        )
        qr.add_data(config)
        qr.make(fit=True)
        image = qr.make_image(fill_color="#11111b", back_color="white").convert(
            "RGB"
        )
        data = BytesIO()
        image.save(data, format="PNG")
        pixmap = QPixmap()
        pixmap.loadFromData(data.getvalue(), "PNG")
        return pixmap

    def _copy_config(self) -> None:
        QApplication.clipboard().setText(self._config)
