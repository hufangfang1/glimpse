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

from gui.i18n import tr

from .addon import GlimpseAddon
from .breakpoints import BreakpointRules
from .rules import RuleEngine
from .scope import Scope


class ProxyServer:
    """Manages the mitmproxy instance in a background thread.

    A single asyncio event loop runs forever in a dedicated daemon thread.
    Each start() submits a new _run_proxy coroutine to that loop via
    run_coroutine_threadsafe(), so the loop is NEVER closed between sessions.
    """

    def __init__(
        self,
        port: int = 9090,
        wireguard_port: int = 51820,
        scope: Scope | None = None,
        breakpoints: BreakpointRules | None = None,
        rules: RuleEngine | None = None,
    ) -> None:
        self.port = port
        self.wireguard_port = wireguard_port
        self.wireguard_enabled = False
        self.flow_queue: Queue = Queue()
        self.scope = scope or Scope()
        self.breakpoints = breakpoints or BreakpointRules()
        self.rules = rules or RuleEngine()
        self._master = None
        self._addon: GlimpseAddon | None = None
        self.running = False
        self._stop_event = threading.Event()
        self._generation: int = 0
        self._scope_revision: int = 0
        self._wireguard_config: str | None = None

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
        self._wireguard_config = None
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

    @property
    def wireguard_config(self) -> str | None:
        """Client config for the live WireGuard listener, once it is ready."""
        return self._wireguard_config

    def clear_capture(self) -> None:
        if self._addon is not None:
            self._addon.clear()

    def set_scope(self, allow: list[str], block: list[str]) -> None:
        """Update the live capture scope (takes effect immediately)."""
        old_allow, old_block = self.scope.snapshot()
        self.scope.update(allow=allow, block=block)
        new_allow, new_block = self.scope.snapshot()
        if (new_allow, new_block) == (old_allow, old_block):
            return
        old_allow_set = set(old_allow)
        reconnect_patterns = [p for p in new_allow if p not in old_allow_set]
        should_reconnect = bool(old_allow and reconnect_patterns)
        self._scope_revision += 1
        # Also push to mitmproxy so non-allowed HTTPS hosts skip MITM entirely
        # (otherwise apps with SSL pinning, e.g. Lark, break on TLS handshake).
        self._apply_scope_to_master(
            revision=self._scope_revision,
            reconnect_patterns=reconnect_patterns if should_reconnect else [],
        )

    @property
    def scope_revision(self) -> int:
        return self._scope_revision

    def _apply_scope_to_master(
        self,
        *,
        revision: int,
        reconnect_patterns: list[str],
    ) -> None:
        master = self._master
        if master is None:
            return
        allow_re, ignore_re = self.scope.to_mitm_options()
        addon = self._addon
        generation = self._generation

        async def _update() -> None:
            try:
                if self.wireguard_enabled and addon is not None:
                    # In WireGuard mode, global host options run before the
                    # virtual destination has been resolved back to an SNI.
                    # Scope is applied by GlimpseAddon.tls_clienthello instead.
                    master.options.update(
                        allow_hosts=[],
                        ignore_hosts=[],
                    )
                    if reconnect_patterns:
                        addon.begin_scope_reconnect(
                            generation,
                            revision,
                            reconnect_patterns,
                        )
                        target_ids = addon.passthrough_client_ids(
                            reconnect_patterns
                        )
                        proxyserver = master.addons.get("proxyserver")
                        handlers = (
                            list(proxyserver.connections.values())
                            if proxyserver is not None
                            else []
                        )
                        reset_count = 0
                        for handler in handlers:
                            if handler.client.id not in target_ids:
                                continue
                            try:
                                io = handler.transports[handler.client]
                                if io.writer is not None:
                                    io.writer.close()
                                    reset_count += 1
                            except (KeyError, OSError, RuntimeError):
                                pass
                        self.flow_queue.put(
                            (
                                "scope_reconnecting",
                                generation,
                                revision,
                                reset_count,
                            )
                        )
                        asyncio.create_task(
                            self._scope_reconnect_timeout(
                                addon,
                                generation,
                                revision,
                            )
                        )
                    else:
                        addon.cancel_scope_reconnect()
                        self.flow_queue.put(("scope_applied", generation))
                else:
                    master.options.update(
                        allow_hosts=allow_re,
                        ignore_hosts=ignore_re,
                    )
                    self.flow_queue.put(("scope_applied", generation))
            except Exception as exc:
                self.flow_queue.put(("error", f"Capture error: scope update failed: {exc}"))

        asyncio.run_coroutine_threadsafe(_update(), self._loop)

    async def _scope_reconnect_timeout(
        self,
        addon: GlimpseAddon,
        generation: int,
        revision: int,
    ) -> None:
        await asyncio.sleep(15)
        if (
            generation == self._generation
            and self._addon is addon
            and addon.expire_scope_reconnect(revision)
        ):
            self.flow_queue.put(
                ("scope_reconnect_timeout", generation, revision)
            )

    # ------------------------------------------------------------------ #
    # Breakpoints / interactive intercept
    # ------------------------------------------------------------------ #

    def set_breakpoints(
        self,
        *,
        patterns: list[str] | None = None,
        on_request: bool | None = None,
        on_response: bool | None = None,
        enabled: bool | None = None,
    ) -> None:
        self.breakpoints.update(
            patterns=patterns,
            on_request=on_request,
            on_response=on_response,
            enabled=enabled,
        )

    def set_breakpoints_enabled(self, enabled: bool) -> None:
        self.breakpoints.set_enabled(enabled)

    def release_flow(self, flow_id: str, edits: dict | None) -> None:
        """Resume a held flow (optionally with edits) on the loop thread."""
        addon = self._addon
        if addon is None:
            return

        async def _release() -> None:
            addon.release(flow_id, edits)

        asyncio.run_coroutine_threadsafe(_release(), self._loop)

    def abort_flow(self, flow_id: str) -> None:
        """Kill a held flow (drop the connection) on the loop thread."""
        addon = self._addon
        if addon is None:
            return

        async def _abort() -> None:
            addon.abort(flow_id)

        asyncio.run_coroutine_threadsafe(_abort(), self._loop)

    # ------------------------------------------------------------------ #
    # Mock / rewrite rules
    # ------------------------------------------------------------------ #

    def set_rules(self, rules: list[dict]) -> None:
        """Update live mock/rewrite rules (takes effect immediately)."""
        self.rules.update(rules)

    # ------------------------------------------------------------------ #
    # Certificate helpers
    # ------------------------------------------------------------------ #

    @property
    def cert_path(self) -> Path:
        return Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.pem"

    @property
    def _login_keychain(self) -> str:
        """Path to the current user's login keychain (works on all modern macOS)."""
        return str(Path.home() / "Library" / "Keychains" / "login.keychain-db")

    def cert_installed(self) -> bool:
        if not self.cert_path.exists():
            return False
        try:
            result = subprocess.run(
                [
                    "security", "find-certificate",
                    "-c", "mitmproxy",
                    self._login_keychain,
                ],
                capture_output=True,
            )
            return result.returncode == 0
        except OSError:
            return False

    def install_cert_macos(self) -> tuple[bool, str]:
        """Install CA cert into the user login keychain (no admin password needed).

        Installing into the login keychain avoids the macOS Ventura/Sonoma
        restriction that blocks osascript from modifying the System keychain
        ("no user interaction was possible"). Safari, Chrome, Firefox, and
        URLSession all honour login-keychain trust, which is sufficient for
        local HTTPS debugging.
        """
        if not self.cert_path.exists():
            return False, tr("dialog.cert.cert_missing")

        try:
            subprocess.run(
                [
                    "security", "add-trusted-cert",
                    "-r", "trustRoot",
                    "-k", self._login_keychain,
                    str(self.cert_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            return True, tr("dialog.cert.installed_ok")
        except subprocess.CalledProcessError as exc:
            err = (exc.stderr or exc.stdout or str(exc)).strip()
            return False, tr("dialog.cert.install_failed", err=err)
        except OSError as exc:
            return False, tr("dialog.cert.osascript_failed", exc=str(exc))

    @staticmethod
    def local_ip() -> str:
        """Best-effort LAN address for mobile device proxy setup.

        Never raises — falls back to 127.0.0.1 if every probe fails. We catch
        ``subprocess.SubprocessError`` separately because ``TimeoutExpired``
        is NOT an ``OSError`` and would otherwise crash the caller when
        ``ipconfig`` hangs (which we've seen on machines with stale network
        interfaces).
        """
        import platform
        import subprocess

        def usable(ip: str) -> bool:
            return bool(ip) and not (
                ip.startswith("198.18.") or ip.startswith("198.19.")
            )

        if platform.system() == "Darwin":
            for iface in ("en0", "en1"):
                try:
                    result = subprocess.run(
                        ["ipconfig", "getifaddr", iface],
                        capture_output=True,
                        text=True,
                        timeout=2,
                    )
                except (OSError, subprocess.SubprocessError):
                    continue
                ip = result.stdout.strip()
                if result.returncode == 0 and usable(ip):
                    return ip

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(1.0)
                sock.connect(("8.8.8.8", 80))
                ip = sock.getsockname()[0]
                # 198.18.0.0/15 is often a VPN/tunnel interface, not reachable from phone.
                if usable(ip):
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

    def _rewrite_wireguard_endpoint(self, config: str) -> str:
        """Replace mitmproxy's tunnel-prone endpoint with our LAN-safe address."""
        endpoint = f"Endpoint = {self.local_ip()}:{self.wireguard_port}"
        lines = [
            endpoint if line.lstrip().startswith("Endpoint =") else line
            for line in config.splitlines()
        ]
        return "\n".join(lines)

    async def _watch_wireguard_config(self, master, gen: int) -> None:
        """Publish the generated client config after the WG server is listening."""
        while not self._stop_event.is_set() and gen == self._generation:
            try:
                proxyserver = master.addons.get("proxyserver")
                if proxyserver:
                    for server in proxyserver.servers:
                        if getattr(server.mode, "type_name", None) == "wireguard":
                            config = server.client_conf()
                            if config:
                                self._wireguard_config = (
                                    self._rewrite_wireguard_endpoint(config)
                                )
                                self.flow_queue.put(("wireguard_ready", gen))
                                return
            except Exception:
                # Startup errors are reported by master.run(); this watcher only
                # exposes the optional client config to the GUI.
                pass
            await asyncio.sleep(0.1)

    async def _run_proxy(self, gen: int) -> None:
        from mitmproxy import options
        from mitmproxy.tools.dump import DumpMaster

        master = None
        wireguard_watcher = None
        try:
            modes = [
                f"wireguard@{self.wireguard_port}"
                if self.wireguard_enabled
                else f"regular@{self.port}"
            ]
            opts = options.Options(
                listen_host="0.0.0.0",
                listen_port=self.port,
                mode=modes,
            )
            # Apply scope at startup — non-allowed HTTPS hosts will be passed
            # through untouched, so SSL-pinned apps (Lark, banking, etc.) keep
            # working when the user has set a whitelist.
            if not self.wireguard_enabled:
                allow_re, ignore_re = self.scope.to_mitm_options()
                if allow_re:
                    opts.allow_hosts = allow_re
                if ignore_re:
                    opts.ignore_hosts = ignore_re

            master = DumpMaster(opts, with_termlog=False, with_dumper=False)
            addon = GlimpseAddon(
                self.flow_queue,
                scope=self.scope,
                breakpoints=self.breakpoints,
                rules=self.rules,
                wireguard_mode=self.wireguard_enabled,
            )
            self._addon = addon
            master.addons.add(addon)
            self._master = master
            if self.wireguard_enabled:
                wireguard_watcher = asyncio.create_task(
                    self._watch_wireguard_config(master, gen)
                )
        except Exception as exc:
            self.flow_queue.put(("error", str(exc)))
            self.flow_queue.put(("stopped", gen))
            return

        async def _stop_watcher() -> None:
            while not self._stop_event.is_set():
                await asyncio.sleep(0.1)
            # Release any paused flows first so their suspended request/response
            # hooks resume and exit — otherwise master.run() can wedge waiting on
            # a held coroutine and stop would hang.
            if self._addon is not None:
                self._addon.drain()
            if master is not None:
                master.shutdown()

        watcher = asyncio.ensure_future(_stop_watcher())
        crashed = False
        try:
            await master.run()
            # If master.run() returns while _stop_event is NOT set, mitmproxy
            # exited on its own (network reset, sleep/wake, internal error).
            crashed = not self._stop_event.is_set()
        except OSError as exc:
            self.flow_queue.put(("error", str(exc)))
            crashed = not self._stop_event.is_set()
        except Exception as exc:
            msg = str(exc)
            if msg:
                self.flow_queue.put(("error", msg))
            crashed = not self._stop_event.is_set()
        finally:
            watcher.cancel()
            try:
                await watcher
            except asyncio.CancelledError:
                pass
            if wireguard_watcher is not None:
                wireguard_watcher.cancel()
                try:
                    await wireguard_watcher
                except asyncio.CancelledError:
                    pass
            if master is not None:
                await self._shutdown_servers(master)
            self._master = None
            self._addon = None
            self._wireguard_config = None
            if crashed:
                self.flow_queue.put(("crashed", gen))
            else:
                self.flow_queue.put(("stopped", gen))
