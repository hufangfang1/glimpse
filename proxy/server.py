"""
ProxyServer — wraps mitmproxy in a background daemon thread so the
Qt event loop can run freely in the main thread.
"""
from __future__ import annotations

import asyncio
import socket
import subprocess
import threading
from pathlib import Path
from queue import Queue

from .addon import GlimpseAddon
from .scope import Scope


class ProxyServer:
    """Manages the mitmproxy instance in a background thread.

    A single asyncio event loop runs forever in a dedicated daemon thread.
    Each start() submits a new _run_proxy coroutine to that loop via
    run_coroutine_threadsafe(), so the loop is NEVER closed between sessions.
    """

    def __init__(self, port: int = 9090, scope: Scope | None = None) -> None:
        self.port = port
        self.flow_queue: Queue = Queue()
        self.scope = scope or Scope()
        self._master = None
        self._addon: GlimpseAddon | None = None
        self.running = False
        self._stop_event = threading.Event()
        self._generation: int = 0

        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._loop.run_forever,
            daemon=True,
            name="mitmproxy-loop",
        )
        self._loop_thread.start()

    # ------------------------------------------------------------------ #
    # Public control API
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        if self.running:
            return
        self._generation += 1
        self._stop_event.clear()
        gen = self._generation
        asyncio.run_coroutine_threadsafe(self._run_proxy(gen), self._loop)
        self.running = True

    def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        self._stop_event.set()

    def change_port(self, port: int) -> None:
        """Stop (if running); port change takes effect on next start()."""
        if self.running:
            self.stop()
        self.port = port

    def clear_capture(self) -> None:
        if self._addon is not None:
            self._addon.clear()

    def set_scope(self, allow: list[str], block: list[str]) -> None:
        """Update the live capture scope (takes effect immediately)."""
        self.scope.update(allow=allow, block=block)
        # Also push to mitmproxy so non-allowed HTTPS hosts skip MITM entirely
        # (otherwise apps with SSL pinning, e.g. Lark, break on TLS handshake).
        self._apply_scope_to_master()

    def _apply_scope_to_master(self) -> None:
        master = self._master
        if master is None:
            return
        allow_re, block_re = self.scope.to_mitm_patterns()

        async def _update() -> None:
            try:
                master.options.update(
                    allow_hosts=allow_re,
                    ignore_hosts=block_re,
                )
            except Exception as exc:
                self.flow_queue.put(("error", f"Capture error: scope update failed: {exc}"))

        asyncio.run_coroutine_threadsafe(_update(), self._loop)

    # ------------------------------------------------------------------ #
    # Certificate helpers
    # ------------------------------------------------------------------ #

    @property
    def cert_path(self) -> Path:
        return Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.pem"

    def cert_installed(self) -> bool:
        if not self.cert_path.exists():
            return False
        try:
            result = subprocess.run(
                [
                    "security", "find-certificate",
                    "-c", "mitmproxy",
                    "/Library/Keychains/System.keychain",
                ],
                capture_output=True,
            )
            return result.returncode == 0
        except OSError:
            return False

    def install_cert_macos(self) -> tuple[bool, str]:
        """Install CA cert via osascript (prompts for admin password)."""
        if not self.cert_path.exists():
            return False, "证书文件尚未生成，请先启动代理后再试"

        cert = str(self.cert_path)
        script = (
            f'do shell script "security add-trusted-cert -d -r trustRoot '
            f'-k /Library/Keychains/System.keychain \'{cert}\'" '
            f"with administrator privileges"
        )
        try:
            subprocess.run(
                ["osascript", "-e", script],
                check=True,
                capture_output=True,
                text=True,
            )
            return True, "证书已成功安装到系统钥匙串，请重启浏览器后生效。"
        except subprocess.CalledProcessError as exc:
            err = (exc.stderr or exc.stdout or str(exc)).strip()
            if "User canceled" in err or "用户取消" in err:
                return False, "已取消安装。"
            return False, f"安装失败：{err}"
        except OSError as exc:
            return False, f"无法调用 osascript：{exc}"

    @staticmethod
    def local_ip() -> str:
        """Best-effort LAN address for mobile device proxy setup."""
        import platform
        import subprocess

        if platform.system() == "Darwin":
            for iface in ("en0", "en1"):
                try:
                    result = subprocess.run(
                        ["ipconfig", "getifaddr", iface],
                        capture_output=True,
                        text=True,
                        timeout=2,
                    )
                    ip = result.stdout.strip()
                    if result.returncode == 0 and ip:
                        return ip
                except OSError:
                    pass

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                ip = sock.getsockname()[0]
                # 198.18.0.0/15 is often a VPN/tunnel interface, not reachable from phone.
                if not ip.startswith("198.18."):
                    return ip
        except OSError:
            pass
        return "127.0.0.1"

    # ------------------------------------------------------------------ #
    # Internal — runs inside the persistent self._loop
    # ------------------------------------------------------------------ #

    async def _shutdown_servers(self, master) -> None:
        """Release listening sockets — mitmproxy does not do this on should_exit."""
        try:
            ps = master.addons.get("proxyserver")
            if ps:
                await ps.servers.update([])
        except Exception:
            pass

    async def _run_proxy(self, gen: int) -> None:
        from mitmproxy import options
        from mitmproxy.tools.dump import DumpMaster

        master = None
        try:
            opts = options.Options(
                listen_host="0.0.0.0",
                listen_port=self.port,
            )
            # Apply scope at startup — non-allowed HTTPS hosts will be passed
            # through untouched, so SSL-pinned apps (Lark, banking, etc.) keep
            # working when the user has set a whitelist.
            allow_re, block_re = self.scope.to_mitm_patterns()
            if allow_re:
                opts.allow_hosts = allow_re
            if block_re:
                opts.ignore_hosts = block_re

            master = DumpMaster(opts, with_termlog=False, with_dumper=False)
            addon = GlimpseAddon(self.flow_queue, scope=self.scope)
            self._addon = addon
            master.addons.add(addon)
            self._master = master
        except Exception as exc:
            self.flow_queue.put(("error", str(exc)))
            self.flow_queue.put(("stopped", gen))
            return

        async def _stop_watcher() -> None:
            while not self._stop_event.is_set():
                await asyncio.sleep(0.1)
            if master is not None:
                master.shutdown()

        watcher = asyncio.ensure_future(_stop_watcher())
        try:
            await master.run()
        except OSError as exc:
            self.flow_queue.put(("error", str(exc)))
        except Exception as exc:
            msg = str(exc)
            if msg:
                self.flow_queue.put(("error", msg))
        finally:
            watcher.cancel()
            try:
                await watcher
            except asyncio.CancelledError:
                pass
            if master is not None:
                await self._shutdown_servers(master)
            self._master = None
            self._addon = None
            self.flow_queue.put(("stopped", gen))
