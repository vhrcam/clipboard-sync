# Clipboard Sync

A lightweight tool that keeps your Mac and Windows clipboards in sync over local Wi-Fi. Copy on one machine, paste on the other. No cloud, no third-party service.

## How it works

- Your Mac runs a WebSocket server, your Windows PC connects as a client
- Both machines poll the clipboard every 0.3 seconds
- When a change is detected, it's sent to the other machine instantly
- Echo prevention stops clipboard updates from bouncing back and forth

## Setup

Install dependencies on both machines:

```
pip install websockets pyperclip
```

On your Mac (server):

```
python clipboard.py server
```

It prints your local IP. On your Windows PC (client):

```
python clipboard.py client <server-ip>
```

Leave both terminals open in the background and copy/paste normally.

## Features

- **Text sync** — code, URLs, paragraphs, anything you copy
- **Bidirectional** — Mac to Windows and Windows to Mac
- **Auto-reconnect** — client retries every 5 seconds if the connection drops
- **Echo prevention** — won't re-send text it just received
- **Live console log** — shows `[→ sent]` and `[← recv]` with a preview

## Limitations

- Text only (no images or files)
- Same Wi-Fi network only
- No encryption (fine for home networks, not public Wi-Fi)
