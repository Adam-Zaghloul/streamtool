# StreamTool

> **⚠️ Educational Purposes Only**
> This tool was built to demonstrate network traffic interception, proxy-based stream analysis, and Python automation on Windows. It is intended strictly for personal, educational, and research use. Do not use this tool to access, capture, or redistribute content you do not have the rights to. Always respect the Terms of Service of any website you interact with.

---

A self-installing Python tool for Windows that automatically captures hidden HLS/MP4 stream URLs from any webpage and plays them natively via **mpv** — bypassing embedded players for a direct, higher-quality connection.

---

## Author

**Adam Zaghloul**
Electronics Engineering Technology Graduate — La Cité collégiale, Ottawa (April 2026)
OACETT Student Member · C.Tech Pathway · Member #00927515

*Analog Design · RF/Telecom · Embedded Systems · IoT Security · Networking*

📍 Ottawa, ON · Bilingual (EN/FR) · Open to Electronics Technician roles across Canada
📧 adamzaghloul07@gmail.com
📞 514-247-9095

---

## Feedback, Bug Reports & Contributions

This project is actively maintained. I welcome:

- 🐛 **Bug reports** — open an Issue describing the problem, your OS version, Python version, and the full error output
- 💡 **Suggestions** — feature ideas, edge cases, or workflow improvements
- 🔧 **Pull requests** — fixes, refactors, or new capabilities
- 📬 **Direct contact** — reach me at adamzaghloul07@gmail.com for anything not suited for a public issue

If you found this useful or have feedback, I genuinely want to hear it.

---

## What It Does

Many video websites embed their streams inside iframes or protect them with session tokens, making them invisible to browser DevTools. StreamTool solves this by routing your browser through a local mitmproxy instance, intercepting the real stream URL the moment the video plays, then launching mpv with the correct authentication headers and cookies.

```
Your Browser → mitmproxy (localhost) → Website
                    ↓
              Stream URL captured
                    ↓
              mpv plays it directly
```

---

## Features

- **Fully self-installing** — downloads and configures all dependencies on first run
- **Automatic proxy management** — sets and clears the Windows system proxy without manual steps
- **Token-aware** — detects expired stream tokens and loops back to re-capture automatically
- **Cookie support** — exports browser cookies via extension or auto-extracts from Chrome
- **Safe cleanup** — proxy is always disabled on exit, even on crash or Ctrl+C

---

## Requirements

### You must install manually (one time only)

| Requirement | Version tested | Download |
|---|---|---|
| **Python** | 3.14.4 | https://www.python.org/downloads/ |
| **mitmproxy CA cert** | mitmproxy 12.2.3 | http://mitm.it (while proxy is running) |

> **Python install note:** On the Python installer, check ✅ **"Add Python to PATH"** before clicking Install Now.

### Installed automatically by the script

| Tool | Version tested | Source |
|---|---|---|
| mitmproxy | 12.2.3 | `pip install mitmproxy` |
| yt-dlp | 2026.06.09 | `pip install yt-dlp` |
| mpv | 0.40.x (git) | [zhongfly/mpv-winbuild](https://github.com/zhongfly/mpv-winbuild/releases/latest) |
| 7zr.exe | latest | https://www.7-zip.org/a/7zr.exe |

---

## Tested Environment

| Component | Details |
|---|---|
| OS | Windows 10 Home — Build 10.0.19045 (22H2) |
| Python | 3.14.4 |
| pip | 26.1.2 |
| mitmproxy | 12.2.3 |
| yt-dlp | 2026.06.09 |
| mpv | git build — zhongfly/mpv-winbuild, June 2026 |
| OpenSSL | 4.0.1 (9 Jun 2026) |
| Browser | Chrome / Edge |

---

## Installation

```powershell
# 1. Download streamtool.py to your Downloads folder
# 2. Run it — everything else is automatic
python "$env:USERPROFILE\Downloads\streamtool.py"
```

---

## Usage

### Normal flow

```
1. Run the script
2. Missing dependencies are installed automatically
3. mitmproxy starts and the Windows system proxy is set automatically
4. If the CA cert is missing, the script guides you through installing it (one-time)
5. Open Chrome or Edge, go to your video page, press Play
6. The stream URL is captured automatically
7. The script locates or exports cookies.txt
8. mpv opens and plays the stream directly
```

### CA cert install (one-time only)

While the proxy is running, if the cert is missing the script will prompt you:

```
1. Open Chrome/Edge → go to http://mitm.it
2. Click "Windows" → download mitmproxy-ca-cert.p12
3. Double-click the file:
     Store Location    → Local Machine
     Certificate Store → Trusted Root Certification Authorities
4. Fully close and reopen your browser (not just a new tab)
```

### Cookies

The script prompts for cookies when `cookies.txt` is not found:

**Option 1 — Browser extension (recommended, Chrome stays open)**
- Install [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldbecc)
- Navigate to the video page
- Click the extension → Export → save as `cookies.txt` to your `Downloads\` folder

**Option 2 — Auto-extract (Chrome must be fully closed)**
- The script uses yt-dlp's internal reader to extract Chrome's cookie database directly

### Token expiry

Stream URLs often contain short-lived tokens (30–120 seconds). If mpv exits within 5 seconds of launch, the script detects this automatically and offers to loop back to re-capture a fresh URL — no manual steps needed.

---

## mpv Controls

| Key | Action |
|---|---|
| `Space` | Pause / Resume |
| `f` | Toggle fullscreen |
| `→` / `←` | Seek +/- 5 seconds |
| `↑` / `↓` | Seek +/- 1 minute |
| `9` / `0` | Volume down / up |
| `m` | Mute |
| `q` | Quit |

---

## How It Works (Technical)

### Stream capture

StreamTool uses [mitmproxy](https://mitmproxy.org/) as a transparent HTTPS proxy. A custom addon script (`StreamCapture`) inspects every HTTP response and writes the URL + `Referer` header to a temp file when the URL matches video stream patterns (`.m3u8`, `.mp4`, `.mpd`, `/manifest`, `/playlist`).

The main script polls that file every 300ms with a spinner. The moment a URL appears it terminates mitmdump, restores the system proxy, and proceeds.

```python
class StreamCapture:
    def response(self, flow):
        url = flow.request.url
        if any(x in url for x in [".m3u8", ".mp4", ".mpd", "/manifest", "/playlist"]):
            # write url + referer to capture file
```

### Proxy management

The Windows system proxy is set and cleared via the registry:

```
HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings
  ProxyEnable = 1
  ProxyServer = 127.0.0.1:{port}
```

`ctypes.windll.wininet.InternetSetOptionW` notifies Chrome and Edge of the change immediately without requiring a restart.

### Startup safety

On every launch the script immediately calls `set_system_proxy(False)` to clean up any leftover proxy state from a previous crash. `atexit` and `SIGTERM` handlers ensure the proxy is always disabled regardless of how the process exits.

### mpv invocation

```
mpv --http-header-fields="Referer: <referer>" --cookies-file="<cookies.txt>" "<stream_url>"
```

---

## File Structure After First Run

```
Downloads\
  streamtool.py                ← the script
  streamtool_session.json      ← last captured URL, referer, cookies path
  cookies.txt                  ← exported browser cookies
  7zr.exe                      ← standalone 7-Zip CLI (used for mpv extraction)
  mpv\
    mpv.exe                    ← player
    mpv.com
    *.dll                      ← mpv runtime libraries
```

---

## Troubleshooting

**Proxy stuck on after a crash**
```powershell
$key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
Set-ItemProperty -Path $key -Name ProxyEnable -Value 0
```

**mitmdump not found after pip install**
```powershell
$env:PATH += ";$env:APPDATA\Python\Python314\Scripts"
```

**mpv exits immediately**
The token expired before mpv could connect. The script detects this and offers to re-capture. Refresh the video page in your browser, press Play, and the fresh URL is captured automatically.

**Chrome cookie auto-extract fails**
Chrome locks its SQLite cookie database while running. Close all Chrome windows and confirm no `chrome.exe` processes remain in Task Manager, then retry.

**Site still broken after cert install**
Some sites use certificate pinning (hardcoded cert fingerprints) and reject mitmproxy's CA entirely. Use browser DevTools (Network tab → filter `.m3u8` / `.mp4`) with the proxy disabled as a fallback.

**yt-dlp uninstall requires admin**
yt-dlp installed system-wide requires elevated permissions to remove:
```powershell
# Run PowerShell as Administrator
pip uninstall yt-dlp -y
```

---

## Resources

| Resource | Link |
|---|---|
| mitmproxy documentation | https://docs.mitmproxy.org |
| mitmproxy addon API | https://docs.mitmproxy.org/stable/addons-overview/ |
| yt-dlp | https://github.com/yt-dlp/yt-dlp |
| mpv player | https://mpv.io |
| mpv Windows builds (zhongfly) | https://github.com/zhongfly/mpv-winbuild |
| mpv Windows builds (shinchiro) | https://github.com/shinchiro/mpv-winbuild-cmake |
| 7-Zip | https://www.7-zip.org |
| Get cookies.txt LOCALLY (Chrome) | https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldbecc |
| HLS — HTTP Live Streaming (Apple) | https://developer.apple.com/streaming/ |
| MPEG-DASH standard | https://dashif.org |
| mitmproxy CA cert install guide | https://docs.mitmproxy.org/stable/concepts-certificates/ |

---

## License

MIT License — © 2026 Adam Zaghloul

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED.
