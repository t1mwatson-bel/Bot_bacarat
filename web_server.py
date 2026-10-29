import os
import json
from flask import Flask, jsonify, send_from_directory
from config import PREDICTIONS_FILE, MOSCOW_TZ
from stats import get_full_stats

app = Flask(__name__, static_folder='.')

def load_predictions_from_file():
    try:
        if not os.path.exists(PREDICTIONS_FILE):
            return []
        with open(PREDICTIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []

# Главная страница
@app.route('/')
def index():
    # Ищем index.html или stats.html
    for path in ("index.html", "stats.html"):
        if os.path.exists(path):
            return send_from_directory('.', path)
    return "OK - HTML not found", 404

# API для данных
@app.route('/api/stats')
def api_stats():
    predictions = load_predictions_from_file()
    try:
        data = get_full_stats(predictions)
    except Exception as e:
        data = {"error": str(e), "summary": {}, "dogons": [], "suits": [], "daily": [], "last": []}
    return jsonify(data)

# Healthcheck
@app.route('/health')
def health():
    from datetime import datetime
    return jsonify({"ok": True, "time": datetime.now(MOSCOW_TZ).isoformat()})

def start_web_server():
    port = int(os.getenv("PORT", 8000))
    print(f"🌐 Flask сервер запущен: 0.0.0.0:{port}", flush=True)
    # host='0.0.0.0' обязательно для Bothost
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)