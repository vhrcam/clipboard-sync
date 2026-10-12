import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import webview

from copycat import VERSION
from copycat.engine import Engine, data_dir

# PyInstaller unpacks bundled files to sys._MEIPASS.
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

log = logging.getLogger("copycat")


class Bridge:
    """Public methods are callable from the page as window.pywebview.api.<name>()."""

    def __init__(self):
        self._window = None
        self._engine = None
        self._ready = False

    def ready(self):
        self._ready = True
        log.info("window ready")
        return self._engine.snapshot()

    def pair(self, accept):
        self._engine.submit("pair", bool(accept))

    def connect(self, address):
        self._engine.submit("connect", str(address)[:255])

    def unpair(self):
        self._engine.submit("unpair")

    def _call(self, function, payload):
        if self._ready and self._window:
            self._window.run_js(f"window.copycat.{function}({json.dumps(payload)})")


def main():
    handler = RotatingFileHandler(data_dir() / "copycat.log", maxBytes=1_000_000, backupCount=1, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log.info("CopyCat %s starting", VERSION)

    bridge = Bridge()
    engine = Engine(
        on_update=lambda snapshot: bridge._call("update", snapshot),
        on_event=lambda event: bridge._call("event", event),
    )
    bridge._engine = engine
    bridge._window = webview.create_window(
        "CopyCat",
        url=str(BASE_DIR / "ui" / "index.html"),
        js_api=bridge,
        width=960,
        height=620,
        min_size=(760, 540),
        background_color="#0a0a0d",
    )
    engine.start()
    webview.start()
    engine.stop()


if __name__ == "__main__":
    main()
