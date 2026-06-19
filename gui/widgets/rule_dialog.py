"""
Mock / rewrite rule editor.

The first version deliberately edits the rule JSON directly: it keeps the UI
small while still exposing the full engine surface (mock, map-local via file,
request rewrite, response rewrite). The engine validates and normalizes rules
again before saving, so malformed rows never reach the proxy.
"""
from __future__ import annotations

import json
from typing import Dict, List

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from gui.i18n import tr
from proxy.rules import RuleEngine


EXAMPLE_RULES: List[Dict[str, object]] = [
    {
        "enabled": True,
        "name": "Mock health",
        "kind": "mock",
        "match": "*/api/health",
        "status": 200,
        "headers": {"content-type": "application/json"},
        "body": {"ok": True},
    },
    {
        "enabled": False,
        "name": "Map local file",
        "kind": "mock",
        "match": "*/api/config",
        "status": 200,
        "headers": {"content-type": "application/json"},
        "file": "~/Desktop/config.json",
    },
    {
        "enabled": False,
        "name": "Rewrite request header",
        "kind": "request_rewrite",
        "match": "*/api/*",
        "set_headers": {"x-debug": "glimpse"},
        "remove_headers": ["x-remove-me"],
    },
    {
        "enabled": False,
        "name": "Rewrite response body",
        "kind": "response_rewrite",
        "match": "*/api/*",
        "body_find": "\"beta\": false",
        "body_replace": "\"beta\": true",
    },
]


class RuleDialog(QDialog):
    """Modal editor for mock / rewrite rules."""

    def __init__(self, rules: List[Dict], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("rules.dialog.title"))
        self.setModal(True)
        self.resize(760, 620)

        header = QLabel(tr("rules.dialog.header"))
        header.setStyleSheet(
            "color: #89dceb; font-weight: 600; font-size: 12px;"
            "text-transform: uppercase; letter-spacing: 1px;"
        )

        self._edit = QPlainTextEdit()
        self._edit.setFont(QFont("SF Mono, Menlo, monospace", 12))
        self._edit.setTabChangesFocus(True)
        self._edit.setPlainText(json.dumps(rules, indent=2, ensure_ascii=False))

        hint = QLabel(tr("rules.dialog.hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #a6adc8; font-size: 11px; padding: 6px 0;")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Reset
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("common.save"))
        buttons.button(QDialogButtonBox.StandardButton.Reset).setText(tr("rules.dialog.examples"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("common.cancel"))
        self._btn_format = buttons.addButton(
            tr("editor.format_json"),
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Reset).clicked.connect(self._load_examples)
        self._btn_format.clicked.connect(self._format_json)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(8)
        root.addWidget(header)
        root.addWidget(self._edit, 1)
        root.addWidget(hint)
        root.addWidget(buttons)

    def values(self) -> List[Dict]:
        loaded = json.loads(self._edit.toPlainText() or "[]")
        if not isinstance(loaded, list):
            raise ValueError(tr("rules.dialog.error.not_list"))
        return RuleEngine._clean_rules(loaded)

    def accept(self) -> None:
        try:
            self.values()
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            QMessageBox.warning(
                self,
                tr("rules.dialog.error.title"),
                tr("rules.dialog.error.text", exc=str(exc)),
            )
            return
        super().accept()

    def _load_examples(self) -> None:
        self._edit.setPlainText(json.dumps(EXAMPLE_RULES, indent=2, ensure_ascii=False))

    def _format_json(self) -> None:
        try:
            loaded = json.loads(self._edit.toPlainText() or "[]")
        except json.JSONDecodeError as exc:
            QMessageBox.warning(
                self,
                tr("rules.dialog.error.title"),
                tr("rules.dialog.error.text", exc=str(exc)),
            )
            return
        self._edit.setPlainText(json.dumps(loaded, indent=2, ensure_ascii=False))
