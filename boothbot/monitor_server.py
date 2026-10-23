"""Lightweight stdlib-only HTTP server for remote monitoring of a live booth session.
Runs only while the fullscreen booth view is active - started/stopped by BoothApp.run()."""
import io
import json
import socket
import threading
import time
import traceback
from collections import OrderedDict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from PIL import Image

from . import capture_log, monitor_page

DEFAULT_PORT = 8080
PORT_SCAN_ATTEMPTS = 10
REFRESH_SECONDS = 10
PHOTO_PANEL_LIMIT = 12
PHOTO_THUMB_SIZE = (480, 480)
PHOTO_THUMB_CACHE = 48
# One page view asks for the photo list once plus once per thumbnail - reuse it briefly rather
# than re-reading captures.csv for every image.
PHOTO_LIST_TTL_S = 5


def get_lan_ip() -> str:
    """Best-effort local network IP, using only the stdlib. Never raises."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))  # sends nothing - just asks the routing table which interface would be used
        return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        sock.close()


def _json_safe(status: dict) -> dict:
    def convert(value):
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], datetime):
            return {"at": value[0].isoformat(), "message": value[1]}
        return value

    return {key: convert(value) for key, value in status.items()}


class _MonitorHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    # SO_REUSEADDR (HTTPServer's default) lets a *second* process silently bind the same port
    # on Windows instead of failing - that would break the "is this port free" fallback scan in
    # MonitorServer.start(). Disable it and request genuinely exclusive binding instead.
    allow_reuse_address = False
    status_provider = None
    # Returns [(path, captured_at)] of the photos the page may show, or None when it shouldn't show
    # any (the setting is off). Also the whitelist for /photo/ - nothing outside it is ever served.
    photos_provider = None

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def init_photo_state(self):
        # Handler threads run concurrently - _photo_lock guards both caches.
        self._photo_lock = threading.Lock()
        self._photo_list = (0.0, None)  # (expires at, list)
        self._thumbs = OrderedDict()  # photo name -> JPEG bytes

    def current_photos(self):
        if self.photos_provider is None:
            return None
        with self._photo_lock:
            expires_at, photos = self._photo_list
            if time.monotonic() < expires_at:
                return photos
        photos = self.photos_provider()
        with self._photo_lock:
            self._photo_list = (time.monotonic() + PHOTO_LIST_TTL_S, photos)
        return photos

    def thumbnail(self, path):
        with self._photo_lock:
            if path.name in self._thumbs:
                self._thumbs.move_to_end(path.name)
                return self._thumbs[path.name]
        with Image.open(path) as image:
            image.draft("RGB", PHOTO_THUMB_SIZE)
            image = image.convert("RGB")
            image.thumbnail(PHOTO_THUMB_SIZE)
            buffer = io.BytesIO()
            image.save(buffer, "JPEG", quality=80)
        data = buffer.getvalue()
        with self._photo_lock:
            self._thumbs[path.name] = data
            while len(self._thumbs) > PHOTO_THUMB_CACHE:
                self._thumbs.popitem(last=False)
        return data


class _MonitorRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"  # keep-alive would leave handler threads parked on idle sockets

    def log_message(self, *args):
        pass  # stderr is None in a PyInstaller --windowed build; the default logger would crash on every request

    def log_error(self, *args):
        pass

    def do_GET(self):
        try:
            parsed = urlsplit(self.path)
            if parsed.path == "/":
                self._handle_dashboard(parse_qs(parsed.query))
            elif parsed.path == "/status.json":
                self._handle_status_json()
            elif parsed.path.startswith("/photo/"):
                self._handle_photo(unquote(parsed.path[len("/photo/"):]))
            elif parsed.path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
            else:
                self._send_text(404, "text/plain; charset=utf-8", "Not found")
        except Exception:
            self._send_text(500, "text/html; charset=utf-8", f"<pre>{traceback.format_exc()}</pre>")

    def _handle_dashboard(self, query):
        status = self.server.status_provider()
        entries = capture_log.read_entries()
        hourly, totals = capture_log.summarize(entries)
        pending = capture_log.list_pending()
        refresh_seconds = 0 if query.get("refresh", [None])[0] == "0" else REFRESH_SECONDS
        photos = self.server.current_photos()
        body = monitor_page.render_dashboard(
            status, hourly, totals, pending, refresh_seconds=refresh_seconds,
            photos=None if photos is None else photos[:PHOTO_PANEL_LIMIT],
        )
        self._send_text(200, "text/html; charset=utf-8", body)

    def _handle_photo(self, name):
        # Served only if it's on the current list - so never a hidden photo, one from another day,
        # anything at all with the setting off, or a path outside the photos folder.
        photos = self.server.current_photos() or []
        path = next((path for path, _captured_at in photos if path.name == name), None)
        if path is None:
            self._send_text(404, "text/plain; charset=utf-8", "Not found")
            return
        try:
            data = self.server.thumbnail(path)
        except OSError:
            self._send_text(404, "text/plain; charset=utf-8", "Not found")
            return
        # The filename never gets reused for a different photo, so browsers may keep it - the page
        # reloads every few seconds and would otherwise fetch every thumbnail again each time.
        self._send_bytes(200, "image/jpeg", data, cache_control="private, max-age=3600")

    def _handle_status_json(self):
        status = self.server.status_provider()
        entries = capture_log.read_entries()
        _hourly, totals = capture_log.summarize(entries)
        pending = capture_log.list_pending()
        payload = {
            "status": _json_safe(status),
            "totals": _json_safe(totals),
            "pending": [_json_safe(entry) for entry in pending],
        }
        self._send_text(200, "application/json", json.dumps(payload))

    def _send_text(self, code, content_type, body):
        self._send_bytes(code, content_type, body.encode("utf-8"))

    def _send_bytes(self, code, content_type, data, cache_control="no-store"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache_control)
        self.end_headers()
        self.wfile.write(data)


class MonitorServer:
    """Wraps a ThreadingHTTPServer running on a daemon thread. Binding never raises -
    start() returns None on failure so a busy port can't take the booth down."""

    def __init__(self, status_provider, photos_provider=None, port: int = DEFAULT_PORT, host: str = "0.0.0.0"):
        self.status_provider = status_provider
        self.photos_provider = photos_provider
        self.port = port
        self.host = host
        self.url = None
        self._httpd = None
        self._thread = None

    def start(self) -> str | None:
        for candidate_port in range(self.port, self.port + PORT_SCAN_ATTEMPTS):
            try:
                httpd = _MonitorHTTPServer((self.host, candidate_port), _MonitorRequestHandler)
            except OSError:
                continue
            httpd.status_provider = self.status_provider
            httpd.photos_provider = self.photos_provider
            httpd.init_photo_state()
            self._httpd = httpd
            self.port = candidate_port
            self._thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            self._thread.start()
            self.url = f"http://{get_lan_ip()}:{candidate_port}"
            return self.url

        self.url = None
        return None

    def stop(self) -> None:
        if self._httpd is None:
            return
        try:
            self._httpd.shutdown()
            self._httpd.server_close()
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._httpd = None
        self._thread = None
