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
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from proxy.models import FlowModel
from proxy.scope import Scope
from proxy.server import ProxyServer
from gui.themes import DARK
from gui.widgets.traffic_table import TrafficTable
from gui.widgets.detail_panel import DetailPanel
from gui.widgets.scope_dialog import ScopeDialog

MAX_CAPTURED_FLOWS = 2000


class MainWindow(QMainWindow):

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Glimpse — HTTP Debugger")
        self.resize(1280, 780)

        self._server = ProxyServer(port=9090, scope=Scope.load())
        self._flows: Dict[str, FlowModel] = {}
        self._selected_flow_id: Optional[str] = None

        self._build_ui()
        self._build_menu()
        self._apply_theme()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_queue)
        self._timer.start(50)

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        tb = QToolBar("Controls")
        tb.setMovable(False)
        tb.setFloatable(False)
        self.addToolBar(tb)

        self._btn_start = QPushButton("▶  Start")
        self._btn_start.setObjectName("btn_start")
        self._btn_start.setFixedWidth(90)
        self._btn_start.clicked.connect(self._start_proxy)

        self._btn_stop = QPushButton("■  Stop")
        self._btn_stop.setObjectName("btn_stop")
        self._btn_stop.setFixedWidth(90)
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._stop_proxy)

        port_label = QLabel("Port:")
        port_label.setStyleSheet("color: #a6adc8; margin-left: 8px;")
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1024, 65535)
        self._port_spin.setValue(9090)
        self._port_spin.setFixedWidth(70)

        btn_clear = QPushButton("🗑  Clear")
        btn_clear.setFixedWidth(80)
        btn_clear.clicked.connect(self._clear_traffic)

        filter_label = QLabel("Filter:")
        filter_label.setStyleSheet("color: #a6adc8; margin-left: 8px;")
        self._filter_input = QLineEdit()
        self._filter_input.setPlaceholderText("host / path / method…")
        self._filter_input.setFixedWidth(220)
        self._filter_input.textChanged.connect(self._on_filter_changed)

        self._btn_replay = QPushButton("↩  Replay")
        self._btn_replay.setFixedWidth(96)
        self._btn_replay.setEnabled(False)
        self._btn_replay.setToolTip("Replay the selected request  (⇧⌘R)")
        self._btn_replay.clicked.connect(self._replay_selected)

        self._btn_scope = QPushButton("🎯 Scope")
        self._btn_scope.setFixedWidth(90)
        self._btn_scope.setToolTip("Edit allow / block host patterns  (⌘L)")
        self._btn_scope.clicked.connect(self._edit_scope)

        btn_cert = QPushButton("🔐 Install Cert")
        btn_cert.setFixedWidth(110)
        btn_cert.setToolTip("Install mitmproxy CA certificate into macOS system keychain")
        btn_cert.clicked.connect(self._install_cert)

        tb.addWidget(self._btn_start)
        tb.addWidget(self._btn_stop)
        tb.addSeparator()
        tb.addWidget(port_label)
        tb.addWidget(self._port_spin)
        tb.addSeparator()
        tb.addWidget(btn_clear)
        tb.addWidget(self._btn_replay)
        tb.addSeparator()
        tb.addWidget(filter_label)
        tb.addWidget(self._filter_input)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        tb.addWidget(self._btn_scope)
        tb.addWidget(btn_cert)

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

        self._sb_status = QLabel("● Stopped")
        self._sb_status.setStyleSheet("color: #f38ba8;")
        self._sb_count = QLabel("0 requests")
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

        file_menu = menu.addMenu("File")
        act_start = QAction("Start Proxy", self)
        act_start.setShortcut(QKeySequence("Meta+R"))
        act_start.triggered.connect(self._start_proxy)
        file_menu.addAction(act_start)

        act_stop = QAction("Stop Proxy", self)
        act_stop.setShortcut(QKeySequence("Meta+."))
        act_stop.triggered.connect(self._stop_proxy)
        file_menu.addAction(act_stop)

        file_menu.addSeparator()
        act_quit = QAction("Quit", self)
        act_quit.setShortcut(QKeySequence("Meta+Q"))
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        edit_menu = menu.addMenu("Edit")
        act_clear = QAction("Clear Traffic", self)
        act_clear.setShortcut(QKeySequence("Meta+K"))
        act_clear.triggered.connect(self._clear_traffic)
        edit_menu.addAction(act_clear)

        act_replay = QAction("Replay Selected", self)
        act_replay.setShortcut(QKeySequence("Meta+Shift+R"))
        act_replay.triggered.connect(self._replay_selected)
        edit_menu.addAction(act_replay)

        act_copy_url = QAction("Copy URL", self)
        act_copy_url.setShortcut(QKeySequence("Meta+Shift+C"))
        act_copy_url.triggered.connect(self._copy_selected_url)
        edit_menu.addAction(act_copy_url)

        act_copy_curl = QAction("Copy as cURL", self)
        act_copy_curl.setShortcut(QKeySequence("Meta+Alt+C"))
        act_copy_curl.triggered.connect(self._copy_selected_curl)
        edit_menu.addAction(act_copy_curl)

        edit_menu.addSeparator()
        act_scope = QAction("Capture Scope…", self)
        act_scope.setShortcut(QKeySequence("Meta+L"))
        act_scope.triggered.connect(self._edit_scope)
        edit_menu.addAction(act_scope)

        help_menu = menu.addMenu("Help")
        act_setup = QAction("Setup Instructions", self)
        act_setup.triggered.connect(self._show_setup)
        help_menu.addAction(act_setup)

    def _apply_theme(self) -> None:
        self.setStyleSheet(DARK)

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
                QMessageBox.critical(self, "代理启动失败", err_msg)

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
            QMessageBox.critical(self, "Error", f"Failed to start proxy: {exc}")
            return

        lan = self._server.local_ip()
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._port_spin.setEnabled(False)
        self._sb_status.setText("● Running")
        self._sb_status.setStyleSheet("color: #a6e3a1;")
        self._sb_addr.setText(
            f"127.0.0.1:{port}  ·  LAN {lan}:{port}  ·  请配置浏览器/系统 HTTP 代理"
        )

    def _stop_proxy(self) -> None:
        self._server.stop()
        self._btn_stop.setEnabled(False)
        self._btn_start.setEnabled(False)
        self._port_spin.setEnabled(False)
        self._sb_status.setText("● Stopping…")
        self._sb_status.setStyleSheet("color: #fab387;")

    def _on_proxy_stopped(self, gen: int) -> None:
        if gen != self._server._generation:
            return
        self._server.running = False
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._port_spin.setEnabled(True)
        self._sb_status.setText("● Stopped")
        self._sb_status.setStyleSheet("color: #f38ba8;")
        self._sb_addr.setText("")

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
            self.statusBar().showMessage(f"Scope 保存失败: {exc}", 5000)
        self._update_scope_status()

    def _add_to_scope(self, action: str, pattern: str) -> None:
        """Append a host pattern to allow/block list (from right-click menu)."""
        pattern = (pattern or "").strip()
        if not pattern:
            return
        allow, block = self._server.scope.snapshot()
        target = allow if action == "allow" else block
        if pattern.lower() in (p.lower() for p in target):
            self.statusBar().showMessage(
                f"'{pattern}' 已在{('白' if action == 'allow' else '黑')}名单中", 3000
            )
            return
        target.append(pattern)
        self._apply_scope(allow, block)
        kind = "白" if action == "allow" else "黑"
        self.statusBar().showMessage(
            f"已加入{kind}名单：{pattern} · 长连接需让 App 重连后生效", 5000
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
        self._sb_count.setText(f"{n} request{'s' if n != 1 else ''}")

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
                self, "安装证书",
                "证书文件尚未生成。\n\n请先点击 ▶ Start 启动代理，\n"
                "mitmproxy 会自动在 ~/.mitmproxy/ 生成 CA 证书。"
            )
            return

        if self._server.cert_installed():
            QMessageBox.information(self, "安装证书", "mitmproxy CA 证书已在系统钥匙串中。")
            return

        reply = QMessageBox.question(
            self, "安装 HTTPS 证书",
            "将把 mitmproxy CA 证书安装到系统钥匙串（需要输入管理员密码）。\n\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        ok, msg = self._server.install_cert_macos()
        if ok:
            QMessageBox.information(self, "安装证书", msg)
        else:
            QMessageBox.warning(self, "安装证书", msg)

    # ------------------------------------------------------------------ #
    # Setup help
    # ------------------------------------------------------------------ #

    def _show_setup(self) -> None:
        lan = self._server.local_ip()
        QMessageBox.information(
            self, "Setup Instructions",
            "1. Click ▶ Start to launch the proxy (default port 9090)\n\n"
            "2. Desktop browser — set HTTP proxy to:\n"
            "   Host: 127.0.0.1   Port: 9090\n\n"
            "3. Mobile device (same Wi-Fi) — set HTTP proxy to:\n"
            f"   Host: {lan}   Port: 9090\n\n"
            "4. For HTTPS decryption, click 🔐 Install Cert\n"
            "   (macOS will prompt for administrator password)\n\n"
            "5. On iOS/Android, also install the cert from http://mitm.it\n\n"
            "6. Filter traffic using the search bar in the toolbar."
        )

    def closeEvent(self, event) -> None:
        self._server.stop()
        self._timer.stop()
        super().closeEvent(event)
