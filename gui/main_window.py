"""
Main application window.
"""
from __future__ import annotations

import threading
import uuid
from queue import Empty
from typing import Dict, Optional

import httpx
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QAction, QActionGroup, QKeySequence
from PyQt6.QtWidgets import (
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QToolBar,
    QWidget,
)

from proxy.models import FlowModel
from proxy.scope import Scope
from proxy.server import ProxyServer
from gui.i18n import LANGUAGES, i18n, tr
from gui.themes import DARK
from gui.widgets.traffic_table import TrafficTable
from gui.widgets.detail_panel import DetailPanel
from gui.widgets.scope_dialog import ScopeDialog

MAX_CAPTURED_FLOWS = 2000


class MainWindow(QMainWindow):

    def __init__(self) -> None:
        super().__init__()
        self.resize(1280, 780)

        self._server = ProxyServer(port=9090, scope=Scope.load())
        self._flows: Dict[str, FlowModel] = {}
        self._selected_flow_id: Optional[str] = None
        # Track current proxy state so retranslate can refresh the status label
        # without flipping it back to "Stopped" mid-run.
        self._proxy_state: str = "stopped"   # "stopped" | "running" | "stopping"

        self._build_ui()
        self._build_menu()
        self._apply_theme()
        self.retranslate()
        i18n.language_changed.connect(self.retranslate)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_queue)
        self._timer.start(50)

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        self._toolbar = QToolBar("Controls")
        self._toolbar.setMovable(False)
        self._toolbar.setFloatable(False)
        self.addToolBar(self._toolbar)

        self._btn_start = QPushButton()
        self._btn_start.setObjectName("btn_start")
        self._btn_start.setFixedWidth(90)
        self._btn_start.clicked.connect(self._start_proxy)

        self._btn_stop = QPushButton()
        self._btn_stop.setObjectName("btn_stop")
        self._btn_stop.setFixedWidth(90)
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._stop_proxy)

        self._port_label = QLabel()
        self._port_label.setStyleSheet("color: #a6adc8; margin-left: 8px;")
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1024, 65535)
        self._port_spin.setValue(9090)
        self._port_spin.setFixedWidth(70)

        self._btn_clear = QPushButton()
        self._btn_clear.setFixedWidth(80)
        self._btn_clear.clicked.connect(self._clear_traffic)

        self._filter_label = QLabel()
        self._filter_label.setStyleSheet("color: #a6adc8; margin-left: 8px;")
        self._filter_input = QLineEdit()
        self._filter_input.setFixedWidth(220)
        self._filter_input.textChanged.connect(self._on_filter_changed)

        self._btn_replay = QPushButton()
        self._btn_replay.setFixedWidth(96)
        self._btn_replay.setEnabled(False)
        self._btn_replay.clicked.connect(self._replay_selected)

        self._btn_scope = QPushButton()
        self._btn_scope.setFixedWidth(110)
        self._btn_scope.clicked.connect(self._edit_scope)

        self._btn_cert = QPushButton()
        self._btn_cert.setFixedWidth(120)
        self._btn_cert.clicked.connect(self._install_cert)

        self._toolbar.addWidget(self._btn_start)
        self._toolbar.addWidget(self._btn_stop)
        self._toolbar.addSeparator()
        self._toolbar.addWidget(self._port_label)
        self._toolbar.addWidget(self._port_spin)
        self._toolbar.addSeparator()
        self._toolbar.addWidget(self._btn_clear)
        self._toolbar.addWidget(self._btn_replay)
        self._toolbar.addSeparator()
        self._toolbar.addWidget(self._filter_label)
        self._toolbar.addWidget(self._filter_input)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._toolbar.addWidget(spacer)
        self._toolbar.addWidget(self._btn_scope)
        self._toolbar.addWidget(self._btn_cert)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._traffic_table = TrafficTable()
        self._traffic_table.flow_selected.connect(self._on_flow_selected)
        self._traffic_table.replay_requested.connect(self._replay_flow)
        self._traffic_table.delete_requested.connect(self._delete_flow)
        self._traffic_table.filter_host_requested.connect(self._apply_host_filter)
        self._traffic_table.scope_add_requested.connect(self._add_to_scope)

        self._detail_panel = DetailPanel()
        self._detail_panel.replay_requested.connect(self._replay_flow)

        splitter.addWidget(self._traffic_table)
        splitter.addWidget(self._detail_panel)
        splitter.setSizes([700, 580])
        splitter.setChildrenCollapsible(False)

        self.setCentralWidget(splitter)

        self._sb_status = QLabel()
        self._sb_status.setStyleSheet("color: #f38ba8;")
        self._sb_count = QLabel()
        self._sb_scope = QLabel("")
        self._sb_scope.setStyleSheet("color: #f9e2af;")
        self._sb_addr = QLabel("")

        sb = self.statusBar()
        sb.addWidget(self._sb_status)
        sb.addWidget(QLabel("   "))
        sb.addWidget(self._sb_count)
        sb.addWidget(QLabel("   "))
        sb.addWidget(self._sb_scope)
        sb.addPermanentWidget(self._sb_addr)

        self._update_scope_status()

    def _build_menu(self) -> None:
        menu = self.menuBar()

        self._file_menu = menu.addMenu("")
        self._act_start = QAction(self)
        self._act_start.setShortcut(QKeySequence("Meta+R"))
        self._act_start.triggered.connect(self._start_proxy)
        self._file_menu.addAction(self._act_start)

        self._act_stop = QAction(self)
        self._act_stop.setShortcut(QKeySequence("Meta+."))
        self._act_stop.triggered.connect(self._stop_proxy)
        self._file_menu.addAction(self._act_stop)

        self._file_menu.addSeparator()
        self._act_quit = QAction(self)
        self._act_quit.setShortcut(QKeySequence("Meta+Q"))
        self._act_quit.triggered.connect(self.close)
        self._file_menu.addAction(self._act_quit)

        self._edit_menu = menu.addMenu("")
        self._act_clear = QAction(self)
        self._act_clear.setShortcut(QKeySequence("Meta+K"))
        self._act_clear.triggered.connect(self._clear_traffic)
        self._edit_menu.addAction(self._act_clear)

        self._act_replay = QAction(self)
        self._act_replay.setShortcut(QKeySequence("Meta+Shift+R"))
        self._act_replay.triggered.connect(self._replay_selected)
        self._edit_menu.addAction(self._act_replay)

        self._act_copy_url = QAction(self)
        self._act_copy_url.setShortcut(QKeySequence("Meta+Shift+C"))
        self._act_copy_url.triggered.connect(self._copy_selected_url)
        self._edit_menu.addAction(self._act_copy_url)

        self._act_copy_curl = QAction(self)
        self._act_copy_curl.setShortcut(QKeySequence("Meta+Alt+C"))
        self._act_copy_curl.triggered.connect(self._copy_selected_curl)
        self._edit_menu.addAction(self._act_copy_curl)

        self._edit_menu.addSeparator()
        self._act_scope = QAction(self)
        self._act_scope.setShortcut(QKeySequence("Meta+L"))
        self._act_scope.triggered.connect(self._edit_scope)
        self._edit_menu.addAction(self._act_scope)

        # Language menu — checkable radio group.
        self._language_menu = menu.addMenu("")
        self._language_group = QActionGroup(self)
        self._language_group.setExclusive(True)
        self._language_actions: Dict[str, QAction] = {}
        for code, label in LANGUAGES.items():
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(code == i18n.language)
            act.triggered.connect(lambda _checked=False, c=code: i18n.set_language(c))
            self._language_group.addAction(act)
            self._language_menu.addAction(act)
            self._language_actions[code] = act

        self._help_menu = menu.addMenu("")
        self._act_setup = QAction(self)
        self._act_setup.triggered.connect(self._show_setup)
        self._help_menu.addAction(self._act_setup)

    def _apply_theme(self) -> None:
        self.setStyleSheet(DARK)

    # ------------------------------------------------------------------ #
    # i18n
    # ------------------------------------------------------------------ #

    def retranslate(self) -> None:
        self.setWindowTitle(tr("app.title"))

        # Toolbar
        self._toolbar.setWindowTitle(tr("toolbar.controls"))
        self._btn_start.setText(tr("toolbar.start"))
        self._btn_stop.setText(tr("toolbar.stop"))
        self._port_label.setText(tr("toolbar.port"))
        self._btn_clear.setText(tr("toolbar.clear"))
        self._filter_label.setText(tr("toolbar.filter"))
        self._filter_input.setPlaceholderText(tr("toolbar.filter.placeholder"))
        self._btn_replay.setText(tr("toolbar.replay"))
        self._btn_replay.setToolTip(tr("toolbar.replay.tooltip"))
        self._btn_scope.setText(tr("toolbar.scope"))
        self._btn_scope.setToolTip(tr("toolbar.scope.tooltip"))
        self._btn_cert.setText(tr("toolbar.cert"))
        self._btn_cert.setToolTip(tr("toolbar.cert.tooltip"))

        # Menus
        self._file_menu.setTitle(tr("menu.file"))
        self._act_start.setText(tr("menu.file.start"))
        self._act_stop.setText(tr("menu.file.stop"))
        self._act_quit.setText(tr("menu.file.quit"))

        self._edit_menu.setTitle(tr("menu.edit"))
        self._act_clear.setText(tr("menu.edit.clear"))
        self._act_replay.setText(tr("menu.edit.replay"))
        self._act_copy_url.setText(tr("menu.edit.copy_url"))
        self._act_copy_curl.setText(tr("menu.edit.copy_curl"))
        self._act_scope.setText(tr("menu.edit.scope"))

        self._language_menu.setTitle(tr("menu.language"))
        for code, action in self._language_actions.items():
            action.setChecked(code == i18n.language)

        self._help_menu.setTitle(tr("menu.help"))
        self._act_setup.setText(tr("menu.help.setup"))

        # Status — refresh the parts that depend on the current state.
        self._refresh_status_label()
        self._update_count()
        self._update_scope_status()
        self._refresh_address_label()

    # ------------------------------------------------------------------ #
    # Queue polling
    # ------------------------------------------------------------------ #

    def _poll_queue(self) -> None:
        q = self._server.flow_queue
        try:
            while True:
                item = q.get_nowait()
                self._handle_queue_item(item)
        except Empty:
            pass

    def _handle_queue_item(self, item) -> None:
        kind = item[0]

        if kind == "flow":
            flow: FlowModel = item[1]
            self._add_flow(flow)

        elif kind == "ws_message":
            flow_id, msg = item[1], item[2]
            if flow_id in self._flows:
                self._flows[flow_id].ws_messages.append(msg)
                self._traffic_table.update_flow(self._flows[flow_id])
                self._refresh_detail_if_selected(flow_id)

        elif kind == "ws_end":
            flow_id, duration = item[1], item[2]
            if flow_id in self._flows:
                self._flows[flow_id].duration = duration
                self._traffic_table.update_flow(self._flows[flow_id])
                self._refresh_detail_if_selected(flow_id)

        elif kind == "error":
            err_msg = item[1]
            if err_msg.startswith("Capture error:"):
                self.statusBar().showMessage(err_msg, 5000)
            else:
                self._on_proxy_stopped(self._server._generation)
                QMessageBox.critical(
                    self,
                    tr("dialog.start_failed.title"),
                    tr("dialog.start_failed.text", exc=err_msg),
                )

        elif kind == "stopped":
            gen = item[1]
            self._on_proxy_stopped(gen)

    def _add_flow(self, flow: FlowModel) -> None:
        self._flows[flow.id] = flow
        self._traffic_table.append_flow(flow)
        self._trim_old_flows()
        self._update_count()

    def _trim_old_flows(self) -> None:
        overflow = len(self._flows) - MAX_CAPTURED_FLOWS
        if overflow <= 0:
            return
        for old in self._traffic_table.pop_oldest(overflow):
            self._flows.pop(old.id, None)
            if self._selected_flow_id == old.id:
                self._selected_flow_id = None
                self._detail_panel.load(None)

    def _refresh_detail_if_selected(self, flow_id: str) -> None:
        if self._selected_flow_id == flow_id and flow_id in self._flows:
            self._detail_panel.load(self._flows[flow_id])

    # ------------------------------------------------------------------ #
    # Proxy control
    # ------------------------------------------------------------------ #

    def _start_proxy(self) -> None:
        port = self._port_spin.value()
        self._server.port = port
        try:
            self._server.start()
        except Exception as exc:
            QMessageBox.critical(
                self,
                tr("common.error"),
                tr("dialog.start_failed.text", exc=str(exc)),
            )
            return

        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._port_spin.setEnabled(False)
        self._proxy_state = "running"
        self._refresh_status_label()
        self._refresh_address_label()

    def _stop_proxy(self) -> None:
        self._server.stop()
        self._btn_stop.setEnabled(False)
        self._btn_start.setEnabled(False)
        self._port_spin.setEnabled(False)
        self._proxy_state = "stopping"
        self._refresh_status_label()

    def _on_proxy_stopped(self, gen: int) -> None:
        if gen != self._server._generation:
            return
        self._server.running = False
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._port_spin.setEnabled(True)
        self._proxy_state = "stopped"
        self._refresh_status_label()
        self._sb_addr.setText("")

    def _refresh_status_label(self) -> None:
        if self._proxy_state == "running":
            self._sb_status.setText(tr("status.running"))
            self._sb_status.setStyleSheet("color: #a6e3a1;")
        elif self._proxy_state == "stopping":
            self._sb_status.setText(tr("status.stopping"))
            self._sb_status.setStyleSheet("color: #fab387;")
        else:
            self._sb_status.setText(tr("status.stopped"))
            self._sb_status.setStyleSheet("color: #f38ba8;")

    def _refresh_address_label(self) -> None:
        if self._proxy_state != "running":
            self._sb_addr.setText("")
            return
        # Network probing must never break the start flow — fall back to
        # 127.0.0.1 if anything in local_ip() misbehaves (e.g. ipconfig hangs).
        try:
            lan = self._server.local_ip()
        except Exception:
            lan = "127.0.0.1"
        self._sb_addr.setText(
            tr("status.address", port=self._server.port, lan=lan)
        )

    # ------------------------------------------------------------------ #
    # Traffic controls
    # ------------------------------------------------------------------ #

    def _clear_traffic(self) -> None:
        self._flows.clear()
        self._selected_flow_id = None
        self._server.clear_capture()
        self._traffic_table.clear()
        self._detail_panel.load(None)
        self._update_count()

    def _on_filter_changed(self, text: str) -> None:
        self._traffic_table.set_filter(text)

    def _on_flow_selected(self, flow: Optional[FlowModel]) -> None:
        self._selected_flow_id = flow.id if flow else None
        self._detail_panel.load(flow)
        self._btn_replay.setEnabled(flow is not None)

    def _apply_host_filter(self, host: str) -> None:
        self._filter_input.setText(host)

    def _delete_flow(self, flow: FlowModel) -> None:
        self._traffic_table.remove_flow(flow.id)
        self._flows.pop(flow.id, None)
        if self._selected_flow_id == flow.id:
            self._selected_flow_id = None
            self._detail_panel.load(None)
            self._btn_replay.setEnabled(False)
        self._update_count()

    def _selected_flow(self) -> Optional[FlowModel]:
        if self._selected_flow_id is None:
            return None
        return self._flows.get(self._selected_flow_id)

    def _replay_selected(self) -> None:
        flow = self._selected_flow()
        if flow is not None:
            self._replay_flow(flow)

    def _copy_selected_url(self) -> None:
        flow = self._selected_flow()
        if flow is not None:
            self._copy_clipboard(flow.url)

    def _copy_selected_curl(self) -> None:
        flow = self._selected_flow()
        if flow is not None:
            self._copy_clipboard(flow.to_curl())

    @staticmethod
    def _copy_clipboard(text: str) -> None:
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(text or "")

    # ------------------------------------------------------------------ #
    # Capture scope
    # ------------------------------------------------------------------ #

    def _edit_scope(self) -> None:
        allow, block = self._server.scope.snapshot()
        dlg = ScopeDialog(allow=allow, block=block, parent=self)
        dlg.set_apply_callback(self._apply_scope)
        dlg.exec()

    def _apply_scope(self, allow, block) -> None:
        self._server.set_scope(allow=allow, block=block)
        try:
            self._server.scope.save()
        except OSError as exc:
            self.statusBar().showMessage(
                tr("status.scope_save_failed", exc=str(exc)), 5000
            )
        self._update_scope_status()

    def _add_to_scope(self, action: str, pattern: str) -> None:
        """Append a host pattern to allow/block list (from right-click menu)."""
        pattern = (pattern or "").strip()
        if not pattern:
            return
        allow, block = self._server.scope.snapshot()
        target = allow if action == "allow" else block
        kind = tr("status.kind.allow") if action == "allow" else tr("status.kind.block")
        if pattern.lower() in (p.lower() for p in target):
            self.statusBar().showMessage(
                tr("status.scope_exists", pattern=pattern, kind=kind), 3000
            )
            return
        target.append(pattern)
        self._apply_scope(allow, block)
        self.statusBar().showMessage(
            tr("status.scope_added", kind=kind, pattern=pattern), 5000
        )

    def _update_scope_status(self) -> None:
        allow, block = self._server.scope.snapshot()
        if not allow and not block:
            self._sb_scope.setText("")
            self._btn_scope.setStyleSheet("")
            return
        parts = []
        if allow:
            parts.append(f"allow {len(allow)}")
        if block:
            parts.append(f"block {len(block)}")
        self._sb_scope.setText("🎯 " + " · ".join(parts))
        # subtle visual cue on the toolbar button so users can tell at a glance.
        self._btn_scope.setStyleSheet(
            "QPushButton { background-color: #f9e2af; color: #1e1e2e; "
            "border-color: #f9e2af; font-weight: 600; }"
        )

    def _update_count(self) -> None:
        n = self._traffic_table.count()
        if n == 1:
            self._sb_count.setText(tr("status.requests.one"))
        else:
            self._sb_count.setText(tr("status.requests", n=n))

    # ------------------------------------------------------------------ #
    # Request replay
    # ------------------------------------------------------------------ #

    def _replay_flow(self, flow: FlowModel) -> None:
        def _do_replay() -> None:
            replay_id = f"{flow.id}_replay_{uuid.uuid4().hex[:8]}"
            try:
                with httpx.Client(verify=False, follow_redirects=True, timeout=30) as client:
                    req = client.build_request(
                        method=flow.method,
                        url=flow.url,
                        headers={k: v for k, v in flow.request_headers.items()
                                 if k.lower() not in ("host", "content-length")},
                        content=flow.request_body or None,
                    )
                    resp = client.send(req)

                replayed = FlowModel(
                    id=replay_id,
                    flow_type="http",
                    method=flow.method,
                    scheme=flow.scheme,
                    host=flow.host,
                    path=flow.path,
                    query=flow.query,
                    status_code=resp.status_code,
                    status_message=resp.reason_phrase,
                    request_headers=dict(resp.request.headers),
                    request_body=flow.request_body,
                    response_headers=dict(resp.headers),
                    response_body=resp.content,
                    duration=resp.elapsed.total_seconds(),
                )
                self._server.flow_queue.put(("flow", replayed))
            except Exception as exc:
                error_flow = FlowModel(
                    id=replay_id + "_err",
                    flow_type="http",
                    method=flow.method,
                    scheme=flow.scheme,
                    host=flow.host,
                    path=flow.path,
                    error=str(exc),
                )
                self._server.flow_queue.put(("flow", error_flow))

        t = threading.Thread(target=_do_replay, daemon=True)
        t.start()

    # ------------------------------------------------------------------ #
    # Certificate installation
    # ------------------------------------------------------------------ #

    def _install_cert(self) -> None:
        if not self._server.cert_path.exists():
            QMessageBox.information(
                self,
                tr("dialog.cert.title"),
                tr("dialog.cert.not_generated"),
            )
            return

        if self._server.cert_installed():
            QMessageBox.information(
                self,
                tr("dialog.cert.title"),
                tr("dialog.cert.already_installed"),
            )
            return

        reply = QMessageBox.question(
            self,
            tr("dialog.cert.confirm.title"),
            tr("dialog.cert.confirm.text"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        ok, msg = self._server.install_cert_macos()
        if ok:
            QMessageBox.information(self, tr("dialog.cert.title"), msg)
        else:
            QMessageBox.warning(self, tr("dialog.cert.title"), msg)

    # ------------------------------------------------------------------ #
    # Setup help
    # ------------------------------------------------------------------ #

    def _show_setup(self) -> None:
        lan = self._server.local_ip()
        QMessageBox.information(
            self,
            tr("dialog.setup.title"),
            tr("dialog.setup.text", lan=lan),
        )

    def closeEvent(self, event) -> None:
        self._server.stop()
        self._timer.stop()
        super().closeEvent(event)
