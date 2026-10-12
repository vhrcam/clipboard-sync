import asyncio
import json
import os
import time

import pytest
import websockets

from copycat import engine as engine_module
from copycat.engine import Engine
from copycat.security import b64

BASE_PORT = 28700


class FakeClipboard:
    def __init__(self, text):
        self.text = text

    def read(self):
        return self.text

    def write(self, text):
        self.text = text


def wait_for(condition, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        time.sleep(0.05)
    return False


def state(engine):
    return engine.link.state if engine.link else None


@pytest.fixture(autouse=True)
def no_discovery(monkeypatch):
    # CI machines often block multicast, so these tests link computers with Connect by IP.
    monkeypatch.setattr(engine_module.Engine, "_advertise", lambda self: asyncio.sleep(0))


@pytest.fixture
def make_engine(tmp_path):
    engines = []

    def make(name, offset, folder=None):
        folder = folder or tmp_path / name
        folder.mkdir(exist_ok=True)
        clip = FakeClipboard(f"start {name}")
        events = []
        engine = Engine(on_update=lambda s: None, on_event=events.append, clipboard=clip,
                        folder=folder, port=BASE_PORT + offset)
        engine.name = name
        engine.start()
        assert wait_for(lambda: engine.status == "ready", 5)
        engines.append(engine)
        return engine, clip, events

    yield make
    for engine in engines:
        engine.stop()


def pair(a, b, b_port):
    a.submit("connect", f"127.0.0.1:{b_port}")
    assert wait_for(lambda: state(a) == "pairing" and state(b) == "pairing")
    assert a.snapshot()["pairing"]["code"] == b.snapshot()["pairing"]["code"]
    a.submit("pair", True)
    assert wait_for(lambda: a.snapshot()["pairing"] and a.snapshot()["pairing"]["waiting"], 2)
    assert state(a) == "pairing"
    b.submit("pair", True)
    assert wait_for(lambda: state(a) == "connected" and state(b) == "connected")


def test_pair_and_sync_both_ways(make_engine):
    a, clip_a, events_a = make_engine("A", 1)
    b, clip_b, events_b = make_engine("B", 2)
    pair(a, b, BASE_PORT + 2)

    clip_a.text = "hello from A"
    assert wait_for(lambda: clip_b.text == "hello from A")
    clip_b.text = "héllo 🐱 from B\nsecond line"
    assert wait_for(lambda: clip_a.text == "héllo 🐱 from B\nsecond line")

    time.sleep(1.5)
    assert sum(e["kind"] == "sent" for e in events_a) == 1
    assert sum(e["kind"] == "sent" for e in events_b) == 1


def test_reconnects_without_pairing_again(make_engine, tmp_path):
    a, clip_a, _ = make_engine("A", 3)
    b, _, _ = make_engine("B", 4)
    pair(a, b, BASE_PORT + 4)
    b.stop()
    assert wait_for(lambda: a.link is None)

    b2, clip_b2, _ = make_engine("B", 5, folder=tmp_path / "B")
    a.submit("connect", f"127.0.0.1:{BASE_PORT + 5}")
    assert wait_for(lambda: state(a) == "connected" and state(b2) == "connected")
    clip_a.text = "after restart"
    assert wait_for(lambda: clip_b2.text == "after restart")


def test_not_now_and_unpair(make_engine):
    a, _, events_a = make_engine("A", 6)
    b, _, _ = make_engine("B", 7)
    a.submit("connect", f"127.0.0.1:{BASE_PORT + 7}")
    assert wait_for(lambda: state(b) == "pairing")
    b.submit("pair", False)
    assert wait_for(lambda: a.link is None and b.link is None)
    assert wait_for(lambda: any("chose not to pair" in e.get("text", "") for e in events_a), 2)

    pair(a, b, BASE_PORT + 7)
    a.submit("unpair")
    assert wait_for(lambda: a.link is None and b.link is None)
    assert wait_for(lambda: not a.paired.ids() and not b.paired.ids(), 3)


def test_impostor_without_private_key_is_rejected(make_engine):
    a, _, _ = make_engine("A", 8)
    b, _, events_b = make_engine("B", 9)
    pair(a, b, BASE_PORT + 9)
    a.stop()
    assert wait_for(lambda: b.link is None)

    async def impostor():
        async with websockets.connect(f"ws://127.0.0.1:{BASE_PORT + 9}") as ws:
            await ws.send(json.dumps({"type": "hello", "v": 1, "name": "A", "os": "mac",
                                      "key": b64(a.identity.public_key), "nonce": b64(os.urandom(16))}))
            await ws.recv()
            await ws.send(os.urandom(64))
            with pytest.raises(websockets.exceptions.ConnectionClosed):
                await asyncio.wait_for(ws.recv(), 5)
                await asyncio.wait_for(ws.recv(), 5)

    asyncio.run(impostor())
    assert b.link is None
    assert not any(e["kind"] == "received" for e in events_b)
    assert b.status == "ready"
