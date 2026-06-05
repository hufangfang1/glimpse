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
    "status.proxy_restarting": "● Proxy restarted (network change detected)",
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
    "ctx.edit": "Edit / Compose…",
    "ctx.filter_host": "Filter by host  ·  {host}",
    "ctx.add_allow": "Add to allowlist",
    "ctx.add_block": "Add to blocklist",
    "ctx.delete": "Delete",

    # CORS diagnostics
    "cors.hint.blocked": (
        "⚠  Cross-origin request from {origin} — no CORS headers in response, "
        "browser / WebView will block this."
    ),
    "cors.hint.allowed": (
        "✓  Cross-origin request from {origin} — CORS headers present, "
        "browser / WebView will allow this."
    ),

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

    # Request editor
    "toolbar.collections": "📝 Collections",
    "toolbar.collections.tooltip": "Open the request editor / saved collections",
    "editor.title": "Request Editor",
    "editor.saved": "✓ Saved",
    "editor.new_group": "+ New Group",
    "editor.rename_group": "Rename Group",
    "editor.delete_group": "Delete Group",
    "editor.delete_request": "Delete Request",
    "editor.group_name": "Group name:",
    "editor.confirm_delete": "Delete this and all requests inside it?",
    "editor.send": "Send",
    "editor.sending": "Sending…",
    "editor.save": "Save",
    "editor.save_as": "Save As…",
    "editor.save.tooltip": "Update the open saved request, or save into the default group if this is a new draft",
    "editor.save_as.tooltip": "Always save as a new entry and choose a group",
    "editor.choose_group": "Save into group:",
    "editor.name.label": "Name",
    "editor.name.placeholder": "/api/path",
    "editor.name.tooltip": "Label shown in the collections list only — does not change URL, method, or body. Applied when you click Save.",
    "editor.no_url": "Please enter a URL first.",
    "editor.no_response": "— no response yet —",
    "editor.error": "Request failed: {err}",
    "editor.response_status": "{code} {reason}   ·   {size}   ·   {dur}",
    "editor.tab.params": "Params",
    "editor.tab.headers": "Headers",
    "editor.tab.cookies": "Cookies",
    "editor.tab.body": "Body",
    "editor.kv.key": "Key",
    "editor.kv.value": "Value",
    "editor.kv.delete": "Remove row",
    "editor.sync_cookie": "Sync Cookies",
    "editor.cookie.captured": "From captured traffic",
    "editor.cookie.chrome": "From Chrome (login keychain)",
    "editor.cookie.safari": "From Safari",
    "editor.cookie.no_host": "Enter a valid URL with a host first.",
    "editor.cookie.none": "No cookies found for {host} via {source}.",
    "editor.cookie.chrome_wait": "Waiting for Keychain access…\n\nIf macOS prompts you, click Allow (or Always Allow).\nThis may take a moment on first use.",
    "editor.cookie.chrome_keychain_denied": "Keychain access was denied or cancelled.\n\nOpen Keychain Access and ensure Glimpse (or Terminal) may read \"Chrome Safe Storage\".",
    "editor.cookie.chrome_keychain_unavailable": "Could not read the Chrome Safe Storage key from Keychain.\n\nTry again and approve the prompt, or use \"From captured traffic\" instead.",
    "editor.cookie.chrome_no_database": "No Chrome / Edge cookie database found.\n\nMake sure the browser is installed and you have visited this site at least once.",
    "editor.cookie.chrome_decrypt": "Cookies for this site are encrypted in a format Glimpse cannot decrypt (e.g. Chrome 127+ app-bound cookies).\n\nUse \"From captured traffic\" while browsing through the proxy.",
    "editor.cookie.chrome_no_session": "Chrome session cookies (e.g. PHPSESSID) could not be decrypted.\n\nChrome 127+ protects them with app-bound encryption. Use the steps in the next tip instead of \"From Chrome\".",
    "editor.cookie.auth_tip": "Login was rejected even though cookies were sent. Try:\n\n1. Set the method to GET if you opened this URL in the browser address bar.\n2. Start Glimpse proxy, visit the site in Chrome with the system proxy enabled, then use Sync Cookies → \"From captured traffic\" — this copies the exact Cookie header the browser sent.\n3. Avoid re-syncing from Chrome if PHPSESSID is missing or looks wrong.",
    "editor.format_json": "Format JSON",
    "editor.body.not_json": "Body is not valid JSON.",
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
    "status.proxy_restarting": "● 代理已自动重启（检测到网络变化）",
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
    "dialog.cert.confirm.text": "将把 mitmproxy CA 证书安装到登录鬥北串（login keychain）。\n\n是否继续？",
    "dialog.cert.install_failed": "安装失败：{err}",
    "dialog.cert.cert_missing": "证书文件尚未生成，请先启动代理后再试",
    "dialog.cert.installed_ok": "证书已成功安装到登录鬥北串，请重启浏览器后生效。",
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
    "ctx.edit": "编辑 / 发起请求…",
    "ctx.filter_host": "按 host 过滤  ·  {host}",
    "ctx.add_allow": "加入白名单",
    "ctx.add_block": "加入黑名单",
    "ctx.delete": "删除",

    # CORS diagnostics
    "cors.hint.blocked": (
        "⚠  跨域请求（来源：{origin}）— 响应中没有 CORS 头，"
        "浏览器 / WebView 将拦截此请求。"
    ),
    "cors.hint.allowed": (
        "✓  跨域请求（来源：{origin}）— 响应包含 CORS 头，"
        "浏览器 / WebView 会放行。"
    ),

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

    # Request editor
    "toolbar.collections": "📝 请求集",
    "toolbar.collections.tooltip": "打开请求编辑器 / 保存的请求集",
    "editor.title": "请求编辑器",
    "editor.saved": "✓ 已保存",
    "editor.new_group": "+ 新建分组",
    "editor.rename_group": "重命名分组",
    "editor.delete_group": "删除分组",
    "editor.delete_request": "删除请求",
    "editor.group_name": "分组名称：",
    "editor.confirm_delete": "确定删除该分组及其内所有请求？",
    "editor.send": "发送",
    "editor.sending": "发送中…",
    "editor.save": "保存",
    "editor.save_as": "另存为…",
    "editor.save.tooltip": "更新当前已打开的请求；若是新草稿则保存到默认分组（不弹窗）",
    "editor.save_as.tooltip": "始终另存为一条新记录，并选择分组",
    "editor.choose_group": "保存到分组：",
    "editor.name.label": "名称",
    "editor.name.placeholder": "/api/路径",
    "editor.name.tooltip": "仅用于左侧请求集列表的显示名称，不会修改 URL、方法或 Body；点击「保存」后生效",
    "editor.no_url": "请先填写 URL。",
    "editor.no_response": "— 暂无响应 —",
    "editor.error": "请求失败：{err}",
    "editor.response_status": "{code} {reason}   ·   {size}   ·   {dur}",
    "editor.tab.params": "Params",
    "editor.tab.headers": "Headers",
    "editor.tab.cookies": "Cookies",
    "editor.tab.body": "Body",
    "editor.kv.key": "键",
    "editor.kv.value": "值",
    "editor.kv.delete": "删除此行",
    "editor.sync_cookie": "同步 Cookie",
    "editor.cookie.captured": "从抓包流量提取",
    "editor.cookie.chrome": "从 Chrome 读取（登录钥匙串）",
    "editor.cookie.safari": "从 Safari 读取",
    "editor.cookie.no_host": "请先填写带 host 的合法 URL。",
    "editor.cookie.none": "通过 {source} 未找到 {host} 的 Cookie。",
    "editor.cookie.chrome_wait": "正在等待钥匙串授权…\n\n若系统弹出提示，请点击「允许」或「始终允许」。\n首次使用可能需要稍等片刻。",
    "editor.cookie.chrome_keychain_denied": "钥匙串访问被拒绝或已取消。\n\n可在「钥匙串访问」中为 Glimpse（或终端）开启「Chrome Safe Storage」的读取权限。",
    "editor.cookie.chrome_keychain_unavailable": "无法从钥匙串读取 Chrome 加密密钥。\n\n请重试并在弹窗中允许，或改用「从抓包流量提取」。",
    "editor.cookie.chrome_no_database": "未找到 Chrome / Edge 的 Cookie 数据库。\n\n请确认浏览器已安装，且曾访问过该站点。",
    "editor.cookie.chrome_decrypt": "该站点的 Cookie 使用了 Glimpse 无法解密的格式（例如 Chrome 127+ 的应用绑定加密）。\n\n建议通过代理访问页面后，使用「从抓包流量提取」。",
    "editor.cookie.chrome_no_session": "未能解密 Chrome 的会话 Cookie（如 PHPSESSID）。\n\nChrome 127+ 使用应用绑定加密，离线读取会失败。请按下方「登录失效」提示改用抓包同步。",
    "editor.cookie.auth_tip": "服务端返回「登录失效」，说明 Cookie 未通过校验。建议：\n\n1. 若在浏览器地址栏直接打开该链接，请把请求方式改为 GET（不要用 POST）。\n2. 启动 Glimpse 抓包，Chrome 走系统代理后重新打开该页面，再用「同步 Cookie → 从抓包流量提取」——与浏览器发出的 Cookie 完全一致。\n3. 不要依赖「从 Chrome 读取」补齐 PHPSESSID（新版 Chrome 往往读不到）。",
    "editor.format_json": "格式化 JSON",
    "editor.body.not_json": "Body 不是合法的 JSON。",
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
