#!/usr/bin/env python3
"""
StreamTool — Automated stream URL capture and playback
  Step 1: Dependency check
  Step 2: Stream URL + Referer capture via mitmproxy
  Step 3: Cookies
  Step 4: Playback via mpv
"""
import subprocess, sys, shutil, os, socket, winreg, ctypes
import tempfile, json, re as _re, time, http.cookiejar
from pathlib import Path

# ━━━ Paths ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
APPDATA      = Path(os.environ.get("APPDATA",     ""))
USERPROFILE  = Path(os.environ.get("USERPROFILE", ""))
PY_VER       = f"Python{sys.version_info.major}{sys.version_info.minor}"
PY_SCRIPTS   = APPDATA / "Python" / PY_VER / "Scripts"
SESSION_FILE = USERPROFILE / "Downloads" / "streamtool_session.json"
CAPTURE_FILE = USERPROFILE / "Downloads" / "streamtool_capture.txt"
COOKIES_PATH = USERPROFILE / "Downloads" / "cookies.txt"

MPV_CANDIDATES = [
    USERPROFILE / "Downloads" / "mpv" / "mpv.exe",
    USERPROFILE / "scoop" / "apps" / "mpv" / "current" / "mpv.exe",
    Path("C:/ProgramData/scoop/apps/mpv/current/mpv.exe"),
]

EXT_URL = ("https://chromewebstore.google.com/detail/"
           "get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldbecc")

# ━━━ Capture addon ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def make_addon(capture_file):
    return f'''\
CAPTURE_FILE = r"{capture_file}"

class StreamCapture:
    def response(self, flow):
        url = flow.request.url
        ref = flow.request.headers.get("referer", "")
        if any(x in url for x in [".m3u8", ".mp4", ".mpd", "/manifest", "/playlist"]):
            try:
                with open(CAPTURE_FILE, "w", encoding="utf-8") as fh:
                    fh.write(url + "\\n" + ref + "\\n")
            except Exception:
                pass

addons = [StreamCapture()]
'''

# ━━━ Print helpers ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def ok(msg):   print(f"  [OK] {msg}")
def fail(msg): print(f"  [!!] {msg}")
def info(msg): print(f"  [..] {msg}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STEP 1 — Dependency checks
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def find_exe(name):
    found = shutil.which(name)
    if found: return Path(found)
    c = PY_SCRIPTS / f"{name}.exe"
    return c if c.exists() else None

def check_python():
    ok(f"Python {sys.version.split()[0]}  ->  {sys.executable}")

def check_mitmproxy():
    try:
        import mitmproxy  # noqa
        from importlib.metadata import version
        ver  = version("mitmproxy")
        path = find_exe("mitmdump")
        ok(f"mitmproxy {ver}  ->  {path or 'in PATH'}")
        return True, path
    except ImportError:
        fail("mitmproxy not installed"); return False, None

def check_ytdlp():
    path = find_exe("yt-dlp")
    if path:
        r = subprocess.run([str(path), "--version"], capture_output=True, text=True)
        ok(f"yt-dlp {r.stdout.strip()}  ->  {path}"); return True, path
    r = subprocess.run([sys.executable, "-m", "yt_dlp", "--version"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        ok(f"yt-dlp {r.stdout.strip()}  (module)"); return True, None
    fail("yt-dlp not installed"); return False, None

def check_mpv():
    path = find_exe("mpv")
    if path: ok(f"mpv  ->  {path}"); return True, path
    for c in MPV_CANDIDATES:
        if c.exists(): ok(f"mpv  ->  {c}"); return True, c
    fail("mpv not found"); return False, None

def pip_install(pkg):
    info(f"Installing {pkg} ...")
    subprocess.run([sys.executable, "-m", "pip", "install", "--user", pkg])

def auto_install_mpv():
    """
    Install mpv automatically:
      1. Download 7zr.exe (standalone 7-Zip CLI) for extraction
      2. Fetch latest mpv-x86_64 .7z from zhongfly/mpv-winbuild
      3. Extract with 7zr.exe (supports BCJ2 which py7zr does not)
      4. Fall back to winget if GitHub fails
    """
    import urllib.request

    MPV_DIR  = USERPROFILE / "Downloads" / "mpv"
    ZZR_PATH = USERPROFILE / "Downloads" / "7zr.exe"

    # ── Step A: get 7zr.exe if not already present ────────────────────────────
    if not ZZR_PATH.exists():
        info("Downloading 7zr.exe (standalone 7-Zip, ~500 KB) ...")
        try:
            urllib.request.urlretrieve(
                "https://www.7-zip.org/a/7zr.exe", ZZR_PATH)
            ok(f"7zr.exe ready -> {ZZR_PATH}")
        except Exception as e:
            fail(f"Could not download 7zr.exe: {e}")
            ZZR_PATH = None
    else:
        ok(f"7zr.exe already present -> {ZZR_PATH}")

    # ── Step B: pick mpv-x86_64 asset (not ffmpeg, not v3, not aarch64) ───────
    def pick_asset(release):
        for a in release.get("assets", []):
            n = a["name"].lower()
            if (n.startswith("mpv-")
                    and n.endswith(".7z")
                    and "x86_64" in n
                    and "v3"     not in n
                    and "aarch"  not in n
                    and "dev"    not in n
                    and "debug"  not in n
                    and "lgpl"   not in n):
                return a
        return None

    # ── Step C: download with progress bar ────────────────────────────────────
    def download(url, dest):
        info(f"Downloading {dest.name}  (may take a minute) ...")
        def _prog(b, bs, total):
            done = b * bs
            pct  = min(100, done * 100 // total) if total > 0 else 0
            print(f"\r  [..] {pct:3d}%  {done/1_048_576:.1f} MB",
                  end="", flush=True)
        urllib.request.urlretrieve(url, dest, _prog)
        print()
        ok(f"Downloaded {dest.name}")

    # ── Step D: extract with 7zr.exe, then flatten mpv.exe ───────────────────
    def extract(archive):
        if not ZZR_PATH or not ZZR_PATH.exists():
            fail("7zr.exe not available — cannot extract"); return False
        info("Extracting ...")
        MPV_DIR.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            [str(ZZR_PATH), "x", str(archive),
             f"-o{MPV_DIR}", "-y"],
            capture_output=True, text=True)
        archive.unlink(missing_ok=True)
        if r.returncode != 0:
            fail(f"7zr extraction failed: {r.stderr.strip() or r.stdout.strip()}")
            return False
        # Flatten: mpv.exe may land in a subdirectory
        if not (MPV_DIR / "mpv.exe").exists():
            hits = list(MPV_DIR.rglob("mpv.exe"))
            if hits:
                src = hits[0].parent
                for f in src.iterdir():
                    dst = MPV_DIR / f.name
                    if not dst.exists():
                        f.rename(dst)
                try: src.rmdir()
                except Exception: pass
        if (MPV_DIR / "mpv.exe").exists():
            ok(f"mpv installed -> {MPV_DIR / 'mpv.exe'}"); return True
        fail("mpv.exe not found after extraction"); return False

    # ── Step E: GitHub API fetch ──────────────────────────────────────────────
    def gh_get(url):
        req = urllib.request.Request(
            url, headers={"User-Agent": "streamtool/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())

    # ── Method 1: zhongfly GitHub (daily mpv builds) ─────────────────────────
    for api in [
        "https://api.github.com/repos/zhongfly/mpv-winbuild/releases/latest",
        "https://api.github.com/repos/zhongfly/mpv-winbuild/releases?per_page=5",
    ]:
        info("Checking zhongfly/mpv-winbuild ...")
        try:
            data     = gh_get(api)
            releases = data if isinstance(data, list) else [data]
            for rel in releases:
                asset = pick_asset(rel)
                if asset:
                    info(f"Found: {asset['name']}")
                    dest = USERPROFILE / "Downloads" / asset["name"]
                    download(asset["browser_download_url"], dest)
                    return extract(dest)
        except Exception as e:
            info(f"GitHub attempt failed: {e}"); continue

    # ── Method 2: winget ─────────────────────────────────────────────────────
    info("Trying winget ...")
    for pkg_id in ["mpv.mpv", "mpv-player.mpv"]:
        r = subprocess.run(
            ["winget", "install", pkg_id,
             "--silent",
             "--accept-package-agreements",
             "--accept-source-agreements"],
            capture_output=True, text=True)
        if r.returncode == 0:
            ok("mpv installed via winget"); return True

    fail("All auto-install methods failed")
    return False

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STEP 2 — Stream URL capture
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def find_free_port(start=8080):
    for p in range(start, start + 20):
        with socket.socket() as s:
            try:   s.bind(("127.0.0.1", p)); return p
            except OSError: continue
    raise RuntimeError("No free port found in 8080-8099")

def wait_for_port(host, port, timeout=12):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            time.sleep(0.2)
    return False

def set_system_proxy(enabled, port=8080):
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, int(enabled))
        if enabled:
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"127.0.0.1:{port}")
        winreg.CloseKey(key)
        ctypes.windll.wininet.InternetSetOptionW(0, 39, 0, 0)
        ctypes.windll.wininet.InternetSetOptionW(0, 37, 0, 0)
        return True
    except Exception as e:
        fail(f"Could not auto-set proxy: {e}"); return False

def check_cert():
    try:
        r = subprocess.run(["certutil", "-store", "Root"],
                           capture_output=True, text=True,
                           errors="replace", timeout=10)
        return "mitmproxy" in r.stdout.lower()
    except Exception:
        return False

def capture_stream(paths):
    mitmdump = str(paths.get("mitmdump") or "mitmdump")
    try: CAPTURE_FILE.unlink()
    except FileNotFoundError: pass

    try:
        port = find_free_port()
    except RuntimeError as e:
        fail(str(e)); return None, None

    addon_path = Path(tempfile.mktemp(suffix="_streamtool.py"))
    addon_path.write_text(make_addon(str(CAPTURE_FILE)), encoding="utf-8")
    proc = None; proxy_set = False

    try:
        info(f"Starting mitmdump on port {port} ...")
        proc = subprocess.Popen(
            [mitmdump, "--ssl-insecure", "--mode", f"regular@{port}",
             "-s", str(addon_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if not wait_for_port("127.0.0.1", port):
            fail("mitmdump did not start in time"); return None, None
        ok(f"Proxy ready on 127.0.0.1:{port}")

        proxy_set = set_system_proxy(True, port)
        if proxy_set: ok("System proxy set  (Chrome / Edge auto-updated)")
        else: print(f"  [!!] Set browser proxy manually: 127.0.0.1:{port}")
        time.sleep(0.5)

        if not check_cert():
            print()
            print("  [!!] mitmproxy CA cert not found.")
            print("  1. Go to  http://mitm.it  in your browser")
            print("  2. Click Windows -> download the .p12 file")
            print("  3. Install to: Local Machine -> Trusted Root Certification Authorities")
            print("  4. Fully close and reopen browser")
            print()
            input("  Press Enter once done ... ")
        else:
            ok("mitmproxy CA cert found")

        print()
        print("  +----------------------------------------------------------+")
        print("  |  Open Chrome/Edge, go to your video page, PLAY it.      |")
        print("  |  StreamTool captures the URL automatically.              |")
        print("  |  Press Ctrl+C to cancel.                                 |")
        print("  +----------------------------------------------------------+")
        print()

        spin = ['-', '\\', '|', '/']; i = 0
        while True:
            if CAPTURE_FILE.exists():
                lines   = CAPTURE_FILE.read_text(encoding="utf-8").strip().splitlines()
                url     = lines[0].strip() if lines else None
                referer = lines[1].strip() if len(lines) > 1 else ""
                if url:
                    print(f"\r  [OK] Stream URL captured!                    ")
                    ok(f"Referer: {referer or '(none)'}")
                    return url, referer
            print(f"\r  [{spin[i % 4]}] Waiting for stream ...", end="", flush=True)
            i += 1; time.sleep(0.3)

    except KeyboardInterrupt:
        print("\n  [..] Cancelled."); return None, None
    finally:
        if proc and proc.poll() is None: proc.terminate()
        set_system_proxy(False)
        if proxy_set: ok("System proxy disabled")
        try: addon_path.unlink()
        except Exception: pass
        try: CAPTURE_FILE.unlink()
        except Exception: pass

    return None, None

def save_session(url, referer, cookies_file=None):
    data = {
        "url":          url,
        "referer":      referer or "",
        "cookies_file": str(cookies_file) if cookies_file else str(COOKIES_PATH),
    }
    SESSION_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STEP 3 — Cookies
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def is_valid_cookies(path):
    if not path.exists() or path.stat().st_size < 50:
        return False
    try:
        head = path.read_text(encoding="utf-8", errors="ignore")[:300]
        return "HTTP Cookie" in head or head.strip().startswith("#")
    except Exception:
        return False

def step3_cookies(paths, session):
    cookies_path = Path(session.get("cookies_file", str(COOKIES_PATH)))

    if is_valid_cookies(cookies_path):
        ok(f"cookies.txt found: {cookies_path}")
        return cookies_path

    print()
    info("cookies.txt not found. Choose a method:")
    print()
    print("  1. Browser extension  (Chrome stays open)   [recommended]")
    print("  2. Auto-extract       (Chrome must be fully closed)")
    print("  3. Skip               (continue without cookies)")
    print()

    choice = ""
    while choice not in ("1", "2", "3"):
        choice = input("  Enter 1, 2, or 3: ").strip()
    print()

    if choice == "1": return _guide_extension(cookies_path)
    elif choice == "2": return _auto_extract(paths, session, cookies_path)
    else:
        info("Skipping cookies — site may work without them")
        return None

def _guide_extension(cookies_path):
    print("  Install 'Get cookies.txt LOCALLY' Chrome extension:")
    print(f"  {EXT_URL}")
    print()
    print("  1. Install the extension")
    print("  2. Go to the VIDEO PAGE in Chrome")
    print("  3. Click extension icon -> Export as cookies.txt")
    print(f"  4. Save to:  {cookies_path}")
    print()
    input("  Press Enter once cookies.txt is saved ... ")

    if is_valid_cookies(cookies_path):
        ok(f"cookies.txt valid: {cookies_path}")
        return cookies_path
    fail(f"Not found or invalid: {cookies_path}")
    return None

def _auto_extract(paths, session, cookies_path):
    print("  Close ALL Chrome windows, then press Enter ...")
    input()
    print()
    info("Reading Chrome cookie database via yt-dlp ...")
    try:
        import yt_dlp
        ydl_opts = {
            "cookiesfrombrowser": ("chrome", None, None, None),
            "quiet": True, "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            cj = ydl.cookiejar

        out = http.cookiejar.MozillaCookieJar(str(cookies_path))
        count = 0
        for cookie in cj:
            out.set_cookie(cookie); count += 1
        out.save(ignore_discard=True, ignore_expires=True)

        if is_valid_cookies(cookies_path) and count > 0:
            ok(f"Extracted {count} cookies -> {cookies_path}")
            return cookies_path
        raise RuntimeError("empty result")
    except Exception as e:
        fail(f"Auto-extract failed: {e}")
        info("Falling back to extension method ...")
        print()
        return _guide_extension(cookies_path)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STEP 4 — Playback
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def step4_playback(paths, session, cookies_path):
    url     = session.get("url", "")
    referer = session.get("referer", "")

    if not url:
        fail("No URL in session — run Step 2 again")
        return False

    mpv_path = str(paths.get("mpv") or "mpv")

    # ── Build mpv command ─────────────────────────────────────────────────────
    cmd = [mpv_path]

    if referer:
        cmd.append(f"--http-header-fields=Referer: {referer}")

    if cookies_path and Path(cookies_path).exists():
        cmd.append(f"--cookies-file={cookies_path}")

    cmd.append(url)

    # ── Print summary ─────────────────────────────────────────────────────────
    print()
    print(f"  URL     : {url[:70]}{'...' if len(url) > 70 else ''}")
    print(f"  Referer : {referer or '(none)'}")
    print(f"  Cookies : {cookies_path or '(none)'}")
    print()
    print("  Controls:  Space=pause  f=fullscreen  q=quit  9/0=volume  arrows=seek")
    print()
    info("Launching mpv ...")
    print()

    # ── Launch ────────────────────────────────────────────────────────────────
    start = time.time()
    try:
        proc = subprocess.Popen(cmd)
    except FileNotFoundError:
        fail(f"mpv not found at: {mpv_path}")
        return False

    # Poll for 5 s — if mpv quits that fast the token has expired
    for _ in range(25):
        time.sleep(0.2)
        if proc.poll() is not None:
            break

    elapsed = time.time() - start

    if proc.poll() is not None and elapsed < 5:
        print()
        fail(f"mpv exited after {elapsed:.1f}s — stream URL has expired")
        print()
        print("  The URL token is time-limited and ran out before mpv could open it.")
        print("  Re-capture a fresh URL: go back to Step 2 (y) or quit (n).")
        return False

    # mpv is running — wait for user to close it
    ok("mpv is playing!")
    proc.wait()
    print()
    ok("Playback finished.")
    return True

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Main
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    import atexit, signal

    # ── Safety net: always kill proxy on exit, crash, or Ctrl+C ────────────
    def _emergency_proxy_off(*_):
        try: set_system_proxy(False)
        except Exception: pass

    atexit.register(_emergency_proxy_off)
    signal.signal(signal.SIGTERM, _emergency_proxy_off)

    # ── Also clean up any leftover proxy from a previous crashed run ────────
    set_system_proxy(False)

    # ── Step 1: Dependency check (once per run) ─────────────────────────────
    print()
    print("=" * 57)
    print("  StreamTool -- Step 1: Dependency Check")
    print("=" * 57)
    print()

    issues, paths = [], {}
    check_python(); print()

    for check_fn, pkg, key in [
        (check_mitmproxy, "mitmproxy", "mitmdump"),
        (check_ytdlp,     "yt-dlp",    "yt-dlp"),
    ]:
        found, path = check_fn()
        if not found:
            pip_install(pkg); found, path = check_fn()
        if found:  paths[key] = path
        else:      issues.append(f"{key}: run: pip install {pkg}")

    found, path = check_mpv()
    if not found:
        info("mpv not found — auto-downloading from GitHub ...")
        if auto_install_mpv():
            found, path = check_mpv()
    if found: paths["mpv"] = path
    else:
        issues.append(
            "mpv auto-install failed.\n"
            "     Manual: https://github.com/shinchiro/mpv-winbuild-cmake/releases/latest\n"
            f"     Extract mpv.exe to: {USERPROFILE}\\Downloads\\mpv\\"
        )

    print()
    if issues:
        fail("Fix these before continuing:")
        for i, m in enumerate(issues, 1): print(f"    {i}. {m}")
        return
    ok("Step 1 PASSED")

    # ── Steps 2-4 loop (re-capture if token expires) ─────────────────────────
    cookies_path = None   # resolved once in Step 3, reused on retry

    while True:

        # ── Step 2: Capture ────────────────────────────────────────────────
        print()
        print("=" * 57)
        print("  StreamTool -- Step 2: Capture Stream URL")
        print("=" * 57)
        print()

        url, referer = capture_stream(paths)
        if not url:
            fail("No stream URL captured — exiting."); return

        print()
        print(f"    URL     : {url[:70]}{'...' if len(url) > 70 else ''}")
        print(f"    Referer : {referer or '(none)'}")
        session = save_session(url, referer, cookies_path)
        ok("Step 2 PASSED")

        # ── Step 3: Cookies (first pass only — reused on retry) ────────────
        if cookies_path is None:
            print()
            print("=" * 57)
            print("  StreamTool -- Step 3: Cookies")
            print("=" * 57)
            print()

            cookies_path = step3_cookies(paths, session)
            session["cookies_file"] = str(cookies_path) if cookies_path else ""
            SESSION_FILE.write_text(json.dumps(session, indent=2), encoding="utf-8")

            print()
            ok("Step 3 PASSED")

        # ── Step 4: Playback ───────────────────────────────────────────────
        print()
        print("=" * 57)
        print("  StreamTool -- Step 4: Playback")
        print("=" * 57)

        success = step4_playback(paths, session, cookies_path)

        if success:
            print("=" * 57)
            print()
            break

        # Token expired or other failure — offer retry
        print()
        again = input("  Re-capture URL and try again? (y/n): ").strip().lower()
        if again != "y":
            break
        print()


if __name__ == "__main__":
    main()
