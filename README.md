# CopyCat

Copy on your Mac, paste on your Windows PC, and the other way around. CopyCat keeps both clipboards in sync over your home Wi-Fi. No cloud, no account, no third-party service.

| Launch | Connected |
|---|---|
| ![CopyCat launch screen](screenshots/launch.png) | ![Mac and PC both connected](screenshots/connected.png) |

## What it does

- **Launch animation:** the CopyCat wordmark fades in letter by letter, then a line-art cat draws itself, blinks and swishes its tail.
- **Connection screen:** your Mac and your PC side by side. Grey dots mean not connected, a spinner means connecting, and a green check means connected.
- **Text sync:** code, links, paragraphs, anything you copy as text.
- **Both directions:** Mac to Windows and Windows to Mac.
- **Auto-reconnect:** the PC retries every 5 seconds if the connection drops.
- **Echo prevention:** text that just arrived is never sent back.

## How it works

- The Mac runs a WebSocket server and the PC connects to it.
- Each side checks its clipboard every 0.3 seconds and sends anything new as a small JSON message.
- Text received from the other computer is remembered before it's written to the clipboard, so it doesn't bounce back.
- The app window is built with [pywebview](https://pywebview.flowrl.com/): Python runs the sync and an HTML/CSS screen shows the status, in a native window on both macOS and Windows.

## Run it

Set up once on each computer:

```
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Open the app:

```
python app.py
```

Terminal version of the sync, while it's being connected to the app. On the Mac:

```
python clipboard.py server
```

It prints the Mac's IP address. On the PC:

```
python clipboard.py client <mac-ip>
```

## Status

- [x] Clipboard sync engine (`clipboard.py`)
- [x] App window, launch animation and connection screen (the statuses are a demo for now)
- [ ] Connect the screen to the real sync
- [ ] Package as a double-click `.app` and `.exe`

## Limitations

- Text only (no images or files yet)
- Both computers must be on the same Wi-Fi
- No encryption yet, so use it on your home network, not public Wi-Fi
