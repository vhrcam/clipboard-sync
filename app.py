from pathlib import Path

import webview

UI_DIR = Path(__file__).resolve().parent / "ui"


def main():
    webview.create_window(
        "CopyCat",
        url=str(UI_DIR / "index.html"),
        width=960,
        height=620,
        min_size=(760, 520),
        background_color="#0a0a0d",
    )
    webview.start()


if __name__ == "__main__":
    main()
