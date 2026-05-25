#!/usr/bin/env python3
"""
Glimpse — HTTP/HTTPS debugging proxy
Entry point
"""
import os
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from gui.main_window import MainWindow


def main() -> None:
    # Suppress benign macOS / Qt font and IMKit noise
    os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.fonts=false")

    # High-DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Glimpse")
    app.setApplicationVersion("0.1.0")
    app.setOrganizationName("glimpse")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
