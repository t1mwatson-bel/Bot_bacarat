import os
import json
import http.server
import socketserver

from datetime import datetime

from config import (
    PREDICTIONS_FILE,
    STATS_HTML_FILE,
    MOSCOW_TZ,
)

from stats import get_full_stats


# =====================================================================
# ЗАГРУЗКА ПРОГНОЗОВ ИЗ ФАЙЛА
# =====================================================================

def load_predictions_from_file():
    try:
        if not os.path.exists(PREDICTIONS_FILE):
            return []

        with open(PREDICTIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        return data if isinstance(data, list) else []

    except Exception as e:
        print(f"⚠️ Ошибка чтения прогнозов: {e}", flush=True)
        return []


# =====================================================================
# HTTP HANDLER
# =====================================================================

class StatsHandler(http.server.SimpleHTTPRequestHandler):

    def do_GET(self):

        # ---- Главная страница ----
        if self.path in ("/", "/index.html"):

            if os.path.exists(STATS_HTML_FILE):
                self.path = "/" + STATS_HTML_FILE
                return super().do_GET()

            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("OK".encode("utf-8"))
            return

        # ---- API со статистикой ----
        if self.path.startswith("/api/stats"):

            predictions = load_predictions_from_file()

            try:
                data = get_full_stats(predictions)
            except Exception as e:
                print(f"⚠️ Ошибка подсчёта статистики: {e}", flush=True)
                data = {
                    "summary": {},
                    "dogons": [],
                    "suits": [],
                    "daily": [],
                    "last": [],
                    "updated_at": datetime.now(MOSCOW_TZ).isoformat(),
                }

            body = json.dumps(data, ensure_ascii=False).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        # ---- Health check ----
        if self.path == "/health":

            body = json.dumps({
                "ok": True,
                "time": datetime.now(MOSCOW_TZ).isoformat(),
            }).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # ---- Всё остальное ----
        return super().do_GET()

    def log_message(self, format, *args):
        pass


# =====================================================================
# START (вызывается в фоне из bot.py)
# =====================================================================

def start_web_server():
    port = int(os.getenv("PORT", 8000))

    try:
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass

    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    try:
        with ReusableTCPServer(("0.0.0.0", port), StatsHandler) as httpd:
            print(f"🌐 Веб-сервер запущен: 0.0.0.0:{port}", flush=True)
            httpd.serve_forever()
    except Exception as e:
        print(f"⚠️ Ошибка веб-сервера на порту {port}: {e}", flush=True)