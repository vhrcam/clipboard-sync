import asyncio
import json
import logging
import os
import socket
import subprocess
import sys
import threading
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import suppress
from pathlib import Path

import pyperclip
import websockets
from cryptography.exceptions import InvalidTag
from websockets.exceptions import ConnectionClosed, WebSocketException
from zeroconf import IPVersion, ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

from . import VERSION
from .security import Cipher, Identity, PairedDevices, b64, device_id_for, pairing_code, unb64

PORT = int(os.environ.get("COPYCAT_PORT", "8765"))
SERVICE = "_copycat._tcp.local."
PROTOCOL_VERSION = 1
POLL_SECONDS = 0.3
RETRY_SECONDS = 5
HANDSHAKE_SECONDS = 10
MAX_TEXT_BYTES = 5 * 1024 * 1024
MAX_FRAME_BYTES = 2 * MAX_TEXT_BYTES + 4096

log = logging.getLogger("copycat")


def data_dir() -> Path:
    if os.environ.get("COPYCAT_HOME"):
        path = Path(os.environ["COPYCAT_HOME"])
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "CopyCat"
    elif sys.platform == "win32":
        path = Path(os.environ.get("APPDATA", Path.home())) / "CopyCat"
    else:
        path = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "copycat"
    path.mkdir(parents=True, exist_ok=True)
    return path


def this_os() -> str:
    return {"darwin": "mac", "win32": "windows"}.get(sys.platform, "linux")


def device_name() -> str:
    if sys.platform == "darwin":
        try:
            name = subprocess.run(
                ["scutil", "--get", "ComputerName"], capture_output=True, text=True, timeout=2
            ).stdout.strip()
            if name:
                return name
        except (OSError, subprocess.SubprocessError):
            pass
    return os.environ.get("COMPUTERNAME") or socket.gethostname().split(".")[0]


def local_ip() -> str:
    # Connecting a UDP socket sends nothing; it only picks the interface that would be used.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def preview(text: str, limit: int = 40) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit].rstrip() + "…"


class SystemClipboard:
    def read(self):
        try:
            return pyperclip.paste()
        except pyperclip.PyperclipException:
            return None

    def write(self, text: str):
        try:
            pyperclip.copy(text)
        except pyperclip.PyperclipException:
            log.warning("couldn't write the clipboard", exc_info=True)


class ProtocolError(Exception):
    pass


class Link:
    """One connection to another computer, from handshake to close."""

    def __init__(self, ws, manual_target=None):
        self.ws = ws
        self.manual_target = manual_target
        self.cipher = None
        self.peer_id = None
        self.peer_key = None
        self.peer_name = None
        self.peer_os = None
        self.state = "connecting"
        self.code = None
        self.accepted_here = False
        self.accepted_there = False

    async def send(self, message: dict):
        await self.ws.send(self.cipher.seal(message))

    async def recv(self) -> dict:
        frame = await self.ws.recv()
        if not isinstance(frame, bytes):
            raise ProtocolError("expected an encrypted frame")
        return self.cipher.open(frame)


class Engine:
    def __init__(self, on_update, on_event, clipboard=None, folder=None, port=PORT):
        self._on_update = on_update
        self._on_event = on_event
        self.clipboard = clipboard or SystemClipboard()
        self.folder = folder or data_dir()
        self.port = port
        self.identity = Identity(self.folder)
        self.paired = PairedDevices(self.folder)
        self.name = device_name()
        self.os = this_os()
        self.ip = local_ip()
        self.status = "starting"
        self.error = None
        self.link = None
        self.dialing = False
        self.dialing_manual = False
        self.found = {}
        self.manual_hosts = set()
        self.declined = set()
        self.last_seen = None
        self.loop = None
        self._clip_lock = None
        self._tasks = set()
        self._zeroconf = None
        self._browser = None
        self._server = None

    # ---- called from other threads ----

    def start(self):
        threading.Thread(target=lambda: asyncio.run(self._main()), name="copycat-engine", daemon=True).start()

    def submit(self, action: str, *args):
        handler = {"pair": self._do_pair, "connect": self._do_connect, "unpair": self._do_unpair}[action]
        if self.loop:
            self.loop.call_soon_threadsafe(lambda: self._spawn(handler(*args)))

    def stop(self):
        if not self.loop or self.loop.is_closed() or self._stopped.is_set():
            return
        try:
            asyncio.run_coroutine_threadsafe(self._shutdown(), self.loop).result(timeout=3)
        except FutureTimeout:
            log.warning("shutdown timed out")

    def snapshot(self) -> dict:
        link = self.link
        if link and link.peer_id:
            peer = {"name": link.peer_name, "os": link.peer_os, "state": link.state}
        elif link or self.dialing_manual:
            peer = {"name": None, "os": None, "state": "connecting"}
        else:
            peer = None
        pairing = None
        if link and link.state == "pairing":
            pairing = {"code": f"{link.code[:3]} {link.code[3:]}", "waiting": link.accepted_here}
        return {
            "version": VERSION,
            "self": {"name": self.name, "os": self.os, "ip": self.ip, "port": self.port, "state": self.status},
            "peer": peer,
            "pairing": pairing,
            "error": self.error,
        }

    # ---- engine thread ----

    async def _main(self):
        self.loop = asyncio.get_running_loop()
        self._clip_lock = asyncio.Lock()
        self._stopped = asyncio.Event()
        self.last_seen = await asyncio.to_thread(self.clipboard.read)
        try:
            self._server = await websockets.serve(self._session, "0.0.0.0", self.port, max_size=MAX_FRAME_BYTES)
        except OSError:
            log.exception("couldn't listen on port %s", self.port)
            self.status = "error"
            self.error = "CopyCat couldn't start. Is it already open?"
            self._update()
            return
        self.status = "ready"
        log.info("listening on %s:%s as %s (%s)", self.ip, self.port, self.name, self.identity.device_id)
        self._update()
        await self._advertise()
        self._spawn(self._watch_clipboard())
        self._spawn(self._redial_forever())
        await self._stopped.wait()

    async def _shutdown(self):
        for task in list(self._tasks):
            task.cancel()
        if self.link:
            await self.link.ws.close()
        if self._server:
            self._server.close()
        if self._zeroconf:
            await self._zeroconf.async_unregister_all_services()
            await self._zeroconf.async_close()
        self._stopped.set()

    def _spawn(self, coro):
        task = self.loop.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task):
        self._tasks.discard(task)
        if not task.cancelled() and task.exception():
            log.error("background task failed", exc_info=task.exception())

    def _update(self):
        self._on_update(self.snapshot())

    def _notice(self, text: str):
        self._on_event({"kind": "notice", "text": text})

    # ---- discovery ----

    async def _advertise(self):
        try:
            self._zeroconf = AsyncZeroconf(ip_version=IPVersion.V4Only)
            info = AsyncServiceInfo(
                SERVICE,
                f"{self.identity.device_id}.{SERVICE}",
                addresses=[socket.inet_aton(self.ip)],
                port=self.port,
                properties={"id": self.identity.device_id, "v": str(PROTOCOL_VERSION)},
                server=f"copycat-{self.identity.device_id}.local.",
            )
            await self._zeroconf.async_register_service(info)
            self._browser = AsyncServiceBrowser(self._zeroconf.zeroconf, SERVICE, handlers=[self._on_service])
        except OSError:
            log.exception("automatic discovery is unavailable; Connect by IP still works")

    def _on_service(self, zeroconf, service_type, name, state_change):
        if name.startswith(self.identity.device_id):
            return
        if state_change is ServiceStateChange.Removed:
            self.found = {pid: v for pid, v in self.found.items() if v[2] != name}
            return
        self.loop.call_soon_threadsafe(lambda: self._spawn(self._resolve(service_type, name)))

    async def _resolve(self, service_type, name):
        info = AsyncServiceInfo(service_type, name)
        if not await info.async_request(self._zeroconf.zeroconf, 3000):
            return
        peer_id = (info.properties or {}).get(b"id", b"").decode(errors="ignore")
        addresses = info.parsed_addresses(IPVersion.V4Only)
        if not peer_id or peer_id == self.identity.device_id or not addresses or not info.port:
            return
        self.found[peer_id] = (addresses[0], info.port, name)
        log.info("found %s at %s:%s", peer_id, addresses[0], info.port)
        await self._maybe_dial()

    async def _redial_forever(self):
        while True:
            await asyncio.sleep(RETRY_SECONDS)
            await self._maybe_dial()

    async def _maybe_dial(self):
        if self.link or self.dialing or self.status != "ready":
            return
        paired = self.paired.ids()
        targets = []
        for peer_id, (host, port, _) in list(self.found.items()):
            if peer_id in self.declined or (paired and peer_id not in paired):
                continue
            # Only the computer with the lower id dials, so the two never connect to each other twice.
            if self.identity.device_id < peer_id:
                targets.append((host, port))
        targets += sorted(self.manual_hosts)
        for host, port in targets:
            if self.link or await self._dial(host, port):
                return

    async def _dial(self, host, port, manual=False) -> bool:
        self.dialing = True
        self.dialing_manual = manual
        if manual:
            self._update()
        try:
            ws = await websockets.connect(f"ws://{host}:{port}", max_size=MAX_FRAME_BYTES, open_timeout=5)
        except (OSError, asyncio.TimeoutError, WebSocketException) as e:
            log.info("couldn't reach %s:%s (%s)", host, port, e)
            if manual:
                self._notice(f"Couldn't reach {host}. Is CopyCat open there, on the same Wi-Fi?")
            return False
        finally:
            self.dialing = False
            self.dialing_manual = False
            if manual:
                self._update()
        self._spawn(self._session(ws, manual_target=(host, port) if manual else None))
        return True

    # ---- a connection ----

    async def _session(self, ws, manual_target=None):
        if self.link:
            await ws.close()
            return
        link = Link(ws, manual_target)
        self.link = link
        self._update()
        try:
            await asyncio.wait_for(self._handshake(link), HANDSHAKE_SECONDS)
            if link.state == "connected":
                self._connected(link)
            self._update()
            async for frame in ws:
                await self._handle(link, frame)
        except (ConnectionClosed, asyncio.TimeoutError, InvalidTag, ProtocolError, ValueError, KeyError, TypeError) as e:
            log.info("connection ended: %r", e)
        finally:
            if self.link is link:
                self.link = None
            await ws.close()
            self._update()

    async def _handshake(self, link: Link):
        nonce = os.urandom(16)
        await link.ws.send(json.dumps({
            "type": "hello",
            "v": PROTOCOL_VERSION,
            "name": self.name,
            "os": self.os,
            "key": b64(self.identity.public_key),
            "nonce": b64(nonce),
        }))
        hello = json.loads(await link.ws.recv())
        if hello.get("type") != "hello" or hello.get("v") != PROTOCOL_VERSION:
            raise ProtocolError("not a compatible CopyCat")
        peer_key, peer_nonce = unb64(hello["key"]), unb64(hello["nonce"])
        if len(peer_key) != 32 or len(peer_nonce) != 16:
            raise ProtocolError("malformed hello")
        peer_id = device_id_for(peer_key)
        if peer_id == self.identity.device_id:
            raise ProtocolError("connected to myself")

        link.peer_id, link.peer_key = peer_id, peer_key
        link.peer_name = str(hello.get("name") or "Unknown computer")[:48]
        link.peer_os = hello.get("os") if hello.get("os") in ("mac", "windows", "linux") else "linux"
        first, second = sorted([(self.identity.device_id, nonce), (peer_id, peer_nonce)])
        link.cipher = Cipher(self.identity.session_key(peer_key, first[1] + second[1]))

        # The first encrypted message doubles as proof that the other side holds its private key.
        paired_here = self.paired.is_paired(peer_id, peer_key)
        await link.send({"type": "trust", "paired": paired_here})
        reply = await link.recv()
        if reply.get("type") != "trust":
            raise ProtocolError("expected trust")
        if paired_here and reply.get("paired") is True:
            link.state = "connected"
        else:
            link.state = "pairing"
            link.code = pairing_code(self.identity.public_key, peer_key)
        log.info("handshake with %s (%s): %s", link.peer_name, peer_id, link.state)

    async def _handle(self, link: Link, frame):
        if not isinstance(frame, bytes):
            raise ProtocolError("unencrypted frame")
        message = link.cipher.open(frame)
        kind = message.get("type")
        if kind == "pair" and link.state == "pairing":
            if message.get("accept") is not True:
                self.declined.add(link.peer_id)
                self._notice(f"{link.peer_name} chose not to pair.")
                await link.ws.close()
                return
            link.accepted_there = True
            self._finish_pairing(link)
        elif kind == "unpair":
            self.paired.remove(link.peer_id)
            self.declined.add(link.peer_id)
            self._notice(f"{link.peer_name} unpaired from this computer.")
            await link.ws.close()
        elif kind == "clip" and link.state == "connected":
            text = message["text"]
            if not isinstance(text, str):
                raise ProtocolError("clip text must be a string")
            async with self._clip_lock:
                self.last_seen = text
                await asyncio.to_thread(self.clipboard.write, text)
            self._on_event({"kind": "received", "peer": link.peer_name, "preview": preview(text)})

    def _finish_pairing(self, link: Link):
        if link.accepted_here and link.accepted_there:
            self.paired.add(link.peer_id, link.peer_key, link.peer_name)
            link.state = "connected"
            link.code = None
            self._connected(link)
            log.info("paired with %s (%s)", link.peer_name, link.peer_id)
        self._update()

    def _connected(self, link: Link):
        self.declined.discard(link.peer_id)
        if link.manual_target:
            self.manual_hosts.add(link.manual_target)

    # ---- clipboard ----

    async def _watch_clipboard(self):
        while True:
            await asyncio.sleep(POLL_SECONDS)
            async with self._clip_lock:
                current = await asyncio.to_thread(self.clipboard.read)
                if not current or current == self.last_seen:
                    continue
                self.last_seen = current
            link = self.link
            if not link or link.state != "connected":
                continue
            if len(current.encode()) > MAX_TEXT_BYTES:
                self._notice("That copy is too big to sync (5 MB max).")
                continue
            try:
                await link.send({"type": "clip", "text": current})
            except ConnectionClosed:
                continue
            self._on_event({"kind": "sent", "peer": link.peer_name, "preview": preview(current)})

    # ---- actions from the window ----

    async def _do_pair(self, accept: bool):
        link = self.link
        if not link or link.state != "pairing":
            return
        if not accept:
            self.declined.add(link.peer_id)
            with suppress(ConnectionClosed):
                await link.send({"type": "pair", "accept": False})
            await link.ws.close()
            return
        link.accepted_here = True
        with suppress(ConnectionClosed):
            await link.send({"type": "pair", "accept": True})
        self._finish_pairing(link)

    async def _do_connect(self, address: str):
        host, _, port_text = address.strip().partition(":")
        if not host or " " in host:
            self._notice("Type the other computer's IP address, like 192.168.1.20.")
            return
        if self.link:
            self._notice("Already connected. Unpair first to switch computers.")
            return
        await self._dial(host, int(port_text) if port_text.isdigit() else PORT, manual=True)

    async def _do_unpair(self):
        link = self.link
        if not link or not link.peer_id:
            return
        self.paired.remove(link.peer_id)
        self.declined.add(link.peer_id)
        self.manual_hosts.clear()
        with suppress(ConnectionClosed):
            await link.send({"type": "unpair"})
        await link.ws.close()
