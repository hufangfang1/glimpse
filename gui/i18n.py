"""
Lightweight i18n for Glimpse.

The translator stores the current language in ~/.glimpse/settings.json and
emits ``language_changed`` whenever it flips. Widgets subscribe to that
signal and call their own ``retranslate()`` method to refresh their visible
strings without having to be rebuilt.

Usage::

    from gui.i18n import i18n, tr

    label.setText(tr("toolbar.start"))
    i18n.language_changed.connect(self.retranslate)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from PyQt6.QtCore import QObject, pyqtSignal


SETTINGS_DIR = Path.home() / ".glimpse"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"

DEFAULT_LANG = "zh"

LANGUAGES: Dict[str, str] = {
    "zh": "中文",
    "en": "English",
}


# ─────────────────────────────────────────────────────────────────────────────
# String tables
# ─────────────────────────────────────────────────────────────────────────────

_EN: Dict[str, str] = {
    # Window / generic
    "app.title": "Glimpse — HTTP Debugger",
    "common.ok": "OK",
    "common.cancel": "Cancel",
    "common.save": "Save",
    "common.apply": "Apply",
    "common.clear_all": "Clear All",
    "common.error": "Error",

    # Toolbar
    "toolbar.controls": "Controls",
    "toolbar.start": "▶  Start",
    "toolbar.stop": "■  Stop",
    "toolbar.port": "Port:",
    "toolbar.clear": "🗑  Clear",
    "toolbar.filter": "Filter:",
    "toolbar.filter.placeholder": "host / path / method…",
    "toolbar.replay": "↩  Replay",
    "toolbar.replay.tooltip": "Replay the selected request  (⇧⌘R)",
    "toolbar.scope": "🎯 Scope",
    "toolbar.scope.tooltip": "Edit allow / block host patterns  (⌘L)",
    "toolbar.cert": "🔐 Install Cert",
    "toolbar.cert.tooltip": "Install mitmproxy CA certificate into macOS system keychain",

    # Status bar
    "status.stopped": "● Stopped",
    "status.running": "● Running",
    "status.stopping": "● Stopping…",
    "status.requests": "{n} requests",
    "status.requests.one": "1 request",
    "status.address": "127.0.0.1:{port}  ·  LAN {lan}:{port}  ·  configure HTTP proxy in your browser/system",
    "status.scope_save_failed": "Failed to save scope: {exc}",
    "status.scope_added": "Added to {kind}list: {pattern} · keep-alive connections need an app reconnect",
    "status.scope_exists": "'{pattern}' is already in the {kind}list",
    "status.kind.allow": "allow",
    "status.kind.block": "block",

    # Menus
    "menu.file": "File",
    "menu.file.start": "Start Proxy",
    "menu.file.stop": "Stop Proxy",
    "menu.file.quit": "Quit",
    "menu.edit": "Edit",
    "menu.edit.clear": "Clear Traffic",
    "menu.edit.replay": "Replay Selected",
    "menu.edit.copy_url": "Copy URL",
    "menu.edit.copy_curl": "Copy as cURL",
    "menu.edit.scope": "Capture Scope…",
    "menu.language": "Language",
    "menu.help": "Help",
    "menu.help.setup": "Setup Instructions",

    # Dialogs — proxy / cert / setup
    "dialog.start_failed.title": "Failed to start proxy",
    "dialog.start_failed.text": "Failed to start proxy: {exc}",
    "dialog.cert.title": "Install Certificate",
    "dialog.cert.not_generated": (
        "The certificate has not been generated yet.\n\n"
        "Please click ▶ Start to launch the proxy first; mitmproxy will\n"
        "automatically create the CA certificate under ~/.mitmproxy/."
    ),
    "dialog.cert.already_installed": "The mitmproxy CA certificate is already in the system keychain.",
    "dialog.cert.confirm.title": "Install HTTPS Certificate",
    "dialog.cert.confirm.text": (
        "About to install the mitmproxy CA certificate into the system keychain "
        "(requires administrator password).\n\nContinue?"
    ),
    "dialog.cert.install_failed": "Installation failed: {err}",
    "dialog.cert.cert_missing": "Certificate file not generated. Please start the proxy first.",
    "dialog.cert.installed_ok": "Certificate installed into the system keychain. Restart your browser to apply.",
    "dialog.cert.cancelled": "Installation cancelled.",
    "dialog.cert.osascript_failed": "Failed to invoke osascript: {exc}",
    "dialog.setup.title": "Setup Instructions",
    "dialog.setup.text": (
        "1. Click ▶ Start to launch the proxy (default port 9090)\n\n"
        "2. Desktop browser — set HTTP proxy to:\n"
        "   Host: 127.0.0.1   Port: 9090\n\n"
        "3. Mobile device (same Wi-Fi) — set HTTP proxy to:\n"
        "   Host: {lan}   Port: 9090\n\n"
        "4. For HTTPS decryption, click 🔐 Install Cert\n"
        "   (macOS will prompt for administrator password)\n\n"
        "5. On iOS/Android, also install the cert from http://mitm.it\n\n"
        "6. Filter traffic using the search bar in the toolbar."
    ),

    # Detail panel — placeholder & tabs
    "detail.placeholder": "← Select a request to inspect",
    "detail.tab.overview": "Overview",
    "detail.tab.request": "Request",
    "detail.tab.response": "Response",
    "detail.tab.websocket": "WebSocket",

    # Overview tab
    "overview.url": "URL",
    "overview.method": "Method",
    "overview.status": "Status",
    "overview.host": "Host",
    "overview.size": "Size",
    "overview.duration": "Duration",
    "overview.timestamp": "Timestamp",
    "overview.content_type": "Content-Type",
    "overview.replay": "↩ Replay",

    # Request / Response sections
    "section.headers": "Headers",
    "section.body": "Body",
    "headers.empty": "— no headers —",
    "body.empty": "— empty body —",
    "body.binary_image": "[Binary image: {ctype}, {size}]",
    "ws.empty": "— no WebSocket messages —",

    # Body toolbar
    "body.tree": "Tree",
    "body.raw": "Raw",
    "body.expand_all": "Expand All",
    "body.collapse_all": "Collapse All",
    "body.find": "🔍 Find",
    "body.find.tooltip": "Find in body  (⌘F)",
    "find.placeholder": "Find in body…",
    "find.prev.tooltip": "Previous match  (⇧⏎)",
    "find.next.tooltip": "Next match  (⏎)",
    "find.close.tooltip": "Close  (Esc)",
    "find.matches": "{n} matches",
    "find.matches.one": "1 match",
    "find.matches.pos": "{cur} / {total}",

    # Traffic table — headers
    "col.seq": "#",
    "col.method": "Method",
    "col.status": "Status",
    "col.host": "Host",
    "col.path": "Path",
    "col.type": "Type",
    "col.size": "Size",
    "col.duration": "Duration",
    "col.time": "Time",

    # Traffic table — context menu
    "ctx.copy_url": "Copy URL",
    "ctx.copy_curl": "Copy as cURL",
    "ctx.copy_host": "Copy Host",
    "ctx.copy_path": "Copy Path",
    "ctx.copy_body": "Copy Response Body",
    "ctx.replay": "Replay Request",
    "ctx.filter_host": "Filter by host  ·  {host}",
    "ctx.add_allow": "Add to allowlist",
    "ctx.add_block": "Add to blocklist",
    "ctx.delete": "Delete",

    # Scope dialog
    "scope.title": "Capture Scope",
    "scope.allow.title": "Allow (whitelist)",
    "scope.block.title": "Block (blacklist)",
    "scope.allow.placeholder": "empty = capture all hosts\nexample:\n  api.example.com\n  *.example.com",
    "scope.block.placeholder": "empty = nothing blocked\nexample:\n  *.apple.com\n  *.icloud.com\n  *.gvt1.com",
    "scope.hint": (
        "One host pattern per line. Wildcards * supported, case-insensitive.\n"
        "Example:  api.example.com    *.example.com    *.googleapis.com\n"
        "To match both root and subdomains, add two lines: example.com and *.example.com\n"
        "\n"
        "When the allowlist is non-empty, other hosts are forwarded without TLS\n"
        "interception, so SSL-pinned apps (Lark, WeChat, banking, etc.) keep working.\n"
        "Blocklist takes priority. Changes do not affect existing keep-alive\n"
        "connections — the app needs to reconnect."
    ),
}


_ZH: Dict[str, str] = {
    # Window / generic
    "app.title": "Glimpse — HTTP 抓包工具",
    "common.ok": "确定",
    "common.cancel": "取消",
    "common.save": "保存",
    "common.apply": "应用",
    "common.clear_all": "全部清空",
    "common.error": "错误",

    # Toolbar
    "toolbar.controls": "控制",
    "toolbar.start": "▶  启动",
    "toolbar.stop": "■  停止",
    "toolbar.port": "端口：",
    "toolbar.clear": "🗑  清空",
    "toolbar.filter": "过滤：",
    "toolbar.filter.placeholder": "host / path / method…",
    "toolbar.replay": "↩  重放",
    "toolbar.replay.tooltip": "重放当前选中的请求  (⇧⌘R)",
    "toolbar.scope": "🎯 抓包范围",
    "toolbar.scope.tooltip": "编辑白名单 / 黑名单  (⌘L)",
    "toolbar.cert": "🔐 安装证书",
    "toolbar.cert.tooltip": "把 mitmproxy CA 证书安装到 macOS 系统钥匙串",

    # Status bar
    "status.stopped": "● 已停止",
    "status.running": "● 运行中",
    "status.stopping": "● 正在停止…",
    "status.requests": "{n} 个请求",
    "status.requests.one": "1 个请求",
    "status.address": "127.0.0.1:{port}  ·  LAN {lan}:{port}  ·  请配置浏览器/系统 HTTP 代理",
    "status.scope_save_failed": "Scope 保存失败：{exc}",
    "status.scope_added": "已加入{kind}名单：{pattern} · 长连接需让 App 重连后生效",
    "status.scope_exists": "'{pattern}' 已在{kind}名单中",
    "status.kind.allow": "白",
    "status.kind.block": "黑",

    # Menus
    "menu.file": "文件",
    "menu.file.start": "启动代理",
    "menu.file.stop": "停止代理",
    "menu.file.quit": "退出",
    "menu.edit": "编辑",
    "menu.edit.clear": "清空流量",
    "menu.edit.replay": "重放选中请求",
    "menu.edit.copy_url": "复制 URL",
    "menu.edit.copy_curl": "复制为 cURL",
    "menu.edit.scope": "抓包范围…",
    "menu.language": "语言",
    "menu.help": "帮助",
    "menu.help.setup": "使用说明",

    # Dialogs — proxy / cert / setup
    "dialog.start_failed.title": "代理启动失败",
    "dialog.start_failed.text": "代理启动失败：{exc}",
    "dialog.cert.title": "安装证书",
    "dialog.cert.not_generated": (
        "证书文件尚未生成。\n\n请先点击 ▶ 启动 启动代理，\n"
        "mitmproxy 会自动在 ~/.mitmproxy/ 生成 CA 证书。"
    ),
    "dialog.cert.already_installed": "mitmproxy CA 证书已在系统钥匙串中。",
    "dialog.cert.confirm.title": "安装 HTTPS 证书",
    "dialog.cert.confirm.text": "将把 mitmproxy CA 证书安装到系统钥匙串（需要输入管理员密码）。\n\n是否继续？",
    "dialog.cert.install_failed": "安装失败：{err}",
    "dialog.cert.cert_missing": "证书文件尚未生成，请先启动代理后再试",
    "dialog.cert.installed_ok": "证书已成功安装到系统钥匙串，请重启浏览器后生效。",
    "dialog.cert.cancelled": "已取消安装。",
    "dialog.cert.osascript_failed": "无法调用 osascript：{exc}",
    "dialog.setup.title": "使用说明",
    "dialog.setup.text": (
        "1. 点击 ▶ 启动 启动代理（默认端口 9090）\n\n"
        "2. 桌面浏览器 — 将 HTTP 代理设为：\n"
        "   Host: 127.0.0.1   Port: 9090\n\n"
        "3. 移动设备（同一 Wi-Fi）— 将 HTTP 代理设为：\n"
        "   Host: {lan}   Port: 9090\n\n"
        "4. 如需解密 HTTPS，请点击 🔐 安装证书\n"
        "   （macOS 会弹出管理员密码框）\n\n"
        "5. iOS/Android 还需要从 http://mitm.it 安装证书\n\n"
        "6. 工具栏的搜索框可以按 host/path/method 过滤流量。"
    ),

    # Detail panel — placeholder & tabs
    "detail.placeholder": "← 在左侧选择一条请求查看详情",
    "detail.tab.overview": "概览",
    "detail.tab.request": "请求",
    "detail.tab.response": "响应",
    "detail.tab.websocket": "WebSocket",

    # Overview tab
    "overview.url": "URL",
    "overview.method": "方法",
    "overview.status": "状态",
    "overview.host": "Host",
    "overview.size": "大小",
    "overview.duration": "耗时",
    "overview.timestamp": "时间",
    "overview.content_type": "Content-Type",
    "overview.replay": "↩ 重放",

    # Request / Response sections
    "section.headers": "Headers",
    "section.body": "Body",
    "headers.empty": "— 无 headers —",
    "body.empty": "— body 为空 —",
    "body.binary_image": "[二进制图片：{ctype}, {size}]",
    "ws.empty": "— 没有 WebSocket 消息 —",

    # Body toolbar
    "body.tree": "树形",
    "body.raw": "原文",
    "body.expand_all": "全部展开",
    "body.collapse_all": "全部折叠",
    "body.find": "🔍 查找",
    "body.find.tooltip": "在 body 中查找  (⌘F)",
    "find.placeholder": "在 body 中查找…",
    "find.prev.tooltip": "上一个匹配  (⇧⏎)",
    "find.next.tooltip": "下一个匹配  (⏎)",
    "find.close.tooltip": "关闭  (Esc)",
    "find.matches": "{n} 个匹配",
    "find.matches.one": "1 个匹配",
    "find.matches.pos": "{cur} / {total}",

    # Traffic table — headers
    "col.seq": "#",
    "col.method": "方法",
    "col.status": "状态",
    "col.host": "Host",
    "col.path": "Path",
    "col.type": "类型",
    "col.size": "大小",
    "col.duration": "耗时",
    "col.time": "时间",

    # Traffic table — context menu
    "ctx.copy_url": "复制 URL",
    "ctx.copy_curl": "复制为 cURL",
    "ctx.copy_host": "复制 Host",
    "ctx.copy_path": "复制 Path",
    "ctx.copy_body": "复制响应体",
    "ctx.replay": "重放请求",
    "ctx.filter_host": "按 host 过滤  ·  {host}",
    "ctx.add_allow": "加入白名单",
    "ctx.add_block": "加入黑名单",
    "ctx.delete": "删除",

    # Scope dialog
    "scope.title": "抓包范围",
    "scope.allow.title": "白名单（Allow）",
    "scope.block.title": "黑名单（Block）",
    "scope.allow.placeholder": "留空 = 抓所有 host\n例如：\n  api.example.com\n  *.example.com",
    "scope.block.placeholder": "留空 = 不屏蔽\n例如：\n  *.apple.com\n  *.icloud.com\n  *.gvt1.com",
    "scope.hint": (
        "每行一个 host 模式，支持通配符 *，大小写不敏感\n"
        "示例：  api.example.com    *.example.com    *.googleapis.com\n"
        "想同时匹配根域名和子域名，请加两行：example.com 和 *.example.com\n"
        "\n"
        "白名单非空时，其他 host 会绕过 mitmproxy 直接转发（不解 TLS），\n"
        "这样飞书、微信、银行等做了证书绑定（SSL pinning）的 App 不会被打断。\n"
        "黑名单优先于白名单。修改对已有长连接不生效，需让 App 重连。"
    ),
}


TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "en": _EN,
    "zh": _ZH,
}


# ─────────────────────────────────────────────────────────────────────────────
# Translator
# ─────────────────────────────────────────────────────────────────────────────

class _I18n(QObject):
    """Process-wide singleton emitting ``language_changed`` on flips."""

    language_changed = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._lang = self._load_language()

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    def _load_language(self) -> str:
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return DEFAULT_LANG
        lang = data.get("language") if isinstance(data, dict) else None
        if isinstance(lang, str) and lang in TRANSLATIONS:
            return lang
        return DEFAULT_LANG

    def _save_language(self) -> None:
        try:
            SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        except OSError:
            return

        data: Dict[str, object] = {}
        if SETTINGS_FILE.exists():
            try:
                loaded = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = loaded
            except (OSError, json.JSONDecodeError):
                pass

        data["language"] = self._lang
        try:
            SETTINGS_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    # ------------------------------------------------------------------ #
    # Public
    # ------------------------------------------------------------------ #

    @property
    def language(self) -> str:
        return self._lang

    def set_language(self, lang: str) -> None:
        if lang not in TRANSLATIONS or lang == self._lang:
            return
        self._lang = lang
        self._save_language()
        self.language_changed.emit(lang)

    def tr(self, key: str, **kwargs) -> str:
        text = TRANSLATIONS.get(self._lang, {}).get(key)
        if text is None:
            text = TRANSLATIONS.get("en", {}).get(key, key)
        if kwargs:
            try:
                return text.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                return text
        return text


i18n = _I18n()


def tr(key: str, **kwargs) -> str:
    """Module-level shortcut around the singleton translator."""
    return i18n.tr(key, **kwargs)
