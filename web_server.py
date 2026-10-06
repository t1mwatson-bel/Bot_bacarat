import os
import json

from datetime import datetime

from flask import Flask, jsonify, render_template

from config import (
    PREDICTIONS_FILE,
    MOSCOW_TZ,
)

from stats import get_full_stats


# =====================================================================
# FLASK
# =====================================================================

app = Flask(__name__)

# Не кэшировать ответы API
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0


# =====================================================================
# ЧТЕНИЕ ДАННЫХ
# =====================================================================

def load_predictions_from_file():
    """Читает predictions.json. Возвращает список."""

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
# ROUTES
# =====================================================================

@app.route("/")
def index():
    """Главная страница — неоновый сайт."""

    return render_template("index.html")


@app.route("/api/stats")
def api_stats():
    """JSON со всей статистикой для сайта."""

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

    return jsonify(data)


@app.route("/health")
def health():
    """Проверка, что сервер жив."""

    return jsonify({
        "ok": True,
        "time": datetime.now(MOSCOW_TZ).isoformat(),
    })


# =====================================================================
# СТАРТ
# =====================================================================

if __name__ == "__main__":
    port = int(os.getenv("WEB_PORT", "8000"))

    print(f"🌐 Web server: http://0.0.0.0:{port}", flush=True)

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )