import asyncio
import json
import socket
import sys
import time

import pyperclip
import websockets

PORT = 8765
POLL_SECONDS = 0.3
RETRY_SECONDS = 5
MAX_MESSAGE_BYTES = 10 * 1024 * 1024

USAGE = """Usage:
  python clipboard.py server
  python clipboard.py client <server-ip>"""


def preview(text, limit=50):
    flat = text.replace("\n", " ")
    return flat if len(flat) <= limit else flat[:limit] + "..."


def read_clipboard():
    try:
        return pyperclip.paste()
    except pyperclip.PyperclipException:
        return None


def write_clipboard(text):
    try:
        pyperclip.copy(text)
    except pyperclip.PyperclipException as e:
        print(f"[!] couldn't write clipboard: {e}")


def local_ip():
    # Connecting a UDP socket sends nothing; it just reveals which network interface would be used.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


class ClipboardSync:
    def __init__(self):
        self.last_seen = read_clipboard()

    async def send_changes(self, ws):
        while True:
            current = read_clipboard()
            if current is not None and current != self.last_seen:
                self.last_seen = current
                message = {"type": "text", "text": current, "ts": time.time()}
                await ws.send(json.dumps(message))
                print(f"[→ sent] {preview(current)}")
            await asyncio.sleep(POLL_SECONDS)

    async def receive_changes(self, ws):
        async for raw in ws:
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if message.get("type") != "text":
                continue
            text = message["text"]
            # Marking it as seen before writing is what stops it echoing back to the sender.
            self.last_seen = text
            write_clipboard(text)
            print(f"[← recv] {preview(text)}")

    async def run(self, ws):
        tasks = [
            asyncio.create_task(self.send_changes(ws)),
            asyncio.create_task(self.receive_changes(ws)),
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            error = task.exception()
            if error and not isinstance(error, websockets.exceptions.ConnectionClosed):
                raise error


async def run_server():
    sync = ClipboardSync()

    async def handle(ws):
        print(f"[+] connected: {ws.remote_address[0]}")
        await sync.run(ws)
        print("[-] disconnected")

    async with websockets.serve(handle, "0.0.0.0", PORT, max_size=MAX_MESSAGE_BYTES):
        ip = local_ip()
        print(f"[clipboard-sync] server running on {ip}:{PORT}")
        print("[clipboard-sync] on the other computer run:")
        print(f"    python clipboard.py client {ip}")
        await asyncio.Future()


async def run_client(host):
    sync = ClipboardSync()
    uri = f"ws://{host}:{PORT}"
    while True:
        print(f"[clipboard-sync] connecting to {uri}...")
        try:
            async with websockets.connect(uri, max_size=MAX_MESSAGE_BYTES) as ws:
                print("[clipboard-sync] connected, clipboard sync active")
                await sync.run(ws)
            print("[!] connection lost")
        except (OSError, websockets.exceptions.WebSocketException):
            print(f"[!] couldn't reach {uri}")
        print(f"[clipboard-sync] retrying in {RETRY_SECONDS}s")
        await asyncio.sleep(RETRY_SECONDS)


def main():
    args = sys.argv[1:]
    try:
        if args == ["server"]:
            asyncio.run(run_server())
        elif len(args) == 2 and args[0] == "client":
            asyncio.run(run_client(args[1]))
        else:
            print(USAGE)
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n[clipboard-sync] stopped")


if __name__ == "__main__":
    main()
