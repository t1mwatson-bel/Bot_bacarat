import os
import json
import http.server
import socketserver

from datetime import datetime

from config import (
    PREDICTIONS_FILE,
    MOSCOW_TZ,
)

from stats import get_full_stats


def load_predictions_from_file():
    try:
        if not os.path.exists(PREDICTIONS_FILE):
            return []
        with open(PREDICTIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


class StatsHandler(http.server.SimpleHTTPRequestHandler):

    def do_GET(self):

        # Главная
        if self.path in ("/", "/index.html"):
            for path in ("index.html", "stats.html", "templates/index.html"):
                if os.path.exists(path):
                    with open(path, "rb") as f:
                        body = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"OK - HTML not found")
            return

        # API
        if self.path.startswith("/api/stats"):
            predictions = load_predictions_from_file()
            try:
                data = get_full_stats(predictions)
            except Exception as e:
                data = {"error": str(e), "summary": {}, "dogons": [], "suits": [], "daily": [], "last": []}
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # Health
        if self.path == "/health":
            body = json.dumps({"ok": True, "time": datetime.now(MOSCOW_TZ).isoformat()}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        return super().do_GET()

    def log_message(self, *args):
        pass


class ReusableTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def start_web_server():
    port = int(os.getenv("PORT", 8000))
    try:
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass

    with ReusableTCPServer(("0.0.0.0", port), StatsHandler) as httpd:
        print(f"🌐 Веб-сервер запущен: 0.0.0.0:{port}", flush=True)
        httpd.serve_forever()